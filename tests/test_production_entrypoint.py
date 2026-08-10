from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import monatise.application.production as production_module
from monatise.adapters.coinglass_production import CoinGlassProductionAdapter
from monatise.application.production import ProductionASGI, ProductionRuntime
from monatise.application.registry import PRODUCTION_ENGINE_ORDER
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
            latest_current_price=lambda symbol: {"BTC": 65_000, "ETH": 3_500, "SOL": 170}[symbol],
            dashboard_query=lambda path, query: {"code": "0", "data": [{"path": path, "symbol": query.get("symbol")}]},
        )
        self.redis_coordination = Coordination()
        self.telegram = None
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


def test_notification_verification_route_is_not_exposed():
    assert request(ProductionASGI(Runtime()), "/api/notifications/test", {"confirmation": "TEST_NOTIFICATION_ONLY"})[0] == 404


def test_market_dashboard_uses_server_backed_read_only_data_routes():
    app = ProductionASGI(Runtime())
    candles = get(app, "/api/market/candles", query="symbol=BTC&interval=30m&limit=96")
    assert candles[0]["status"] == 200
    candle_payload = json.loads(candles[1]["body"])
    assert candle_payload["status"] == "ready"
    assert candle_payload["source"] == "coinglass"
    assert candle_payload["candles"][0]["time"] == 1785672000000
    assert candle_payload["execution_enabled"] is False

    operator = get(app, "/api/operator")
    assert json.loads(operator[1]["body"])["integrations"]["coinglass"]["configured"] is True

    dataset = get(app, "/api/coinglass/proxy/api/futures/open-interest/exchange-list", query="symbol=BTC")
    assert dataset[0]["status"] == 200
    assert json.loads(dataset[1]["body"])["data"][0]["symbol"] == "BTC"


def test_frontend_read_routes_are_implemented_by_production_app():
    runtime = Runtime()
    runtime.coinglass.candles = lambda symbol, limit, interval: [
        Candle(f"2026-08-02T{index % 24:02d}:00:00+00:00", 100 + index, 102 + index, 99 + index, 101 + index, 1000)
        for index in range(limit)
    ]
    app = ProductionASGI(runtime)

    markets = get(app, "/api/markets")
    assert markets[0]["status"] == 200
    assert {item["symbol"] for item in json.loads(markets[1]["body"])["assets"]} == {"BTC", "ETH", "SOL"}

    fibonacci = get(app, "/api/analysis/fibonacci", query="symbol=BTC&interval=1h&limit=120")
    assert fibonacci[0]["status"] == 200
    fibonacci_payload = json.loads(fibonacci[1]["body"])
    assert fibonacci_payload["analysis"]["symbol"] == "BTC"
    assert fibonacci_payload["source"] == "coinglass"

    radar = get(app, "/api/context/radar", query="symbol=BTC&interval=1h&limit=120")
    assert radar[0]["status"] == 200
    radar_payload = json.loads(radar[1]["body"])
    assert radar_payload["indicator"]["trend"] == "up"
    assert radar_payload["contextAssets"][0]["price"] is not None

    context = get(app, "/api/coinglass/context", query="symbol=BTC&interval=1h")
    assert context[0]["status"] == 200
    context_payload = json.loads(context[1]["body"])
    assert context_payload["available"] is True
    assert context_payload["fundingRate"][0]["symbol"] == "BTC"
    assert context_payload["execution_enabled"] is False


def test_web_dashboard_exposes_stock_assets_and_sanitized_quiver_context(monkeypatch):
    context = {
        "symbol": "NVDA",
        "source": "Quiver Quantitative",
        "configured": True,
        "available": True,
        "summary": {"score": 2, "bias": "supportive", "drivers": ["Congress purchase"]},
        "datasets": {"congress": [{"secret_raw_row": True}], "insider": [{}, {}], "news": [{}]},
        "dataset_health": {"congress": {"ok": True}, "insider": {"ok": True}},
    }
    adapter = SimpleNamespace(context=lambda symbol: {**context, "symbol": symbol})
    monkeypatch.setattr(production_module.QuiverAdapter, "from_env", classmethod(lambda cls: adapter))
    app = ProductionASGI(Runtime())

    assets_response = get(app, "/api/assets")
    assets = json.loads(assets_response[1]["body"])["assets"]
    assert assets_response[0]["status"] == 200
    assert {item["symbol"] for item in assets} >= {"AAPL", "TSLA", "NVDA", "QQQ", "SPY"}

    first = get(app, "/api/quiver/context", query="symbol=NVDA")
    second = get(app, "/api/quiver/context", query="symbol=NVDA")
    payload = json.loads(first[1]["body"])
    assert first[0]["status"] == second[0]["status"] == 200
    assert payload["datasetCounts"] == {"congress": 1, "insider": 2, "news": 1}
    assert payload["summary"]["bias"] == "supportive"
    assert "datasets" not in payload
    assert json.loads(second[1]["body"])["cache_hit"] is True


