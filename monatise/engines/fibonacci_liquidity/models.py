from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from monatise.engines._validation import require_finite

from monatise.engines.liquidity.models import LiquidityAssessment
from monatise.engines.market_data.models import MarketSnapshot
from monatise.engines.market_structure.models import MarketStructureAssessment
from monatise.engines.reclaim.models import ReclaimAssessment
from monatise.engines.supply_demand.models import ZoneAssessment


class FibonacciDirection(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    UNKNOWN = "unknown"


class FibonacciLevelType(StrEnum):
    RETRACEMENT = "retracement"
    EXTENSION = "extension"
    INVALIDATION = "invalidation"


class FibonacciZoneType(StrEnum):
    EQUILIBRIUM = "equilibrium"
    OTE = "ote"
    DEEP_RETRACEMENT = "deep_retracement"
    EXTENSION_CLUSTER = "extension_cluster"


class AnchorQuality(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INVALID = "invalid"


@dataclass(frozen=True)
class FibonacciRequest:
    market: MarketSnapshot
    structure: MarketStructureAssessment
    liquidity: LiquidityAssessment | None = None
    zones: ZoneAssessment | None = None
    reclaim: ReclaimAssessment | None = None

    retracement_ratios: tuple[float, ...] = (
        0.382,
        0.5,
        0.618,
        0.705,
        0.786,
        0.886,
    )
    extension_ratios: tuple[float, ...] = (
        1.0,
        1.272,
        1.414,
        1.618,
        2.0,
    )

    ote_lower_ratio: float = 0.618
    ote_upper_ratio: float = 0.786
    deep_retracement_ratio: float = 0.886

    confluence_tolerance_pct: float = 0.0025
    cluster_tolerance_pct: float = 0.003
    invalidation_buffer_pct: float = 0.0015

    maximum_anchor_age_candles: int = 160
    minimum_anchor_range_atr: float = 2.0
    minimum_structure_confidence: float = 0.45
    maximum_alternate_anchors: int = 3

    def validate(self) -> None:
        require_finite(**{
            **{f"retracement_ratio_{index}": value for index, value in enumerate(self.retracement_ratios)},
            **{f"extension_ratio_{index}": value for index, value in enumerate(self.extension_ratios)},
            "ote_lower_ratio": self.ote_lower_ratio,
            "ote_upper_ratio": self.ote_upper_ratio,
            "deep_retracement_ratio": self.deep_retracement_ratio,
            "confluence_tolerance_pct": self.confluence_tolerance_pct,
            "cluster_tolerance_pct": self.cluster_tolerance_pct,
            "invalidation_buffer_pct": self.invalidation_buffer_pct,
            "minimum_anchor_range_atr": self.minimum_anchor_range_atr,
            "minimum_structure_confidence": self.minimum_structure_confidence,
        })
        if not self.retracement_ratios:
            raise ValueError("at least one retracement ratio is required")
        if not self.extension_ratios:
            raise ValueError("at least one extension ratio is required")
        if any(ratio <= 0 or ratio >= 1 for ratio in self.retracement_ratios):
            raise ValueError("retracement ratios must be between 0 and 1")
        if any(ratio < 1 for ratio in self.extension_ratios):
            raise ValueError("extension ratios must be at least 1")
        if not 0 < self.ote_lower_ratio < self.ote_upper_ratio < 1:
            raise ValueError("OTE bounds must satisfy 0 < lower < upper < 1")
        if not self.ote_upper_ratio <= self.deep_retracement_ratio < 1:
            raise ValueError("deep retracement ratio must be above OTE upper bound")
        if self.confluence_tolerance_pct < 0:
            raise ValueError("confluence_tolerance_pct cannot be negative")
        if self.cluster_tolerance_pct < 0:
            raise ValueError("cluster_tolerance_pct cannot be negative")
        if self.invalidation_buffer_pct < 0:
            raise ValueError("invalidation_buffer_pct cannot be negative")
        if self.maximum_anchor_age_candles < 2:
            raise ValueError("maximum_anchor_age_candles must be at least 2")
        if self.minimum_anchor_range_atr <= 0:
            raise ValueError("minimum_anchor_range_atr must be positive")
        if not 0 <= self.minimum_structure_confidence <= 1:
            raise ValueError("minimum_structure_confidence must be between 0 and 1")
        if self.maximum_alternate_anchors < 0:
            raise ValueError("maximum_alternate_anchors cannot be negative")


@dataclass(frozen=True)
class FibonacciAnchor:
    direction: FibonacciDirection
    start_index: int
    end_index: int
    start_price: float
    end_price: float
    range_size: float
    range_atr_multiple: float
    age_candles: int
    structure_confidence: float
    reclaim_aligned: bool
    quality: AnchorQuality
    score: float
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FibonacciLevel:
    ratio: float
    price: float
    level_type: FibonacciLevelType
    distance_pct: float
    liquidity_confluence: bool
    zone_confluence: bool
    structure_confluence: bool
    reclaim_confluence: bool
    score: float
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FibonacciZone:
    zone_type: FibonacciZoneType
    lower_price: float
    upper_price: float
    midpoint: float
    current_price_inside: bool
    liquidity_confluence: bool
    supply_demand_confluence: bool
    score: float
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FibonacciAssessment:
    symbol: str
    direction: FibonacciDirection
    primary_anchor: FibonacciAnchor | None
    alternate_anchors: tuple[FibonacciAnchor, ...]
    retracement_levels: tuple[FibonacciLevel, ...]
    extension_levels: tuple[FibonacciLevel, ...]
    zones: tuple[FibonacciZone, ...]
    invalidation_level: FibonacciLevel | None
    nearest_retracement: FibonacciLevel | None
    nearest_extension: FibonacciLevel | None
    active_zone: FibonacciZone | None
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_valid_anchor(self) -> bool:
        return (
            self.primary_anchor is not None
            and self.primary_anchor.quality is not AnchorQuality.INVALID
        )

    @property
    def price_inside_ote(self) -> bool:
        return (
            self.active_zone is not None
            and self.active_zone.zone_type is FibonacciZoneType.OTE
        )
