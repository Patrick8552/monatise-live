from __future__ import annotations

import asyncio
from types import SimpleNamespace

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
        "aggregated-cvd": {"cvd": "12"},
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


def test_coinglass_uses_official_dataset_parameters_and_normalizes_native_fields():
    calls = {}
    responses = {
        "open-interest": [{"open_interest_usd": "100"}],
        "funding-rate": [{"close": "0.01"}],
        "liquidation": [{"liquidation_usd": "20"}],
        "taker-buy-sell": [{"aggregated_buy_volume_usd": "180", "aggregated_sell_volume_usd": "120"}],
        "orderbook": [{"aggregated_bids_usd": "60", "aggregated_asks_usd": "40"}],
        "aggregated-cvd": [{"cum_vol_delta": "12"}],
    }

    def transport(path, params, timeout):
        calls[path] = params
        return {"code": 0, "data": next(value for key, value in responses.items() if key in path)}

    adapter = CoinGlassProductionAdapter(lambda: "secret", transport=transport, requests_per_second=100000)
    assert adapter.derivatives_snapshot("BTC") == {"open_interest": 100.0, "funding_rate": 0.01, "liquidation_volume": 20.0, "derivatives_volume": 300.0, "order_book_imbalance": 0.2, "cvd": 12.0}
    assert calls[adapter.ENDPOINTS["funding_rate"]] == {"symbol": "BTC", "interval": "1h", "limit": "2"}
    assert calls[adapter.ENDPOINTS["liquidations"]] == {
        "exchange_list": "Binance",
        "symbol": "BTC",
        "interval": "1h",
        "limit": "2",
    }
    assert calls[adapter.ENDPOINTS["order_book"]]["exchange_list"] == "Binance"
    assert calls[adapter.ENDPOINTS["order_book"]]["symbol"] == "BTC"


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


def test_coinglass_optional_dataset_failure_does_not_mark_price_feed_unhealthy():
    def transport(path, *_):
        if "price/history" in path:
            return {"code": 0, "data": [{"time": "2026-08-03T12:00:00+00:00", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 1}]}
        raise RuntimeError("optional dataset unavailable")

    adapter = CoinGlassProductionAdapter(lambda: "secret", transport=transport, maximum_attempts=1, requests_per_second=100000)
    assert adapter.candles("BTC", 2)
    with pytest.raises(RuntimeError):
        adapter.open_interest("BTC")
    assert adapter.health().healthy is True
    assert adapter.health().consecutive_failures == 0


def test_coinglass_price_failure_marks_essential_feed_unhealthy():
    calls = 0

    def transport(path, *_):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"code": 0, "data": [{"open_interest_usd": 100}]}
        raise RuntimeError(f"essential dataset unavailable: {path}")

    adapter = CoinGlassProductionAdapter(lambda: "secret", transport=transport, maximum_attempts=1, requests_per_second=100000)
    assert adapter.open_interest("BTC")
    with pytest.raises(RuntimeError):
        adapter.candles("BTC", 2)
    assert adapter.health().healthy is False
    assert adapter.health().consecutive_failures == 1


def test_coinglass_counts_an_exhausted_request_not_each_retry_attempt():
    adapter = CoinGlassProductionAdapter(lambda: "secret", transport=lambda *_: (_ for _ in ()).throw(RuntimeError("down")), maximum_attempts=3, requests_per_second=100000)
    with pytest.raises(RuntimeError):
        adapter.candles("BTC", 2)
    assert adapter.health().consecutive_failures == 1


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


def test_coinglass_supplies_canonical_price_candles():
    def transport(path, params, timeout):
        assert path.endswith("/price/history")
        assert params["symbol"] == "BTCUSDT"
        return {"code": 0, "data": [{"time": 1_700_000_000_000, "open": "10", "high": "12", "low": "9", "close": "11", "volume_usd": "100"}]}

    adapter = CoinGlassProductionAdapter(lambda: "secret", transport=transport, requests_per_second=100000)
    candle = adapter.candles("BTC", 2)[0]
    assert candle.close == 11
    assert adapter.latest_price("BTC") == 11


def test_coinglass_malformed_candle_fails_closed():
    adapter = CoinGlassProductionAdapter(lambda: "secret", transport=lambda *_: {"code": 0, "data": [{"time": 1}]}, requests_per_second=100000)
    with pytest.raises(Exception, match="malformed candle"):
        adapter.candles("BTC", 2)


