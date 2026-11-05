"""Immutable inputs and canonical identities; decimal prices, explicit clocks."""
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal, Context, localcontext, ROUND_HALF_EVEN, InvalidOperation, DivisionByZero, Overflow
from enum import StrEnum
from hashlib import sha256
import json
import re
from functools import wraps, cached_property

NS = 10**9
MINUTE = 60*NS
WIDTHS = {'1m': MINUTE, '5m': 5*MINUTE, '15m': 15*MINUTE, '1h': 60*MINUTE, '4h': 240*MINUTE}
TERMINAL = frozenset({'INVALIDATED', 'EXPIRED', 'SUPERSEDED'})


def fixed_decimal(function):
    """Decisions cannot depend on a caller's ambient decimal precision/traps."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        with localcontext(Context(prec=40, rounding=ROUND_HALF_EVEN,
                                  Emin=-999999, Emax=999999,
                                  traps=[InvalidOperation, DivisionByZero, Overflow])):
            return function(*args, **kwargs)
    return wrapped


def dec(value):
    if isinstance(value, bool):
        raise ValueError('boolean_is_not_a_price')
    d = Decimal(str(value))
    if not d.is_finite():
        raise ValueError('finite_decimal_required')
    return d


def encode(value):
    if isinstance(value, Decimal):
        return format(value, 'f')
    if is_dataclass(value):
        return {f.name: encode(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(encode(v) for v in value)
    return value


def canonical(value):
    return json.dumps(encode(value), sort_keys=True, separators=(',', ':'), allow_nan=False)


def identity(kind, *values):
    return kind + ':' + sha256(canonical(values).encode()).hexdigest()


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


class Side(StrEnum):
    BUY = 'BUY'
    SELL = 'SELL'

    @property
    def sign(self):
        return Decimal(1 if self == Side.BUY else -1)


class State(StrEnum):
    UP = 'UP'
    DOWN = 'DOWN'
    NEUTRAL = 'NEUTRAL_RANGE'
    MIXED = 'MIXED_TRANSITION'
    UNAVAILABLE = 'UNAVAILABLE'


@dataclass(frozen=True)
class Instrument:
    dataset: str
    venue: str
    publisher_id: int
    instrument_id: int
    symbol: str
    product: str
    expiry_ns: int
    tick: Decimal
    multiplier: Decimal
    definition_hash: str
    currency: str = 'USD'
    price_unit: str = 'NATIVE_CONTRACT_QUOTATION'

    def __post_init__(self):
        terms = {'GC': ('XCEC', Decimal('.1'), Decimal('100')),
                 'BTC': ('XCME', Decimal('5'), Decimal('5')),
                 'ES': ('XCME', Decimal('.25'), Decimal('50')),
                 'NQ': ('XCME', Decimal('.25'), Decimal('20'))}
        if (self.dataset != 'GLBX.MDP3' or self.product not in terms or self.currency != 'USD' or not self.price_unit
                or (self.venue, self.tick, self.multiplier) != terms.get(self.product)
                or self.instrument_id <= 0 or self.publisher_id <= 0 or self.expiry_ns <= 0
                or len(self.definition_hash) != 64 or re.fullmatch(self.product+r'[FGHJKMNQUVXZ][0-9]{1,2}', self.symbol) is None):
            raise ValueError('reviewed_exact_native_definition_required')

    @cached_property
    def key(self):
        # Metadata revision/capture packaging is provenance, not market identity.
        return identity('contract-v1', self.dataset, self.publisher_id, self.instrument_id,
                        self.symbol, self.expiry_ns)


@dataclass(frozen=True)
class Bar:
    contract: str
    timeframe: str
    open_ns: int
    close_ns: int
    available_ns: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    source: str
    quality: tuple[str, ...] = ()

    def __post_init__(self):
        if (self.timeframe not in WIDTHS or self.close_ns-self.open_ns != WIDTHS[self.timeframe]
                or self.available_ns < self.close_ns or self.volume < 0 or not self.source
                or not all(dec(v) > 0 for v in (self.open, self.high, self.low, self.close))
                or not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high):
            raise ValueError('invalid_completed_native_bar')

    @cached_property
    def key(self):
        return identity('bar-v1', self.contract, self.timeframe, self.open_ns)


@dataclass(frozen=True)
class Trade:
    contract: str
    event_ns: int
    receive_ns: int
    available_ns: int
    price: Decimal
    size: int
    aggressor: str | None
    source: str
    quality: tuple[str, ...] = ()
    raw_flags: int = 0
    sequence: int | None = None
    native_ordinal: int | None = None

    def __post_init__(self):
        if self.size <= 0 or dec(self.price) <= 0 or self.aggressor not in ('BUY', 'SELL', None):
            raise ValueError('invalid_execution')


@dataclass(frozen=True)
class Quote:
    contract: str
    receive_ns: int
    available_ns: int
    bid: Decimal
    ask: Decimal
    source: str
    quality: tuple[str, ...] = ()
    sequence: int | None = None
    native_ordinal: int | None = None
    raw_flags: int = 0

    def __post_init__(self):
        if not Decimal(0) < self.bid < self.ask:
            raise ValueError('two_sided_unlocked_quote_required')


def latest_quote(quotes):
    # Receive/admission clocks alone can tie within a native packet. Preserve
    # vendor sequence and physical source order rather than sorting source hashes.
    pair = max(enumerate(quotes), key=lambda v: (v[1].receive_ns,v[1].available_ns,
               v[1].sequence if v[1].sequence is not None else -1,
               v[1].native_ordinal if v[1].native_ordinal is not None else v[0],v[0]),default=None)
    return pair[1] if pair else None


@dataclass(frozen=True)
class QuoteUnavailable:
    """A native absent/locked/crossed BBO update; contains no invented prices."""
    contract: str
    receive_ns: int
    available_ns: int
    source: str
    quality: tuple[str, ...] = ('NATIVE_BBO_UNAVAILABLE',)
    sequence: int | None = None
    native_ordinal: int | None = None
    raw_flags: int = 0


def current_quote(snapshot):
    event = latest_quote(snapshot.quotes + snapshot.quote_invalidations)
    return event if isinstance(event, Quote) else None


@dataclass(frozen=True)
class Coverage:
    kind: str
    start_ns: int
    end_ns: int
    available_ns: int
    source: str

    def covers(self, start, end, cutoff):
        return self.start_ns <= start < end <= self.end_ns and self.available_ns <= cutoff


@dataclass(frozen=True)
class Schedule:
    intervals: tuple[tuple[int, int], ...]
    reference: str
    review_hash: str

    def __post_init__(self):
        if (not isinstance(self.intervals, tuple) or any(not isinstance(v,tuple) or len(v)!=2 for v in self.intervals)
                or not self.reference or len(self.review_hash) != 64 or not self.intervals):
            raise ValueError('dated_calendar_review_required')
        if any(a >= b for a, b in self.intervals) or any(a[1] > b[0] for a, b in zip(self.intervals, self.intervals[1:])):
            raise ValueError('ordered_nonoverlapping_calendar_required')

    def contains(self, start, end):
        return any(a <= start < end <= b for a, b in self.intervals)

    def closes_after(self, at):
        return next((b for a, b in self.intervals if a <= at < b), at)


@dataclass(frozen=True)
class News:
    start_ns: int
    end_ns: int
    available_ns: int
    event: str
    source: str


@dataclass(frozen=True)
class Snapshot:
    instrument: Instrument
    cutoff_ns: int
    bars: tuple[Bar, ...]
    trades: tuple[Trade, ...]
    quotes: tuple[Quote, ...]
    coverage: tuple[Coverage, ...]
    schedule: Schedule
    replay_mode: str
    manifest_hash: str
    news: tuple[News, ...] = ()
    news_coverage: bool = False
    quality: tuple[str, ...] = ()
    evidence_kind: str = 'GENUINE_NATIVE_ARCHIVE'
    quote_invalidations: tuple[QuoteUnavailable, ...] = ()

    def __post_init__(self):
        if type(self.news_coverage) is not bool:
            raise ValueError('explicit_news_coverage_boolean_required')
        if self.replay_mode not in ('AS_RECORDED', 'HISTORICAL_EVENT_TIME', 'ENGINEERING_FIXTURE'):
            raise ValueError('explicit_replay_mode_required')
        if len(self.manifest_hash) != 64 or self.cutoff_ns <= 0:
            raise ValueError('snapshot_provenance_required')
        for rows in (self.bars, self.trades, self.quotes, self.quote_invalidations):
            if not isinstance(rows, tuple) or any(x.contract != self.instrument.key for x in rows):
                raise ValueError('immutable_exact_contract_snapshot_required')
        if any(not isinstance(getattr(self,k),tuple) for k in ('coverage','news','quality')):
            raise ValueError('immutable_snapshot_metadata_required')
        if any(x.receive_ns>self.cutoff_ns for rows in (self.trades,self.quotes,self.quote_invalidations) for x in rows):
            raise ValueError('future_provider_record_without_clock_review')
        # Future records may exist in an archive, never in an admitted snapshot.
        if any(x.available_ns > self.cutoff_ns for rows in (self.bars, self.trades, self.quotes,self.quote_invalidations) for x in rows):
            raise ValueError('future_record_in_snapshot')
        if any(b.close_ns > self.cutoff_ns for b in self.bars):
            raise ValueError('developing_bar_in_snapshot')

    @cached_property
    def hash(self):
        return digest(self)


@dataclass(frozen=True)
class Pivot:
    contract: str
    timeframe: str
    kind: str
    price: Decimal
    pivot_ns: int
    confirmed_ns: int
    available_ns: int
    source_ids: tuple[str, ...]

    @cached_property
    def key(self):
        return identity('pivot-v1', self.contract, self.timeframe, self.kind, self.pivot_ns, self.price)


@dataclass(frozen=True)
class Event:
    kind: str
    contract: str
    side: Side
    at_ns: int
    available_ns: int
    reference_id: str
    level: Decimal
    bar_id: str
    parent_ids: tuple[str, ...] = ()

    @cached_property
    def key(self):
        return identity('event-v1', self.contract, self.kind, self.side, self.at_ns,
                        self.reference_id, self.bar_id, self.parent_ids)


@dataclass(frozen=True)
class Observation:
    pathway: str
    side: Side
    origin: Event
    stage: str
    detected_ns: int
    armed_ns: int | None
    trigger: Event | None
    protected_level: Decimal
    stop_level: Decimal | None
    events: tuple[Event, ...]
    reasons: tuple[str, ...] = ()
    canonical: bool = True
    reset_epoch: int = 0

    @cached_property
    def opportunity_id(self):
        if not self.canonical:
            return None
        return identity('opportunity-v1', self.origin.contract, self.side,
                        self.origin.key, self.reset_epoch)

    @cached_property
    def key(self):
        return identity('observation-v1', self.pathway, self.origin.key, self.stage,
                        self.trigger.key if self.trigger else None, self.reasons, tuple(e.key for e in self.events))


@dataclass(frozen=True)
class Target:
    price: Decimal
    reference_id: str
    available_ns: int


@dataclass(frozen=True)
class Plan:
    opportunity_id: str
    side: Side
    entry: Decimal
    entry_low: Decimal
    entry_high: Decimal
    stop: Decimal
    targets: tuple[Target, ...]
    net_rr: tuple[Decimal, ...]
    initial_risk: Decimal
    round_trip_cost: Decimal
    cost_risk_ratio: Decimal
    lateness_ns: int
    trigger_id: str
    trigger_ns: int
    armed_ns: int
    expires_ns: int
    stop_reference: str
    evidence_ids: tuple[str, ...]
    cost_model: str
    spread_points: Decimal
    management: str = 'FULL_EXIT_FIRST_TARGET_FIXED_STOP'

    @cached_property
    def hash(self):
        return digest(self)


@dataclass(frozen=True)
class Candidate:
    observation: Observation
    plan: Plan | None
    reasons: tuple[str, ...]
    context_category: str = 'UNRESOLVED'

    @property
    def eligible(self):
        return self.plan is not None and not self.reasons
