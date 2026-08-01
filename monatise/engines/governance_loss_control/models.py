from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from monatise.engines._validation import require_finite

from monatise.engines.capital_allocation.models import AllocationResult
from monatise.engines.execution_policy.models import ExecutionPolicyResult
from monatise.engines.portfolio_intelligence.models import PortfolioIntelligenceResult
from monatise.engines.risk_validation.models import RiskResult


class GovernanceState(StrEnum):
    NORMAL = "normal"
    CAUTION = "caution"
    COOLDOWN = "cooldown"
    FROZEN = "frozen"
    KILL_SWITCH = "kill_switch"


class GovernanceDecision(StrEnum):
    ALLOW = "allow"
    REDUCE = "reduce"
    BLOCK = "block"


class GovernanceAction(StrEnum):
    NONE = "none"
    REDUCE_RISK = "reduce_risk"
    START_COOLDOWN = "start_cooldown"
    FREEZE_NEW_SETUPS = "freeze_new_setups"
    REQUIRE_MANUAL_REVIEW = "require_manual_review"
    ACTIVATE_KILL_SWITCH = "activate_kill_switch"


@dataclass(frozen=True)
class LossControlSnapshot:
    initial_equity: float
    current_equity: float
    daily_start_equity: float
    daily_realized_pnl: float
    daily_unrealized_pnl: float
    consecutive_losses: int
    losses_last_24h: int
    open_risk_amount: float
    last_loss_at: datetime | None = None
    kill_switch_active: bool = False
    manual_freeze_active: bool = False

    def validate(self) -> None:
        require_finite(
            initial_equity=self.initial_equity,
            current_equity=self.current_equity,
            daily_start_equity=self.daily_start_equity,
            open_risk_amount=self.open_risk_amount,
        )
        if self.initial_equity <= 0:
            raise ValueError("initial_equity must be positive")
        if self.current_equity <= 0:
            raise ValueError("current_equity must be positive")
        if self.daily_start_equity <= 0:
            raise ValueError("daily_start_equity must be positive")
        if self.consecutive_losses < 0:
            raise ValueError("consecutive_losses cannot be negative")
        if self.losses_last_24h < 0:
            raise ValueError("losses_last_24h cannot be negative")
        if self.open_risk_amount < 0:
            raise ValueError("open_risk_amount cannot be negative")


@dataclass(frozen=True)
class GovernanceRequest:
    snapshot: LossControlSnapshot
    risk: RiskResult
    allocation: AllocationResult
    execution_policy: ExecutionPolicyResult
    portfolio: PortfolioIntelligenceResult | None
    observed_at: datetime

    maximum_daily_loss_pct: float = 0.04
    maximum_total_drawdown_pct: float = 0.10
    caution_drawdown_pct: float = 0.05
    maximum_consecutive_losses: int = 3
    maximum_losses_24h: int = 5
    cooldown_minutes: int = 120
    caution_risk_multiplier: float = 0.50
    allow_manual_override: bool = False
    manual_override_id: str | None = None

    def validate(self) -> None:
        self.snapshot.validate()
        symbols = {
            self.risk.symbol,
            self.allocation.symbol,
            self.execution_policy.symbol,
        }
        if len(symbols) != 1:
            raise ValueError("risk, allocation, and execution symbols must match")
        for name, value in {
            "maximum_daily_loss_pct": self.maximum_daily_loss_pct,
            "maximum_total_drawdown_pct": self.maximum_total_drawdown_pct,
            "caution_drawdown_pct": self.caution_drawdown_pct,
            "caution_risk_multiplier": self.caution_risk_multiplier,
        }.items():
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.caution_drawdown_pct > self.maximum_total_drawdown_pct:
            raise ValueError("caution drawdown cannot exceed maximum drawdown")
        if self.maximum_consecutive_losses < 1:
            raise ValueError("maximum_consecutive_losses must be positive")
        if self.maximum_losses_24h < 1:
            raise ValueError("maximum_losses_24h must be positive")
        if self.cooldown_minutes < 1:
            raise ValueError("cooldown_minutes must be positive")
        if self.allow_manual_override and not self.manual_override_id:
            raise ValueError("manual_override_id is required when override is enabled")


@dataclass(frozen=True)
class GovernanceResult:
    symbol: str
    state: GovernanceState
    decision: GovernanceDecision
    actions: tuple[GovernanceAction, ...]
    approved_risk_multiplier: float
    daily_loss_pct: float
    total_drawdown_pct: float
    cooldown_until: datetime | None
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def permits_new_setups(self) -> bool:
        return self.decision in {
            GovernanceDecision.ALLOW,
            GovernanceDecision.REDUCE,
        }