def test_web_quiver_context_rejects_unsupported_symbols() -> None:
    response = get(ProductionASGI(Runtime()), "/api/quiver/context", query="symbol=BTC")
    assert response[0]["status"] == 400


def test_web_quiver_context_singleflights_concurrent_cache_misses(monkeypatch) -> None:
    calls = []
    context = {
        "symbol": "NVDA",
        "source": "Quiver Quantitative",
        "configured": True,
        "available": True,
        "summary": {"score": 0, "bias": "neutral", "dataset_freshness": {}},
        "datasets": {"congress": [{}], "insider": [{}]},
        "dataset_health": {"congress": {"ok": True}, "insider": {"ok": True}},
    }

    def load_context(symbol):  # noqa: ANN001, ANN202
        calls.append(symbol)
        time.sleep(0.05)
        return {**context, "symbol": symbol}

    adapter = SimpleNamespace(context=load_context)
    monkeypatch.setattr(production_module.QuiverAdapter, "from_env", classmethod(lambda cls: adapter))
    app = ProductionASGI(Runtime())
    scope = {"query_string": b"symbol=NVDA"}

    async def concurrent_requests():  # noqa: ANN202
        return await asyncio.gather(app._quiver_context_status(scope), app._quiver_context_status(scope))

    results = asyncio.run(concurrent_requests())
    assert [result[0] for result in results] == [200, 200]
    assert calls == ["NVDA"]


def test_market_candles_default_to_supported_startup_interval():
    response = get(ProductionASGI(Runtime()), "/api/market/candles", query="symbol=BTC&limit=2")

    assert response[0]["status"] == 200
    assert json.loads(response[1]["body"])["interval"] == "30m"


def test_market_dashboard_routes_reject_unsupported_queries():
    app = ProductionASGI(Runtime())
    assert get(app, "/api/market/candles", query="symbol=EURUSD&interval=15m&limit=96")[0]["status"] == 400
    assert get(app, "/api/market/candles", query="symbol=BTC&interval=2h&limit=96")[0]["status"] == 400
    assert get(app, "/api/market/candles", query="symbol=BTC&interval=15m&limit=2000")[0]["status"] == 400
    assert get(app, "/api/coinglass/proxy/not-allowed")[0]["status"] == 400


@pytest.mark.parametrize("interval", CoinGlassProductionAdapter.SUPPORTED_INTERVALS)
def test_market_candles_unlock_all_coinglass_v4_intervals(interval):
    response = get(ProductionASGI(Runtime()), "/api/market/candles", query=f"symbol=BTC&interval={interval}&limit=96")
    assert response[0]["status"] == 200
    assert json.loads(response[1]["body"])["interval"] == interval


def test_public_dashboard_analysis_is_read_only_production_output_without_notification():
    runtime = Runtime()
    response = get(ProductionASGI(runtime), "/api/public/analysis", query="symbol=BTC&interval=1h")
    payload = json.loads(response[1]["body"])

    assert response[0]["status"] == 200
    assert payload["ok"] is True
    assert payload["source"] == "monatise-live"
    assert payload["execution_enabled"] is False
    assert payload["analysis"]["execution_enabled"] is False
    assert runtime.calls == [("BTC", {"interval": "1h", "source": "monatise.web", "notify": False})]


def test_public_dashboard_analysis_rejects_unsupported_assets_and_intervals():
    app = ProductionASGI(Runtime())
    assert get(app, "/api/public/analysis", query="symbol=XRP&interval=1h")[0]["status"] == 400
    assert get(app, "/api/public/analysis", query="symbol=BTC&interval=2h")[0]["status"] == 400


@pytest.mark.parametrize("interval", CoinGlassProductionAdapter.SUPPORTED_INTERVALS)
def test_public_dashboard_analysis_uses_selected_coinglass_interval(interval):
    runtime = Runtime()
    response = get(ProductionASGI(runtime), "/api/public/analysis", query=f"symbol=BTC&interval={interval}")
    assert response[0]["status"] == 200
    assert runtime.calls == [("BTC", {"interval": interval, "source": "monatise.web", "notify": False})]


