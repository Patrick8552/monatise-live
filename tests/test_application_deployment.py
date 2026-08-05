from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from monatise.application.deployment import COINGLASS_PROVIDER_KEY, MigrationRunner, OrchestrationASGI, OrchestrationRuntime, PaperSafetyConfiguration, RedisSchedulerLeadership, TelegramNotificationTransport, register_coinglass_provider, scheduled_analysis_configuration
from monatise.application.registry import CANONICAL_ENGINE_ORDER
from monatise.application.registry import PRODUCTION_ENGINE_ORDER
from monatise.application.production_analysis import build_production_analysis_run
from monatise.infrastructure.dependency_injection import Container


def test_paper_safety_defaults_are_immutable_and_disabled():
    config = PaperSafetyConfiguration.from_environment({})
    assert config.mode == "paper"
    assert config.execution_enabled is False
    assert config.governance_kill_switch_enabled is True


def test_startup_failure_records_phase_and_logs_traceback(caplog):
    runtime = OrchestrationRuntime(environment={})

    with caplog.at_level(logging.ERROR, logger="monatise.orchestration"):
        with pytest.raises(RuntimeError, match="PostgreSQL configuration is unavailable"):
            asyncio.run(runtime.start())

    assert runtime.dependencies["startup"] == {
        "status": "error",
        "phase": "postgresql_configuration",
        "error_type": "RuntimeError",
    }
    record = next(item for item in caplog.records if item.message.startswith("orchestration startup failed"))
    assert record.exc_info is not None


def test_lifespan_failure_is_sanitized_and_logged(caplog):
    class FailingRuntime:
        async def start(self):
            raise RuntimeError("private provider detail")

    pending = [{"type": "lifespan.startup"}]
    sent = []

    async def receive():
        return pending.pop(0)

    async def send(message):
        sent.append(message)

    with caplog.at_level(logging.ERROR, logger="monatise.orchestration"):
        asyncio.run(OrchestrationASGI(FailingRuntime())({"type": "lifespan"}, receive, send))

    assert sent == [{"type": "lifespan.startup.failed", "message": "startup_failed"}]
    record = next(item for item in caplog.records if item.message == "application lifespan startup failed")
    assert record.exc_info is not None


def test_telegram_transport_returns_provider_message_id(monkeypatch):
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self): return b'{"ok":true,"result":{"message_id":321}}'

    monkeypatch.setattr("monatise.application.deployment.urlopen", lambda request, timeout: Response())
    transport = TelegramNotificationTransport(lambda: "test-token")

    assert asyncio.run(transport.send_message("chat", "hello")) == 321


@pytest.mark.parametrize(
    "environment",
    [
        {"MONATISE_MODE": "live"},
        {"MONATISE_NETWORK": "mainnet"},
        {"MONATISE_EXECUTION_ENABLED": "true"},
        {"MONATISE_AUTONOMOUS_EXECUTION": "1"},
        {"MONATISE_EXECUTION_ADAPTER_ENABLED": "yes"},
        {"MONATISE_OPENCLAW_EXECUTION_ALLOWED": "true"},
        {"MONATISE_TELEGRAM_EXECUTION_ALLOWED": "true"},
        {"MONATISE_GOVERNANCE_KILL_SWITCH_ENABLED": "false"},
        {"MONATISE_AUDIT_LOGGING_ENABLED": "false"},
    ],
)
def test_paper_safety_rejects_unsafe_environment(environment):
    with pytest.raises(ValueError, match="unsafe orchestration configuration"):
        PaperSafetyConfiguration.from_environment(environment)


def test_scheduled_analysis_configuration_is_explicit_bounded_and_crypto_only():
    assert scheduled_analysis_configuration({}) is None
    assert scheduled_analysis_configuration({
        "MONATISE_SCHEDULED_ANALYSIS_ENABLED": "true",
        "MONATISE_SCHEDULED_ANALYSIS_SYMBOLS": "BTC, ETH, BTC",
        "MONATISE_SCHEDULED_ANALYSIS_TIMEFRAMES": "5m,15m,5m",
    }) == (("BTC", "ETH"), ("5m", "15m"))
    with pytest.raises(ValueError, match="unsupported scheduled analysis symbols"):
        scheduled_analysis_configuration({
            "MONATISE_SCHEDULED_ANALYSIS_ENABLED": "true",
            "MONATISE_SCHEDULED_ANALYSIS_SYMBOLS": "XAUUSD",
        })
    with pytest.raises(ValueError, match="unsupported scheduled analysis timeframes"):
        scheduled_analysis_configuration({
            "MONATISE_SCHEDULED_ANALYSIS_ENABLED": "true",
            "MONATISE_SCHEDULED_ANALYSIS_TIMEFRAMES": "2h",
        })


