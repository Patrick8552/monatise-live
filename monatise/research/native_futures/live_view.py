"""Isolated read-only view of already admitted native data, not a second feed.

Freeze on the collector's owning event loop; compute outside that loop. Typed
observations/bars/contracts are immutable. Every mutable collection is detached.
This avoids re-reading the entire raw journal for every chart refresh. Independent
raw/spool forensic reconciliation remains separate and is never claimed here.
"""
from collections import deque
from copy import copy,deepcopy
from types import SimpleNamespace
import time

from monatise.research.phase10.market_info import FuturesMarketInfo
from monatise.research.phase9.rotation import atomic_json
from monatise.research.institutional.models import digest
from .information_gate import NativeInformationGate
from .chart import chart_snapshot


def freeze_service(pipeline,health):
    """Caller must own ingestion; this function has no await or SDK interaction."""
    if not 1<=len(pipeline.gates)<=3 or any(type(g) is not NativeInformationGate for g in pipeline.gates.values()):
        raise ValueError('native_admitted_pipeline_required')
    gates={}
    for iid,gate in pipeline.gates.items():
        frozen=copy(gate)
        for key,value in vars(gate).items():
            if isinstance(value,dict):
                detached=copy(value)
                for k,v in value.items():
                    if isinstance(v,(deque,list,tuple)):detached[k]=tuple(v)
                    elif isinstance(v,dict):detached[k]=deepcopy(v)
                setattr(frozen,key,detached)
            elif isinstance(value,(deque,list,tuple)):setattr(frozen,key,tuple(value))
            elif isinstance(value,set):setattr(frozen,key,set(value))
        gates[iid]=frozen
    view=SimpleNamespace(gates=gates,calendars=dict(pipeline.calendars),
        bars={iid:{tf:dict(rows) for tf,rows in series.items()} for iid,series in pipeline.bars.items()},
        enabled_schemas=tuple(pipeline.enabled_schemas))
    state=deepcopy(health)
    state['verification_scope']='LIVE_COLLECTOR_ADMITTED_IMMUTABLE_VIEW; INDEPENDENT_RAW_JOURNAL_FORENSICS_SEPARATE'
    state['independent_raw_replay_performed_for_this_view']=False
    return FuturesMarketInfo(view,source_health=lambda now:deepcopy(state))


def publish_view(service,*,cutoff_ns,capture_id,reader_commit,chart_path,cache_path):
    """Run in a worker thread with the detached view, never the mutable pipeline."""
    began=time.time_ns()
    def save_report(report):
        body=dict(version='native-analysis-cache-v1',capture_id=str(capture_id),
            calculation_started_ns=began,calculation_completed_ns=time.time_ns(),analysis=report,
            reader_source_commit=reader_commit,verification_scope='LIVE_COLLECTOR_ADMITTED_IMMUTABLE_VIEW')
        atomic_json(cache_path,dict(body=body,sha256=digest(body)))
    try:
        body=chart_snapshot(service,cutoff_ns=cutoff_ns,capture_id=capture_id,
            reader_commit=reader_commit,report_sink=save_report)
        atomic_json(chart_path,dict(body=body,sha256=digest(body)))
        status=dict(status='READY',observed_at_ns=time.time_ns(),error=None,
            duration_seconds=(time.time_ns()-began)/10**9,verification_scope='LIVE_COLLECTOR_ADMITTED_IMMUTABLE_VIEW')
        for path in (chart_path,cache_path):atomic_json(str(path)+'.status',status)
        return dict(**status,cutoff_ns=cutoff_ns,chart_sha256=digest(body),
            frames={s:{tf:dict(bars=len(f['bars']),frame_sha256=f.get('frame_sha256'),
                last_close_ns=f['bars'][-1]['close_ns'] if f['bars'] else None) for tf,f in frames.items()} for s,frames in body['charts'].items()})
    except Exception as exc:
        status=dict(status='REFRESH_FAILED',observed_at_ns=time.time_ns(),error=type(exc).__name__)
        for path in (chart_path,cache_path):atomic_json(str(path)+'.status',status)
        raise


