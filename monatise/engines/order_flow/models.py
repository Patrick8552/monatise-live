from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from monatise.engines._validation import require_finite

from monatise.engines.market_structure.models import MarketStructureAssessment
from monatise.engines.regime.models import RegimeAssessment


class FlowBias(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    CONFLICTED = "conflicted"
    UNKNOWN = "unknown"


class ParticipationState(StrEnum):
    INSTITUTIONAL_BUYING = "institutional_buying"
    INSTITUTIONAL_SELLING = "institutional_selling"
    SHORT_COVERING = "short_covering"
    LONG_LIQUIDATION = "long_liquidation"
    PASSIVE_ACCUMULATION = "passive_accumulation"
    PASSIVE_DISTRIBUTION = "passive_distribution"
    BALANCED = "balanced"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class FlowHealth(StrEnum):
    HEALTHY = "healthy"
    FRAGILE = "fragile"
    EXHAUSTED = "exhausted"
    TRAPPED = "trapped"
    UNAVAILABLE = "unavailable"


class FlowConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


@dataclass(frozen=True)
class FlowInput:
    open_interest_change_pct: float | None = None
    price_change_pct: float | None = None
    cvd_change: float | None = None
    liquidation_long_usd: float | None = None
    liquidation_short_usd: float | None = None
    footprint_delta: float | None = None
    large_trade_net_usd: float | None = None
    bid_ask_imbalance: float | None = None
    order_book_depth_change_pct: float | None = None
    funding_rate: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderFlowRequest:
    symbol: str
    flow: FlowInput
    regime: RegimeAssessment | None = None
    structure: MarketStructureAssessment | None = None
    minimum_inputs: int = 3
    extreme_liquidation_ratio: float = 3.0
    extreme_imbalance: float = 0.60
    high_funding_abs: float = 0.001

    def validate(self) -> None:
        require_finite(
            extreme_liquidation_ratio=self.extreme_liquidation_ratio,
            extreme_imbalance=self.extreme_imbalance,
            high_funding_abs=self.high_funding_abs,
        )
        if not self.symbol.strip():
            raise ValueError("symbol is required")
        if self.minimum_inputs < 1:
            raise ValueError("minimum_inputs must be positive")
        if self.extreme_liquidation_ratio <= 1:
            raise ValueError("extreme_liquidation_ratio must exceed 1")
        if not 0 < self.extreme_imbalance <= 1:
            raise ValueError("extreme_imbalance must be between 0 and 1")
        if self.high_funding_abs <= 0:
            raise ValueError("high_funding_abs must be positive")


@dataclass(frozen=True)
class OrderFlowAssessment:
    symbol: str
    bias: FlowBias
    participation: ParticipationState
    health: FlowHealth
    confidence: FlowConfidence
    score: float
    execution_timing_score: float
    inputs_used: int
    reasons: tuple[str, ...]
    normalized_inputs: dict[str, float | None]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def supports_bullish_execution(self) -> bool:
        return (
            self.bias is FlowBias.BULLISH
            and self.health is FlowHealth.HEALTHY
            and self.execution_timing_score >= 0.60
        )

    @property
    def supports_bearish_execution(self) -> bool:
        return (
            self.bias is FlowBias.BEARISH
            and self.health is FlowHealth.HEALTHY
            and self.execution_timing_score >= 0.60
        )
