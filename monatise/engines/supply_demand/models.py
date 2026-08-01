from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from monatise.engines._validation import require_finite

from monatise.engines.liquidity.models import LiquidityAssessment
from monatise.engines.market_data.models import MarketSnapshot
from monatise.engines.regime.models import RegimeAssessment


class ZoneType(StrEnum):
    DEMAND = "demand"
    SUPPLY = "supply"


class ZoneDirection(StrEnum):
    RALLY_BASE_RALLY = "rally_base_rally"
    DROP_BASE_RALLY = "drop_base_rally"
    RALLY_BASE_DROP = "rally_base_drop"
    DROP_BASE_DROP = "drop_base_drop"


class ZoneStrength(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ZoneFreshness(StrEnum):
    FRESH = "fresh"
    TESTED = "tested"
    MITIGATED = "mitigated"
    INVALIDATED = "invalidated"


@dataclass(frozen=True)
class ZoneRequest:
    market: MarketSnapshot
    regime: RegimeAssessment | None = None
    liquidity: LiquidityAssessment | None = None
    impulse_window: int = 3
    base_max_candles: int = 4
    minimum_impulse_atr: float = 1.5
    base_body_ratio_max: float = 0.55
    zone_touch_tolerance_pct: float = 0.001
    invalidation_tolerance_pct: float = 0.0015
    max_zones_per_type: int = 6

    def validate(self) -> None:
        require_finite(
            minimum_impulse_atr=self.minimum_impulse_atr,
            base_body_ratio_max=self.base_body_ratio_max,
            zone_touch_tolerance_pct=self.zone_touch_tolerance_pct,
            invalidation_tolerance_pct=self.invalidation_tolerance_pct,
        )
        if self.impulse_window < 1:
            raise ValueError("impulse_window must be positive")
        if self.base_max_candles < 1:
            raise ValueError("base_max_candles must be positive")
        if self.minimum_impulse_atr <= 0:
            raise ValueError("minimum_impulse_atr must be positive")
        if not 0 < self.base_body_ratio_max <= 1:
            raise ValueError("base_body_ratio_max must be between 0 and 1")
        if self.zone_touch_tolerance_pct < 0:
            raise ValueError("zone_touch_tolerance_pct cannot be negative")
        if self.invalidation_tolerance_pct < 0:
            raise ValueError("invalidation_tolerance_pct cannot be negative")
        if self.max_zones_per_type < 1:
            raise ValueError("max_zones_per_type must be positive")


@dataclass(frozen=True)
class SupplyDemandZone:
    zone_type: ZoneType
    direction: ZoneDirection
    proximal: float
    distal: float
    created_index: int
    base_start_index: int
    base_end_index: int
    departure_index: int
    strength: ZoneStrength
    freshness: ZoneFreshness
    departure_atr_multiple: float
    touches: int
    distance_pct: float
    liquidity_confluence: bool
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def lower_bound(self) -> float:
        return min(self.proximal, self.distal)

    @property
    def upper_bound(self) -> float:
        return max(self.proximal, self.distal)

    def contains(self, price: float) -> bool:
        return self.lower_bound <= price <= self.upper_bound


@dataclass(frozen=True)
class ZoneAssessment:
    symbol: str
    current_price: float
    demand_zones: tuple[SupplyDemandZone, ...]
    supply_zones: tuple[SupplyDemandZone, ...]
    nearest_demand: SupplyDemandZone | None
    nearest_supply: SupplyDemandZone | None
    active_demand: SupplyDemandZone | None
    active_supply: SupplyDemandZone | None
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_valid_zones(self) -> bool:
        return bool(self.demand_zones or self.supply_zones)

    @property
    def price_inside_zone(self) -> bool:
        return self.active_demand is not None or self.active_supply is not None