def write_view_input(service,*,path,cutoff_ns,capture_id,reader_commit):
    """Private, bounded process handoff; never accept provider/user pickle data."""
    import hashlib,os,pickle
    from pathlib import Path
    path=Path(path)
    payload=pickle.dumps(service.pipeline,protocol=5)
    if len(payload)>512*1024**2:raise ValueError('bounded_private_view_required')
    pending=path.with_suffix('.pending')
    with pending.open('wb') as handle:
        handle.write(payload);handle.flush();os.fsync(handle.fileno())
    pending.chmod(0o600);os.replace(pending,path)
    manifest=dict(version='owned-native-live-view-handoff-v1',path=path.name,bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),cutoff_ns=cutoff_ns,capture_id=str(capture_id),
        reader_commit=reader_commit,health=service.source_health(cutoff_ns),
        scope='PRIVATE_TYPED_ADMITTED_STATE; NO_SDK_OR_CREDENTIALS')
    manifest_path=Path(str(path)+'.manifest.json');atomic_json(manifest_path,manifest)
    return manifest_path


def read_view_input(manifest_path,*,capture_id,reader_commit):
    """Whitelist classes and bind owner/bytes/hash/source/capture before decoding."""
    import hashlib,io,os,pickle,stat
    from pathlib import Path
    from decimal import Decimal
    from types import SimpleNamespace
    from collections import OrderedDict
    from monatise.research.institutional.models import Contract,Source,MarketObservation
    from monatise.research.databento.datasets import InstrumentMetadata
    from monatise.research.databento.candles import HistoricalBar,ExchangeCalendar
    from monatise.research.databento.bar_coverage import NativeBarCoverage,HistoricalBarCoverage
    from monatise.research.databento.live_models import ClockReview
    from monatise.research.phase10.source import read_json
    manifest_path=Path(manifest_path);manifest=read_json(manifest_path)
    if (manifest['version']!='owned-native-live-view-handoff-v1' or manifest['capture_id']!=str(capture_id)
            or manifest['reader_commit']!=reader_commit):raise ValueError('view_handoff_identity_mismatch')
    path=manifest_path.parent/manifest['path'];info=path.lstat()
    if (path.parent!=manifest_path.parent or path.is_symlink() or not stat.S_ISREG(info.st_mode)
            or info.st_uid!=os.getuid() or info.st_mode&0o077 or not 1<=info.st_size<=512*1024**2):
        raise ValueError('owned_private_view_file_required')
    payload=path.read_bytes()
    if len(payload)!=manifest['bytes'] or hashlib.sha256(payload).hexdigest()!=manifest['sha256']:
        raise ValueError('view_handoff_hash_mismatch')
    classes=(SimpleNamespace,OrderedDict,Decimal,NativeInformationGate,Contract,Source,MarketObservation,
        InstrumentMetadata,HistoricalBar,ExchangeCalendar,NativeBarCoverage,HistoricalBarCoverage,ClockReview)
    allowed={(c.__module__,c.__name__):c for c in classes}
    class Decoder(pickle.Unpickler):
        def find_class(self,module,name):
            try:return allowed[(module,name)]
            except KeyError:raise ValueError('unapproved_view_handoff_class') from None
    pipeline=Decoder(io.BytesIO(payload)).load()
    if type(pipeline) is not SimpleNamespace:raise ValueError('typed_native_view_required')
    return freeze_service(pipeline,manifest['health']),manifest


def main(argv=None):
    import argparse,json
    from pathlib import Path
    p=argparse.ArgumentParser(description='Separate native chart calculation process; no provider client')
    p.add_argument('--input-manifest',required=True);p.add_argument('--capture-id',required=True)
    p.add_argument('--reader-commit',required=True);p.add_argument('--chart',required=True)
    p.add_argument('--cache',required=True);p.add_argument('--result',required=True)
    args=p.parse_args(argv)
    pin=Path(__file__).resolve().parents[3]/'.source-commit'
    if not pin.is_file() or pin.read_text().strip()!=args.reader_commit:raise ValueError('pinned_view_process_source_required')
    service,manifest=read_view_input(args.input_manifest,capture_id=args.capture_id,reader_commit=args.reader_commit)
    result=publish_view(service,cutoff_ns=manifest['cutoff_ns'],capture_id=args.capture_id,
        reader_commit=args.reader_commit,chart_path=args.chart,cache_path=args.cache)
    result['process_isolation']='SEPARATE_OS_PROCESS; NO_PROVIDER_CONNECTION'
    result['input_sha256']=manifest['sha256'];atomic_json(args.result,result)
    return 0


if __name__=='__main__':raise SystemExit(main())
