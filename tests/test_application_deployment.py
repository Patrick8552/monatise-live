from __future__ import annotations

import asyncio
import json

import pytest

from monatise.application.deployment import MigrationRunner, OrchestrationASGI, OrchestrationRuntime, PaperSafetyConfiguration, RedisSchedulerLeadership
from monatise.application.registry import CANONICAL_ENGINE_ORDER


def test_paper_safety_defaults_are_immutable_and_disabled():
    config = PaperSafetyConfiguration.from_environment({})
    assert config.mode == "paper"
    assert config.execution_enabled is False
    assert config.governance_kill_switch_enabled is True


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
            "dependencies": {"engine_registry": {"status": "ok", "count": 20, "order": list(CANONICAL_ENGINE_ORDER)}},
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


def test_runtime_requires_managed_dependencies_without_exposing_urls():
    runtime = OrchestrationRuntime(environment={"MONATISE_MODE": "paper"})
    with pytest.raises(RuntimeError, match="PostgreSQL configuration is unavailable"):
        asyncio.run(runtime.start())
    assert "postgresql://" not in json.dumps(runtime.dependencies)


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
