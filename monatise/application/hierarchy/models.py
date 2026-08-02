from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Any, Mapping


class BoundaryStatus(StrEnum):
    FORMING = "forming"
    FINALIZED = "finalized"
    LATE_FINALIZED = "late_finalized"
    MISSING = "missing"
    INVALID = "invalid"


class DataQualityState(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    REVISED = "revised"


class StrategicState(StrEnum):
    BLOCKED = "blocked"
    NEUTRAL = "neutral"
    LONG_ONLY = "long_only"
    SHORT_ONLY = "short_only"
    GRID_ALLOWED = "grid_allowed"


class SetupState(StrEnum):
    NO_SETUP = "no_setup"
    WATCHING = "watching"
    SETUP_CONFIRMED = "setup_confirmed"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class TriggerState(StrEnum):
    WAITING_FOR_CLOSE = "waiting_for_close"
    TRIGGER_CONFIRMED = "trigger_confirmed"
    TRIGGER_REJECTED = "trigger_rejected"
    ENTRY_MISSED = "entry_missed"
    DATA_REVISED = "data_revised"


class FinalOutcome(StrEnum):
    VALID_SIGNAL = "valid_signal"
    NO_TRADE = "no_trade"
    BLOCKED = "blocked"
    DUPLICATE = "duplicate"
    EXPIRED = "expired"
    STALE_CONTEXT = "stale_context"
    DATA_UNAVAILABLE = "data_unavailable"
    MACRO_DEGRADED = "macro_degraded"
    SUPERSEDED = "superseded"


ContextState = StrategicState | SetupState | TriggerState | FinalOutcome


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def deterministic_id(kind: str, values: Mapping[str, Any]) -> str:
    payload = json.dumps(values, separators=(",", ":"), sort_keys=True, default=str)
    return f"{kind}-{hashlib.sha256(payload.encode()).hexdigest()[:24]}"


@dataclass(frozen=True)
class Provenance:
    provider: str
    exchange: str
    instrument: str
    source_version: str
    normalization_version: str

    def __post_init__(self) -> None:
        if any(not value.strip() for value in asdict(self).values()):
            raise ValueError("all provenance fields are required")


@dataclass(frozen=True)
class NormalizedCandle:
    candle_id: str
    symbol: str
    timeframe: str
    open_time: datetime
    scheduled_close_time: datetime
    provider_timestamp: datetime
    received_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_final: bool
    boundary_status: BoundaryStatus
    content_hash: str
    provenance: Provenance

    def __post_init__(self) -> None:
        for name in ("open_time", "scheduled_close_time", "provider_timestamp", "received_at"):
            _aware(getattr(self, name), name)
        if self.scheduled_close_time <= self.open_time:
            raise ValueError("candle close must be after candle open")
        if self.low > self.high or not self.low <= self.open <= self.high or not self.low <= self.close <= self.high:
            raise ValueError("invalid OHLC range")
        if any(not isfinite(value) for value in (self.open, self.high, self.low, self.close, self.volume)):
            raise ValueError("candle values must be finite")
        if self.is_final != (self.boundary_status in {BoundaryStatus.FINALIZED, BoundaryStatus.LATE_FINALIZED}):
            raise ValueError("finalization flag and boundary status disagree")


@dataclass(frozen=True)
class EvidenceIdentity:
    context_id: str
    symbol: str
    source_timeframe: str
    source_candle_id: str
    parent_context_id: str | None
    strategy_version: str

    @classmethod
    def create(cls, *, kind: str, symbol: str, timeframe: str, candle_id: str, parent_id: str | None, strategy_version: str) -> "EvidenceIdentity":
        values = {"symbol": symbol.upper(), "timeframe": timeframe, "candle_id": candle_id, "parent_id": parent_id, "strategy_version": strategy_version}
        return cls(deterministic_id(kind, values), symbol.upper(), timeframe, candle_id, parent_id, strategy_version)


@dataclass(frozen=True)
class EvidenceContext:
    identity: EvidenceIdentity
    source_open_time: datetime | None
    source_close_time: datetime | None
    evaluated_at: datetime
    expires_at: datetime
    state: ContextState
    direction: str
    confidence: float
    data_quality: DataQualityState
    provenance: Provenance
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (self.source_open_time is None) != (self.source_close_time is None):
            raise ValueError("source candle boundaries must be provided together")
        if self.identity.source_timeframe in {"4h", "1h", "15m", "5m"} and self.source_open_time is None:
            raise ValueError("timeframe evidence requires source candle boundaries")
        if self.source_open_time is not None and self.source_close_time is not None:
            _aware(self.source_open_time, "source_open_time")
            _aware(self.source_close_time, "source_close_time")
            if self.source_close_time <= self.source_open_time:
                raise ValueError("source candle close must be after open")
        _aware(self.evaluated_at, "evaluated_at")
        _aware(self.expires_at, "expires_at")
        if self.expires_at <= self.evaluated_at:
            raise ValueError("context expiry must be after evaluation")
        if not 0 <= self.confidence <= 1 or not isfinite(self.confidence):
            raise ValueError("confidence must be between zero and one")
        object.__setattr__(self, "evidence", dict(self.evidence))


@dataclass(frozen=True)
class RiskProposal:
    entry_zone_low: float
    entry_zone_high: float
    reference_entry: float
    structural_invalidation: float
    volatility_buffer: float
    estimated_spread_allowance: float
    estimated_slippage_allowance: float
    final_stop: float
    target_liquidity: float
    minimum_reward_to_risk: float
    calculated_reward_to_risk: float
    movement_tolerance: float
    expires_at: datetime
    estimates_observed: bool = False

    def __post_init__(self) -> None:
        _aware(self.expires_at, "expires_at")
        numbers = tuple(value for name, value in asdict(self).items() if name not in {"expires_at", "estimates_observed"})
        if any(not isfinite(value) for value in numbers):
            raise ValueError("risk values must be finite")
        if self.entry_zone_low > self.entry_zone_high:
            raise ValueError("entry zone is inverted")
        if not self.entry_zone_low <= self.reference_entry <= self.entry_zone_high:
            raise ValueError("reference entry must be inside entry zone")
        if min(self.volatility_buffer, self.estimated_spread_allowance, self.estimated_slippage_allowance, self.movement_tolerance) < 0:
            raise ValueError("risk allowances cannot be negative")


@dataclass(frozen=True)
class EvidenceBundle:
    bundle_id: str
    symbol: str
    created_at: datetime
    macro_context: EvidenceContext
    regime_4h: EvidenceContext
    strategy_1h: EvidenceContext
    setup_15m: EvidenceContext
    trigger_5m: EvidenceContext
    risk_inputs: RiskProposal
    strategy_version: str
    execution_enabled: bool = False

    def __post_init__(self) -> None:
        _aware(self.created_at, "created_at")
        contexts = (self.macro_context, self.regime_4h, self.strategy_1h, self.setup_15m, self.trigger_5m)
        if any(context.identity.symbol != self.symbol.upper() for context in contexts):
            raise ValueError("all evidence must use the bundle symbol")
        expected = (None, self.macro_context.identity.context_id, self.regime_4h.identity.context_id, self.strategy_1h.identity.context_id, self.setup_15m.identity.context_id)
        if tuple(context.identity.parent_context_id for context in contexts) != expected:
            raise ValueError("evidence parent chain is invalid")
        if self.execution_enabled:
            raise ValueError("hierarchical evidence cannot enable execution")

    @classmethod
    def create(cls, *, symbol: str, created_at: datetime, macro_context: EvidenceContext, regime_4h: EvidenceContext, strategy_1h: EvidenceContext, setup_15m: EvidenceContext, trigger_5m: EvidenceContext, risk_inputs: RiskProposal, strategy_version: str) -> "EvidenceBundle":
        chain = [item.identity.context_id for item in (macro_context, regime_4h, strategy_1h, setup_15m, trigger_5m)]
        bundle_id = deterministic_id("bundle", {"symbol": symbol.upper(), "chain": chain, "strategy_version": strategy_version})
        return cls(bundle_id, symbol.upper(), created_at, macro_context, regime_4h, strategy_1h, setup_15m, trigger_5m, risk_inputs, strategy_version)
