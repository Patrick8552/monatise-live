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
from monatise.application.production import (
    ProductionASGI,
    ProductionRuntime,
    configured_telegram_webhook_secret,
    telegram_webhook_secret,
)
from monatise.application.deployment import TelegramCommandTransition
from monatise.application.registry import PRODUCTION_ENGINE_ORDER
from monatise.core.models import Candle


class Coordination:
    def __init__(self): self.claims, self.pending, self.processing = set(), [], []
    async def claim_nonce(self, value, **kwargs):
        if value in self.claims: return False
        self.claims.add(value); return True
    async def enqueue_telegram_command(self, update_id, payload, **kwargs):
        key = f"telegram:{update_id}"
        if key in self.claims: return False
        self.claims.add(key)
        self.pending.append(payload)
        return True
    async def dequeue_telegram_command(self, **kwargs):
        if not self.pending: return None
        payload = self.pending.pop(0)
        self.processing.append(payload)
        return payload
    async def renew_telegram_command(self, payload, **kwargs): return payload in self.processing
    async def finish_telegram_command(self, payload): self.processing.remove(payload); return True
    async def retry_telegram_command(self, payload, **kwargs):
        self.processing.remove(payload)
        self.pending.append(payload)
        return TelegramCommandTransition.REQUEUED
    async def release_telegram_command(self, payload):
        self.processing.remove(payload)
        self.pending.append(payload)
        return TelegramCommandTransition.REQUEUED
    async def recover_telegram_commands(self):
        self.pending.extend(self.processing)
        recovered = len(self.processing)
        self.processing.clear()
        return recovered
    async def telegram_queue_metrics(self):
        return {"redis": "connected", "pending_depth": len(self.pending), "active_lease_count": len(self.processing), "retry_count": 0, "dead_letter_count": 0, "last_success_at": None, "oldest_queued_age_seconds": None}


class Runtime:
    def __init__(self):
        self.environment = {
            "MONATISE_ENVIRONMENT": "production",
            "MONATISE_OPENCLAW_TOKEN": "control-secret",
            "COINGLASS_API_KEY": "server-secret",
            "MONATISE_TRADINGVIEW_WEBHOOK_TOKEN": "tv-secret",
            "MONATISE_TELEGRAM_INBOUND_ENABLED": "true",
            "MONATISE_TELEGRAM_BOT_DELIVERY_MODE": "dedicated_render_webhook",
        }
        self.coinglass = SimpleNamespace(
            candles=lambda symbol, limit, interval: [Candle("2026-08-02T12:00:00+00:00", 100, 110, 90, 105, 1000)],
            latest_current_price=lambda symbol: {"BTC": 65_000, "ETH": 3_500, "SOL": 170}[symbol],
            dashboard_query=lambda path, query: {"code": "0", "data": [{"path": path, "symbol": query.get("symbol")}]},
        )
        self.redis_coordination = Coordination()
        self.telegram = None
        self.calls = []
        self._tradingview_alerts: dict[str, dict] = {}
    async def analyse(self, symbol, **kwargs):
        self.calls.append((symbol, kwargs))
        return {"symbol": symbol, "execution_enabled": False, "audit_reference": "run", "state_reference": "run"}
    async def analyse_stock(self, symbol, **kwargs):
        self.calls.append((symbol, kwargs))
        return {"asset": symbol, "decision": "NO_TRADE", "score": 0, "score_threshold": 2, "execution": {"enabled": False, "orders_placed": 0}}
    async def record_tradingview_alert(self, raw_payload, *, fingerprint):
        from monatise.analysis.tradingview import normalize_tradingview_alert
        from monatise.application.deployment import TradingViewAlertDuplicate
        if fingerprint in self._tradingview_alerts:
            raise TradingViewAlertDuplicate(fingerprint)
        alert = normalize_tradingview_alert(raw_payload)
        self._tradingview_alerts[fingerprint] = alert
        return alert
    async def recent_tradingview_alerts(self, *, symbol=None, limit=20):
        from monatise.analysis.tradingview import enrich_tradingview_alert
        alerts = list(self._tradingview_alerts.values())
        if symbol:
            alerts = [alert for alert in alerts if alert["symbol"] == symbol]
        return [enrich_tradingview_alert(alert) for alert in alerts[:limit]]


class Telegram:
    def __init__(self): self.messages, self.callback_answers = [], []
    async def command_response(self, message): self.messages.append(message)
    async def answer_callback_query(self, callback_query_id): self.callback_answers.append(callback_query_id)


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


def post_tradingview_webhook(app, body: bytes, *, token="tv-secret", client=("127.0.0.1", 1234)):
    try:
        parsed = json.loads(body.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        body = f"token={token}, ".encode() + body
    else:
        if isinstance(parsed, dict):
            parsed["token"] = token
            body = json.dumps(parsed, separators=(",", ":")).encode()
    messages = []
    async def receive(): return {"type": "http.request", "body": body, "more_body": False}
    async def send(message): messages.append(message)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/tradingview/webhook",
        "query_string": b"",
        "headers": [],
        "client": client,
    }
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