def test_market_candles_fail_closed_when_all_providers_are_unavailable():
    runtime = Runtime()
    runtime.coinglass.candles = lambda *_: (_ for _ in ()).throw(RuntimeError("plan restriction"))
    response = get(ProductionASGI(runtime), "/api/market/candles", query="symbol=BTC&interval=30m&limit=96")
    payload = json.loads(response[1]["body"])
    assert response[0]["status"] == 503
    assert payload == {
        "status": "unavailable",
        "dataset": "candles",
        "source": "market_data",
        "error_type": "RuntimeError",
    }


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
    assert runtime.calls == [("BTC", {"interval": "1h", "source": "monatise.openclaw"})]


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
    assert runtime.calls == [("BTC", {"interval": "1h", "source": "monatise.openclaw"})]


def test_openclaw_status_returns_quiver_stock_watch_without_execution(monkeypatch):
    adapter = SimpleNamespace(context=lambda symbol: {"symbol": symbol, "available": True, "source": "Quiver Quantitative", "summary": {"score": 4, "drivers": ["insider buying"]}})
    monkeypatch.setattr(production_module.QuiverAdapter, "from_env", classmethod(lambda cls: adapter))
    alpaca = SimpleNamespace(stock_bars=lambda symbol: [], stock_snapshot=lambda symbol: {})
    monkeypatch.setattr(production_module.AlpacaMarketDataAdapter, "from_env", classmethod(lambda cls: alpaca))

    code, payload = openclaw_status(ProductionASGI(Runtime()), query="symbol=NVDA&interval=1h")

    assert code == 200
    assert payload["analysis"]["decision"] == "BUY_WATCH"
    assert payload["analysis"]["execution"] == {"enabled": False, "orders_placed": 0}

    second_code, second = openclaw_status(app := ProductionASGI(Runtime()), query="symbol=NVDA&interval=1h")
    third_code, third = openclaw_status(app, query="symbol=NVDA&interval=1h")
    assert second_code == third_code == 200
    assert second["cache_hit"] is False
    assert third["cache_hit"] is True


def test_openclaw_status_rejects_wrong_or_missing_credentials():
    runtime = Runtime()
    assert openclaw_status(ProductionASGI(runtime), token="wrong")[0] == 401
    runtime.environment["MONATISE_OPENCLAW_TOKEN"] = ""
    assert openclaw_status(ProductionASGI(runtime))[0] == 503


def test_openclaw_status_rejects_unsupported_assets_and_intervals():
    app = ProductionASGI(Runtime())
    assert openclaw_status(app, query="symbol=XRP&interval=1h")[0] == 400
    assert openclaw_status(app, query="symbol=BTC&interval=2h")[0] == 400
    assert app.runtime.calls == []


def test_openclaw_status_is_rate_limited_after_authentication():
    app = ProductionASGI(Runtime())
    app._market_rate_windows["unknown"] = (int(time.time()) // 60, 12)

    code, payload = openclaw_status(app)

    assert code == 429
    assert payload == {"status": "rate_limited"}
    assert app.runtime.calls == []


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
            ordered=lambda: tuple(SimpleNamespace(name=name) for name in PRODUCTION_ENGINE_ORDER)
        )
    )
    runtime.dependencies = {
        key: {"status": "ok"}
        for key in (
            "configuration", "postgresql", "migrations", "redis", "event_bus",
            "state_manager", "audit_repository", "audit_integrity", "audit_logging",
            "scheduler", "engine_registry", "pipeline_orchestrator", "governance",
            "notifications", "coinglass", "market_data", "hierarchy_shadow",
        )
    }
    runtime.dependencies["scheduler"]["leader"] = False

    ready, payload = runtime.readiness()

    assert ready is True
    assert payload["dependencies"]["scheduler"]["leader"] is False


def test_production_runtime_requires_explicit_environment_and_safety_configuration():
    with pytest.raises(ValueError, match="must be production"):
        asyncio.run(ProductionRuntime(environment={}).start())
    with pytest.raises(ValueError, match="safety configuration"):
        asyncio.run(ProductionRuntime(environment={"MONATISE_ENVIRONMENT": "production"}).start())


def test_production_analysis_has_no_macro_fields_or_macro_audit():
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
    result = asyncio.run(runtime.analyse("BTC", source="monatise.production"))
    assert "macro_confidence_degraded" not in result
    assert "macro_mode" not in result
    assert records == []


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
        "monatise:production-analysis",
        "MONATISE_HIERARCHICAL_SHADOW_ENABLED",
        "MONATISE_HIERARCHICAL_TELEGRAM_PUBLISH_ENABLED",
        "hierarchy-shadow-v1",
    ]
    assert all(value in text for value in required)
    forbidden = ["mainnet", "value: live", "BACKPACK_API_KEY"]
    assert all(value not in text for value in forbidden)