def test_coinglass_dashboard_queries_are_allowlisted_cached_and_server_side():
    calls = []
    def transport(path, params, timeout):
        calls.append((path, params))
        return {"code": 0, "data": [{"symbol": params.get("symbol")}]}

    adapter = CoinGlassProductionAdapter(lambda: "server-secret", transport=transport, requests_per_second=100000)
    first = adapter.dashboard_query("/api/futures/open-interest/exchange-list", {"symbol": "BTC"})
    second = adapter.dashboard_query("/api/futures/open-interest/exchange-list", {"symbol": "BTC"})
    assert first == second == {"code": 0, "data": [{"symbol": "BTC"}]}
    assert len(calls) == 1
    with pytest.raises(ValueError, match="unsupported"):
        adapter.dashboard_query("/api/private/account", {})
    with pytest.raises(ValueError, match="parameters"):
        adapter.dashboard_query("/api/futures/open-interest/exchange-list", {"api_key": "browser-secret"})


def test_coinglass_dashboard_liquidations_accepts_required_exchange_list():
    captured = []

    def transport(path, params, timeout):
        captured.append((path, params, timeout))
        return {"code": 0, "data": [{"liquidation_usd": "20"}]}

    adapter = CoinGlassProductionAdapter(lambda: "server-secret", transport=transport, requests_per_second=100000)
    payload = adapter.dashboard_query(
        "/api/futures/liquidation/aggregated-history",
        {"exchange_list": "Binance", "symbol": "BTC", "interval": "1h", "limit": "2"},
    )

    assert payload["data"][0]["liquidation_usd"] == "20"
    assert captured[0][1]["exchange_list"] == "Binance"


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


def test_telegram_completed_signal_contains_actionable_levels_and_coinglass_source():
    run = AnalysisRun("BTC", {})
    now = run.requested_at
    outputs = {
        "decision": SimpleNamespace(
            direction=SimpleNamespace(value="long"),
            classification=SimpleNamespace(value="trend"),
            conviction=0.78,
            reasons=("bullish structure confirmed", "positive derivatives flow"),
            metadata={"signed_signal_score": 8, "grid_signal_score": 2, "minimum_signal_score": 7},
        ),
        "risk_validation": SimpleNamespace(
            validated_entry=65000.0,
            validated_invalidation=63500.0,
            validated_target=68000.0,
            reward_risk=2.0,
            signal_expires_at=now,
        ),
        "market_data": SimpleNamespace(quality=SimpleNamespace(source="CoinGlass futures price history")),
    }
    result = PipelineResult(
        run.run_id, run.correlation_id, "BTC", PipelineStage.COMPLETED,
        PipelineContext(run, outputs), PipelineStatistics(1, {}, {}, 20), None, None, now, now,
    )

    message = TelegramNotifier.format(result)

    assert "BTC LONG (TREND)" in message
    assert "Entry: 65,000" in message
    assert "Stop: 63,500" in message
    assert "Target: 68,000" in message
    assert "Confidence: 78%" in message
    assert "Score: +8/10" in message
    assert "CoinGlass futures price history" in message


def test_telegram_no_trade_message_is_explicit_and_explained():
    run = AnalysisRun("BTC", {})
    now = run.requested_at
    decision = SimpleNamespace(
        classification=SimpleNamespace(value="no_trade"),
        reasons=("insufficient directional conviction", "conflicting order flow"),
        metadata={"signed_signal_score": 6, "grid_signal_score": 2, "minimum_signal_score": 7},
    )
    result = PipelineResult(
        run.run_id, run.correlation_id, "BTC", PipelineStage.BLOCKED,
        PipelineContext(run, {"decision": decision}), PipelineStatistics(1, {}, {}, 11),
        None, "decision", now, now,
    )

    message = TelegramNotifier.format(result)

    assert "Monatise NO_TRADE: BTC" in message
    assert "stages 11/19" in message
    assert "insufficient directional conviction" in message
    assert "Score: +6/10 | trade threshold: ±7" in message
    assert f"Run: {run.run_id}" in message


def test_telegram_grid_analysis_is_included_and_labeled():
    run = AnalysisRun("BTC", {})
    now = run.requested_at
    outputs = {
        "decision": SimpleNamespace(
            direction=SimpleNamespace(value="two_sided"),
            classification=SimpleNamespace(value="grid"),
            conviction=0.72,
            reasons=("balanced two-sided liquidity",),
            metadata={"signed_signal_score": 0, "grid_signal_score": 7, "minimum_signal_score": 7},
        ),
        "risk_validation": SimpleNamespace(
            validated_entry=65000.0,
            validated_invalidation=63700.0,
            validated_target=67600.0,
            reward_risk=2.0,
            signal_expires_at=now,
        ),
        "market_data": SimpleNamespace(quality=SimpleNamespace(source="CoinGlass futures price history")),
    }
    result = PipelineResult(
        run.run_id, run.correlation_id, "BTC", PipelineStage.COMPLETED,
        PipelineContext(run, outputs), PipelineStatistics(1, {}, {}, 20), None, None, now, now,
    )

    message = TelegramNotifier.format(result)

    assert "Monatise GRID: BTC (TWO_SIDED)" in message
    assert "Entry: 65,000" in message
    assert "CoinGlass futures price history" in message
    assert "Score: 7/10" in message


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