def telegram_webhook(app, update, *, secret="telegram-secret"):
    messages = []
    async def run():
        body = json.dumps(update, separators=(",", ":")).encode()
        async def receive(): return {"type": "http.request", "body": body, "more_body": False}
        async def send(message): messages.append(message)
        scope = {
            "type": "http", "method": "POST", "path": "/api/telegram/webhook",
            "headers": [(b"x-telegram-bot-api-secret-token", secret.encode())],
        }
        await app(scope, receive, send)
        if messages[0]["status"] == 200 and json.loads(messages[1]["body"]).get("status") == "accepted":
            await app._process_telegram_command_once(timeout_seconds=0)
    asyncio.run(run())
    return messages[0]["status"], json.loads(messages[1]["body"])


def test_telegram_webhook_is_secret_and_chat_restricted():
    runtime = Runtime()
    runtime.environment.update({"MONATISE_TELEGRAM_BOT_TOKEN": "bot-token", "MONATISE_TELEGRAM_CHAT_ID": "42"})
    runtime.telegram = Telegram()
    app = ProductionASGI(runtime)
    update = {"update_id": 1, "message": {"chat": {"id": 42}, "text": "/analyze BTC"}}

    assert telegram_webhook(app, update, secret="wrong")[0] == 401
    update["message"]["chat"]["id"] = 99
    assert telegram_webhook(app, update, secret=telegram_webhook_secret("bot-token")) == (200, {"status": "ignored"})
    assert runtime.calls == []


def test_dedicated_monatise_bot_configuration_is_isolated_from_openclaw_and_legacy_bot_names():
    environment = {
        "TELEGRAM_BOT_TOKEN": "donpbot-token",
        "OPENCLAW_TELEGRAM_BOT_TOKEN": "donpbot-token",
        "MONATISE_OPENCLAW_TOKEN": "openclaw-control-token",
    }
    assert configured_telegram_webhook_secret(environment) == ""

    runtime = Runtime()
    runtime.environment.update(environment)
    runtime.environment.pop("MONATISE_TELEGRAM_BOT_DELIVERY_MODE")
    runtime.environment["MONATISE_TELEGRAM_BOT_TOKEN"] = "existing-donpbot-token"
    runtime.environment["MONATISE_TELEGRAM_CHAT_ID"] = "42"
    runtime.telegram = Telegram()
    app = ProductionASGI(runtime)
    update = {"update_id": 40, "message": {"chat": {"id": 42}, "from": {"id": 42}, "text": "/analyze gold"}}
    assert telegram_webhook(app, update, secret="anything") == (503, {"status": "unavailable"})
    assert environment["OPENCLAW_TELEGRAM_BOT_TOKEN"] == "donpbot-token"


def test_explicit_dedicated_webhook_secret_is_used_and_validated():
    environment = {
        "MONATISE_TELEGRAM_BOT_TOKEN": "monatise-bot-token",
        "MONATISE_TELEGRAM_BOT_DELIVERY_MODE": "dedicated_render_webhook",
        "MONATISE_TELEGRAM_WEBHOOK_SECRET": "render_webhook_secret-42",
    }
    assert configured_telegram_webhook_secret(environment) == "render_webhook_secret-42"
    with pytest.raises(ValueError, match="invalid format"):
        configured_telegram_webhook_secret({**environment, "MONATISE_TELEGRAM_WEBHOOK_SECRET": "not valid!"})

    runtime = Runtime()
    runtime.environment.update({
        **environment,
        "MONATISE_TELEGRAM_CHAT_ID": "42",
        "MONATISE_TELEGRAM_ALLOWED_USER_IDS": "42",
    })
    runtime.telegram = Telegram()
    app = ProductionASGI(runtime)
    update = {"update_id": 41, "message": {"chat": {"id": 42}, "from": {"id": 42}, "text": "/help"}}
    assert telegram_webhook(app, update, secret="render_webhook_secret-42") == (200, {"status": "accepted"})


