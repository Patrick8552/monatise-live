"""Source-bound proof of a complete captured provider OHLCV interval, not a fill.

Only an acknowledged, replay-complete, fault-free stream with an actual native
END_OF_INTERVAL can issue this review. It proves the captured provider subset,
not independent exchange completeness. A heartbeat alone never qualifies.
"""
from dataclasses import dataclass

from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.institutional.models import digest, hash_required


@dataclass(frozen=True)
class NativeBarCoverage:
    identity: tuple
    schema: str
    start_ns: int
    end_ns: int
    available_ns: int
    marker_sha256: str
    prefix_sha256: str
    review_reference: str
    clock_review: object | None = None

    def __post_init__(self):
        from .candles import WIDTHS
        for t in (self.start_ns,self.end_ns,self.available_ns):timestamp_ns(t)
        for h in (self.marker_sha256,self.prefix_sha256):hash_required(h)
        if self.clock_review is not None:self.clock_review.bounds(self.available_ns)
        step=WIDTHS.get(self.schema.removeprefix('ohlcv-'))
        if (self.schema not in {'ohlcv-1s','ohlcv-1m','ohlcv-1h'} or not isinstance(self.identity,tuple)
                or len(self.identity)!=5 or not self.review_reference or not step
                or self.start_ns%step or self.end_ns%step or not self.start_ns<self.end_ns<=self.available_ns):
            raise ValueError('exact_finalized_native_bar_coverage_required')
        dataset,publisher,iid,symbol,expires=self.identity
        timestamp_ns(expires)
        if (dataset!='GLBX.MDP3' or type(publisher) is not int or publisher<=0 or type(iid) is not int or iid<=0
                or not isinstance(symbol,str) or not symbol or self.end_ns>expires):raise ValueError('exact_native_coverage_identity_required')

    @property
    def sha256(self):return digest(self)

    def covers(self,identity,schema,start,end):
        return self.identity==identity and self.schema==schema and self.start_ns<=start<end<=self.end_ns


def review_native_coverage(state,gate,schema, *, now_ns,source_reference):
    """Issue from current control evidence after raw+spool+cursor commits."""
    from .candles import WIDTHS
    iid=gate.contract.metadata.instrument_id
    health=state.health(now_ns)
    marker=state.interval_receipts.get(schema)
    if (not marker or schema not in state.acknowledged or schema not in state.completed
            or iid not in state.verified_definitions or state.quality_reasons
            or state.component_reasons.get((schema,iid)) or health['stalled_connections']
            or schema in gate.faults):return None
    step=WIDTHS[schema[6:]]
    captured_start=state.coverage_start_ns.get(f'{schema}:{iid}',state.scope.start_ns)
    start=(captured_start+step-1)//step*step
    end=marker['event_ns']
    lower,_=state.clock_review.bounds(now_ns) if state.clock_review else (0,0)
    if end<=start or end>now_ns+min(0,lower):return None
    return NativeBarCoverage(gate.contract.identity,schema,start,end,now_ns,
        marker['record_sha256'],digest(state.checkpoint()),source_reference,state.clock_review)
