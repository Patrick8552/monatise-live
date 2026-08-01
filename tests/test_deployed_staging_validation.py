from __future__ import annotations

import importlib.util
from pathlib import Path


SPEC = importlib.util.spec_from_file_location("deployed_staging_validation", Path(__file__).parents[1] / "scripts" / "deployed_staging_validation.py")
validation = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(validation)


def test_deployed_scenarios_enforce_no_trade_and_governance(monkeypatch):
    payloads = {
        "live": {"classification": "trend", "execution_enabled": False},
        "no_trade": {"classification": "no_trade", "risk_validation_invoked": False, "execution_enabled": False},
        "governance_block": {"blocked_by": "governance_loss_control", "execution_enabled": False},
    }
    monkeypatch.setattr(validation, "post_scenario", lambda base, token, scenario: (200, payloads[scenario]))
    assert validation.run("https://staging.example", "secret") == []


def test_deployed_scenarios_fail_closed(monkeypatch):
    monkeypatch.setattr(validation, "post_scenario", lambda *_: (503, {"status": "unavailable"}))
    assert len(validation.run("https://staging.example", "secret")) == 3
