"""Immutable identities, native positions, calculations and preview contracts."""
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
import re

from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.databento.datasets import InstrumentMetadata
from . import VERSION

MAPPING_VERSION='native-futures-normalization-v2'
_JSON_ATOMS = frozenset((str, int, float, bool, type(None)))


def encode(value):
    if type(value) in _JSON_ATOMS:
        return value
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [encode(v) for v in value]
    if is_dataclass(value):
        # Walk fields once. asdict recursively deep-copies the complete nested
        # evidence tree before encode walks it again; large immutable native
        # candle/source trees paid that cost on every digest. The canonical
        # field names, recursion and JSON representation remain identical.
        return {field.name: encode(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, (Decimal, datetime)):
        return str(value) if isinstance(value, Decimal) else value.isoformat()
    return value


def digest(value):
    return hashlib.sha256(json.dumps(encode(value), sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def hash_required(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("source_sha256_required")


def number(value, *, positive=False):
    if isinstance(value, bool):
        raise ValueError("numeric_boolean_forbidden")
    result = Decimal(str(value))
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError("finite_economic_value_required")
    return result


@dataclass(frozen=True)
class Contract:
    metadata: InstrumentMetadata
    asset_class: str
    currency: str
    tick_size: Decimal
    multiplier: Decimal
    price_unit: str
    convention_reference: str

    def __post_init__(self):
        if (not isinstance(self.metadata, InstrumentMetadata)
                or self.asset_class not in {"futures", "futures_option"}
                or self.currency != "USD" or not self.price_unit or not self.convention_reference
                or number(self.tick_size, positive=True) != Decimal(dict(self.metadata.native_terms)["min_price_increment"])/10**9):
            raise ValueError("reviewed_native_economic_terms_required")
        number(self.multiplier, positive=True)

    @property
    def identity(self):
        m = self.metadata
        return (m.dataset, m.publisher_id, m.instrument_id, m.raw_symbol, m.expiration_ns)


@dataclass(frozen=True)
class Source:
    archive_sha256: str
    record_sha256: str
    ordinal: int
    retrieval_ns: int
    admission_ns: int
    evidence_kind: str
    clock_review: object | None = None

    def __post_init__(self):
        hash_required(self.archive_sha256)
        hash_required(self.record_sha256)
        for t in (self.retrieval_ns, self.admission_ns):
            timestamp_ns(t)
        if (type(self.ordinal) is not int or self.ordinal < 0
                or self.retrieval_ns > self.admission_ns
                or self.evidence_kind not in {"AUTHENTIC_ARCHIVED_RECORD", "AUTHENTIC_LIVE_CAPTURE", "ENGINEERING_SYNTHETIC"}):
            raise ValueError("native_position_and_availability_required")

        if self.clock_review is not None:
            from monatise.research.databento.live_models import ClockReview
            if not isinstance(self.clock_review,ClockReview):raise ValueError('reviewed_capture_clock_required')
            self.clock_review.bounds(self.retrieval_ns)

    @property
    def utc_capture_bounds(self):
        lower,upper=self.clock_review.bounds(self.retrieval_ns) if self.clock_review else (0,0)
        return self.retrieval_ns+lower,self.retrieval_ns+upper

    @property
    def position(self):
        return self.archive_sha256, self.ordinal


@dataclass(frozen=True)
class MarketObservation:
    contract: Contract
    schema: str
    event_ns: int
    receive_ns: int | None
    source: Source
    payload: tuple
    flags: int = 0
    sequence: int | None = None
    provider: str = "Databento"
    quality: str = "CAPTURED_NATIVE_CONTINUITY_UNCERTIFIED"
    normalization_version: str = MAPPING_VERSION
    ts_in_delta: int | None = None

    @property
    def index_ns(self):
        return self.receive_ns if self.receive_ns is not None else self.event_ns

    @property
    def publisher_send_ns(self):
        # Clamped deltas do not represent an exact sending timestamp.
        if self.receive_ns is None or self.ts_in_delta in (None, -(2**31), 2**31-1):return None
        return self.receive_ns-self.ts_in_delta

    def __post_init__(self):
        timestamp_ns(self.event_ns)
        if self.receive_ns is not None:
            timestamp_ns(self.receive_ns)
        m = self.contract.metadata
        clock = self.receive_ns if self.receive_ns is not None else self.event_ns
        if (self.provider != "Databento" or self.normalization_version != MAPPING_VERSION
                or self.quality != "CAPTURED_NATIVE_CONTINUITY_UNCERTIFIED"
                or self.schema not in {"definition", "trades", "mbp-1", "mbp-10", "ohlcv-1s", "ohlcv-1m", "ohlcv-1h", "statistics", "status"}
                or not m.event_ns <= self.event_ns < m.expiration_ns
                or not (m.event_ns if self.schema=='definition' else m.receive_ns) <= clock < m.expiration_ns
                or max(clock,self.event_ns) > self.source.utc_capture_bounds[1]
                or not isinstance(self.payload, tuple)
                or type(self.flags) is not int or not 0 <= self.flags <= 255
                or self.flags & (4 | 8 | 32)):
            raise ValueError("native_clock_schema_or_quality_invalid")
        if self.ts_in_delta is not None and (type(self.ts_in_delta) is not int or not -(2**31)<=self.ts_in_delta<2**31):
            raise ValueError('native_publisher_delta_invalid')

        if self.sequence is not None and (type(self.sequence) is not int or not 0 <= self.sequence < 2**32):
            raise ValueError("native_sequence_invalid")
        if self.schema == 'trades':
            if (len(self.payload)!=3 or type(self.payload[1]) is not int or self.payload[1]<=0
                    or self.payload[2] not in {'BUY','SELL',None}
                    or number(self.payload[0]) % self.contract.tick_size
                    or (m.product!='CL' and number(self.payload[0])<=0)):
                raise ValueError('executed_trade_payload_invalid')
        if self.schema in {'mbp-1','mbp-10'}:
            from monatise.research.databento.advanced import AdvancedAdapters
            if len(self.payload)!=(1 if self.schema=='mbp-1' else 10):
                raise ValueError('book_depth_invalid')
            for level in self.payload:
                if not isinstance(level,tuple) or len(level)!=6:
                    raise ValueError('book_level_invalid')
                for offset in (0,3):
                    p,size,count=level[offset:offset+3]
                    if (type(size) is not int or type(count) is not int or min(size,count)<0
                            or (p is None and (size or count)) or (p is not None and
                            (size<=0 or number(p)%self.contract.tick_size or (m.product!='CL' and number(p)<=0)))):
                        raise ValueError('book_price_or_quantity_invalid')
            AdvancedAdapters._validate_order(self.payload)


class PreviewDecision(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO_TRADE"
    INSUFFICIENT_MARKET_DATA = "INSUFFICIENT_MARKET_DATA"
    MAPPING_UNAVAILABLE = "MAPPING_UNAVAILABLE"


@dataclass(frozen=True)
class SignalPreview:
    asset: str
    broker_instrument: str
    institutional_source_instrument: str | None
    decision: PreviewDecision
    market_regime: str
    directional_bias: str
    entry_zone: tuple[str, str] | None
    proposed_entry: str | None
    structural_stop: str | None
    take_profits: tuple[str, ...]
    reward_risk: str | None
    evidence_score: str | None
    limitations: tuple[str, ...]
    freshness: tuple[tuple[str, str], ...]
    generated_ns: int
    expiration_ns: int | None
    mapping_status: str
    source_provenance: tuple[str, ...]
    rejection_reasons: tuple[str, ...]
    evidence_kind: str
    canonical_path: str
    execution_eligible: bool = False
    publication_eligible: bool = False
    approval_eligible: bool = False
    gil_enabled: bool = False

    def __post_init__(self):
        timestamp_ns(self.generated_ns)
        if (not isinstance(self.decision, PreviewDecision) or not self.asset or not self.broker_instrument
                or self.evidence_kind not in {"AUTHENTIC_ARCHIVED_RECORD", "ENGINEERING_SYNTHETIC", "UNAVAILABLE"}
                or any((self.execution_eligible, self.publication_eligible, self.approval_eligible, self.gil_enabled))):
            raise ValueError("non_executable_typed_preview_required")
        for h in self.source_provenance:
            hash_required(h)
        if self.decision in {PreviewDecision.LONG, PreviewDecision.SHORT}:
            if (self.expiration_ns is None or self.expiration_ns <= self.generated_ns
                    or self.entry_zone is None or self.proposed_entry is None
                    or self.structural_stop is None or not self.take_profits or self.reward_risk is None):
                raise ValueError("qualified_geometry_and_expiry_required")
            entry, stop = number(self.proposed_entry, positive=True), number(self.structural_stop, positive=True)
            low, high = map(lambda v:number(v, positive=True), self.entry_zone)
            targets = tuple(number(v, positive=True) for v in self.take_profits)
            if (not low <= entry <= high or number(self.reward_risk, positive=True) < Decimal("1.5")
                    or (stop >= low or any(t <= entry for t in targets) if self.decision == PreviewDecision.LONG
                        else stop <= high or any(t >= entry for t in targets))):
                raise ValueError("invalid_qualified_preview_geometry")