def test_production_analysis_graph_completely_excludes_risk_engine_and_consumers():
    run = build_production_analysis_run("BTC", interval="15m")

    assert tuple(run.stage_inputs) == PRODUCTION_ENGINE_ORDER
    assert "risk_validation" not in run.stage_inputs
    assert "capital_allocation" not in run.stage_inputs
    assert "execution_policy" not in run.stage_inputs
    assert "governance_loss_control" not in run.stage_inputs
    assert set(PRODUCTION_ENGINE_ORDER).issubset(CANONICAL_ENGINE_ORDER)


def test_runtime_registers_paper_only_analysis_jobs_for_each_configured_symbol():
    class Scheduler:
        def __init__(self): self.definitions = []
        async def register(self, definition): self.definitions.append(definition)

    scheduler = Scheduler()
    runtime = OrchestrationRuntime(environment={
        "MONATISE_SCHEDULED_ANALYSIS_ENABLED": "true",
        "MONATISE_SCHEDULED_ANALYSIS_SYMBOLS": "BTC,SOL",
        "MONATISE_SCHEDULED_ANALYSIS_TIMEFRAMES": "5m,1h",
    })
    runtime.application = SimpleNamespace(infrastructure=SimpleNamespace(scheduler=scheduler))

    job_ids = asyncio.run(runtime._register_scheduled_analysis())

    assert job_ids == ("scheduled-analysis-btc-5m", "scheduled-analysis-btc-1h", "scheduled-analysis-sol-5m", "scheduled-analysis-sol-1h")
    assert [item.interval.total_seconds() for item in scheduler.definitions] == [300, 3600, 300, 3600]
    assert all(item.metadata["execution_enabled"] is False for item in scheduler.definitions)
    assert all(item.metadata["notification_policy"] == "qualified_changes" for item in scheduler.definitions)
    assert all("paper-only" in item.tags for item in scheduler.definitions)


@pytest.mark.parametrize(("direction", "signed_score"), [("long", 8), ("short", -8)])
def test_qualified_directional_setups_are_claimed_for_telegram(direction, signed_score):
    runtime = OrchestrationRuntime(environment={})
    decision = SimpleNamespace(
        classification=SimpleNamespace(value="trend"),
        direction=SimpleNamespace(value=direction),
        metadata={"signed_signal_score": signed_score, "minimum_signal_score": 7},
    )
    risk = SimpleNamespace(
        decision=SimpleNamespace(value="approved"),
        validated_entry=65_000,
        validated_invalidation=63_500 if direction == "long" else 66_500,
        validated_target=68_000 if direction == "long" else 62_000,
        metadata={},
    )
    result = SimpleNamespace(
        symbol="BTC",
        status=SimpleNamespace(value="completed"),
        context=SimpleNamespace(outputs={"decision": decision, "risk_validation": risk}),
    )

    assert runtime._claim_material_telegram_signal(result, "1h") is True
    assert runtime._claim_material_telegram_signal(result, "1h") is False


@pytest.mark.parametrize(("direction", "signed_score"), [("long", -8), ("short", 8)])
def test_mismatched_directional_scores_are_not_claimed_for_telegram(direction, signed_score):
    runtime = OrchestrationRuntime(environment={})
    result = SimpleNamespace(
        symbol="BTC",
        status=SimpleNamespace(value="completed"),
        context=SimpleNamespace(outputs={
            "decision": SimpleNamespace(
                classification=SimpleNamespace(value="trend"),
                direction=SimpleNamespace(value=direction),
                metadata={"signed_signal_score": signed_score, "minimum_signal_score": 7},
            ),
            "risk_validation": SimpleNamespace(metadata={}),
        }),
    )

    assert runtime._claim_material_telegram_signal(result, "1h") is False


