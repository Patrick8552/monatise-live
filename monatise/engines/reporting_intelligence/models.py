from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from monatise.engines.capital_allocation.models import AllocationResult
from monatise.engines.decision.models import DecisionResult
from monatise.engines.execution_policy.models import ExecutionPolicyResult
from monatise.engines.fibonacci_liquidity.models import FibonacciAssessment
from monatise.engines.liquidity.models import LiquidityAssessment
from monatise.engines.liquidity_sweep.models import SweepAssessment
from monatise.engines.macro.models import MacroAssessment
from monatise.engines.market_data.models import MarketSnapshot
from monatise.engines.market_structure.models import MarketStructureAssessment
from monatise.engines.order_flow.models import OrderFlowAssessment
from monatise.engines.portfolio_intelligence.models import PortfolioIntelligenceResult
from monatise.engines.reclaim.models import ReclaimAssessment
from monatise.engines.regime.models import RegimeAssessment
from monatise.engines.risk_validation.models import RiskResult
from monatise.engines.rsi.models import RSIAssessment
from monatise.engines.supply_demand.models import ZoneAssessment


class ReportChannel(StrEnum):
    DASHBOARD = "dashboard"
    TELEGRAM = "telegram"
    AUDIT = "audit"
    API = "api"


class ReportSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    BLOCKED = "blocked"
    APPROVED = "approved"


@dataclass(frozen=True)
class ReportSection:
    name: str
    summary: str
    severity: ReportSeverity
    score: float | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReportRequest:
    generated_at: datetime
    channel: ReportChannel

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
    decision: DecisionResult
    rsi: RSIAssessment
    risk: RiskResult
    allocation: AllocationResult
    execution_policy: ExecutionPolicyResult
    portfolio: PortfolioIntelligenceResult | None = None

    include_full_evidence: bool = False
    include_debug_metadata: bool = False

    def validate(self) -> None:
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
            self.decision.symbol,
            self.rsi.symbol,
            self.risk.symbol,
            self.allocation.symbol,
            self.execution_policy.symbol,
        }
        if self.macro is not None:
            symbols.add(self.macro.symbol)
        if len(symbols) != 1:
            raise ValueError("all report inputs must use the same symbol")


@dataclass(frozen=True)
class ReportResult:
    symbol: str
    channel: ReportChannel
    headline: str
    severity: ReportSeverity
    summary: str
    sections: tuple[ReportSection, ...]
    decision_trace: tuple[str, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    payload: dict[str, Any]
    generated_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def publishable(self) -> bool:
        return True
