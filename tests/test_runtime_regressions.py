import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tests.test_ftmo_master import NOW, Store, active_environment, heartbeat, service
from tests.test_production_entrypoint import Runtime, request
from monatise.application.ftmo_master import FTMOMasterRepository, FTMOMasterError
from monatise.application.production import ProductionASGI
from monatise.core.models import Candle
from monatise.engines.market_data import MarketDataEngine
from monatise.engines.market_data.models import MarketDataRequest


@pytest.mark.parametrize("operation", ["close", "cancel", "sl", "tp", "breakeven"])
def test_valid_management_request_creates_proposal(monkeypatch, operation):
    monkeypatch.setattr("monatise.application.ftmo_master._utc", lambda value=None: value or NOW)
    async def scenario():
        control, _ = service(active_environment(FTMO_TEMPORARY_ARM_REQUIRED="false"))
        await control.accept_bridge_heartbeat(heartbeat(positions=[{"ticket": "123"}], orders=[{"ticket": "123"}]), now=NOW)
        await control.repository.update_control(kill_switch=False)
        result = await control.create_management_proposal(actor="42", operation=operation, target_id="123", value="2501")
        assert result["status"] == "pending_confirmation"
        command = await control.approve(result["proposal_id"], "42", now=NOW)
        assert command["operation"] == operation
        assert command["payload"]["target_id"] == "123"
        assert command["analysis_id"] == "operator:" + result["proposal_id"]
    asyncio.run(scenario())


def test_concurrent_quote_demand_renewals_both_succeed():
    class RacingStore(Store):
        def __init__(self):
            super().__init__()
            self.reads = 0
            self.both_read = asyncio.Event()

        async def get(self, namespace, key):
            record = await super().get(namespace, key)
            if namespace == FTMOMasterRepository.QUOTE_DEMANDS:
                self.reads += 1
                if self.reads == 2:
                    self.both_read.set()
                await self.both_read.wait()
            return record

    async def scenario():
        repository = FTMOMasterRepository(RacingStore())
        results = await asyncio.gather(
            repository.request_execution_quote("INTC", expires_at=NOW + timedelta(seconds=17)),
            repository.request_execution_quote("INTC", expires_at=NOW + timedelta(seconds=30)),
            return_exceptions=True,
        )
        assert not [value for value in results if isinstance(value, Exception)], results
        record = await repository.store.get(repository.QUOTE_DEMANDS, "INTC")
        assert record.value["expires_at"] == (NOW + timedelta(seconds=30)).isoformat()
    asyncio.run(scenario())


