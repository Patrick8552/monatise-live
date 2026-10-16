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
