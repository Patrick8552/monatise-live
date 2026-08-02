from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from monatise.application.production import ProductionASGI, ProductionRuntime


class Coordination:
    def __init__(self): self.claims = set()
    async def claim_nonce(self, value):
        if value in self.claims: return False
        self.claims.add(value); return True


class Runtime:
    def __init__(self):
        self.environment = {"MONATISE_ENVIRONMENT": "production", "MONATISE_OPENCLAW_TOKEN": "control-secret"}
        self.redis_coordination = Coordination()
        self.calls = []
    async def analyse(self, symbol, **kwargs):
        self.calls.append((symbol, kwargs))
        return {"symbol": symbol, "execution_enabled": False, "audit_reference": "run", "state_reference": "run"}


def request(app, path, payload, *, token="control-secret"):
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(token.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    messages = []
    async def receive(): return {"type": "http.request", "body": body, "more_body": False}
    async def send(message): messages.append(message)
    scope = {"type": "http", "method": "POST", "path": path, "headers": [(b"x-monatise-timestamp", timestamp.encode()), (b"x-monatise-signature", signature.encode())]}
    asyncio.run(app(scope, receive, send))
    return messages[0]["status"], json.loads(messages[1]["body"])


def test_production_analysis_is_authenticated_symbol_only_and_non_executable():
    runtime = Runtime()
    app = ProductionASGI(runtime)
    assert request(app, "/api/analysis", {"symbol": "BTC"}, token="wrong")[0] == 401
    assert request(app, "/api/analysis", {"symbol": "BTC", "leverage": 2})[0] == 400
    code, payload = request(app, "/api/analysis", {"symbol": "BTC"})
    assert code == 200 and payload["execution_enabled"] is False
    assert runtime.calls == [("BTC", {"source": "monatise.production"})]


def test_staging_route_is_disabled_in_production():
    assert request(ProductionASGI(Runtime()), "/api/staging/analyse", {"symbol": "BTC"})[0] == 404


def test_production_runtime_requires_explicit_environment_and_macro_flag():
    with pytest.raises(ValueError, match="must be production"):
        asyncio.run(ProductionRuntime(environment={}).start())
    with pytest.raises(ValueError, match="degraded mode"):
        asyncio.run(ProductionRuntime(environment={"MONATISE_ENVIRONMENT": "production"}).start())
    with pytest.raises(ValueError, match="safety configuration"):
        asyncio.run(ProductionRuntime(environment={"MONATISE_ENVIRONMENT": "production", "MONATISE_ALLOW_DEGRADED_MACRO": "true"}).start())


def test_degraded_macro_is_disclosed_and_audited_for_every_production_analysis():
    records = []
    class Audit:
        async def append(self, **kwargs): records.append(kwargs)
    class Orchestrator:
        async def run(self, run):
            return SimpleNamespace(
                run_id="run-1", correlation_id=run.correlation_id, symbol=run.symbol,
                status=SimpleNamespace(value="blocked"), blocked_by="decision",
                context=SimpleNamespace(outputs={"decision": SimpleNamespace(classification=SimpleNamespace(value="no_trade"))}),
                statistics=SimpleNamespace(completed_stages=11),
            )
    runtime = ProductionRuntime(environment={})
    runtime.application = SimpleNamespace(orchestrator=Orchestrator(), infrastructure=SimpleNamespace(audit=Audit()))
    runtime.dependencies["macro_provider"] = {"status": "degraded", "mode": "degraded_unavailable_factors"}
    result = asyncio.run(runtime.analyse("BTC", source="monatise.production"))
    assert result["macro_confidence_degraded"] is True
    assert result["macro_mode"] == "degraded_unavailable_factors"
    assert records[0]["payload"] == {"event": "degraded_macro_used", "mode": "unavailable_factors", "confidence": 0}


def test_production_blueprint_is_analysis_only_and_isolated():
    text = (Path(__file__).parents[1] / "render.yaml").read_text()
    required = ["name: monatise-live", "monatise.application.production:app", "autoDeployTrigger: off", "MONATISE_MODE", "MONATISE_ENVIRONMENT", "MONATISE_ALLOW_DEGRADED_MACRO", "monatise:production-analysis"]
    assert all(value in text for value in required)
    forbidden = ["mainnet", "value: live", "BACKPACK_API_KEY", "MONATISE_STAGING_API_TOKEN", "monatise-paper-staging"]
    assert all(value not in text for value in forbidden)
