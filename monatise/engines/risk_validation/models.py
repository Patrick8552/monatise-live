from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from monatise.engines._validation import require_finite

from monatise.engines.decision.models import DecisionResult
from monatise.engines.fibonacci_liquidity.models import FibonacciAssessment
from monatise.engines.macro.models import MacroAssessment
from monatise.engines.market_data.models import MarketSnapshot
from monatise.engines.market_structure.models import MarketStructureAssessment
from monatise.engines.order_flow.models import OrderFlowAssessment
from monatise.engines.regime.models import RegimeAssessment
from monatise.engines.rsi.models import RSIAssessment
from monatise.engines.supply_demand.models import ZoneAssessment


class RiskDecision(StrEnum):
    APPROVED = "approved"
    CONDITIONAL = "conditional"
    REJECTED = "rejected"


class RiskSide(StrEnum):
    LONG = "long"
    SHORT = "short"
    GRID = "grid"
    NONE = "none"


class RiskIssueSeverity(StrEnum):
    WARNING = "warning"
    BLOCKER = "blocker"


@dataclass(frozen=True)
class RiskIssue:
    code: str
    severity: RiskIssueSeverity
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskRequest:
    market: MarketSnapshot
    decision: DecisionResult
    macro: MacroAssessment | None
    regime: RegimeAssessment
    structure: MarketStructureAssessment
    fibonacci: FibonacciAssessment
    zones: ZoneAssessment
    order_flow: OrderFlowAssessment
    rsi: RSIAssessment

    observed_at: datetime
    signal_expires_at: datetime

    proposed_entry: float | None = None
    proposed_invalidation: float | None = None
    proposed_target: float | None = None

    account_equity: float | None = None
    risk_percent: float = 0.01
    maximum_risk_percent: float = 0.02

    minimum_reward_risk: float = 1.5
    maximum_stop_distance_pct: float = 0.05
    minimum_stop_distance_pct: float = 0.001
    volatility_stop_multiplier: float = 1.0
    normal_buffer_pct: float = 0.001
    high_volatility_buffer_pct: float = 0.002
    allow_conditional_without_account_equity: bool = True

    def validate(self) -> None:
        require_finite(
            proposed_entry=self.proposed_entry,
            proposed_invalidation=self.proposed_invalidation,
            proposed_target=self.proposed_target,
            account_equity=self.account_equity,
            risk_percent=self.risk_percent,
            maximum_risk_percent=self.maximum_risk_percent,
            minimum_reward_risk=self.minimum_reward_risk,
            maximum_stop_distance_pct=self.maximum_stop_distance_pct,
            minimum_stop_distance_pct=self.minimum_stop_distance_pct,
            volatility_stop_multiplier=self.volatility_stop_multiplier,
            normal_buffer_pct=self.normal_buffer_pct,
            high_volatility_buffer_pct=self.high_volatility_buffer_pct,
        )
        symbols = {
            self.market.symbol,
            self.decision.symbol,
            self.regime.symbol,
            self.structure.symbol,
            self.fibonacci.symbol,
            self.zones.symbol,
            self.order_flow.symbol,
            self.rsi.symbol,
        }
        if self.macro is not None:
            symbols.add(self.macro.symbol)
        if len(symbols) != 1:
            raise ValueError("all risk inputs must use the same symbol")
        if not 0 < self.risk_percent <= 1:
            raise ValueError("risk_percent must be between 0 and 1")
        if not 0 < self.maximum_risk_percent <= 1:
            raise ValueError("maximum_risk_percent must be between 0 and 1")
        if self.risk_percent > self.maximum_risk_percent:
            raise ValueError("risk_percent exceeds maximum_risk_percent")
        if self.minimum_reward_risk <= 0:
            raise ValueError("minimum_reward_risk must be positive")
        if self.maximum_stop_distance_pct <= 0:
            raise ValueError("maximum_stop_distance_pct must be positive")
        if self.minimum_stop_distance_pct < 0:
            raise ValueError("minimum_stop_distance_pct cannot be negative")
        if self.minimum_stop_distance_pct >= self.maximum_stop_distance_pct:
            raise ValueError("minimum stop distance must be below maximum")
        if self.volatility_stop_multiplier <= 0:
            raise ValueError("volatility_stop_multiplier must be positive")
        if self.normal_buffer_pct < 0:
            raise ValueError("normal_buffer_pct cannot be negative")
        if self.high_volatility_buffer_pct < self.normal_buffer_pct:
            raise ValueError(
                "high_volatility_buffer_pct must be >= normal_buffer_pct"
            )
        if self.account_equity is not None and self.account_equity <= 0:
            raise ValueError("account_equity must be positive")


@dataclass(frozen=True)
class RiskResult:
    symbol: str
    decision: RiskDecision
    side: RiskSide
    risk_score: float
    approved_risk_percent: float
    risk_amount: float | None
    validated_entry: float | None
    validated_invalidation: float | None
    validated_target: float | None
    stop_distance: float | None
    stop_distance_pct: float | None
    reward_risk: float | None
    signal_expires_at: datetime
    issues: tuple[RiskIssue, ...]
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def approved_for_execution_policy(self) -> bool:
        return self.decision is RiskDecision.APPROVED