def test_webhook_ownership_monitor_detects_owned_and_lost_routes():
    class OwnershipTelegram(Telegram):
        def __init__(self, url):
            super().__init__()
            self.url = url

        async def webhook_info(self):
            return {
                "url": self.url,
                "pending_update_count": 0,
                "last_error_date": None,
                "last_error_message": None,
            }

    async def scenario():
        runtime = Runtime()
        runtime.environment["MONATISE_PUBLIC_URL"] = "https://monatise-live.onrender.com"
        runtime.dependencies = {"telegram_inbound": {"enabled": True}}
        runtime.telegram = OwnershipTelegram("https://monatise-live.onrender.com/api/telegram/webhook")
        app = ProductionASGI(runtime)
        assert await app._verify_telegram_webhook_ownership() is True
        assert runtime.dependencies["telegram_inbound"]["webhook_owner_verified"] is True
        assert runtime.dependencies["telegram_inbound"]["registration"] == "registered"

        runtime.telegram.url = ""
        assert await app._verify_telegram_webhook_ownership() is False
        assert runtime.dependencies["telegram_inbound"]["webhook_owner_verified"] is False
        assert runtime.dependencies["telegram_inbound"]["registration"] == "lost"

    asyncio.run(scenario())


def test_telegram_callback_approval_is_private_authorized_and_replay_safe():
    class FTMO:
        def __init__(self): self.approvals = []
        def authorized(self, user_id, chat_type): return user_id == "42" and chat_type == "private"
        async def approve(self, proposal_id, user_id):
            self.approvals.append((proposal_id, user_id))
            return {"command_id": "c" * 64}

    runtime = Runtime()
    runtime.environment.update({"MONATISE_TELEGRAM_BOT_TOKEN": "bot-token", "MONATISE_TELEGRAM_CHAT_ID": "42"})
    runtime.telegram = Telegram()
    runtime.ftmo_master = FTMO()
    app = ProductionASGI(runtime)
    update = {
        "update_id": 101,
        "callback_query": {
            "id": "callback-101", "from": {"id": 42}, "data": "ftmo:approve:a1b2c3d4e5f6",
            "message": {"chat": {"id": 42, "type": "private"}},
        },
    }
    secret = telegram_webhook_secret("bot-token")

    assert telegram_webhook(app, update, secret=secret) == (200, {"status": "accepted"})
    assert telegram_webhook(app, update, secret=secret) == (200, {"status": "duplicate"})
    assert runtime.ftmo_master.approvals == [("a1b2c3d4e5f6", "42")]
    assert runtime.telegram.callback_answers == ["callback-101"]
    assert runtime.telegram.messages == ["FTMO command cccccccccccc approved and queued for the account-bound MT5 EA."]

    update["update_id"] = 102
    update["callback_query"]["data"] = "ftmo:approve:../../unsafe"
    assert telegram_webhook(app, update, secret=secret) == (200, {"status": "ignored"})


def test_ftmo_broker_and_position_lifecycle_are_reported_to_telegram():
    async def scenario():
        runtime = Runtime()
        runtime.telegram = Telegram()
        app = ProductionASGI(runtime)
        await app._notify_ftmo_command_result({
            "status": "reconciled", "lifecycle_state": "BROKER_ACCEPTED",
            "broker_ticket": "12345678", "broker_retcode": "10009",
            "requested_price": "63128.40", "fill_price": "63128.50", "executed_volume": "0.01",
            "executed_stop_loss": "62980", "executed_take_profit": "63450",
            "payload": {"symbol": "BTCUSD", "side": "buy", "entry": "63128.40", "volume": "0.01"},
            "analysis_provenance": {"analysis_provider": "coinglass"},
        })
        await app._notify_ftmo_lifecycle({
            "lifecycle_state": "POSITION_OPEN", "symbol": "BTCUSD", "side": "buy",
            "entry": "63128.50", "volume": "0.01", "stop_loss": "62980", "take_profit": "63450",
            "broker_ticket": "12345678", "unrealized_profit": "1.20", "analysis_provider": "coinglass",
        })

        assert runtime.telegram.messages[0].startswith("FTMO EXECUTION CONFIRMATION\nInstrument: BTCUSD | Direction: BUY")
        assert "Execution source: FTMO MT5 | Analysis source: coinglass + Monatise" in runtime.telegram.messages[0]
        assert runtime.telegram.messages[1].startswith("FTMO POSITION OPEN\nInstrument: BTCUSD | Direction: BUY")
        assert "Unrealized P/L: 1.20" in runtime.telegram.messages[1]

    asyncio.run(scenario())


def test_telegram_crypto_command_runs_15m_read_only_analysis():
    runtime = Runtime()
    runtime.environment.update({"MONATISE_TELEGRAM_BOT_TOKEN": "bot-token", "MONATISE_TELEGRAM_CHAT_ID": "42"})
    runtime.telegram = Telegram()
    app = ProductionASGI(runtime)
    update = {"update_id": 2, "message": {"chat": {"id": 42}, "text": "/analyse BTC"}}

    assert telegram_webhook(app, update, secret=telegram_webhook_secret("bot-token")) == (200, {"status": "accepted"})
    assert runtime.calls == [("BTC", {"interval": "15m", "source": "monatise.telegram.command", "notify": False})]
    assert runtime.telegram.messages == ["Monatise NO TRADE: BTC\nTimeframe: 15m\nScore: +0/10 | threshold: ±7\nExecution: disabled"]


