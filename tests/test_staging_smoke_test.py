from __future__ import annotations

import importlib.util
from pathlib import Path

from monatise.application.registry import CANONICAL_ENGINE_ORDER


SPEC = importlib.util.spec_from_file_location("staging_smoke_test", Path(__file__).parents[1] / "scripts" / "staging_smoke_test.py")
smoke = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(smoke)


def _ready_payload():
    dependencies = {name: {"status": "ok"} for name in (
        "postgresql", "redis", "migrations", "event_bus", "state_manager", "audit_repository", "audit_integrity", "scheduler", "pipeline_orchestrator", "coinglass", "macro_provider",
    )}
    dependencies["engine_registry"] = {"status": "ok", "count": 20, "order": list(CANONICAL_ENGINE_ORDER)}
    dependencies["notifications"] = {"status": "ok", "telegram": "unavailable_optional", "openclaw": "configured_non_executable"}
    dependencies["governance"] = {"status": "ok", "kill_switch": True}
    dependencies["macro_provider"] = {"status": "ok", "mode": "degraded_unavailable_factors", "blocks_on_missing_data": False}
    return {"status": "ready", "mode": "paper", "execution_enabled": False, "dependencies": dependencies}


def test_smoke_test_succeeds_for_safe_ready_service(monkeypatch):
    monkeypatch.setattr(smoke, "get_json", lambda base, path: (200, {"status": "alive"}) if path.endswith("live") else (200, _ready_payload()))
    assert smoke.run("https://staging.example") == []


def test_smoke_test_fails_closed_on_execution_or_dependency_error(monkeypatch):
    payload = _ready_payload()
    payload["execution_enabled"] = True
    payload["dependencies"]["redis"] = {"status": "error"}
    monkeypatch.setattr(smoke, "get_json", lambda base, path: (200, {"status": "alive"}) if path.endswith("live") else (503, payload))
    failures = smoke.run("https://staging.example")
    assert "readiness failed" in failures
    assert "redis is not ready" in failures
    assert "paper-only execution invariant failed" in failures
