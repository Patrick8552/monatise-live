"""Production composition root for the Monatise application layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from monatise.application.orchestrator import ApplicationInfrastructure, PipelineOrchestrator
from monatise.application.registry import EngineRegistry, canonical_registrations
from monatise.application.persistence import DurableAuditRepository, DurableEventStore, DurableStateManager, DurableTaskScheduler
from monatise.engines.market_data import MarketDataEngine
from monatise.infrastructure.audit_database import InMemoryAuditRepository
from monatise.infrastructure.configuration import ConfigurationManager
from monatise.infrastructure.dependency_injection import Container
from monatise.infrastructure.event_bus import EventBus
from monatise.infrastructure.feature_flags import FeatureFlagManager
from monatise.infrastructure.observability import ObservabilityManager
from monatise.infrastructure.observability import HealthStatus
from monatise.infrastructure.plugin_framework import PluginContext, PluginManager
from monatise.infrastructure.security import ActorIdentity, Permission, SecurityManager, SecurityPolicy
from monatise.infrastructure.state_manager import StateManager
from monatise.infrastructure.task_scheduler import TaskScheduler


@dataclass(frozen=True)
class MonatiseApplication:
    orchestrator: PipelineOrchestrator
    registry: EngineRegistry
    infrastructure: ApplicationInfrastructure

    async def start(self) -> dict[str, Any]:
        if self.registry.validate():
            raise RuntimeError("application startup validation failed")
        await self.infrastructure.plugins.start_all()
        await self.infrastructure.scheduler.start()
        await self.infrastructure.observability.run_health_checks()
        return self.orchestrator.health()

    async def shutdown(self) -> None:
        await self.infrastructure.scheduler.stop()
        await self.infrastructure.plugins.stop_all()
        await self.infrastructure.observability.export()


def create_durable_infrastructure(document_store: Any) -> ApplicationInfrastructure:
    """Build production wiring around a PostgreSQL or Redis document store."""
    container = Container()
    configuration = ConfigurationManager()
    configuration.load_defaults({"application": {"market": "crypto", "execution_enabled": False, "persistence": "durable"}})
    configuration.freeze()
    event_bus = EventBus(store=DurableEventStore(document_store))
    return ApplicationInfrastructure(
        container=container,
        event_bus=event_bus,
        configuration=configuration,
        plugins=PluginManager(context=PluginContext(container, event_bus, configuration, {"market": "crypto", "persistence": "durable"})),
        scheduler=DurableTaskScheduler(document_store),
        state=DurableStateManager(document_store),
        audit=DurableAuditRepository(document_store),
        feature_flags=FeatureFlagManager(),
        security=SecurityManager(),
        observability=ObservabilityManager(),
    )


def create_application(
    *,
    market_data_providers: dict[str, Any],
    macro_provider: Any | None = None,
    derivatives_provider: Any | None = None,
    infrastructure: ApplicationInfrastructure | None = None,
) -> MonatiseApplication:
    if infrastructure is None:
        container = Container()
        event_bus = EventBus()
        configuration = ConfigurationManager()
        configuration.load_defaults({"application": {"market": "crypto", "execution_enabled": False}})
        configuration.freeze()
        observability = ObservabilityManager()
        infrastructure = ApplicationInfrastructure(
            container=container,
            event_bus=event_bus,
            configuration=configuration,
            plugins=PluginManager(context=PluginContext(container, event_bus, configuration, {"market": "crypto"})),
            scheduler=TaskScheduler(),
            state=StateManager(),
            audit=InMemoryAuditRepository(),
            feature_flags=FeatureFlagManager(),
            security=SecurityManager(),
            observability=observability,
        )
    security = infrastructure.security
    actor = ActorIdentity("monatise-application", "application", ("analysis",), (Permission.RUN_ANALYSIS, Permission.READ_MARKET_DATA, Permission.WRITE_AUDIT, Permission.PUBLISH_NOTIFICATIONS))
    policy = SecurityPolicy("analysis_pipeline", "run", (Permission.RUN_ANALYSIS,), allowed_actor_types=("application", "scheduler", "openclaw"))
    try:
        security.register_actor(actor)
    except Exception as exc:
        if "already registered" not in str(exc):
            raise
    try:
        security.register_policy(policy)
    except Exception as exc:
        if "already registered" not in str(exc):
            raise

    registry = EngineRegistry(infrastructure.container)
    for registration in canonical_registrations():
        if registration.name == "market_data":
            engine = MarketDataEngine(market_data_providers, derivatives_provider=derivatives_provider)
        else:
            engine = registration.engine_type()
        registry.register(registration, engine)
    async def registry_health():
        status = registry.health()["status"]
        return (HealthStatus.HEALTHY if status == "healthy" else HealthStatus.UNHEALTHY, f"20-engine registry is {status}")
    infrastructure.observability.register_health_check("engine_registry", registry_health, replace=True)
    return MonatiseApplication(PipelineOrchestrator(registry, infrastructure), registry, infrastructure)
