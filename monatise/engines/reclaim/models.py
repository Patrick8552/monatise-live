from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from monatise.engines._validation import require_finite

from monatise.engines.liquidity_sweep.models import SweepAssessment, SweepEvent
from monatise.engines.market_data.models import MarketSnapshot
from monatise.engines.regime.models import RegimeAssessment
from monatise.engines.supply_demand.models import ZoneAssessment


class ReclaimDirection(StrEnum):
    BULLISH_RECLAIM = "bullish_reclaim"
    BEARISH_RECLAIM = "bearish_reclaim"


class ReclaimStatus(StrEnum):
    CONFIRMED = "confirmed"
    POSSIBLE = "possible"
    FAILED = "failed"
    NONE = "none"
    INVALID = "invalid"


@dataclass(frozen=True)
class ReclaimRequest:
    market: MarketSnapshot
    sweep: SweepAssessment
    regime: RegimeAssessment | None = None
    zones: ZoneAssessment | None = None
    confirmation_candles: int = 4
    reclaim_tolerance_pct: float = 0.001
    hold_tolerance_pct: float = 0.0015
    minimum_body_ratio: float = 0.45
    require_follow_through: bool = True

    def validate(self) -> None:
        require_finite(
            reclaim_tolerance_pct=self.reclaim_tolerance_pct,
            hold_tolerance_pct=self.hold_tolerance_pct,
            minimum_body_ratio=self.minimum_body_ratio,
        )
        if self.confirmation_candles < 1:
            raise ValueError("confirmation_candles must be positive")
        if self.reclaim_tolerance_pct < 0:
            raise ValueError("reclaim_tolerance_pct cannot be negative")
        if self.hold_tolerance_pct < 0:
            raise ValueError("hold_tolerance_pct cannot be negative")
        if not 0 <= self.minimum_body_ratio <= 1:
            raise ValueError("minimum_body_ratio must be between 0 and 1")


@dataclass(frozen=True)
class ReclaimEvent:
    sweep_event: SweepEvent
    direction: ReclaimDirection
    status: ReclaimStatus
    reclaim_index: int | None
    confirmation_index: int | None
    reclaim_price: float
    close_price: float | None
    body_ratio: float | None
    held_level: bool
    zone_confluence: bool
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReclaimAssessment:
    symbol: str
    events: tuple[ReclaimEvent, ...]
    strongest_event: ReclaimEvent | None
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_confirmed_reclaim(self) -> bool:
        return any(event.status is ReclaimStatus.CONFIRMED for event in self.events)

    @property
    def has_failed_reclaim(self) -> bool:
        return any(event.status is ReclaimStatus.FAILED for event in self.events)
