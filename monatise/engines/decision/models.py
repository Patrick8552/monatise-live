from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from monatise.engines._validation import require_finite

from monatise.engines.fibonacci_liquidity.models import FibonacciAssessment
from monatise.engines.liquidity.models import LiquidityAssessment
from monatise.engines.liquidity_sweep.models import SweepAssessment
from monatise.engines.macro.models import MacroAssessment
from monatise.engines.market_data.models import MarketSnapshot
from monatise.engines.market_structure.models import MarketStructureAssessment
from monatise.engines.order_flow.models import OrderFlowAssessment
from monatise.engines.reclaim.models import ReclaimAssessment
from monatise.engines.regime.models import RegimeAssessment
from monatise.engines.supply_demand.models import ZoneAssessment


class DecisionClassification(StrEnum):
    GRID = "grid"
    TREND = "trend"
    NO_TRADE = "no_trade"


class DecisionDirection(StrEnum):
    LONG = "long"
    SHORT = "short"
    TWO_SIDED = "two_sided"
    NONE = "none"


class DecisionState(StrEnum):
    APPROVED_FOR_RISK_REVIEW = "approved_for_risk_review"
    CONDITIONAL = "conditional"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class DecisionEvidence:
    source: str
    score: float
    direction: DecisionDirection
    weight: float
    reason: str
    blocking: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionRequest:
    market: MarketSnapshot
    macro: MacroAssessment | None
    regime: RegimeAssessment
    liquidity: LiquidityAssessment
    sweep: SweepAssessment
    zones: ZoneAssessment
    reclaim: ReclaimAssessment
    structure: MarketStructureAssessment
    fibonacci: FibonacciAssessment
    order_flow: OrderFlowAssessment

    minimum_conviction: float = 0.58
    high_conviction: float = 0.75
    maximum_conflict_ratio: float = 0.35
    grid_regime_bonus: float = 0.12
    trend_regime_bonus: float = 0.12
    require_structure_for_trend: bool = True
    require_two_sided_liquidity_for_grid: bool = True

    def validate(self) -> None:
        require_finite(
            minimum_conviction=self.minimum_conviction,
            high_conviction=self.high_conviction,
            maximum_conflict_ratio=self.maximum_conflict_ratio,
            grid_regime_bonus=self.grid_regime_bonus,
            trend_regime_bonus=self.trend_regime_bonus,
        )
        symbols = {
            self.market.symbol,
            self.regime.symbol,
            self.liquidity.symbol,
            self.sweep.symbol,
            self.zones.symbol,
            self.reclaim.symbol,
            self.structure.symbol,
            self.fibonacci.symbol,
            self.order_flow.symbol,
        }
        if self.macro is not None:
            symbols.add(self.macro.symbol)
        if len(symbols) != 1:
            raise ValueError("all decision inputs must use the same symbol")
        if not 0 <= self.minimum_conviction <= 1:
            raise ValueError("minimum_conviction must be between 0 and 1")
        if not self.minimum_conviction <= self.high_conviction <= 1:
            raise ValueError("high_conviction must be >= minimum_conviction")
        if not 0 <= self.maximum_conflict_ratio <= 1:
            raise ValueError("maximum_conflict_ratio must be between 0 and 1")
        if self.grid_regime_bonus < 0:
            raise ValueError("grid_regime_bonus cannot be negative")
        if self.trend_regime_bonus < 0:
            raise ValueError("trend_regime_bonus cannot be negative")


@dataclass(frozen=True)
class DecisionResult:
    symbol: str
    classification: DecisionClassification
    direction: DecisionDirection
    state: DecisionState
    conviction: float
    long_score: float
    short_score: float
    grid_score: float
    conflict_ratio: float
    evidence: tuple[DecisionEvidence, ...]
    blockers: tuple[str, ...]
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def passes_to_risk_engine(self) -> bool:
        return self.state is DecisionState.APPROVED_FOR_RISK_REVIEW
