"""Canonical, DI-backed registry for the twenty crypto analysis engines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from monatise.infrastructure.dependency_injection import Container


CANONICAL_ENGINE_ORDER = (
    "market_data", "regime", "liquidity", "liquidity_sweep",
    "supply_demand", "reclaim", "market_structure", "fibonacci_liquidity",
    "order_flow", "decision", "rsi", "risk_validation", "capital_allocation",
    "execution_policy", "portfolio_intelligence", "reporting_intelligence",
    "intelligence_learning", "integration", "governance_loss_control",
)


@dataclass(frozen=True)
class EngineRegistration:
    name: str
    engine_type: type
    method: str
    dependencies: tuple[str, ...]
    retryable: bool = False
    blocking: Callable[[Any], bool] | None = None
    metadata: tuple[tuple[str, str], ...] = (("market", "crypto"),)


def _decision_is(output: Any, blocked: set[str]) -> bool:
    decision = getattr(output, "decision", getattr(output, "state", None))
    return str(getattr(decision, "value", decision)).lower() in blocked


def _nested_state_is(output: Any, attribute: str, blocked: set[str]) -> bool:
    value = output
    for part in attribute.split("."):
        value = getattr(value, part, None)
    return str(getattr(value, "value", value)).lower() in blocked


def _property_is_false(output: Any, attribute: str) -> bool:
    return getattr(output, attribute, None) is not True


class EngineRegistry:
    def __init__(self, container: Container) -> None:
        self._container = container
        self._entries: dict[str, EngineRegistration] = {}

    def register(self, registration: EngineRegistration, engine: Any) -> None:
        if registration.name not in CANONICAL_ENGINE_ORDER:
            raise ValueError(f"non-canonical engine: {registration.name}")
        if registration.name in self._entries:
            raise ValueError(f"engine already registered: {registration.name}")
        if not isinstance(engine, registration.engine_type):
            raise TypeError(f"{registration.name} has an invalid implementation")
        if not callable(getattr(engine, registration.method, None)):
            raise TypeError(f"{registration.name} does not implement {registration.method}")
        self._container.register_instance(("engine", registration.name), engine)
        self._entries[registration.name] = registration

    def resolve(self, name: str) -> Any:
        self.require(name)
        return self._container.resolve(("engine", name))

    def require(self, name: str) -> EngineRegistration:
        try:
            return self._entries[name]
        except KeyError as exc:
            raise KeyError(f"engine is not registered: {name}") from exc

    def ordered(self) -> tuple[EngineRegistration, ...]:
        return tuple(self._entries[name] for name in CANONICAL_ENGINE_ORDER if name in self._entries)

    def validate(self, *, complete: bool = True) -> tuple[str, ...]:
        errors = list(self._container.validate_graph())
        if complete:
            missing = [name for name in CANONICAL_ENGINE_ORDER if name not in self._entries]
            if missing:
                errors.append("missing engines: " + ", ".join(missing))
        for entry in self.ordered():
            unknown = [name for name in entry.dependencies if name not in self._entries]
            if unknown:
                errors.append(f"{entry.name} has missing dependencies: {', '.join(unknown)}")
            if any(CANONICAL_ENGINE_ORDER.index(dep) >= CANONICAL_ENGINE_ORDER.index(entry.name) for dep in entry.dependencies if dep in CANONICAL_ENGINE_ORDER):
                errors.append(f"{entry.name} has an out-of-order dependency")
        return tuple(errors)

    def health(self) -> dict[str, Any]:
        errors = self.validate()
        return {"status": "healthy" if not errors else "unhealthy", "engine_count": len(self._entries), "errors": errors}


def canonical_registrations() -> tuple[EngineRegistration, ...]:
    from monatise.engines.capital_allocation import CapitalAllocationEngine
    from monatise.engines.decision import DecisionEngine
    from monatise.engines.execution_policy import ExecutionPolicyEngine
    from monatise.engines.fibonacci_liquidity import FibonacciLiquidityEngine
    from monatise.engines.governance_loss_control import GovernanceLossControlEngine
    from monatise.engines.integration import IntegrationEngine
    from monatise.engines.intelligence_learning import IntelligenceLearningEngine
    from monatise.engines.liquidity import LiquidityEngine
    from monatise.engines.liquidity_sweep import LiquiditySweepEngine
    from monatise.engines.market_data import MarketDataEngine
    from monatise.engines.market_structure import MarketStructureEngine
    from monatise.engines.order_flow import OrderFlowIntelligenceEngine
    from monatise.engines.portfolio_intelligence import PortfolioIntelligenceEngine
    from monatise.engines.reclaim import ReclaimEngine
    from monatise.engines.regime import RegimeEngine
    from monatise.engines.reporting_intelligence import ReportingIntelligenceEngine
    from monatise.engines.risk_validation import RiskValidationEngine
    from monatise.engines.rsi import RSIEngine
    from monatise.engines.supply_demand import SupplyDemandEngine
    types = (MarketDataEngine, RegimeEngine, LiquidityEngine, LiquiditySweepEngine, SupplyDemandEngine, ReclaimEngine, MarketStructureEngine, FibonacciLiquidityEngine, OrderFlowIntelligenceEngine, DecisionEngine, RSIEngine, RiskValidationEngine, CapitalAllocationEngine, ExecutionPolicyEngine, PortfolioIntelligenceEngine, ReportingIntelligenceEngine, IntelligenceLearningEngine, IntegrationEngine, GovernanceLossControlEngine)
    methods = ("collect", "assess", "assess", "assess", "assess", "assess", "assess", "assess", "assess", "assess", "assess", "assess", "assess", "assess", "assess", "build", "assess", "build", "assess")
    retryable = {"market_data", "order_flow", "integration"}
    blockers = {
        "market_data": lambda value: _property_is_false(getattr(value, "quality", None), "usable"),
        "decision": lambda value: (
            _property_is_false(value, "passes_to_risk_engine")
            or _nested_state_is(value, "classification", {"no_trade"})
        ),
        "risk_validation": lambda value: _property_is_false(value, "approved_for_execution_policy"),
        "capital_allocation": lambda value: _property_is_false(value, "approved_for_execution_policy"),
        "execution_policy": lambda value: _decision_is(value, {"blocked", "rejected"}),
        "portfolio_intelligence": lambda value: _property_is_false(value, "permits_new_allocation"),
        "integration": lambda value: _nested_state_is(value, "status", {"blocked", "failed"}),
        "governance_loss_control": lambda value: (
            _property_is_false(value, "permits_new_setups")
            or _nested_state_is(value, "state", {"frozen", "kill_switch"})
        ),
    }
    return tuple(EngineRegistration(name, engine_type, method, CANONICAL_ENGINE_ORDER[:index], name in retryable, blockers.get(name)) for index, (name, engine_type, method) in enumerate(zip(CANONICAL_ENGINE_ORDER, types, methods)))
