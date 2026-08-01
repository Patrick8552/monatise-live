from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from monatise.engines._validation import require_finite

from monatise.engines.capital_allocation.models import AllocationResult
from monatise.engines.decision.models import DecisionResult
from monatise.engines.risk_validation.models import RiskResult


class ExecutionMode(StrEnum):
    DISABLED = "disabled"
    PAPER = "paper"
    LIVE_APPROVAL_REQUIRED = "live_approval_required"


class ExecutionDecision(StrEnum):
    BLOCKED = "blocked"
    PAPER_READY = "paper_ready"
    APPROVAL_REQUIRED = "approval_required"


class ExecutionOrderType(StrEnum):
    LIMIT = "limit"
    MARKET = "market"
    STOP_LIMIT = "stop_limit"


@dataclass(frozen=True)
class ExecutionPolicyRequest:
    decision: DecisionResult
    risk: RiskResult
    allocation: AllocationResult
    mode: ExecutionMode

    observed_at: datetime
    requested_order_type: ExecutionOrderType = ExecutionOrderType.LIMIT
    requested_leverage: float = 1.0
    maximum_leverage: float = 3.0
    maximum_slippage_pct: float = 0.002
    maximum_spread_pct: float = 0.0015
    current_spread_pct: float | None = None
    estimated_slippage_pct: float | None = None
    manual_approval_id: str | None = None
    exchange_name: str | None = None

    def validate(self) -> None:
        require_finite(
            requested_leverage=self.requested_leverage,
            maximum_leverage=self.maximum_leverage,
            maximum_slippage_pct=self.maximum_slippage_pct,
            maximum_spread_pct=self.maximum_spread_pct,
            current_spread_pct=self.current_spread_pct,
            estimated_slippage_pct=self.estimated_slippage_pct,
        )
        symbols = {
            self.decision.symbol,
            self.risk.symbol,
            self.allocation.symbol,
        }
        if len(symbols) != 1:
            raise ValueError("decision, risk, and allocation symbols must match")
        if self.requested_leverage <= 0:
            raise ValueError("requested_leverage must be positive")
        if self.maximum_leverage <= 0:
            raise ValueError("maximum_leverage must be positive")
        if self.maximum_slippage_pct < 0:
            raise ValueError("maximum_slippage_pct cannot be negative")
        if self.maximum_spread_pct < 0:
            raise ValueError("maximum_spread_pct cannot be negative")
        if (
            self.current_spread_pct is not None
            and self.current_spread_pct < 0
        ):
            raise ValueError("current_spread_pct cannot be negative")
        if (
            self.estimated_slippage_pct is not None
            and self.estimated_slippage_pct < 0
        ):
            raise ValueError("estimated_slippage_pct cannot be negative")


@dataclass(frozen=True)
class ExecutionProposal:
    symbol: str
    side: str
    order_type: ExecutionOrderType
    reference_entry: float | None
    reference_invalidation: float | None
    reference_target: float | None
    approved_capital: float | None
    approved_risk_amount: float | None
    requested_leverage: float
    expires_at: datetime
    exchange_name: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionPolicyResult:
    symbol: str
    mode: ExecutionMode
    decision: ExecutionDecision
    proposal: ExecutionProposal | None
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def may_submit_to_execution_adapter(self) -> bool:
        return False