@pytest.mark.parametrize(("pipeline_status", "risk_decision"), [("blocked", "approved"), ("completed", "rejected")])
def test_risk_blocked_directional_setups_are_not_claimed_for_telegram(pipeline_status, risk_decision):
    runtime = OrchestrationRuntime(environment={})
    result = SimpleNamespace(
        symbol="BTC",
        status=SimpleNamespace(value=pipeline_status),
        context=SimpleNamespace(outputs={
            "decision": SimpleNamespace(
                classification=SimpleNamespace(value="trend"),
                direction=SimpleNamespace(value="long"),
                metadata={"signed_signal_score": 8, "minimum_signal_score": 7},
            ),
            "risk_validation": SimpleNamespace(
                decision=SimpleNamespace(value=risk_decision),
                metadata={},
            ),
        }),
    )

    assert runtime._claim_material_telegram_signal(result, "1h") is False


def test_runtime_registers_fail_closed_hierarchy_shadow_jobs_without_publication():
    class Scheduler:
        def __init__(self): self.definitions = []
        async def register(self, definition): self.definitions.append(definition)

    scheduler = Scheduler()
    runtime = OrchestrationRuntime(environment={
        "MONATISE_HIERARCHICAL_SHADOW_ENABLED": "true",
        "MONATISE_SCHEDULED_ANALYSIS_SYMBOLS": "BTC,ETH",
    })
    runtime.application = SimpleNamespace(infrastructure=SimpleNamespace(scheduler=scheduler))
    runtime.coinglass = SimpleNamespace()

    job_ids = asyncio.run(runtime._register_hierarchy_shadow(SimpleNamespace()))

    assert job_ids == ("hierarchy-shadow-btc", "hierarchy-shadow-eth")
    assert all(item.interval.total_seconds() == 60 for item in scheduler.definitions)
    assert all(item.metadata["shadow"] is True for item in scheduler.definitions)
    assert all(item.metadata["telegram_publish_enabled"] is False for item in scheduler.definitions)
    assert all(item.metadata["execution_enabled"] is False for item in scheduler.definitions)
    assert runtime.dependencies["hierarchy_shadow"]["enabled"] is True


def test_runtime_registers_btc_15m_5m_confluence_on_a_15_minute_cycle():
    class Scheduler:
        def __init__(self): self.definitions = []
        async def register(self, definition): self.definitions.append(definition)

    scheduler = Scheduler()
    runtime = OrchestrationRuntime(environment={
        "MONATISE_HIERARCHICAL_SHADOW_ENABLED": "true",
        "MONATISE_HIERARCHICAL_INTERVAL_SECONDS": "900",
        "MONATISE_HIERARCHICAL_ALWAYS_COLLECT_5M": "true",
        "MONATISE_SCHEDULED_ANALYSIS_SYMBOLS": "BTC",
    })
    runtime.application = SimpleNamespace(infrastructure=SimpleNamespace(scheduler=scheduler))
    runtime.coinglass = SimpleNamespace()

    job_ids = asyncio.run(runtime._register_hierarchy_shadow(SimpleNamespace()))

    assert job_ids == ("hierarchy-shadow-btc",)
    definition = scheduler.definitions[0]
    assert definition.interval.total_seconds() == 900
    assert definition.metadata["confluence_timeframes"] == ("15m", "5m")


def test_runtime_reports_requested_hierarchy_publication_without_publisher_as_error():
    class Scheduler:
        def __init__(self): self.definitions = []
        async def register(self, definition): self.definitions.append(definition)

    scheduler = Scheduler()
    runtime = OrchestrationRuntime(environment={
        "MONATISE_HIERARCHICAL_SHADOW_ENABLED": "true",
        "MONATISE_HIERARCHICAL_TELEGRAM_PUBLISH_ENABLED": "true",
        "MONATISE_SCHEDULED_ANALYSIS_SYMBOLS": "BTC",
    })
    runtime.application = SimpleNamespace(infrastructure=SimpleNamespace(scheduler=scheduler))
    runtime.coinglass = SimpleNamespace()

    asyncio.run(runtime._register_hierarchy_shadow(SimpleNamespace()))

    status = runtime.dependencies["hierarchy_shadow"]
    assert status["status"] == "error"
    assert status["telegram_publish_enabled"] is True
    assert status["telegram_publisher_configured"] is False
    assert status["telegram_publication_operational"] is False
    reconciliation = next(item for item in scheduler.definitions if item.job_id == "hierarchy-publication-reconciliation")
    assert reconciliation.metadata == {
        "operator_resolution_required": True,
        "automatic_resend": False,
        "execution_enabled": False,
    }