def test_telegram_stock_command_returns_no_trade_when_not_confirmed():
    runtime = Runtime()
    runtime.environment.update({"MONATISE_TELEGRAM_BOT_TOKEN": "bot-token", "MONATISE_TELEGRAM_CHAT_ID": "42"})
    runtime.telegram = Telegram()
    app = ProductionASGI(runtime)
    update = {"update_id": 3, "message": {"chat": {"id": 42}, "text": "/analyze NVDA"}}

    assert telegram_webhook(app, update, secret=telegram_webhook_secret("bot-token"))[0] == 200
    assert runtime.calls == [("NVDA", {})]
    assert runtime.telegram.messages[0].startswith("Monatise NO TRADE: NVDA")
    assert runtime.telegram.messages[0].endswith("Execution: disabled")


def test_telegram_rejects_non_ftmo_crypto_even_if_coinglass_can_resolve_it():
    runtime = Runtime()
    runtime.environment.update({"MONATISE_TELEGRAM_BOT_TOKEN": "bot-token", "MONATISE_TELEGRAM_CHAT_ID": "42"})
    runtime.coinglass.resolve_futures_asset = lambda symbol: SimpleNamespace(base_asset=symbol)
    runtime.telegram = Telegram()
    app = ProductionASGI(runtime)
    update = {"update_id": 4, "message": {"chat": {"id": 42}, "text": "/analyze PEPE"}}

    assert telegram_webhook(app, update, secret=telegram_webhook_secret("bot-token"))[0] == 200
    assert runtime.calls == []
    assert "NO TRADE: PEPE" in runtime.telegram.messages[0]


def test_telegram_explicit_asset_class_handles_ftmo_stock_symbol():
    runtime = Runtime()
    runtime.environment.update({"MONATISE_TELEGRAM_BOT_TOKEN": "bot-token", "MONATISE_TELEGRAM_CHAT_ID": "42"})
    runtime.telegram = Telegram()
    app = ProductionASGI(runtime)
    update = {"update_id": 5, "message": {"chat": {"id": 42}, "text": "/analyze PLTR stock"}}

    assert telegram_webhook(app, update, secret=telegram_webhook_secret("bot-token"))[0] == 200
    assert runtime.calls == [("PLTR", {})]


def test_telegram_ftmo_stock_symbol_selects_stock_provider_without_ambiguity():
    runtime = Runtime()
    runtime.environment.update({"MONATISE_TELEGRAM_BOT_TOKEN": "bot-token", "MONATISE_TELEGRAM_CHAT_ID": "42"})
    runtime.telegram = Telegram()
    app = ProductionASGI(runtime)
    update = {"update_id": 7, "message": {"chat": {"id": 42}, "text": "/analyze PLTR"}}

    assert telegram_webhook(app, update, secret=telegram_webhook_secret("bot-token"))[0] == 200
    assert runtime.calls == [("PLTR", {})]
    assert runtime.telegram.messages[0].startswith("Monatise NO TRADE: PLTR")


def test_telegram_failed_delivery_stays_queued_for_retry(monkeypatch):
    class FlakyTelegram(Telegram):
        async def command_response(self, message):
            if not self.messages:
                self.messages.append("failed")
                raise RuntimeError("temporary Telegram outage")
            self.messages.append(message)

    async def no_sleep(_seconds): return None
    monkeypatch.setattr(production_module.asyncio, "sleep", no_sleep)
    runtime = Runtime()
    runtime.telegram = FlakyTelegram()
    app = ProductionASGI(runtime)
    asyncio.run(runtime.redis_coordination.enqueue_telegram_command(6, {"update_id": 6, "text": "/help"}))

    assert asyncio.run(app._process_telegram_command_once(timeout_seconds=0)) is True
    assert len(runtime.redis_coordination.pending) == 1
    assert asyncio.run(app._process_telegram_command_once(timeout_seconds=0)) is True
    assert runtime.redis_coordination.pending == []
    assert runtime.redis_coordination.processing == []


