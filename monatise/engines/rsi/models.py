from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from monatise.engines._validation import require_finite

from monatise.engines.market_data.models import MarketSnapshot
from monatise.engines.market_structure.models import MarketStructureAssessment
from monatise.engines.regime.models import RegimeAssessment


class RSIBias(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    CONFLICTED = "conflicted"
    UNKNOWN = "unknown"


class RSICondition(StrEnum):
    OVERBOUGHT = "overbought"
    OVERSOLD = "oversold"
    BULLISH_MOMENTUM = "bullish_momentum"
    BEARISH_MOMENTUM = "bearish_momentum"
    NEUTRAL = "neutral"
    UNAVAILABLE = "unavailable"


class RSIDivergence(StrEnum):
    REGULAR_BULLISH = "regular_bullish"
    REGULAR_BEARISH = "regular_bearish"
    HIDDEN_BULLISH = "hidden_bullish"
    HIDDEN_BEARISH = "hidden_bearish"
    NONE = "none"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RSIRequest:
    market: MarketSnapshot
    structure: MarketStructureAssessment | None = None
    regime: RegimeAssessment | None = None
    period: int = 14
    overbought: float = 70.0
    oversold: float = 30.0
    bullish_momentum: float = 55.0
    bearish_momentum: float = 45.0
    divergence_lookback: int = 40
    swing_window: int = 3
    minimum_divergence_separation: int = 3

    def validate(self) -> None:
        require_finite(
            overbought=self.overbought,
            oversold=self.oversold,
            bullish_momentum=self.bullish_momentum,
            bearish_momentum=self.bearish_momentum,
        )
        if self.period < 2:
            raise ValueError("period must be at least 2")
        if not 50 < self.overbought < 100:
            raise ValueError("overbought must be between 50 and 100")
        if not 0 < self.oversold < 50:
            raise ValueError("oversold must be between 0 and 50")
        if not 50 < self.bullish_momentum < self.overbought:
            raise ValueError("bullish_momentum must be above 50 and below overbought")
        if not self.oversold < self.bearish_momentum < 50:
            raise ValueError("bearish_momentum must be below 50 and above oversold")
        if self.divergence_lookback < self.period + 5:
            raise ValueError("divergence_lookback is too small")
        if self.swing_window < 1:
            raise ValueError("swing_window must be positive")
        if self.minimum_divergence_separation < 1:
            raise ValueError("minimum_divergence_separation must be positive")


@dataclass(frozen=True)
class RSIAssessment:
    symbol: str
    current_rsi: float | None
    previous_rsi: float | None
    condition: RSICondition
    bias: RSIBias
    divergence: RSIDivergence
    confidence: float
    rsi_series: tuple[float | None, ...]
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.current_rsi is not None and self.condition is not RSICondition.UNAVAILABLE