def test_runtime_notifies_every_analysis_result():
    delivered = []

    class Orchestrator:
        def __init__(self): self.completed = False
        async def run(self, run):
            outputs = {"decision": SimpleNamespace(classification=SimpleNamespace(value="trend"))}
            if self.completed:
                outputs.update({name: object() for name in (
                    "risk_validation", "capital_allocation", "execution_policy", "governance_loss_control",
                )})
            return SimpleNamespace(
                run_id="run-1", correlation_id=run.correlation_id, symbol=run.symbol,
                status=SimpleNamespace(value="completed" if self.completed else "blocked"),
                blocked_by=None if self.completed else "risk_validation",
                context=SimpleNamespace(outputs=outputs),
                statistics=SimpleNamespace(completed_stages=19 if self.completed else 12),
            )

    class Telegram:
        async def deliver(self, result): delivered.append(result.run_id)

    orchestrator = Orchestrator()
    runtime = OrchestrationRuntime(environment={})
    runtime.application = SimpleNamespace(orchestrator=orchestrator)
    runtime.telegram = Telegram()

    asyncio.run(runtime.analyse("BTC", source="monatise.scheduler"))
    assert delivered == ["run-1"]
    orchestrator.completed = True
    asyncio.run(runtime.analyse("BTC", source="monatise.scheduler"))
    assert delivered == ["run-1", "run-1"]


class _ReadyRuntime:
    async def start(self):
        return None

    async def shutdown(self):
        return None

    def readiness(self):
        return True, {
            "status": "ready",
            "mode": "paper",
            "execution_enabled": False,
            "dependencies": {"engine_registry": {"status": "ok", "count": 19, "order": list(CANONICAL_ENGINE_ORDER)}},
        }


def _request(app, path):
    async def call():
        messages = []

        async def receive():
            return {"type": "http.request"}

        async def send(message):
            messages.append(message)

        await app({"type": "http", "path": path}, receive, send)
        return messages

    messages = asyncio.run(call())
    return messages[0]["status"], json.loads(messages[1]["body"])


def test_asgi_liveness_and_readiness():
    app = OrchestrationASGI(_ReadyRuntime())
    assert _request(app, "/health/live") == (200, {"status": "alive"})
    code, payload = _request(app, "/health/ready")
    assert code == 200
    assert payload["execution_enabled"] is False


def test_asgi_readiness_is_sanitized_when_unavailable():
    class Runtime(_ReadyRuntime):
        def readiness(self):
            return False, {"status": "not_ready", "execution_enabled": False, "dependencies": {"postgresql": {"status": "error", "reason": "ConnectionError"}}}

    code, payload = _request(OrchestrationASGI(Runtime()), "/health/ready")
    assert code == 503
    rendered = json.dumps(payload)
    assert "postgresql://" not in rendered
    assert "password" not in rendered.casefold()


class _Redis:
    def __init__(self):
        self.value = None

    async def set(self, key, value, **kwargs):
        if kwargs.get("nx") and self.value is not None:
            return False
        self.value = value
        return True

    async def eval(self, script, count, key, *args):
        if "DEL" in script and self.value == args[0]:
            self.value = None
            return 1
        if "EXPIRE" in script and self.value == args[0]:
            return 1
        return 0


def test_scheduler_leadership_is_singleton_and_recoverable():
    async def scenario():
        redis = _Redis()
        first = RedisSchedulerLeadership(redis, namespace="test", ttl_seconds=30)
        second = RedisSchedulerLeadership(redis, namespace="test", ttl_seconds=30)
        assert await first.acquire() is True
        assert await second.acquire() is False
        await first.release()
        assert await second.acquire() is True
        await second.release()

    asyncio.run(scenario())


def test_scheduler_non_leader_retries_and_starts_after_release():
    async def scenario():
        redis = _Redis()
        first = RedisSchedulerLeadership(redis, namespace="test", ttl_seconds=0.03)
        second = RedisSchedulerLeadership(redis, namespace="test", ttl_seconds=0.03)
        started = asyncio.Event()

        assert await first.acquire() is True
        assert await second.acquire_or_wait(started.set) is False
        await first.release()
        await asyncio.wait_for(started.wait(), timeout=0.2)
        assert second.is_leader is True
        await second.release()

    asyncio.run(scenario())