def test_telegram_worker_survives_transient_dequeue_failure(monkeypatch):
    runtime = Runtime()
    runtime.dependencies = {"telegram_inbound": {"enabled": True}}
    app = ProductionASGI(runtime)
    calls = 0

    async def process_once(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("temporary Redis outage")
        raise asyncio.CancelledError

    async def no_sleep(_seconds): return None
    monkeypatch.setattr(app, "_process_telegram_command_once", process_once)
    monkeypatch.setattr(production_module.asyncio, "sleep", no_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(app._telegram_command_worker())

    assert calls == 2
    assert runtime.dependencies["telegram_inbound"]["worker"] == "retrying"
    assert runtime.dependencies["telegram_inbound"]["status"] == "degraded"


def test_telegram_health_uses_actual_worker_task_lifecycle():
    async def scenario():
        runtime = Runtime()
        runtime.dependencies = {"telegram_inbound": {"worker": "running", "registration": "registered"}}
        app = ProductionASGI(runtime)
        task = asyncio.create_task(asyncio.sleep(0))
        await task
        app._telegram_worker = task

        telemetry = await app._telegram_queue_telemetry()

        assert telemetry["worker"] == "stopped"

    asyncio.run(scenario())


def test_long_running_telegram_command_renews_lease(monkeypatch):
    runtime = Runtime()
    runtime.telegram = Telegram()
    app = ProductionASGI(runtime)
    app.TELEGRAM_HEARTBEAT_SECONDS = 0.001
    renewals = 0
    original_renew = runtime.redis_coordination.renew_telegram_command

    async def renew(payload, **kwargs):
        nonlocal renewals
        renewals += 1
        return await original_renew(payload, **kwargs)

    async def slow_handler(text, **kwargs):
        await asyncio.sleep(0.01)
        assert await kwargs["ownership_check"]() is True

    monkeypatch.setattr(runtime.redis_coordination, "renew_telegram_command", renew)
    monkeypatch.setattr(app, "_handle_telegram_command", slow_handler)
    asyncio.run(runtime.redis_coordination.enqueue_telegram_command(8, {"update_id": 8, "text": "/help"}))

    assert asyncio.run(app._process_telegram_command_once(timeout_seconds=0)) is True
    assert renewals >= 2


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


def test_x_connection_status_is_visible_without_exposing_credentials():
    runtime = Runtime()
    runtime.environment.update({
        "MONATISE_X_BEARER_TOKEN": "secret-token",
        "MONATISE_X_WATCH_ACCOUNTS": "whale_alert, federalreserve",
        "MONATISE_X_OAUTH_CONNECT_URL": "https://openclaw.example/connect/x",
    })
    runtime.x_macro = object()
    runtime.dependencies = {}
    runtime.dependencies["x_macro"] = {"enabled": True}
    messages = get(ProductionASGI(runtime), "/api/x/status")
    code, payload = messages[0]["status"], json.loads(messages[1]["body"])
    assert code == 200
    assert payload["connected"] is True
    assert payload["monitoring"] is True
    assert payload["watch_accounts"] == ["whale_alert", "federalreserve"]
    assert payload["connect_url"] == "https://openclaw.example/connect/x"
    assert "secret-token" not in str(payload)


def test_market_dashboard_uses_server_backed_read_only_data_routes():
    app = ProductionASGI(Runtime())
    candles = get(app, "/api/market/candles", query="symbol=BTC&interval=30m&limit=96")
    assert candles[0]["status"] == 200
    candle_payload = json.loads(candles[1]["body"])
    assert candle_payload["status"] == "ready"
    assert candle_payload["source"] == "coinglass"
    assert candle_payload["candles"][0]["time"] == 1785672000000
    assert candle_payload["execution_enabled"] is False


def test_malformed_candle_timestamp_returns_503_not_a_crash():
    # A provider row missing every timestamp key (start/timestamp/time/t)
    # normalizes to the literal string "None", which is neither a digit
    # string nor valid ISO-8601 -- this must fail closed, not raise past the
    # handler.
    runtime = Runtime()
    runtime.coinglass = SimpleNamespace(
        candles=lambda symbol, limit, interval: [Candle("None", 100, 110, 90, 105, 1000)],
        latest_current_price=lambda symbol: 65_000,
        dashboard_query=lambda path, query: {"code": "0", "data": []},
    )
    app = ProductionASGI(runtime)
    candles = get(app, "/api/market/candles", query="symbol=BTC&interval=30m&limit=96")
    assert candles[0]["status"] == 503
    assert json.loads(candles[1]["body"])["status"] == "unavailable"


def test_analysis_route_rejects_requests_when_replay_protection_unavailable():
    runtime = Runtime()
    runtime.redis_coordination = None
    app = ProductionASGI(runtime)
    status, payload = request(app, "/api/analysis", {"symbol": "BTC"})
    assert status == 503
    assert payload["status"] == "unavailable"

    operator = get(app, "/api/operator")
    assert json.loads(operator[1]["body"])["integrations"]["coinglass"]["configured"] is True

    dataset = get(app, "/api/coinglass/proxy/api/futures/open-interest/exchange-list", query="symbol=BTC")
    assert dataset[0]["status"] == 200
    assert json.loads(dataset[1]["body"])["data"][0]["symbol"] == "BTC"


def test_frontend_read_routes_are_implemented_by_production_app():
    runtime = Runtime()
    def dashboard_query(path, query):  # noqa: ANN001, ANN202
        if path == "/api/futures/funding-rate/exchange-list":
            return {"code": "0", "data": [{"symbol": "BTC", "stablecoin_margin_list": [{"exchange": "Binance", "funding_rate": 0.0001}]}]}
        return {"code": "0", "data": [{"path": path, "symbol": query.get("symbol")}]}

    runtime.coinglass.dashboard_query = dashboard_query
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
    assert context_payload["fundingRate"][0]["exchange"] == "Binance"
    assert context_payload["execution_enabled"] is False

    me = get(app, "/api/me")
    assert me[0]["status"] == 200
    assert json.loads(me[1]["body"])["authenticated"] is False

    tradingview = get(app, "/api/tradingview/signals", query="symbol=BTC")
    assert tradingview[0]["status"] == 200
    assert json.loads(tradingview[1]["body"])["alerts"] == []


def test_liquidity_clusters_endpoint_returns_a_modeled_heatmap():
    runtime = Runtime()
    runtime.coinglass.derivatives_snapshot = lambda symbol, interval: {
        "open_interest": 25_000_000.0,
        "funding_rate": 0.0002,
    }
    app = ProductionASGI(runtime)

    response = get(app, "/api/analysis/liquidity-clusters", query="symbol=BTC&interval=1h")
    assert response[0]["status"] == 200
    payload = json.loads(response[1]["body"])
    assert payload["symbol"] == "BTC"
    assert payload["source"] == "modeled"
    assert "Professional-tier" in payload["methodology"]
    assert isinstance(payload["magnetBias"], float)
    assert len(payload["clusters"]) == 10
    assert all(cluster["side"] in {"long", "short"} for cluster in payload["clusters"])
    assert payload["nearestLongCluster"]["price"] < payload["price"]
    assert payload["nearestShortCluster"]["price"] > payload["price"]
    assert payload["execution_enabled"] is False


def test_liquidity_clusters_endpoint_fails_closed_without_coinglass():
    runtime = Runtime()
    runtime.coinglass = None
    app = ProductionASGI(runtime)
    response = get(app, "/api/analysis/liquidity-clusters", query="symbol=BTC&interval=1h")
    assert response[0]["status"] == 503


def test_retired_generalized_memecoin_routes_are_not_exposed():
    app = ProductionASGI(Runtime())
    for path in ("/api/memecoins/discover", "/api/memecoins/token", "/api/memecoins/creators"):
        response = get(app, path)
        assert response[0]["status"] == 404


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


def test_public_dashboard_analysis_cache_spans_dashboard_refresh_interval():
    runtime = Runtime()
    app = ProductionASGI(runtime)
    first = get(app, "/api/public/analysis", query="symbol=BTC&interval=1h")
    second = get(app, "/api/public/analysis", query="symbol=BTC&interval=1h")

    assert json.loads(first[1]["body"])["cache_hit"] is False
    assert json.loads(second[1]["body"])["cache_hit"] is True
    assert len(runtime.calls) == 1


def test_public_dashboard_analysis_reports_processing_instead_of_unavailable_on_timeout():
    runtime = Runtime()
    runtime.environment["MONATISE_PUBLIC_ANALYSIS_TIMEOUT_SECONDS"] = "0.01"

    async def slow_analysis(symbol, **kwargs):
        runtime.calls.append((symbol, kwargs))
        await asyncio.sleep(60)

    runtime.analyse = slow_analysis
    response = get(ProductionASGI(runtime), "/api/public/analysis", query="symbol=BTC&interval=1h")
    payload = json.loads(response[1]["body"])

    assert response[0]["status"] == 200
    assert payload["processing"] is True
    assert payload["analysis"]["classification"] == "no_trade"
    assert payload["analysis"]["blocked_by"] == "pipeline_processing"
    assert payload["analysis"]["execution_enabled"] is False


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


def test_openclaw_cache_uses_configured_ttl_for_every_asset_class():
    runtime = Runtime()
    runtime.environment["MONATISE_OPENCLAW_CACHE_TTL_SECONDS"] = "60"
    app = ProductionASGI(runtime)
    key = ("PEPE", "15m")
    app._openclaw_cache[key] = (production_module.monotonic() - 61, {"symbol": "PEPE"})

    assert app._openclaw_cached(key) is None


def test_openclaw_cache_is_bounded():
    app = ProductionASGI(Runtime())
    for index in range(257):
        app._store_openclaw_cache((f"ASSET{index}", "15m"), {"index": index})

    assert len(app._openclaw_cache) == 256
    assert ("ASSET0", "15m") not in app._openclaw_cache


def test_openclaw_status_returns_quiver_stock_watch_without_execution():
    runtime = Runtime()
    async def analyse_stock(symbol, **kwargs):
        runtime.calls.append((symbol, kwargs))
        return {"asset": symbol, "decision": "BUY_WATCH", "score": 4, "score_threshold": 2, "execution": {"enabled": False, "orders_placed": 0}}
    runtime.analyse_stock = analyse_stock

    code, payload = openclaw_status(ProductionASGI(runtime), query="symbol=NVDA&interval=1h")

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


def test_public_stock_search_and_analysis_are_read_only() -> None:
    app = ProductionASGI(Runtime())
    search_messages = get(app, "/api/stocks/search", query="q=nv")
    search = json.loads(search_messages[1]["body"])
    assert search_messages[0]["status"] == 200
    assert search["results"][0]["symbol"] == "NVDA"
    assert search["execution_enabled"] is False

    analysis_messages = get(app, "/api/stocks/NVDA/analysis")
    analysis = json.loads(analysis_messages[1]["body"])
    assert analysis_messages[0]["status"] == 200
    assert analysis["symbol"] == "NVDA"
    assert analysis["analysis"]["execution"] == {"enabled": False, "orders_placed": 0}
    assert analysis["execution_enabled"] is False


def test_public_stock_scanner_reads_bounded_ftmo_scheduler_results() -> None:
    runtime = Runtime()
    app = ProductionASGI(runtime)
    messages = get(app, "/api/stocks/scanner")
    payload = json.loads(messages[1]["body"])
    assert messages[0]["status"] == 200
    assert payload["status"] == "warming"
    assert payload["results"] == []
    assert payload["universe_size"] == 59
    assert payload["registry_version"].startswith("ftmo-official-")
    assert payload["providers"] == ["Alpaca", "FlashAlpha", "Quiver Quantitative", "Finnhub"]
    assert payload["execution_enabled"] is False


def test_public_stock_analysis_rejects_malformed_symbol() -> None:
    messages = get(ProductionASGI(Runtime()), "/api/stocks/NVDA%20DROP/analysis")
    assert messages[0]["status"] == 400


def test_openclaw_status_rejects_unsupported_intervals():
    app = ProductionASGI(Runtime())
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
    assert payload["ok"] is True and payload["status"] == "alive" and payload["execution_enabled"] is False
    assert payload["telegram"]["redis"] == "connected"
    assert payload["telegram"]["pending_depth"] == 0


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
        "startCommand: sh scripts/start_production.sh",
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


def test_every_production_entrypoint_uses_the_single_asgi_start_script():
    root = Path(__file__).parents[1]
    dockerfile = (root / "Dockerfile").read_text()
    blueprint = (root / "render.yaml").read_text()
    start_script = (root / "scripts" / "start_production.sh").read_text()

    assert 'CMD ["sh", "scripts/start_production.sh"]' in dockerfile
    assert "startCommand: sh scripts/start_production.sh" in blueprint
    assert "uvicorn monatise.application.production:app" in start_script
    assert "--workers 1" in start_script
    assert "scripts/serve_live.py" not in dockerfile


def test_production_startup_logs_deployment_identity_before_validation(caplog):
    runtime = ProductionRuntime(environment={"MONATISE_ENVIRONMENT": "production", "RENDER_GIT_COMMIT": "abc123"})

    with caplog.at_level("INFO"), pytest.raises(ValueError, match="production safety configuration"):
        asyncio.run(runtime.start())

    message = next(record.getMessage() for record in caplog.records if "monatise production startup" in record.getMessage())
    assert "application=monatise.application.production:app" in message
    assert "environment=production" in message
    assert "commit=abc123" in message
    assert "api_version=v1" in message


def test_tradingview_webhook_rejects_missing_token():
    app = ProductionASGI(Runtime())
    code, payload = post_tradingview_webhook(app, b'{"symbol":"BTCUSDT","action":"buy"}', token="")
    assert code == 401 and payload["status"] == "unauthorized"


def test_tradingview_webhook_rejects_wrong_token():
    app = ProductionASGI(Runtime())
    code, payload = post_tradingview_webhook(app, b'{"symbol":"BTCUSDT","action":"buy"}', token="wrong-secret")
    assert code == 401 and payload["status"] == "unauthorized"


def test_tradingview_webhook_fails_closed_when_token_not_configured():
    runtime = Runtime()
    del runtime.environment["MONATISE_TRADINGVIEW_WEBHOOK_TOKEN"]
    app = ProductionASGI(runtime)
    code, payload = post_tradingview_webhook(app, b'{"symbol":"BTCUSDT","action":"buy"}')
    assert code == 503 and payload["status"] == "unavailable"


def test_tradingview_webhook_accepts_a_valid_alert_and_it_becomes_readable():
    runtime = Runtime()
    app = ProductionASGI(runtime)
    code, payload = post_tradingview_webhook(app, b'{"symbol":"BTCUSDT","action":"buy","confidence":"82"}')
    assert code == 200
    assert payload == {"status": "accepted", "symbol": "BTC", "action": "BUY", "execution_enabled": False}

    signals = get(app, "/api/tradingview/signals", query="symbol=BTC")
    signals_payload = json.loads(signals[1]["body"])
    assert signals_payload["count"] == 1
    assert signals_payload["alerts"][0]["symbol"] == "BTC"
    assert signals_payload["configured"] is True
    # Nothing about ingesting an alert triggers analysis or execution.
    assert runtime.calls == []


def test_tradingview_webhook_accepts_plain_text_alert_body():
    app = ProductionASGI(Runtime())
    code, payload = post_tradingview_webhook(app, b"symbol=ETHUSDT, action=sell, confidence=91")
    assert code == 200
    assert payload["symbol"] == "ETH" and payload["action"] == "SELL"


def test_tradingview_webhook_rejects_a_malformed_alert_without_storing_it():
    runtime = Runtime()
    app = ProductionASGI(runtime)
    code, payload = post_tradingview_webhook(app, b'{"symbol":"OANDA:XAUUSD","action":"buy"}')
    assert code == 422 and payload["status"] == "invalid_alert"
    assert "Gold" in payload["reason"]
    assert runtime._tradingview_alerts == {}


def test_tradingview_webhook_rejects_a_replayed_alert():
    runtime = Runtime()
    app = ProductionASGI(runtime)
    body = b'{"symbol":"BTCUSDT","action":"buy","confidence":"60"}'
    first = post_tradingview_webhook(app, body)
    assert first[0] == 200
    second = post_tradingview_webhook(app, body)
    assert second[0] == 409 and second[1]["status"] == "duplicate_alert"
    assert len(runtime._tradingview_alerts) == 1


def test_tradingview_webhook_accepts_same_payload_in_a_later_freshness_window(monkeypatch):
    runtime = Runtime()
    app = ProductionASGI(runtime)
    body = b'{"symbol":"BTCUSDT","action":"buy","confidence":"60"}'
    monkeypatch.setattr(production_module, "time", lambda: 1_000)
    assert post_tradingview_webhook(app, body)[0] == 200
    monkeypatch.setattr(production_module, "time", lambda: 1_000 + 301)
    assert post_tradingview_webhook(app, body)[0] == 200
    assert len(runtime._tradingview_alerts) == 2


def test_tradingview_webhook_is_rate_limited_per_client():
    app = ProductionASGI(Runtime())
    body = b'{"symbol":"BTCUSDT","action":"wait"}'
    codes = [post_tradingview_webhook(app, body, token="wrong")[0] for _ in range(121)]
    assert codes[-1] == 429


def test_tradingview_webhook_method_not_allowed_on_get():
    code = get(ProductionASGI(Runtime()), "/api/tradingview/webhook")[0]["status"]
    assert code == 405


def test_tradingview_signals_method_not_allowed_on_post():
    messages = []
    async def receive(): return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message): messages.append(message)
    scope = {"type": "http", "method": "POST", "path": "/api/tradingview/signals", "query_string": b"", "headers": [], "client": ("127.0.0.1", 1)}
    asyncio.run(ProductionASGI(Runtime())(scope, receive, send))
    assert messages[0]["status"] == 405


def test_tradingview_signals_output_remains_raw_json_for_safe_client_rendering():
    runtime = Runtime()
    app = ProductionASGI(runtime)
    malicious = json.dumps({"symbol": "BTCUSDT", "action": "buy", "message": "<img src=x onerror=alert(1)>", "indicator": "<b>bias</b>"}).encode()
    assert post_tradingview_webhook(app, malicious)[0] == 200

    signals_payload = json.loads(get(app, "/api/tradingview/signals")[1]["body"])
    alert = signals_payload["alerts"][0]
    assert alert["message"] == "<img src=x onerror=alert(1)>"
    assert alert["indicator"] == "<b>bias</b>"


def test_tradingview_signals_filters_by_symbol():
    runtime = Runtime()
    app = ProductionASGI(runtime)
    post_tradingview_webhook(app, b'{"symbol":"BTCUSDT","action":"buy"}')
    post_tradingview_webhook(app, b'{"symbol":"ETHUSDT","action":"sell"}')

    btc_only = json.loads(get(app, "/api/tradingview/signals", query="symbol=BTC")[1]["body"])
    assert btc_only["count"] == 1
    assert btc_only["alerts"][0]["symbol"] == "BTC"

    everything = json.loads(get(app, "/api/tradingview/signals")[1]["body"])
    assert everything["count"] == 2


def test_tradingview_webhook_request_too_large_is_rejected():
    app = ProductionASGI(Runtime())
    oversized = b'{"symbol":"BTCUSDT","message":"' + b"a" * 8200 + b'"}'
    code, payload = post_tradingview_webhook(app, oversized)
    assert code == 413 and payload["status"] == "request_too_large"
