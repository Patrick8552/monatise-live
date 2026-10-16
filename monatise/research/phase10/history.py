"""Explicit, source-bound historical warm-up; never repairs a live-soak gap."""
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
import hashlib
from pathlib import Path

from monatise.research.databento.candles import ExchangeCalendar, HistoricalBar, WIDTHS, normalize_candle
from monatise.research.institutional.models import digest
from monatise.research.institutional.normalize import observation
from monatise.research.phase9.quality import PlausibilityPolicy, QualityGate
from .source import read_json


def _file(source, maximum):
    path=Path(source['path'])
    if path.is_symlink() or not path.is_file() or path.stat().st_size>maximum:
        raise ValueError('bounded_regular_history_file_required')
    with path.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=source['sha256']:
            raise ValueError('history_native_file_hash_mismatch')
    return path


@dataclass(frozen=True)
class JoinedBar:
    """A complete parent holding its actual immutable native minute children."""
    children: tuple
    timeframe: str
    calendar: ExchangeCalendar
    coverage_reviews: tuple = ()

    def __post_init__(self):
        if not self.children or self.timeframe not in WIDTHS:
            raise ValueError('complete_native_children_required')
        rows=self.children; width=WIDTHS[self.timeframe];start=rows[0].open_ns//width*width
        from monatise.research.databento.bar_coverage import NativeBarCoverage,HistoricalBarCoverage
        if not isinstance(self.coverage_reviews,tuple) or any(not isinstance(r,(NativeBarCoverage,HistoricalBarCoverage)) for r in self.coverage_reviews):
            raise ValueError('typed_native_or_historical_coverage_required')
        proofs=tuple(r for r in self.coverage_reviews if r.covers(
            (rows[0].identity.dataset,rows[0].identity.publisher_id,rows[0].identity.instrument_id,rows[0].identity.raw_symbol,rows[0].identity.expiration_ns),
            'ohlcv-1m',start,start+width))
        if len(proofs)!=len(self.coverage_reviews):raise ValueError('coverage_does_not_cover_exact_parent')
        if ((not proofs and (len(rows)!=width//WIDTHS['1m'] or rows[0].open_ns%width))
                or any(not isinstance(b,HistoricalBar) or b.timeframe!='1m'
                       or b.identity!=rows[0].identity for b in rows)
                or any(a.close_ns>b.open_ns or not proofs and a.close_ns!=b.open_ns for a,b in zip(rows,rows[1:]))
                or any(not start<=b.open_ns<b.close_ns<=start+width for b in rows)
                or not self.calendar.contains(start,start+width)):
            raise ValueError('missing_mixed_or_out_of_session_history_children')
        kinds={b.evidence_kind for b in rows}
        if len(kinds)>1 and not kinds<={'AUTHENTIC_HISTORICAL_DOWNLOAD','AUTHENTIC_LIVE_CAPTURE'}:
            raise ValueError('synthetic_authentic_history_mixing_forbidden')

    @property
    def identity(self):return self.children[0].identity
    @property
    def open_ns(self):return self.children[0].open_ns//WIDTHS[self.timeframe]*WIDTHS[self.timeframe]
    @property
    def close_ns(self):return self.open_ns+WIDTHS[self.timeframe]
    @property
    def prices_fixed(self):
        return (self.children[0].prices_fixed[0],max(b.prices_fixed[1] for b in self.children),
                min(b.prices_fixed[2] for b in self.children),self.children[-1].prices_fixed[3])
    @property
    def volume(self):return sum(b.volume for b in self.children)
    @property
    def retrieval_ns(self):return max([b.retrieval_ns for b in self.children]+[r.available_ns for r in self.coverage_reviews])
    @property
    def source_hashes(self):return tuple(h for b in self.children for h in b.source_hashes)
    @property
    def evidence_kind(self):
        kinds={b.evidence_kind for b in self.children}
        return next(iter(kinds)) if len(kinds)==1 else 'MIXED_AUTHENTIC_HISTORY_AND_LIVE'
    @property
    def clock_review(self):return max(self.children,key=lambda b:b.retrieval_ns).clock_review
    @property
    def schema(self):return 'derived-ohlcv-v1'


def join_minutes(historical, live):
    rows={b.open_ns:b for b in historical}
    if len(rows)!=len(historical):raise ValueError('duplicate_historical_minute')
    for bar in live:
        previous=rows.get(bar.open_ns)
        if previous and (previous.identity!=bar.identity or previous.prices_fixed!=bar.prices_fixed
                         or previous.volume!=bar.volume or previous.source_hashes!=bar.source_hashes):
            raise ValueError('historical_live_overlap_revision')
        rows[bar.open_ns]=bar
    return tuple(rows[k] for k in sorted(rows))


def complete_parents(minutes, target, calendar, *, coverage_reviews=()):
    width=WIDTHS[target];groups=defaultdict(list);rejected=[];result=[]
    for bar in minutes:groups[bar.open_ns//width*width].append(bar)
    for start,children in sorted(groups.items()):
        proofs=tuple(r for r in coverage_reviews if r.start_ns<=start<start+width<=r.end_ns and r.schema=='ohlcv-1m'
            and r.identity[2]==children[0].identity.instrument_id)
        missing=len(children)!=width//WIDTHS['1m']
        try:result.append(JoinedBar(tuple(children),target,calendar,proofs[:1] if missing else ()))
        except ValueError:
            rejected.append(dict(open_ns=start,reason='MISSING_CHILD_OR_REVIEWED_PARTIAL_SESSION_BUCKET'))
    return tuple(result),rejected


class _CombinedGate:
    def __init__(self,live,historical):self.live,self.historical=live,historical
    def __getattr__(self,name):return getattr(self.live,name)
    def lineage_observations(self):
        yield from self.historical.lineage_observations()
        yield from self.live.lineage_observations()


class WarmedPipeline:
    def __init__(self,pipeline,history):
        self.pipeline,self.history=pipeline,history;self.gates=pipeline.gates

    def analyse(self,iid,*,now_ns,mandatory,requested):
        try:return self._analyse(iid,now_ns=now_ns,mandatory=mandatory,requested=requested)
        except (ValueError,TypeError,KeyError,ArithmeticError) as exc:
            result=self.pipeline.analyse(iid,now_ns=now_ns,mandatory=mandatory,requested=requested)
            result['history_warmup']=dict(status='REJECTED_HISTORY_JOIN',reason=str(exc),
                manifest_sha256=self.history['manifest_sha256'],live_soak_gap_repaired=False)
            result['reproducibility_sha256']=digest({k:v for k,v in result.items() if k!='reproducibility_sha256'})
            return result

    def _analyse(self,iid,*,now_ns,mandatory,requested):
        bundle=self.history;live=self.gates[iid];history=bundle['gates'][iid]
        if history.faults or now_ns<bundle['available_ns']:
            result=self.pipeline.analyse(iid,now_ns=now_ns,mandatory=mandatory,requested=requested)
            result['history_warmup']=dict(status='REJECTED_OR_NOT_AVAILABLE',faults=dict(history.faults),
                manifest_sha256=bundle['manifest_sha256'],live_soak_gap_repaired=False)
            result['reproducibility_sha256']=digest({k:v for k,v in result.items() if k!='reproducibility_sha256'})
            return result
        calendar=bundle['calendars'][iid]
        frames={tf:tuple(v for _,v in sorted(series.items()) if v.close_ns+10*10**9<=now_ns
                         and v.retrieval_ns<=now_ns) for tf,series in self.pipeline.bars[iid].items()}
        frames['1m']=join_minutes(bundle['bars'][iid],frames.get('1m',()))
        frames['1m']=tuple(b for b in frames['1m'] if b.close_ns+10*10**9<=now_ns and b.retrieval_ns<=now_ns)
        diagnostics={}
        for tf in ('5m','15m','1h','4h'):
            frames[tf],diagnostics[tf]=complete_parents(frames['1m'],tf,calendar)
        from monatise.research.phase9.coordinator import NativeFuturesCoordinator
        result=NativeFuturesCoordinator().analyse(_CombinedGate(live,history),
            bars_by_timeframe={k:v for k,v in frames.items() if v},calendar=calendar,now_ns=now_ns,
            mandatory=mandatory,requested=requested,reviewed_history=True)
        result['history_warmup']=dict(status='VERIFIED_SEPARATE_ANALYTICAL_HISTORY',
            historical_minutes=len(bundle['bars'][iid]),manifest_sha256=bundle['manifest_sha256'],
            native_file_sha256=bundle['native_file_sha256'],available_ns=bundle['available_ns'],
            live_soak_gap_repaired=False,exchange_continuity_certified=False,
            calibration_training_input=False,parent_rejections=diagnostics)
        result['reproducibility_sha256']=digest({k:v for k,v in result.items() if k!='reproducibility_sha256'})
        return result


def load_history(manifest_path,*,pipeline,authorization_sha256,policy_hashes,cutoff_ns):
    """Verify native DBN, independent second/minute anchor and original policies.

    The manifest is explicitly reviewed operator input. No first-price fallback,
    threshold fitting, source timestamp rewriting, download or reconnect occurs.
    """
    import databento as db
    import databento_dbn as dn
    manifest=read_json(manifest_path);content=dict(manifest);sha=content.pop('manifest_sha256',None)
    if (manifest.get('version')!='reviewed-native-warmup-v1' or digest(content)!=sha
            or manifest['authorization_sha256']!=authorization_sha256 or not manifest['review_reference']
            or manifest['reviewed_at_ns']>cutoff_ns):
        raise ValueError('reviewed_source_bound_history_manifest_required')
    available=max(manifest['source']['retrieval_ns'],manifest['anchors']['retrieval_ns'],manifest['reviewed_at_ns'])
    if available>cutoff_ns:raise ValueError('historical_download_not_available_at_requested_cutoff')
    category=manifest.get('evidence_kind')
    if category not in {'AUTHENTIC_HISTORICAL_DOWNLOAD','ENGINEERING_SYNTHETIC'}:
        raise ValueError('explicit_history_evidence_kind_required')
    source_category='AUTHENTIC_ARCHIVED_RECORD' if category=='AUTHENTIC_HISTORICAL_DOWNLOAD' else category
    native=_file(manifest['source'],16*1024**2);anchors=_file(manifest['anchors'],1024**2)
    start,end=manifest['start_ns'],manifest['end_ns']
    if not 0<end-start<=7*86400*10**9 or start%WIDTHS['1m'] or end%WIDTHS['1m']:
        raise ValueError('bounded_aligned_warmup_history_required')
    first={};anchor_count=0
    for row in db.DBNStore.from_file(anchors):
        anchor_count+=1
        if anchor_count>1000 or not isinstance(row,dn.OHLCVMsg) or row.rtype!=dn.RType.OHLCV_1S:
            raise ValueError('invalid_native_anchor_source')
        if row.instrument_id not in pipeline.gates:raise ValueError('unrequested_history_anchor_identity')
        c=pipeline.gates[row.instrument_id].contract
        normalize_candle(row,schema='ohlcv-1s',identity=c.metadata,retrieval_ns=manifest['anchors']['retrieval_ns'],evidence_kind=category)
        if not start<=row.ts_event<start+WIDTHS['1m']:raise ValueError('history_anchor_window_mismatch')
        if row.instrument_id not in first:first[row.instrument_id]=row
    if set(first)!=set(pipeline.gates):raise ValueError('exact_native_history_anchors_required')
    gates={};bars={iid:[] for iid in pipeline.gates};calendars={}
    for iid,live in pipeline.gates.items():
        c=live.contract;key=c.metadata.raw_symbol+':ohlcv-1m';p=dict(manifest['policies'][key]);p['scale']=Decimal(p['scale']);policy=PlausibilityPolicy(**p)
        if policy.sha256!=policy_hashes[key]:raise ValueError('warmup_cannot_relax_existing_price_policy')
        anchor=first[iid]
        if anchor.ts_event!=start:raise ValueError('native_anchor_must_match_first_minute_open')
        gates[iid]=QualityGate(c,policy,anchor=Decimal(anchor.open)/10**9,anchor_ns=start,
            anchor_sha256=hashlib.sha256(bytes(anchor)).hexdigest(),capacity=20000)
        cal=dict(manifest['calendars'][c.metadata.exchange]);cal['intervals']=tuple(tuple(v) for v in cal['intervals']);calendars[iid]=ExchangeCalendar(**cal)
        if calendars[iid].exchange!=c.metadata.exchange:raise ValueError('history_calendar_exchange_mismatch')
    seen=set();started=set();count=0
    for ordinal,row in enumerate(db.DBNStore.from_file(native)):
        count+=1
        if (count>20000 or not isinstance(row,dn.OHLCVMsg) or row.rtype!=dn.RType.OHLCV_1M
                or row.instrument_id not in gates):raise ValueError('history_row_budget_or_identity_mismatch')
        iid=row.instrument_id;gate=gates[iid]
        if not start<=row.ts_event<end or (iid,row.ts_event) in seen:raise ValueError('duplicate_or_out_of_scope_history_minute')
        if iid not in started and (row.ts_event!=start or row.open!=first[iid].open):
            raise ValueError('independent_native_anchor_disagrees_with_minute')
        started.add(iid)
        seen.add((iid,row.ts_event))
        value=observation(row,schema='ohlcv-1m',contract=gate.contract,archive_sha256=manifest['source']['sha256'],
            ordinal=ordinal,retrieval_ns=manifest['source']['retrieval_ns'],admission_ns=available,
            evidence_kind=source_category,enabled_schemas=('ohlcv-1m',))
        result=gate.ingest(value,now_ns=cutoff_ns)
        if result['accepted']:
            bar=normalize_candle(row,schema='ohlcv-1m',identity=gate.contract.metadata,
                retrieval_ns=available,evidence_kind=category)
            if not calendars[iid].contains(bar.open_ns,bar.close_ns):raise ValueError('historical_bar_outside_reviewed_calendar')
            bars[iid].append(bar)
    if (not count or count!=manifest['source']['records'] or any(not v for v in bars.values())):
        raise ValueError('historical_minutes_missing_or_record_count_mismatch')
    return dict(gates=gates,bars={k:tuple(v) for k,v in bars.items()},calendars=calendars,
                available_ns=available,manifest_sha256=sha,native_file_sha256=manifest['source']['sha256'])