def test_scheduler_stops_and_recontends_after_leadership_loss():
    async def scenario():
        redis = _Redis()
        leadership = RedisSchedulerLeadership(redis, namespace="test", ttl_seconds=0.03)
        restarted = asyncio.Event()
        stopped = asyncio.Event()

        assert await leadership.acquire_or_wait(restarted.set, stopped.set) is True
        redis.value = "another-leader"
        await asyncio.wait_for(stopped.wait(), timeout=0.2)
        await asyncio.sleep(0)

        assert leadership.is_leader is False
        assert leadership._contender is not None  # noqa: SLF001
        await leadership.release()

    asyncio.run(scenario())


def test_coinglass_request_failure_makes_runtime_not_ready_even_with_fallback_policy():
    runtime = OrchestrationRuntime()
    runtime.dependencies["coinglass"] = {"status": "ok"}
    runtime.dependencies["market_data"] = {"status": "ok"}
    runtime.coinglass = SimpleNamespace(
        health=lambda: SimpleNamespace(healthy=False, consecutive_failures=3)
    )

    ready, payload = runtime.readiness()

    assert ready is False
    assert payload["dependencies"]["coinglass"] == {
        "status": "error",
        "latest_request": "failed",
        "consecutive_failures": 3,
    }


def test_single_coinglass_request_failure_is_degraded_but_still_ready():
    runtime = OrchestrationRuntime()
    runtime.safety = SimpleNamespace()
    runtime.application = SimpleNamespace(registry=SimpleNamespace(ordered=lambda: tuple(SimpleNamespace(name=name) for name in PRODUCTION_ENGINE_ORDER)))
    runtime.dependencies = {key: {"status": "ok"} for key in (
        "configuration", "postgresql", "migrations", "redis", "event_bus", "state_manager",
        "audit_repository", "audit_integrity", "audit_logging", "scheduler", "engine_registry",
        "pipeline_orchestrator", "governance", "notifications", "coinglass", "market_data", "hierarchy_shadow",
    )}
    runtime.coinglass = SimpleNamespace(health=lambda: SimpleNamespace(healthy=False, consecutive_failures=1))

    ready, payload = runtime.readiness()

    assert ready is True
    assert payload["dependencies"]["coinglass"] == {
        "status": "ok", "latest_request": "degraded", "consecutive_failures": 1,
    }


def test_runtime_requires_managed_dependencies_without_exposing_urls():
    runtime = OrchestrationRuntime(environment={"MONATISE_MODE": "paper"})
    with pytest.raises(RuntimeError, match="PostgreSQL configuration is unavailable"):
        asyncio.run(runtime.start())
    assert "postgresql://" not in json.dumps(runtime.dependencies)


def test_real_coinglass_adapter_is_resolved_through_di_without_exposing_key():
    container = Container()
    adapter = register_coinglass_provider(container, {"COINGLASS_API_KEY": "never-render-this"}, transport=lambda *_: {"code": 0, "data": []})
    assert container.resolve(COINGLASS_PROVIDER_KEY) is adapter
    assert container.registrations[0].metadata["execution_enabled"] is False
    assert "never-render-this" not in repr(container.registrations)


def test_runtime_uses_coinglass_with_public_backpack_fallback():
    primary = object()
    fallback = object()
    runtime = OrchestrationRuntime()
    runtime.coinglass = primary
    runtime.backpack = fallback

    assert runtime.market_data_providers() == {
        "coinglass": primary,
        "backpack_public": fallback,
    }


class _MigrationCursor:
    def __init__(self, row=None):
        self.row = row

    async def fetchone(self):
        return self.row


class _MigrationConnection:
    def __init__(self):
        self.queries = []

    async def execute(self, query, params=None):
        self.queries.append((query, params))
        return _MigrationCursor(None)


def test_migrations_use_advisory_lock_and_record_version(tmp_path):
    migration = tmp_path / "001_test.sql"
    migration.write_text("CREATE TABLE IF NOT EXISTS test_table(id INT);", encoding="utf-8")
    connection = _MigrationConnection()
    runner = MigrationRunner(connection, tmp_path)
    asyncio.run(runner.run())
    rendered = "\n".join(query for query, _ in connection.queries)
    assert "pg_advisory_lock" in rendered
    assert "pg_advisory_unlock" in rendered
    assert "monatise_schema_migrations" in rendered
    assert runner.current is True
    assert runner.version == "001_test"


def test_render_blueprint_targets_production_only():
    production = (Path(__file__).parents[1] / "render.yaml").read_text(encoding="utf-8")
    assert "name: monatise-live" in production
