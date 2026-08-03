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
from monatise.core.models import Candle


class Coordination:
    def __init__(self): self.claims = set()
    async def claim_nonce(self, value, **kwargs):
        if value in self.claims: return False
        self.claims.add(value); return True


class Runtime:
    def __init__(self):
        self.environment = {
            "MONATISE_ENVIRONMENT": "production",
            "MONATISE_OPENCLAW_TOKEN": "control-secret",
            "COINGLASS_API_KEY": "server-secret",
        }
        self.coinglass = SimpleNamespace(
            candles=lambda symbol, limit, interval: [Candle("2026-08-02T12:00:00+00:00", 100, 110, 90, 105, 1000)],
            dashboard_query=lambda path, query: {"code": "0", "data": [{"path": path, "symbol": query.get("symbol")}]},
        )
        self.redis_coordination = Coordination()
        self.calls = []
    async def analyse(self, symbol, **kwargs):
        self.calls.append((symbol, kwargs))
        return {"symbol": symbol, "execution_enabled": False, "audit_reference": "run", "state_reference": "run"}


def request(app, path, payload, *, token=None):
    if token is None:
        token = "control-secret"
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(token.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    messages = []
    async def receive(): return {"type": "http.request", "body": body, "more_body": False}
    async def send(message): messages.append(message)
    scope = {"type": "http", "method": "POST", "path": path, "headers": [(b"x-monatise-timestamp", timestamp.encode()), (b"x-monatise-signature", signature.encode())]}
    asyncio.run(app(scope, receive, send))
    return messages[0]["status"], json.loads(messages[1]["body"])


def get(app, path, *, method="GET", query="", client=("127.0.0.1", 1234)):
    messages = []
    async def receive(): return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message): messages.append(message)
    scope = {"type": "http", "method": method, "path": path, "query_string": query.encode(), "headers": [], "client": client}
    asyncio.run(app(scope, receive, send))
    return messages


def openclaw_status(app, *, token="control-secret", query="symbol=BTC&interval=1h"):
    messages = []
    async def receive(): return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message): messages.append(message)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/openclaw/status",
        "query_string": query.encode(),
        "headers": [(b"authorization", f"Bearer {token}".encode())],
    }
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


def test_notification_verification_route_is_not_exposed():
    assert request(ProductionASGI(Runtime()), "/api/notifications/test", {"confirmation": "TEST_NOTIFICATION_ONLY"})[0] == 404


def test_market_dashboard_uses_server_backed_read_only_data_routes():
    app = ProductionASGI(Runtime())
    candles = get(app, "/api/market/candles", query="symbol=BTC&interval=15m&limit=96")
    assert candles[0]["status"] == 200
    candle_payload = json.loads(candles[1]["body"])
    assert candle_payload["status"] == "ready"
    assert candle_payload["source"] == "CoinGlass"
    assert candle_payload["candles"][0]["time"] == 1785672000000
    assert candle_payload["execution_enabled"] is False

    operator = get(app, "/api/operator")
    assert json.loads(operator[1]["body"])["integrations"]["coinglass"]["configured"] is True

    dataset = get(app, "/api/coinglass/proxy/api/futures/open-interest/exchange-list", query="symbol=BTC")
    assert dataset[0]["status"] == 200
    assert json.loads(dataset[1]["body"])["data"][0]["symbol"] == "BTC"


def test_market_dashboard_routes_reject_unsupported_queries():
    app = ProductionASGI(Runtime())
    assert get(app, "/api/market/candles", query="symbol=EURUSD&interval=15m&limit=96")[0]["status"] == 400
    assert get(app, "/api/market/candles", query="symbol=BTC&interval=2h&limit=96")[0]["status"] == 400
    assert get(app, "/api/market/candles", query="symbol=BTC&interval=15m&limit=2000")[0]["status"] == 400
    assert get(app, "/api/coinglass/proxy/not-allowed")[0]["status"] == 400


def test_market_candles_fall_back_without_enabling_execution():
    runtime = Runtime()
    runtime.coinglass.candles = lambda *_: (_ for _ in ()).throw(RuntimeError("plan restriction"))
    runtime.market_fallback = SimpleNamespace(
        candles=lambda symbol, limit, interval: [Candle("1785672000000", 100, 110, 90, 106, 900)]
    )
    response = get(ProductionASGI(runtime), "/api/market/candles", query="symbol=BTC&interval=15m&limit=96")
    payload = json.loads(response[1]["body"])
    assert response[0]["status"] == 200
    assert payload["source"] == "Hyperliquid candleSnapshot"
    assert payload["candles"][0]["close"] == 106
    assert payload["candles"][0]["time"] == 1785672000000
    assert payload["execution_enabled"] is False


