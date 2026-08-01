from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from monatise.engines._validation import require_finite

from monatise.engines.market_data.models import MarketSnapshot
from monatise.engines.macro.models import MacroAssessment


class RegimeState(StrEnum):
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    RANGE = "range"
    COMPRESSION = "compression"
    EXPANSION = "expansion"
    HIGH_VOLATILITY = "high_volatility"
    UNSTABLE = "unstable"
    UNKNOWN = "unknown"


class RegimeConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


@dataclass(frozen=True)
class RegimeRequest:
    market: MarketSnapshot
    macro: MacroAssessment | None = None
    fast_window: int = 20
    slow_window: int = 50
    atr_window: int = 14
    compression_window: int = 20
    trend_threshold: float = 0.0025
    compression_threshold: float = 0.55
    expansion_threshold: float = 1.45
    high_volatility_threshold: float = 2.0

    def validate(self) -> None:
        require_finite(
            trend_threshold=self.trend_threshold,
            compression_threshold=self.compression_threshold,
            expansion_threshold=self.expansion_threshold,
            high_volatility_threshold=self.high_volatility_threshold,
        )
        if self.fast_window < 2:
            raise ValueError("fast_window must be at least 2")
        if self.slow_window <= self.fast_window:
            raise ValueError("slow_window must be greater than fast_window")
        if self.atr_window < 2:
            raise ValueError("atr_window must be at least 2")
        if self.compression_window < 2:
            raise ValueError("compression_window must be at least 2")
        if self.trend_threshold <= 0:
            raise ValueError("trend_threshold must be positive")
        if self.compression_threshold <= 0:
            raise ValueError("compression_threshold must be positive")
        if self.expansion_threshold <= 1:
            raise ValueError("expansion_threshold must be greater than 1")
        if self.high_volatility_threshold <= self.expansion_threshold:
            raise ValueError(
                "high_volatility_threshold must exceed expansion_threshold"
            )


@dataclass(frozen=True)
class RegimeAssessment:
    symbol: str
    state: RegimeState
    confidence: RegimeConfidence
    score: float
    reasons: tuple[str, ...]
    metrics: dict[str, float | None] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def permits_liquidity_analysis(self) -> bool:
        return self.state not in {
            RegimeState.UNSTABLE,
            RegimeState.UNKNOWN,
        }

    @property
    def prefers_grid_logic(self) -> bool:
        return self.state in {
            RegimeState.RANGE,
            RegimeState.COMPRESSION,
        }
