"""Event-time trade candles with explicit coverage, no empty-period invention."""
from dataclasses import dataclass
from decimal import Decimal

from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.databento.candles import HistoricalBar, WIDTHS
from monatise.research.institutional.models import MarketObservation, digest, hash_required


@dataclass(frozen=True)
class CoverageReview:
    start_ns: int
    end_ns: int
    available_ns: int
    source_sha256: str
    review_reference: str

    def __post_init__(self):
        for t in (self.start_ns,self.end_ns,self.available_ns): timestamp_ns(t)
        hash_required(self.source_sha256)
        if not self.start_ns < self.end_ns <= self.available_ns or not self.review_reference:
            raise ValueError('causal_captured_window_review_required')


class ContinuousCandles:
    """A complete bucket means complete *reviewed captured window*, never exchange continuity.

    A heartbeat or the last trade does not prove coverage. Caller must establish a
    reviewed watermark. Late events retract the affected bucket on the next view.
    Consumers must obtain a new snapshot after ingest; old snapshots are historical.
    """
    def __init__(self, contract, calendar, *, capacity=50000):
        if ((contract.metadata.dataset,contract.metadata.exchange) != (calendar.dataset,calendar.exchange)
                or type(capacity) is not int or not 1 <= capacity <= 100000):
            raise ValueError('bounded_exact_contract_calendar_required')
        self.contract, self.calendar, self.capacity = contract, calendar, capacity
        self.rows, self.positions, self.tainted = [], {}, set()
        self.watermark = 0

    def ingest(self, value):
        if not isinstance(value,MarketObservation) or value.contract != self.contract or value.schema != 'trades':
            raise ValueError('validated_exact_contract_trade_required')
        prior = self.positions.get(value.source.position)
        if prior is not None:
            if prior != digest(value): raise ValueError('trade_revision_rejected')
            return False
        if len(self.rows) >= self.capacity: raise ValueError('candle_capacity_exceeded')
        if not self.calendar.contains(value.event_ns,value.event_ns+1): raise ValueError('trade_outside_reviewed_session')
        self.positions[value.source.position] = digest(value)
        if value.event_ns < self.watermark:
            for tf,w in WIDTHS.items(): self.tainted.add((tf,value.event_ns//w*w))
        self.rows.append(value)
        return True

    def view(self, timeframe, *, review, now_ns):
        timestamp_ns(now_ns)
        width = WIDTHS[timeframe]
        if review.available_ns > now_ns or review.end_ns < self.watermark:
            raise ValueError('future_or_regressed_watermark')
        self.watermark = review.end_ns
        groups = {}
        for value in self.rows:
            if review.start_ns <= value.event_ns < review.end_ns and value.source.admission_ns <= now_ns:
                start = value.event_ns//width*width
                groups.setdefault(start,[]).append(value)
        output, rejected = [], []
        for start, values in sorted(groups.items()):
            end = start+width
            reason = ('PARTIAL_CAPTURE_WINDOW' if start < review.start_ns or end > review.end_ns else
                      'LATE_EVENT_REQUIRES_REVIEW' if (timeframe,start) in self.tainted else
                      'PARTIAL_SESSION_BOUNDARY' if not self.calendar.contains(start,end) else None)
            if reason:
                rejected.append(dict(open_ns=start,reason=reason)); continue
            values.sort(key=lambda x:(x.event_ns,x.receive_ns or x.event_ns,x.source.ordinal))
            if len({v.source.evidence_kind for v in values}) != 1: raise ValueError('mixed_evidence_categories')
            prices = [int(Decimal(v.payload[0])*10**9) for v in values]
            category = values[0].source.evidence_kind
            category = 'AUTHENTIC_HISTORICAL_DOWNLOAD' if category == 'AUTHENTIC_ARCHIVED_RECORD' else category
            output.append(HistoricalBar(self.contract.metadata,timeframe,start,end,
                (prices[0],max(prices),min(prices),prices[-1]),sum(v.payload[1] for v in values),
                max(review.available_ns,max(v.source.retrieval_ns for v in values)),
                tuple(v.source.record_sha256 for v in values),'derived-ohlcv-v1',category))
        # Absence could mean no executions or missing capture, never a synthetic flat bar.
        missing = []
        first = (review.start_ns+width-1)//width*width
        if (review.end_ns-first)//width > 100000: raise ValueError('bounded_candle_view_required')
        for start in range(first,review.end_ns-width+1,width):
            if start not in groups and self.calendar.contains(start,start+width): missing.append(start)
        return tuple(output), dict(timeframe=timeframe, watermark_ns=review.end_ns,
            coverage_sha256=digest(review), coverage='REVIEWED_CAPTURED_WINDOW_ONLY',
            complete_exchange_continuity=False, missing_or_no_trade_intervals=missing,
            rejected=rejected, gap_fill_count=0, price_clock='EXCHANGE_EVENT_TIME',
            provider_ohlcv_equivalence=False, forming_trade_count=sum(v.event_ns >= review.end_ns for v in self.rows))


def aggregate_complete(bars, *, target, calendar, coverage_reviews=()):
    """Observed OHLCV plus proven provider-empty children; never flat fills.

    Without explicit source-bound coverage, every child remains mandatory.
    Event-time trade-derived bars cannot use receive-time provider coverage.
    """
    from monatise.research.databento.bar_coverage import NativeBarCoverage,HistoricalBarCoverage
    rows = tuple(bars)
    if not rows or len(rows) > 100000: raise ValueError('bounded_bar_input_required')
    source = rows[0].timeframe
    identity=(rows[0].identity.dataset,rows[0].identity.publisher_id,rows[0].identity.instrument_id,
        rows[0].identity.raw_symbol,rows[0].identity.expiration_ns)
    reviews=tuple(coverage_reviews)
    if len(reviews)>100000 or any(not isinstance(r,(NativeBarCoverage,HistoricalBarCoverage)) for r in reviews):raise ValueError('bounded_native_coverage_reviews_required')
    # Select the latest compatible session proof before visiting parent buckets.
    latest={}
    for r in reviews:
        key=(r.identity,r.schema,r.start_ns)
        if key not in latest or r.end_ns>latest[key].end_ns:latest[key]=r
    reviews=tuple(latest.values())
    step,width = WIDTHS[source],WIDTHS[target]
    if width <= step or width % step: raise ValueError('larger_multiple_timeframe_required')
    seen = {}
    for bar in rows:
        if (bar.identity != rows[0].identity or bar.timeframe != source or
                bar.evidence_kind != rows[0].evidence_kind or bar.open_ns in seen):
            raise ValueError('duplicate_mixed_contract_or_roll_boundary')
        if not calendar.contains(bar.open_ns,bar.close_ns): raise ValueError('bar_outside_reviewed_session')
        seen[bar.open_ns] = bar
    output,rejected = [],[]
    for start in sorted({t//width*width for t in seen}):
        end = start+width
        children = [seen[t] for t in range(start,end,step) if t in seen]
        missing=[t for t in range(start,end,step) if t not in seen]
        inherited={r.sha256:r for b in children for r in getattr(b,'coverage_reviews',())}
        possible=tuple({r.sha256:r for r in (*reviews,*inherited.values())}.values())
        proofs=tuple(r for r in possible if r.identity==identity and r.start_ns<=start<end<=r.end_ns
            and (r.schema=='ohlcv-'+source or r.sha256 in inherited)) if missing or inherited else ()
        native_only=all(b.schema=='ohlcv-'+source for b in children)
        in_session=(calendar.valid_from_ns<=start<end<=calendar.valid_to_ns and calendar.contains(start,end))
        if (not in_session or missing and (not proofs or not native_only)
                or inherited and not proofs):
            rejected.append(dict(open_ns=start,reason='MISSING_CHILD_OR_SESSION_EDGE'));continue
        if not children:continue
        proofs=proofs[:1]
        retrieved=max([v.retrieval_ns for v in children]+[r.available_ns for r in proofs])
        output.append(HistoricalBar(rows[0].identity,target,start,end,
            (children[0].prices_fixed[0],max(v.prices_fixed[1] for v in children),
             min(v.prices_fixed[2] for v in children),children[-1].prices_fixed[3]),
            sum(v.volume for v in children),retrieved,
            tuple(h for v in children for h in v.source_hashes),'derived-ohlcv-v1',rows[0].evidence_kind,
            proofs[0].clock_review if proofs and retrieved==proofs[0].available_ns else max(children,key=lambda v:v.retrieval_ns).clock_review,proofs))
    return tuple(output),tuple(rejected)