def test_market_dashboard_data_routes_are_rate_limited_per_client():
    app = ProductionASGI(Runtime())
    app._market_rate_windows["203.0.113.10"] = (int(time.time()) // 60, 120)
    response = get(app, "/api/market/candles", query="symbol=BTC&interval=15m&limit=96", client=("203.0.113.10", 80))
    assert response[0]["status"] == 429


def test_openclaw_status_restores_read_only_legacy_contract():
    runtime = Runtime()
    runtime.telegram = object()
    code, payload = openclaw_status(ProductionASGI(runtime))

    assert code == 200
    assert payload["ok"] is True
    assert payload["access"] == "openclaw_read_only"
    assert payload["analysis"]["execution_enabled"] is False
    assert payload["capabilities"] == {
        "readOnly": True,
        "analysis": True,
        "telegramNotification": True,
        "liveOrders": False,
        "configurationWrites": False,
        "deploymentWrites": False,
    }
    assert runtime.calls == [("BTC", {"source": "monatise.openclaw"})]


def test_openclaw_status_reuses_recent_analysis_by_symbol_and_interval():
    runtime = Runtime()
    runtime.telegram = None
    app = ProductionASGI(runtime)

    first_code, first = openclaw_status(app)
    second_code, second = openclaw_status(app)

    assert first_code == second_code == 200
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert first["analysis"] == second["analysis"]
    assert runtime.calls == [("BTC", {"source": "monatise.openclaw"})]


def test_openclaw_status_rejects_wrong_or_missing_credentials():
    runtime = Runtime()
    assert openclaw_status(ProductionASGI(runtime), token="wrong")[0] == 401
    runtime.environment["MONATISE_OPENCLAW_TOKEN"] = ""
    assert openclaw_status(ProductionASGI(runtime))[0] == 503


def test_production_serves_frontend_homepage_and_assets(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>Monatise</title>")
    (tmp_path / "app.js").write_text("window.MONATISE = true;")
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "dashboard" / "index.html").write_text("<!doctype html><title>Market Dashboard</title>")
    app = ProductionASGI(Runtime(), static_dir=tmp_path)

    homepage = get(app, "/")
    asset = get(app, "/app.js")
    dashboard = get(app, "/dashboard/")

    assert homepage[0]["status"] == 200
    assert b"Monatise" in homepage[1]["body"]
    assert dict(homepage[0]["headers"])[b"content-type"] == b"text/html; charset=utf-8"
    assert asset[0]["status"] == 200
    assert asset[1]["body"] == b"window.MONATISE = true;"
    assert dict(asset[0]["headers"])[b"content-type"] in {
        b"application/javascript; charset=utf-8",
        b"text/javascript; charset=utf-8",
    }
    assert dashboard[0]["status"] == 200
    assert b"Market Dashboard" in dashboard[1]["body"]


def test_production_restores_public_legacy_health_contract():
    response = get(ProductionASGI(Runtime()), "/api/health")
    payload = json.loads(response[1]["body"])

    assert response[0]["status"] == 200
    assert payload == {"ok": True, "status": "alive", "execution_enabled": False}


def test_production_frontend_does_not_shadow_api_or_allow_traversal(tmp_path):
    (tmp_path / "index.html").write_text("Monatise")
    app = ProductionASGI(Runtime(), static_dir=tmp_path)

    assert get(app, "/api/missing")[0]["status"] == 404
    assert get(app, "/../pyproject.toml")[0]["status"] == 404


def test_production_readiness_accepts_healthy_scheduler_contender_during_cutover():
    runtime = ProductionRuntime(environment={})
    runtime.safety = SimpleNamespace()
    runtime.application = SimpleNamespace(
        registry=SimpleNamespace(
            ordered=lambda: tuple(SimpleNamespace(name=name) for name in (
                "market_data", "macro", "regime", "liquidity", "liquidity_sweep",
                "supply_demand", "reclaim", "market_structure", "fibonacci_liquidity",
                "order_flow", "decision", "rsi", "risk_validation", "capital_allocation",
                "execution_policy", "portfolio_intelligence", "reporting_intelligence",
                "intelligence_learning", "integration", "governance_loss_control",
            ))
        )
    )
    runtime.dependencies = {
        key: {"status": "degraded" if key == "macro_provider" else "ok"}
        for key in (
            "configuration", "postgresql", "migrations", "redis", "event_bus",
            "state_manager", "audit_repository", "audit_integrity", "audit_logging",
            "scheduler", "engine_registry", "pipeline_orchestrator", "governance",
            "notifications", "coinglass", "macro_provider", "hierarchy_shadow",
        )
    }
    runtime.dependencies["scheduler"]["leader"] = False

    ready, payload = runtime.readiness()

    assert ready is True
    assert payload["dependencies"]["scheduler"]["leader"] is False


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
    required = [
        "name: monatise-live",
        "monatise.application.production:app",
        "autoDeployTrigger: checksPass",
        "healthCheckPath: /health/live",
        "MONATISE_OPENCLAW_CACHE_TTL_SECONDS",
        "MONATISE_MODE",
        "MONATISE_ENVIRONMENT",
        "MONATISE_ALLOW_DEGRADED_MACRO",
        "monatise:production-analysis",
        "MONATISE_HIERARCHICAL_SHADOW_ENABLED",
        "MONATISE_HIERARCHICAL_TELEGRAM_PUBLISH_ENABLED",
        "hierarchy-shadow-v1",
    ]
    assert all(value in text for value in required)
    forbidden = ["mainnet", "value: live", "BACKPACK_API_KEY", "MONATISE_STAGING_API_TOKEN", "monatise-paper-staging"]
    assert all(value not in text for value in forbidden)
