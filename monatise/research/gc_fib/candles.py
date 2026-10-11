"""Integer-clock native OHLCV ingestion and conservative UTC-grid aggregation.

No synthetic empty minutes, carry-forward, contract roll or spot conversion.
Reviewed exchange sessions must be supplied; this is NOT GoldSessionCalendar.
Missing minutes are unknown (possibly no trades), never certified data gaps.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal

from monatise.research.broker_xauusd.models import digest as canonical_hash


def timestamp_ns(value):
    # This offline interface cannot import Phase 2's adapters into the older
    # pinned selector interpreter. Native clocks are validated again at ingress.
    if type(value) is not int or not 0 < value < 2**63:
        raise ValueError("positive integer nanosecond timestamp required")
    return value

MINUTE = 60 * 10**9
INTERVALS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400}


@dataclass(frozen=True)
class GCIdentity:
    dataset: str = "GLBX.MDP3"
    raw_symbol: str = "GCZ6"
    publisher_id: int = 1
    instrument_id: int = 41271
    economic_exchange: str = "XCEC"

    def __post_init__(self):
        if asdict(self) != dict(dataset="GLBX.MDP3", raw_symbol="GCZ6", publisher_id=1,
                               instrument_id=41271, economic_exchange="XCEC"):
            raise ValueError("exact independently verified GCZ6 identity required")


@dataclass(frozen=True)
class GCSession:
    start_ns: int
    end_ns: int
    review_reference: str

    def __post_init__(self):
        timestamp_ns(self.start_ns); timestamp_ns(self.end_ns)
        if self.start_ns >= self.end_ns or self.start_ns % MINUTE or self.end_ns % MINUTE:
            raise ValueError("reviewed minute-aligned session boundaries required")
        if not self.review_reference.strip():
            raise ValueError("external session review reference required")


@dataclass(frozen=True)
class GCBar:
    identity: GCIdentity
    timeframe: str
    open_ns: int
    close_ns: int
    assumed_available_ns: int
    retrieval_ns: int
    admission_ns: int
    open: str
    high: str
    low: str
    close: str
    volume: int
    source_hashes: tuple[str, ...]
    evidence_kind: str
    availability_basis: str = "RETROSPECTIVE_CLOSE_PLUS_10S_ASSUMPTION"

    def __post_init__(self):
        if not isinstance(self.identity, GCIdentity) or not isinstance(self.source_hashes, tuple):
            raise ValueError("typed immutable GC identity and source hashes required")
        for t in (self.open_ns, self.close_ns, self.assumed_available_ns, self.retrieval_ns, self.admission_ns):
            timestamp_ns(t)
        width = INTERVALS.get(self.timeframe, 0) * 10**9
        if not width or self.open_ns % width or self.close_ns - self.open_ns != width:
            raise ValueError("native UTC-grid interval required")
        if self.assumed_available_ns != self.close_ns + 10 * 10**9:
            raise ValueError("explicit immutable retrospective availability assumption required")
        if self.retrieval_ns > self.admission_ns or self.close_ns > self.retrieval_ns:
            raise ValueError("retrieval/admission/finalization clocks inconsistent")
        values = [Decimal(p) for p in (self.open, self.high, self.low, self.close)]
        if any(not p.is_finite() or p <= 0 for p in values):
            raise ValueError("finite positive GC price required")
        o,h,l,c = values
        if not l <= min(o,c) <= max(o,c) <= h or type(self.volume) is not int or self.volume < 0:
            raise ValueError("invalid OHLCV")
        if self.evidence_kind not in {"ENGINEERING_SYNTHETIC", "AUTHENTIC_HISTORICAL_DOWNLOAD"}:
            raise ValueError("separate research evidence category required")
        if (not self.source_hashes or any(len(s) != 64 or any(c not in "0123456789abcdef" for c in s)
                                          for s in self.source_hashes)):
            raise ValueError("immutable raw-source SHA256 required")

    @property
    def sha256(self):
        return canonical_hash(asdict(self))


def from_observation(observation, *, identity, retrieval_ns, admission_ns):
    """Consumes Phase 2 normalized observations AFTER authentic definition validation."""
    if (observation.dataset != identity.dataset or observation.schema != "ohlcv-1m"
        or observation.namespace != "COMEX:GC:" + identity.raw_symbol
        or (observation.publisher_id, observation.instrument_id) != (identity.publisher_id, identity.instrument_id)
        or observation.historical_retrieval_ns != retrieval_ns or observation.ingestion_ns != admission_ns):
        raise ValueError("validated native Phase 2 OHLCV identity/clocks required")
    if len(observation.payload) != 5:
        raise ValueError("native OHLCV payload required")
    o,h,l,c,v = observation.payload
    if any(type(p) is not int for p in (o,h,l,c)) or type(v) is not int:
        raise ValueError("native integer DBN prices and volume required")
    if any(not 0 < p < 2**63-1 for p in (o,h,l,c)):
        raise ValueError("undefined/invalid native prices quarantined")
    prices = tuple(str(Decimal(p) / Decimal(10**9)) for p in (o,h,l,c))
    return GCBar(identity, "1m", observation.event_ns, observation.event_ns+MINUTE,
                 observation.event_ns+MINUTE+10*10**9, retrieval_ns, admission_ns,
                 *prices, v, (observation.record_sha256,), "AUTHENTIC_HISTORICAL_DOWNLOAD")


def aggregate(bars, *, sessions):
    rows = sorted(tuple(bars), key=lambda b: (b.open_ns, b.sha256))
    sessions = tuple(sorted(sessions, key=lambda s: s.start_ns))
    if not rows or not sessions or len(rows) > 1_000_000:
        raise ValueError("bounded minute data and reviewed GC sessions required")
    if any(a.end_ns > b.start_ns for a,b in zip(sessions, sessions[1:])):
        raise ValueError("overlapping sessions")
    identity, category = rows[0].identity, rows[0].evidence_kind
    unique, rejected, output = {}, [], {tf: [] for tf in INTERVALS}
    for bar in rows:
        if bar.identity != identity or bar.timeframe != "1m" or bar.evidence_kind != category:
            raise ValueError("no mixed contracts, timeframes or evidence categories")
        if bar.open_ns in unique:
            if unique[bar.open_ns] != bar:
                raise ValueError("conflicting candle revision quarantined; no overwrite")
            continue
        if not any(s.start_ns <= bar.open_ns < bar.close_ns <= s.end_ns for s in sessions):
            raise ValueError("record outside reviewed exchange session")
        unique[bar.open_ns] = bar
    rows = sorted(unique.values(), key=lambda b: b.open_ns)
    output["1m"] = rows
    for tf, seconds in INTERVALS.items():
        if tf == "1m": continue
        width, groups = seconds*10**9, {}
        for bar in rows:
            start = bar.open_ns // width * width
            groups.setdefault(start, []).append(bar)
        for start, children in sorted(groups.items()):
            end = start+width
            if not any(s.start_ns <= start < end <= s.end_ns for s in sessions):
                rejected.append({"timeframe":tf,"open_ns":start,"reason":"PARTIAL_SESSION_BOUNDARY"}); continue
            missing = [t for t in range(start,end,MINUTE) if t not in unique]
            if missing:
                rejected.append({"timeframe":tf,"open_ns":start,"reason":"MISSING_OR_NO_TRADE_MINUTES_UNCERTIFIED",
                                 "missing_ns":missing}); continue
            output[tf].append(GCBar(identity,tf,start,end,end+10*10**9,
                max(b.retrieval_ns for b in children),max(b.admission_ns for b in children),
                children[0].open,str(max(Decimal(b.high) for b in children)),
                str(min(Decimal(b.low) for b in children)),children[-1].close,
                sum(b.volume for b in children),tuple(h for b in children for h in b.source_hashes),category))
    return output, tuple(rejected)
