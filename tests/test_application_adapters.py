from __future__ import annotations

import asyncio

import pytest

from monatise.adapters.coinglass_production import CoinGlassProductionAdapter
from monatise.application.models import AnalysisRun, PipelineContext, PipelineResult, PipelineStage, PipelineStatistics
from monatise.application.workflows import OpenClawWorkflow, TelegramNotifier


def test_coinglass_normalizes_six_derivatives_datasets_and_caches():
    calls = []
    values = {
        "open-interest": {"openInterest": "100"},
        "funding-rate": {"fundingRate": "0.01"},
        "liquidation": {"liquidationUsd": "20"},
        "taker-buy-sell": {"cvd": "12"},
        "volume": {"volumeUsd": "300"},
        "orderbook": {"imbalance": "0.2"},
    }

    def transport(path, params, timeout):
        calls.append((path, params, timeout))
        return {"code": "0", "data": next(value for key, value in values.items() if key in path)}

    adapter = CoinGlassProductionAdapter(lambda: "secret", transport=transport, requests_per_second=100000)
    snapshot = adapter.derivatives_snapshot("BTC-USDT")
    assert snapshot == {"open_interest": 100.0, "funding_rate": 0.01, "liquidation_volume": 20.0, "derivatives_volume": 300.0, "order_book_imbalance": 0.2, "cvd": 12.0}
    adapter.derivatives_snapshot("BTC-USDT")
    assert len(calls) == 6
    assert adapter.health().healthy


def test_coinglass_rejects_forex():
    adapter = CoinGlassProductionAdapter(lambda: "secret", transport=lambda *_: {})
    with pytest.raises(ValueError, match="crypto"):
        adapter.open_interest("EURUSD")


def test_coinglass_cache_is_isolated_and_observer_cannot_break_reads():
    calls = []

    def transport(*_):
        calls.append(1)
        return {"code": 0, "data": [{"openInterest": "10"}]}

    adapter = CoinGlassProductionAdapter(lambda: "secret", transport=transport, observer=lambda *_: (_ for _ in ()).throw(RuntimeError("telemetry down")), requests_per_second=100000)
    first = adapter.open_interest("BTC/USDT")
    first[0]["openInterest"] = "999"
    assert adapter.open_interest("BTC/USDT")[0]["openInterest"] == "10"
    assert len(calls) == 1


def test_coinglass_retries_generic_transport_failures():
    attempts = []

    def transport(*_):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("temporary upstream failure")
        return {"code": 0, "data": {"openInterest": 10}}

    adapter = CoinGlassProductionAdapter(lambda: "secret", transport=transport, maximum_attempts=2, requests_per_second=100000)
    assert adapter.open_interest("BTCUSD")["openInterest"] == 10
    assert len(attempts) == 2


def test_telegram_message_has_no_execution_capability():
    sent = []

    class Transport:
        async def send_message(self, chat_id, text):
            sent.append((chat_id, text))

    run = AnalysisRun("BTC", {})
    now = run.requested_at
    result = PipelineResult(run.run_id, run.correlation_id, "BTC", PipelineStage.BLOCKED, PipelineContext(run), PipelineStatistics(1, {}, {}, 0), None, "risk_validation", now, now)
    notifier = TelegramNotifier(Transport(), "42")
    asyncio.run(notifier.deliver(result))
    assert "blocked by risk_validation" in sent[0][1]
    assert notifier.execution_enabled is False


def test_notification_failure_does_not_corrupt_completed_pipeline_result():
    run = AnalysisRun("BTC", {})
    now = run.requested_at
    result = PipelineResult(run.run_id, run.correlation_id, "BTC", PipelineStage.COMPLETED, PipelineContext(run), PipelineStatistics(1, {}, {}, 20), None, None, now, now)

    class Orchestrator:
        async def run(self, value): return result

    class FailedTransport:
        async def send_message(self, chat_id, text): raise RuntimeError("Telegram unavailable")

    workflow = OpenClawWorkflow(Orchestrator(), lambda: run, TelegramNotifier(FailedTransport(), "42"))
    delivered = asyncio.run(workflow.execute())
    assert delivered is result
    assert delivered.status is PipelineStage.COMPLETED
