from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from monatise.engines._validation import require_finite

from monatise.engines.liquidity.models import LiquidityAssessment
from monatise.engines.liquidity_sweep.models import SweepAssessment
from monatise.engines.market_data.models import MarketSnapshot
from monatise.engines.reclaim.models import ReclaimAssessment
from monatise.engines.regime.models import RegimeAssessment
from monatise.engines.supply_demand.models import ZoneAssessment


class StructureBias(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    CONFLICTED = "conflicted"
    UNKNOWN = "unknown"


class StructureState(StrEnum):
    BULLISH_CONTINUATION = "bullish_continuation"
    BEARISH_CONTINUATION = "bearish_continuation"
    BULLISH_REVERSAL = "bullish_reversal"
    BEARISH_REVERSAL = "bearish_reversal"
    RANGE = "range"
    TRANSITION = "transition"
    UNSTABLE = "unstable"
    UNKNOWN = "unknown"


class BreakType(StrEnum):
    BULLISH_BOS = "bullish_bos"
    BEARISH_BOS = "bearish_bos"
    BULLISH_CHOCH = "bullish_choch"
    BEARISH_CHOCH = "bearish_choch"
    FAILED_BULLISH_BREAK = "failed_bullish_break"
    FAILED_BEARISH_BREAK = "failed_bearish_break"


@dataclass(frozen=True)
class StructureEvent:
    break_type: BreakType
    level: float
    candle_index: int
    close_price: float
    displacement_ratio: float
    confirmed: bool
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketStructureRequest:
    market: MarketSnapshot
    regime: RegimeAssessment | None = None
    liquidity: LiquidityAssessment | None = None
    sweep: SweepAssessment | None = None
    reclaim: ReclaimAssessment | None = None
    zones: ZoneAssessment | None = None
    swing_window: int = 3
    confirmation_closes: int = 1
    displacement_body_ratio: float = 0.55
    break_tolerance_pct: float = 0.0005
    failed_break_window: int = 3

    def validate(self) -> None:
        require_finite(
            displacement_body_ratio=self.displacement_body_ratio,
            break_tolerance_pct=self.break_tolerance_pct,
        )
        if self.swing_window < 1:
            raise ValueError("swing_window must be positive")
        if self.confirmation_closes < 1:
            raise ValueError("confirmation_closes must be positive")
        if not 0 <= self.displacement_body_ratio <= 1:
            raise ValueError("displacement_body_ratio must be between 0 and 1")
        if self.break_tolerance_pct < 0:
            raise ValueError("break_tolerance_pct cannot be negative")
        if self.failed_break_window < 1:
            raise ValueError("failed_break_window must be positive")


@dataclass(frozen=True)
class MarketStructureAssessment:
    symbol: str
    bias: StructureBias
    state: StructureState
    events: tuple[StructureEvent, ...]
    latest_event: StructureEvent | None
    swing_highs: tuple[tuple[int, float], ...]
    swing_lows: tuple[tuple[int, float], ...]
    confidence: float
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_confirmed_break(self) -> bool:
        return any(event.confirmed for event in self.events)

    @property
    def directional(self) -> bool:
        return self.bias in {StructureBias.BULLISH, StructureBias.BEARISH}
