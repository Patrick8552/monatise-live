from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from monatise.engines._validation import require_finite

from monatise.engines.liquidity.models import LiquidityAssessment, LiquidityLevel
from monatise.engines.market_data.models import MarketSnapshot
from monatise.engines.regime.models import RegimeAssessment


class SweepDirection(StrEnum):
    BUY_SIDE_TAKEN = "buy_side_taken"
    SELL_SIDE_TAKEN = "sell_side_taken"


class SweepStatus(StrEnum):
    CONFIRMED = "confirmed"
    POSSIBLE = "possible"
    NONE = "none"
    INVALID = "invalid"


@dataclass(frozen=True)
class SweepRequest:
    market: MarketSnapshot
    liquidity: LiquidityAssessment
    regime: RegimeAssessment | None = None
    lookback_candles: int = 8
    breach_tolerance_pct: float = 0.0005
    rejection_close_pct: float = 0.001
    minimum_wick_ratio: float = 0.35
    require_close_back_inside: bool = True

    def validate(self) -> None:
        require_finite(
            breach_tolerance_pct=self.breach_tolerance_pct,
            rejection_close_pct=self.rejection_close_pct,
            minimum_wick_ratio=self.minimum_wick_ratio,
        )
        if self.lookback_candles < 1:
            raise ValueError("lookback_candles must be positive")
        if self.breach_tolerance_pct < 0:
            raise ValueError("breach_tolerance_pct cannot be negative")
        if self.rejection_close_pct < 0:
            raise ValueError("rejection_close_pct cannot be negative")
        if not 0 <= self.minimum_wick_ratio <= 1:
            raise ValueError("minimum_wick_ratio must be between 0 and 1")


@dataclass(frozen=True)
class SweepEvent:
    level: LiquidityLevel
    direction: SweepDirection
    status: SweepStatus
    candle_index: int
    breach_price: float
    close_price: float
    breach_pct: float
    wick_ratio: float
    close_back_inside: bool
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SweepAssessment:
    symbol: str
    events: tuple[SweepEvent, ...]
    strongest_event: SweepEvent | None
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_confirmed_sweep(self) -> bool:
        return any(event.status is SweepStatus.CONFIRMED for event in self.events)

    @property
    def has_possible_sweep(self) -> bool:
        return any(event.status is SweepStatus.POSSIBLE for event in self.events)
