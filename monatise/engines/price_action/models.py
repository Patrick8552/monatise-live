from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from monatise.engines._validation import require_finite
from monatise.engines.market_data.models import MarketSnapshot


class PriceActionFamily(StrEnum):
    CANDLESTICK = "candlestick"
    HEAD_AND_SHOULDERS = "head_and_shoulders"
    ORDER_BLOCK = "order_block"
    WYCKOFF = "wyckoff"


class PriceActionDirection(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class PriceActionConfirmationStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CONFLICT = "conflict"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


@dataclass(frozen=True)
class PriceActionSignal:
    family: PriceActionFamily
    pattern: str
    direction: PriceActionDirection
    confidence: float
    confirmed: bool
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)
    detected_at_index: int = -1
    age_candles: int = 0
    reference_price: float | None = None
    zone_low: float | None = None
    zone_high: float | None = None
    distance_to_entry_ratio: float | None = None
    direction_aligned: bool = False
    location_aligned: bool = False
    fresh: bool = True
    invalidated: bool = False
    evidence_score: float = 0.0

    @property
    def eligible_for_confirmation(self) -> bool:
        return (
            self.confirmed
            and self.direction_aligned
            and self.location_aligned
            and self.fresh
            and not self.invalidated
        )


@dataclass(frozen=True)
class PriceActionRequest:
    market: MarketSnapshot
    expected_direction: PriceActionDirection | None = None
    entry_price: float | None = None
    entry_zone_low: float | None = None
    entry_zone_high: float | None = None
    minimum_candles: int = 8
    minimum_confirmation_confidence: float = 0.70
    maximum_entry_distance_ratio: float = 0.003
    maximum_signal_age_candles: int = 3
    minimum_aligned_families: int = 1
    shoulder_symmetry_tolerance: float = 0.03
    neckline_breakout_threshold: float = 0.001
    order_block_displacement_threshold: float = 1.20
    maximum_order_block_mitigations: int = 2
    wyckoff_penetration_threshold: float = 0.001
    volume_confirmation_ratio: float = 1.0

    def validate(self) -> None:
        require_finite(
            minimum_confirmation_confidence=self.minimum_confirmation_confidence,
            maximum_entry_distance_ratio=self.maximum_entry_distance_ratio,
            shoulder_symmetry_tolerance=self.shoulder_symmetry_tolerance,
            neckline_breakout_threshold=self.neckline_breakout_threshold,
            order_block_displacement_threshold=self.order_block_displacement_threshold,
            wyckoff_penetration_threshold=self.wyckoff_penetration_threshold,
            volume_confirmation_ratio=self.volume_confirmation_ratio,
        )
        if self.minimum_candles < 5:
            raise ValueError("minimum_candles must be at least 5")
        if not 0 <= self.minimum_confirmation_confidence <= 1:
            raise ValueError("minimum_confirmation_confidence must be between 0 and 1")
        if self.maximum_entry_distance_ratio < 0:
            raise ValueError("maximum_entry_distance_ratio cannot be negative")
        if self.maximum_signal_age_candles < 1:
            raise ValueError("maximum_signal_age_candles must be at least 1")
        if self.minimum_aligned_families < 1:
            raise ValueError("minimum_aligned_families must be at least 1")
        if (self.entry_zone_low is None) != (self.entry_zone_high is None):
            raise ValueError("entry zone requires both low and high")
        if self.entry_zone_low is not None and self.entry_zone_low > self.entry_zone_high:
            raise ValueError("entry_zone_low cannot exceed entry_zone_high")
        for name, value in (("entry_price", self.entry_price), ("entry_zone_low", self.entry_zone_low), ("entry_zone_high", self.entry_zone_high)):
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive")
        if not 0 <= self.shoulder_symmetry_tolerance <= 1:
            raise ValueError("shoulder_symmetry_tolerance must be between 0 and 1")
        if self.neckline_breakout_threshold < 0 or self.order_block_displacement_threshold <= 0 or self.wyckoff_penetration_threshold < 0:
            raise ValueError("pattern thresholds must be non-negative")
        if self.maximum_order_block_mitigations < 0 or self.volume_confirmation_ratio < 0:
            raise ValueError("mitigation and volume thresholds cannot be negative")

    @property
    def has_entry_context(self) -> bool:
        return self.entry_price is not None or self.entry_zone_low is not None

    @property
    def effective_entry_zone(self) -> tuple[float, float] | None:
        # A supplied zone deterministically takes precedence over a point entry.
        if self.entry_zone_low is not None and self.entry_zone_high is not None:
            return self.entry_zone_low, self.entry_zone_high
        if self.entry_price is not None:
            return self.entry_price, self.entry_price
        return None


@dataclass(frozen=True)
class PriceActionAssessment:
    symbol: str
    status: PriceActionConfirmationStatus
    signals: tuple[PriceActionSignal, ...]
    reasons: tuple[str, ...]
    eligible_signals: tuple[PriceActionSignal, ...] = ()
    confirming_signals: tuple[PriceActionSignal, ...] = ()
    conflicting_signals: tuple[PriceActionSignal, ...] = ()
    expired_signals: tuple[PriceActionSignal, ...] = ()
    invalidated_signals: tuple[PriceActionSignal, ...] = ()
    aggregate_confidence: float = 0.0
    aligned_family_count: int = 0
    conflicting_family_count: int = 0
    strongest_confirming_pattern: str | None = None
    strongest_conflicting_pattern: str | None = None
    registered_families: tuple[PriceActionFamily, ...] = tuple(PriceActionFamily)
    entry_confirmation_required: bool = True

    @property
    def confirmed_signals(self) -> tuple[PriceActionSignal, ...]:
        return self.confirming_signals

    @property
    def has_confirmation(self) -> bool:
        return self.status is PriceActionConfirmationStatus.CONFIRMED
