from __future__ import annotations

from dataclasses import dataclass
import asyncio

import pytest

from monatise.application.models import AnalysisRun, PipelineContext, PipelineExecutionMetadata, PipelineStage
from monatise.application.orchestrator import ApplicationInfrastructure, PipelineOrchestrator
from monatise.application.registry import CANONICAL_ENGINE_ORDER, EngineRegistration, EngineRegistry
from monatise.application.registry import canonical_registrations
from monatise.application.orchestrator import _json_safe
from monatise.infrastructure.audit_database import InMemoryAuditRepository
from monatise.infrastructure.configuration import ConfigurationManager
from monatise.infrastructure.dependency_injection import Container
from monatise.infrastructure.event_bus import EventBus
from monatise.infrastructure.feature_flags import FeatureFlagManager
from monatise.infrastructure.observability import ObservabilityManager
from monatise.infrastructure.plugin_framework import PluginContext, PluginManager
from monatise.infrastructure.security import ActorIdentity, Permission, SecurityManager, SecurityPolicy
from monatise.infrastructure.state_manager import StateManager
from monatise.infrastructure.task_scheduler import TaskScheduler


@dataclass(frozen=True)
class Output:
    name: str
    decision: str = "approved"


class FakeEngine:
    def __init__(self, name: str, calls: list[str], decision: str = "approved", fail_times: int = 0) -> None:
        self.name, self.calls, self.decision, self.fail_times = name, calls, decision, fail_times

    def assess(self, request):
        self.calls.append(self.name)
        if self.fail_times:
            self.fail_times -= 1
            raise TimeoutError("temporary provider failure")
        return Output(self.name, self.decision)


def make_orchestrator(*, blocked_at: str | None = None, flaky_at: str | None = None):
    container = Container()
    registry = EngineRegistry(container)
    calls: list[str] = []
    for index, name in enumerate(CANONICAL_ENGINE_ORDER):
        blocking = (lambda output: output.decision != "approved") if name == blocked_at else None
        registry.register(EngineRegistration(name, FakeEngine, "assess", CANONICAL_ENGINE_ORDER[:index], retryable=name == flaky_at, blocking=blocking), FakeEngine(name, calls, "rejected" if name == blocked_at else "approved", 1 if name == flaky_at else 0))
    config = ConfigurationManager()
    config.load_defaults({"application": {"market": "crypto"}})
    config.freeze()
    bus = EventBus()
    security = SecurityManager()
    security.register_actor(ActorIdentity("test", "application", ("test",), (Permission.RUN_ANALYSIS,)))
    security.register_policy(SecurityPolicy("analysis_pipeline", "run", (Permission.RUN_ANALYSIS,), allowed_actor_types=("application",)))
    infra = ApplicationInfrastructure(container, bus, config, PluginManager(context=PluginContext(container, bus, config)), TaskScheduler(), StateManager(), InMemoryAuditRepository(), FeatureFlagManager(), security, ObservabilityManager())
    return PipelineOrchestrator(registry, infra), calls, bus


def test_pipeline_executes_all_nineteen_engines_in_canonical_order():
    orchestrator, calls, _ = make_orchestrator()
    inputs = {name: object() for name in CANONICAL_ENGINE_ORDER}
    result = asyncio.run(orchestrator.run(AnalysisRun("BTC", inputs, metadata=PipelineExecutionMetadata(actor_id="test", retry_delay_seconds=0))))
    assert result.status is PipelineStage.COMPLETED
    assert calls == list(CANONICAL_ENGINE_ORDER)
    assert result.statistics.completed_stages == 19
    assert result.execution_enabled is False


def test_blocking_result_stops_every_downstream_engine():
    orchestrator, calls, _ = make_orchestrator(blocked_at="risk_validation")
    inputs = {name: object() for name in CANONICAL_ENGINE_ORDER}
    result = asyncio.run(orchestrator.run(AnalysisRun("ETH", inputs, metadata=PipelineExecutionMetadata(actor_id="test", retry_delay_seconds=0))))
    assert result.status is PipelineStage.BLOCKED
    assert result.blocked_by == "risk_validation"
    assert calls[-1] == "risk_validation"
    assert "capital_allocation" not in calls


def test_analysis_run_rejects_forex():
    with pytest.raises(ValueError, match="forex"):
        AnalysisRun("EURUSD", {})


def test_retryable_provider_failure_recovers_and_records_attempts():
    orchestrator, calls, _ = make_orchestrator(flaky_at="market_data")
    inputs = {name: object() for name in CANONICAL_ENGINE_ORDER}
    result = asyncio.run(orchestrator.run(AnalysisRun("SOL", inputs, metadata=PipelineExecutionMetadata(actor_id="test", maximum_attempts=2, retry_delay_seconds=0))))
    assert result.status is PipelineStage.COMPLETED
    assert calls.count("market_data") == 2
    assert result.statistics.attempts["market_data"] == 2


def test_engine_error_produces_structured_failure_and_stops_pipeline():
    orchestrator, calls, _ = make_orchestrator(flaky_at="market_data")
    engine = orchestrator.registry.resolve("market_data")
    engine.fail_times = 3
    inputs = {name: object() for name in CANONICAL_ENGINE_ORDER}
    result = asyncio.run(orchestrator.run(AnalysisRun("BTC", inputs, metadata=PipelineExecutionMetadata(actor_id="test", maximum_attempts=2, retry_delay_seconds=0))))
    assert result.status is PipelineStage.FAILED
    assert result.failure is not None
    assert result.failure.engine == "market_data"
    assert calls == ["market_data", "market_data"]


@pytest.mark.parametrize(
    ("engine_name", "output"),
    (
        ("market_data", type("Market", (), {"quality": type("Quality", (), {"usable": False})()})()),
        ("decision", type("Decision", (), {"passes_to_risk_engine": False})()),
        ("risk_validation", type("Risk", (), {"approved_for_execution_policy": False})()),
        ("capital_allocation", type("Allocation", (), {"approved_for_execution_policy": False})()),
        ("execution_policy", type("Policy", (), {"decision": "blocked"})()),
        ("governance_loss_control", type("Governance", (), {"permits_new_setups": False})()),
        ("decision", type("NoTrade", (), {"passes_to_risk_engine": True, "classification": "no_trade"})()),
        ("governance_loss_control", type("KillSwitch", (), {"permits_new_setups": True, "state": "kill_switch"})()),
    ),
)
def test_canonical_blocking_contracts(engine_name, output):
    registration = next(item for item in canonical_registrations() if item.name == engine_name)
    assert registration.blocking is not None
    assert registration.blocking(output)


def test_immutable_workflow_models_are_json_serializable():
    run = AnalysisRun("BTC", {"market_data": object()})
    value = _json_safe(PipelineContext(run))
    assert value["run"]["symbol"] == "BTC"
    assert value["run"]["stage_inputs"]["market_data"].startswith("<object object")
