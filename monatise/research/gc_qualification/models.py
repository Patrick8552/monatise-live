"""Native units and cutoff evidence, deliberately unrelated to broker lot sizing."""
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json

from monatise.research.gc_fib.candles import GCIdentity, timestamp_ns


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def hash_value(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("SHA256 lineage required")
    return value


def research_sources(root):
    """Bind the new adapter source separately from the audited canonical baseline."""
    from pathlib import Path
    folder = Path(root)/"monatise/research/gc_qualification"
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob("*.py"))}


@dataclass(frozen=True)
class NativeContract:
    identity: GCIdentity
    definition_sha256: str
    catalog_sha256: str
    definition_event_ns: int
    definition_receive_ns: int
    expiration_ns: int
    tick_size: str
    multiplier: str
    monetary_tick_usd: str
    native_terms: tuple

    def __post_init__(self):
        if not isinstance(self.identity, GCIdentity):
            raise ValueError("native GC identity required")
        hash_value(self.definition_sha256); hash_value(self.catalog_sha256)
        for t in (self.definition_event_ns, self.definition_receive_ns, self.expiration_ns):
            timestamp_ns(t)
        if not self.definition_event_ns <= self.definition_receive_ns < self.expiration_ns:
            raise ValueError("native definition clocks inconsistent")
        terms = dict(self.native_terms)
        if (Decimal(self.tick_size), Decimal(self.multiplier), Decimal(self.monetary_tick_usd)) != (
                Decimal(".1"), Decimal(100), Decimal(10)):
            raise ValueError("unreviewed GC units")
        if (terms.get("unit_of_measure") != "TRYOZ"
                or terms.get("min_price_increment") != "100000000"
                or terms.get("unit_of_measure_qty") != "100000000000"
                or terms.get("display_factor") != "100000000"
                or terms.get("min_price_increment_amount") != "1000000000"
                or terms.get("expiration") != str(self.expiration_ns)):
            raise ValueError("native definition terms inconsistent")

    def units(self, spread):
        # Exchange price quantum = verified tick. This numeric carrier has no
        # MT5 point/lot/account semantics, despite the canonical field's name.
        return dict(point=float(self.tick_size), tick_size=float(self.tick_size), spread_price=float(spread))


@dataclass(frozen=True)
class Quote:
    event_ns: int
    receive_ns: int
    admission_ns: int
    retrieval_ns: int
    bid: str | None
    ask: str | None
    archive_sha256: str
    record_sha256: str
    ordinal: int
    publisher_id: int = 1
    instrument_id: int = 41271

    def __post_init__(self):
        for t in (self.event_ns, self.receive_ns, self.admission_ns, self.retrieval_ns):
            timestamp_ns(t)
        hash_value(self.archive_sha256); hash_value(self.record_sha256)
        if (self.publisher_id, self.instrument_id) != (1, 41271) or type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("quote contract/ordinal mismatch")
        if not self.event_ns <= self.receive_ns <= self.retrieval_ns <= self.admission_ns:
            raise ValueError("quote clocks inconsistent")

    def spread_at(self, cutoff, session_start, max_age_ns):
        # Historical receive is an exchange-feed clock, not the later local
        # archive admission. Availability is explicitly assumed, never certified.
        if not session_start <= self.event_ns <= self.receive_ns <= cutoff:
            raise ValueError("quote_future_or_outside_session")
        if max(cutoff-self.event_ns, cutoff-self.receive_ns) > max_age_ns:
            raise ValueError("quote_stale")
        if self.bid is None or self.ask is None:
            raise ValueError("quote_two_sided_unavailable")
        bid, ask = Decimal(self.bid), Decimal(self.ask)
        if not bid.is_finite() or not ask.is_finite() or not 0 < bid <= ask:
            raise ValueError("quote_invalid_or_crossed")
        if bid % Decimal(".1") or ask % Decimal(".1"):
            raise ValueError("quote_off_native_tick")
        return ask-bid