def test_quote_demand_does_not_retry_database_outages():
    class FailedStore(Store):
        calls = 0

        async def put(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("database unavailable")

    store = FailedStore()
    with pytest.raises(RuntimeError, match="database unavailable"):
        asyncio.run(FTMOMasterRepository(store).request_execution_quote("INTC", expires_at=NOW))
    assert store.calls == 1


@pytest.mark.parametrize(("delay_seconds", "fresh_quote"), [(6, False), (2, True)])
def test_approval_refresh_rechecks_clock_after_bridge_read(monkeypatch, delay_seconds, fresh_quote):
    clock = [NOW]
    monkeypatch.setattr("monatise.application.ftmo_master._utc", lambda value=None: value or clock[0])
    async def scenario():
        control, _ = service(active_environment(FTMO_APPROVAL_QUOTE_WAIT_SECONDS="0"))
        await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        original = control.repository.bridge
        async def delayed_read():
            clock[0] = NOW + timedelta(seconds=delay_seconds)
            bridge = await original()
            if fresh_quote:
                bridge["quotes"]["XAUUSD"]["timestamp"] = clock[0].isoformat()
                bridge["quotes"]["XAUUSD"]["quote_observed_at_utc"] = clock[0].isoformat()
            return bridge
        control.repository.bridge = delayed_read
        if not fresh_quote:
            with pytest.raises(FTMOMasterError, match="stale"):
                await control._fresh_approval_quote("XAUUSD", observed=NOW, wait_for_refresh=True, proposal_id="local-test", actor="42")
            return
        _, quote, _ = await control._fresh_approval_quote("XAUUSD", observed=NOW, wait_for_refresh=True, proposal_id="local-test", actor="42")
        age = (clock[0] - datetime.fromisoformat(quote["timestamp"])).total_seconds()
        assert age <= control.configuration.quote_max_age_seconds, f"returned quote age {age}s exceeds {control.configuration.quote_max_age_seconds}s"
    asyncio.run(scenario())


def test_future_candles_are_not_trade_analysis_ready():
    provider = SimpleNamespace(
        candles=lambda *_: [Candle((NOW + timedelta(days=1, minutes=i)).isoformat(), 100, 102, 99, 101, 10) for i in range(2)],
        latest_price=lambda *_: 101,
    )
    snapshot = MarketDataEngine({"test": provider}, clock=lambda: NOW).collect(MarketDataRequest("BTC"))
    assert not snapshot.is_trade_analysis_ready, snapshot.quality


def test_future_candle_provider_falls_back_to_current_data():
    def provider(offset):
        return SimpleNamespace(
            candles=lambda *_: [Candle((NOW + offset - timedelta(minutes=i)).isoformat(), 100, 102, 99, 101, 10) for i in (1, 0)],
            latest_price=lambda *_: 101,
        )
    snapshot = MarketDataEngine({"future": provider(timedelta(days=1)), "current": provider(timedelta())}, clock=lambda: NOW).collect(MarketDataRequest("BTC"))
    assert snapshot.is_trade_analysis_ready
    assert snapshot.quality.source == "current"
    assert snapshot.metadata["fallback_used"]


def test_feedback_form_has_production_handler(monkeypatch):
    runtime = Runtime()
    runtime.document_store = Store()
    sent = []
    monkeypatch.setattr("monatise.application.production.send_feedback_email", lambda **data: sent.append(data))
    code, payload = request(ProductionASGI(runtime), "/api/feedback", {"rating": 5, "category": "bug", "message": "Local test", "page": "/stocks.html"})
    assert code == 200 and payload["accepted"] and payload["emailDelivered"]
    assert len(sent) == 1
    saved = runtime.document_store.values[("feedback", str(payload["feedbackId"]))]
    assert saved.value["message"] == "Local test"


@pytest.mark.parametrize("payload", [[], {"rating": True}, {"rating": 6},
    {"rating": 5, "category": "invalid", "message": "Local test"},
    {"rating": 5, "category": "bug", "message": []},
    {"rating": 5, "category": "bug", "message": "x"},
    {"rating": 5, "category": "bug", "message": "x" * 1501}])
def test_feedback_rejects_invalid_payload_without_saving_or_email(monkeypatch, payload):
    runtime = Runtime()
    runtime.document_store = Store()
    sent = []
    monkeypatch.setattr("monatise.application.production.send_feedback_email", lambda **data: sent.append(data))
    code, _ = request(ProductionASGI(runtime), "/api/feedback", payload)
    assert code == 400
    assert not sent and not runtime.document_store.values


def test_feedback_saved_when_email_unavailable(monkeypatch):
    def unavailable(**kwargs):
        raise RuntimeError("SMTP unavailable")
    runtime = Runtime()
    runtime.document_store = Store()
    monkeypatch.setattr("monatise.application.production.send_feedback_email", unavailable)
    code, payload = request(ProductionASGI(runtime), "/api/feedback", {"rating": 4, "category": "idea", "message": "Local test"})
    assert code == 200 and payload["accepted"] and not payload["emailDelivered"]
    assert len(runtime.document_store.values) == 1


def test_feedback_rate_limit_is_independent_of_market_reads(monkeypatch):
    runtime = Runtime()
    runtime.document_store = Store()
    monkeypatch.setattr("monatise.application.production.send_feedback_email", lambda **data: None)
    app = ProductionASGI(runtime)
    payload = {"rating": 4, "category": "idea", "message": "Local test"}
    for _ in range(8):
        assert request(app, "/api/feedback", payload)[0] == 200
    assert request(app, "/api/feedback", payload)[0] == 429
    assert not app._market_rate_limited({})
    assert len(runtime.document_store.values) == 8


def test_feedback_storage_failure_does_not_send_or_report_success(monkeypatch):
    class FailedStore(Store):
        async def put(self, *args, **kwargs):
            raise RuntimeError("database unavailable")
    runtime = Runtime()
    runtime.document_store = FailedStore()
    sent = []
    monkeypatch.setattr("monatise.application.production.send_feedback_email", lambda **data: sent.append(data))
    code, payload = request(ProductionASGI(runtime), "/api/feedback", {"rating": 4, "category": "idea", "message": "Local test"})
    assert code == 503 and "accepted" not in payload and not sent


def test_feedback_body_limit_and_method():
    async def call(method, body):
        messages = []
        async def receive():
            return {"type": "http.request", "body": body}
        async def send(message):
            messages.append(message)
        await ProductionASGI(Runtime())({"type": "http", "method": method, "path": "/api/feedback"}, receive, send)
        return messages[0]["status"]
    assert asyncio.run(call("GET", b"")) == 405
    assert asyncio.run(call("POST", b"x" * 8193)) == 413


def test_rejection_retcode_cannot_become_broker_accepted():
    async def scenario():
        control, _ = service(active_environment(FTMO_TEMPORARY_ARM_REQUIRED="false"))
        await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        await control.repository.update_control(kill_switch=False)
        proposal = await control.create_trade_proposal(actor="42", symbol="XAUUSD", side="buy", order_type="market", stop_loss="2490.20", take_profit="2520.20", now=NOW)
        command = await control.approve(proposal["proposal_id"], "42", now=NOW)
        result = await control.acknowledge(command["command_id"], {
            "status": "reconciled", "broker_ticket": "0", "broker_retcode": "10018",
            "submission_attempted": True, "fill_price": "0", "executed_volume": "0", "message": "Market closed",
        })
        assert result["lifecycle_state"] != "BROKER_ACCEPTED", result
    asyncio.run(scenario())


def test_duplicate_broker_ack_keeps_proven_execution_and_does_not_notify_twice():
    async def scenario():
        control, _ = service()
        command_id = "local-ack-replay"
        await control.repository.store.put(control.repository.COMMANDS, command_id, {
            "command_id": command_id, "operation": "open", "payload": {"order_type": "market"}, "status": "delivered",
        })
        first = await control.acknowledge(command_id, {
            "status": "reconciled", "broker_ticket": "42", "broker_retcode": "10009",
            "fill_price": "2500", "executed_volume": "0.1", "submission_attempted": True,
        })
        replay = await control.acknowledge(command_id, {"status": "reconciled", "broker_ticket": "42", "submission_attempted": False})
        assert first["notification_required"]
        assert replay["lifecycle_state"] == "BROKER_ACCEPTED"
        assert replay["broker_retcode"] == "10009"
        assert replay["executed_volume"] == "0.1"
        assert replay["submission_attempted"] is True
        assert not replay["notification_required"]
    asyncio.run(scenario())


@pytest.mark.parametrize("owner,other", [(1, 2), (None, 1), (1, None)])
def test_signal_ledger_cannot_update_another_users_record(tmp_path, owner, other):
    from monatise.live.performance import SignalPerformanceStore
    from tests.test_performance import signal_payload
    store = SignalPerformanceStore(str(tmp_path / "local-audit.db"))
    store.save(signal_payload("shared-id", "PENDING"), user_id=owner)
    with pytest.raises(ValueError, match="belongs to another user"):
        store.save(signal_payload("shared-id", "WIN"), user_id=other)
    assert store.records(user_id=owner)[0].status == "PENDING"
    store.save(signal_payload("shared-id", "WIN"), user_id=owner)
    assert store.records(user_id=owner)[0].status == "WIN"


def test_current_stock_analysis_expires_through_public_validity_helper():
    from tests.test_market_intelligence import Alpaca, Quiver, Finnhub, FlashAlpha, NOW as STOCK_NOW
    from monatise.application.market_intelligence import StockMarketIntelligenceCoordinator
    from monatise.application.stock_analysis import refresh_setup_validity
    coordinator = StockMarketIntelligenceCoordinator(Alpaca(), Quiver(), Finnhub(), FlashAlpha(), environment={})
    analysis = asyncio.run(coordinator.analyse("AAPL", now=STOCK_NOW))
    assert analysis["setup_status"] == "confirmed"
    assert analysis["publication_valid"] is True
    expired = refresh_setup_validity(analysis, now=STOCK_NOW + timedelta(hours=2))
    assert expired["decision"] == "NO_TRADE", {
        key: expired.get(key) for key in ("decision", "expires_at", "setup_expires_at", "setup_state", "freshness", "entry")
    }


@pytest.mark.parametrize("expiry_key", ["expires_at", "valid_until", "setup_expires_at"])
def test_stock_expiry_boundary_and_invalid_expiry(expiry_key):
    from monatise.application.stock_analysis import refresh_setup_validity
    original = {"decision": "BUY_WATCH", "setup_status": "confirmed", "publication_valid": True,
                "entry": 100, expiry_key: (NOW + timedelta(milliseconds=500)).isoformat()}
    if expiry_key == "setup_expires_at":
        original["setup_state"] = "ACTIVE"
    assert refresh_setup_validity(original, now=NOW)["setup_state"] == "ACTIVE"
    expired = refresh_setup_validity(original, now=NOW + timedelta(milliseconds=500))
    assert expired["setup_state"] == "EXPIRED" and expired["entry"] is None
    assert expired["publication_valid"] is False
    assert original["entry"] == 100  # cached source is not mutated
    original[expiry_key] = "invalid"
    assert refresh_setup_validity(original, now=NOW)["decision"] == "NO_TRADE"


def test_stock_scanner_normalizes_expired_current_payload():
    runtime = Runtime()
    expiry = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    analysis = {"symbol": "AAPL", "decision": "BUY_WATCH", "setup_status": "confirmed",
                "valid_until": expiry, "entry": 100, "publication_valid": True}
    runtime.dependencies = {"ftmo_stock_scan": {"last_success_at": expiry, "last_result": {"results": [analysis]}}}
    code, payload = asyncio.run(ProductionASGI(runtime)._stocks_scanner())
    assert code == 200
    assert payload["results"][0]["setup_state"] == "EXPIRED"
    assert payload["results"][0]["entry"] is None
    assert analysis["entry"] == 100
