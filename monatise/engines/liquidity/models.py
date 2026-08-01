from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from monatise.engines._validation import require_finite

from monatise.engines.market_data.models import MarketSnapshot
from monatise.engines.regime.models import RegimeAssessment


class LiquiditySide(StrEnum):
    BUY_SIDE = "buy_side"
    SELL_SIDE = "sell_side"


class LiquidityLevelType(StrEnum):
    SWING_HIGH = "swing_high"
    SWING_LOW = "swing_low"
    EQUAL_HIGHS = "equal_highs"
    EQUAL_LOWS = "equal_lows"
    RANGE_HIGH = "range_high"
    RANGE_LOW = "range_low"
    CLUSTER_HIGH = "cluster_high"
    CLUSTER_LOW = "cluster_low"
    RECENT_HIGH = "recent_high"
    RECENT_LOW = "recent_low"


class LiquidityStrength(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class LiquidityRequest:
    market: MarketSnapshot
    regime: RegimeAssessment | None = None
    swing_window: int = 3
    equal_level_tolerance_pct: float = 0.0015
    cluster_tolerance_pct: float = 0.0025
    minimum_cluster_touches: int = 2
    recent_window: int = 20
    range_window: int = 50
    max_levels_per_side: int = 8

    def validate(self) -> None:
        require_finite(
            equal_level_tolerance_pct=self.equal_level_tolerance_pct,
            cluster_tolerance_pct=self.cluster_tolerance_pct,
        )
        if self.swing_window < 1:
            raise ValueError("swing_window must be at least 1")
        if self.equal_level_tolerance_pct <= 0:
            raise ValueError("equal_level_tolerance_pct must be positive")
        if self.cluster_tolerance_pct <= 0:
            raise ValueError("cluster_tolerance_pct must be positive")
        if self.minimum_cluster_touches < 2:
            raise ValueError("minimum_cluster_touches must be at least 2")
        if self.recent_window < 2:
            raise ValueError("recent_window must be at least 2")
        if self.range_window < self.recent_window:
            raise ValueError("range_window must be at least recent_window")
        if self.max_levels_per_side < 1:
            raise ValueError("max_levels_per_side must be positive")


@dataclass(frozen=True)
class LiquidityLevel:
    price: float
    side: LiquiditySide
    level_type: LiquidityLevelType
    strength: LiquidityStrength
    touches: int
    distance_pct: float
    first_index: int
    last_index: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LiquidityAssessment:
    symbol: str
    current_price: float
    buy_side_levels: tuple[LiquidityLevel, ...]
    sell_side_levels: tuple[LiquidityLevel, ...]
    nearest_buy_side: LiquidityLevel | None
    nearest_sell_side: LiquidityLevel | None
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_mapped_liquidity(self) -> bool:
        return bool(self.buy_side_levels or self.sell_side_levels)

    @property
    def balanced(self) -> bool:
        return bool(self.buy_side_levels and self.sell_side_levels)
