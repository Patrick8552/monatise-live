from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
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
    assert snapshot == {
        "open_interest": 100.0, "open_interest_change_pct": None, "funding_rate": 0.01,
        "liquidation_volume": 20.0, "liquidation_long_usd": None, "liquidation_short_usd": None,
        "derivatives_volume": 300.0, "order_book_imbalance": 0.2, "cvd": 12.0, "cvd_delta": None,
    }
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
    assert adapter.derivatives_snapshot("BTC") == {
        "open_interest": 100.0, "open_interest_change_pct": None, "funding_rate": 0.01,
        "liquidation_volume": 20.0, "liquidation_long_usd": None, "liquidation_short_usd": None,
        "derivatives_volume": 300.0, "order_book_imbalance": 0.2, "cvd": 12.0, "cvd_delta": None,
    }
    assert calls[adapter.ENDPOINTS["funding_rate"]] == {"symbol": "BTC", "interval": "1h", "limit": "2"}
    assert calls[adapter.ENDPOINTS["liquidations"]] == {
        "exchange_list": "Binance",
        "symbol": "BTC",
        "interval": "1h",
        "limit": "2",
    }
    assert calls[adapter.ENDPOINTS["order_book"]]["exchange_list"] == "Binance"
    assert calls[adapter.ENDPOINTS["order_book"]]["symbol"] == "BTC"


def test_derivatives_snapshot_forwards_the_requested_interval_to_every_dataset():
    """funding_rate, liquidations, volume, cvd, and order_book must all be
    fetched at the analysis interval, not silently pinned to 1h -- only
    candles used to bypass this via an explicit params override."""
    calls = {}
    responses = {
        "open-interest": [{"open_interest_usd": "100"}],
        "funding-rate": [{"close": "0.01"}],
        "liquidation": [{"aggregated_long_liquidation_usd": "10", "aggregated_short_liquidation_usd": "5"}],
        "taker-buy-sell": [{"aggregated_buy_volume_usd": "180", "aggregated_sell_volume_usd": "120"}],
        "orderbook": [{"aggregated_bids_usd": "60", "aggregated_asks_usd": "40"}],
        "aggregated-cvd": [{"cum_vol_delta": "12"}],
    }

    def transport(path, params, timeout):
        calls[path] = params
        return {"code": 0, "data": next(value for key, value in responses.items() if key in path)}

    adapter = CoinGlassProductionAdapter(lambda: "secret", transport=transport, requests_per_second=100000)
    adapter.derivatives_snapshot("BTC", "15m")

    assert calls[adapter.ENDPOINTS["funding_rate"]]["interval"] == "15m"
    assert calls[adapter.ENDPOINTS["liquidations"]]["interval"] == "15m"
    assert calls[adapter.ENDPOINTS["volume"]]["interval"] == "15m"
    assert calls[adapter.ENDPOINTS["cvd"]]["interval"] == "15m"
    assert calls[adapter.ENDPOINTS["order_book"]]["interval"] == "15m"
    # open_interest has no interval parameter at all -- it's a live
    # cross-exchange snapshot, not a history endpoint.
    assert "interval" not in calls[adapter.ENDPOINTS["open_interest"]]


def test_coinglass_cvd_delta_is_last_minus_first_row_of_the_fetched_window():
    responses = {
        "open-interest": [{"open_interest_usd": "100"}],
        "funding-rate": [{"close": "0.01"}],
        "liquidation": [{"liquidation_usd": "20"}],
        "taker-buy-sell": [{"aggregated_buy_volume_usd": "180", "aggregated_sell_volume_usd": "120"}],
        "orderbook": [{"aggregated_bids_usd": "60", "aggregated_asks_usd": "40"}],
        "aggregated-cvd": [{"cum_vol_delta": "-30"}, {"cum_vol_delta": "5"}, {"cum_vol_delta": "42"}],
    }

    def transport(path, params, timeout):
        return {"code": 0, "data": next(value for key, value in responses.items() if key in path)}

    adapter = CoinGlassProductionAdapter(lambda: "secret", transport=transport, requests_per_second=100000)
    snapshot = adapter.derivatives_snapshot("BTC")
    assert snapshot["cvd"] == 42.0
    assert snapshot["cvd_delta"] == 72.0


def test_coinglass_liquidations_are_split_by_side_not_duplicated():
    responses = {
        "open-interest": [{"open_interest_usd": "100"}],
        "funding-rate": [{"close": "0.01"}],
        "liquidation": [{"aggregated_long_liquidation_usd": "15000", "aggregated_short_liquidation_usd": "42000"}],
        "taker-buy-sell": [{"aggregated_buy_volume_usd": "180", "aggregated_sell_volume_usd": "120"}],
        "orderbook": [{"aggregated_bids_usd": "60", "aggregated_asks_usd": "40"}],
        "aggregated-cvd": [{"cum_vol_delta": "12"}],
    }

    def transport(path, params, timeout):
        return {"code": 0, "data": next(value for key, value in responses.items() if key in path)}

    adapter = CoinGlassProductionAdapter(lambda: "secret", transport=transport, requests_per_second=100000)
    snapshot = adapter.derivatives_snapshot("BTC")
    assert snapshot["liquidation_long_usd"] == 15000.0
    assert snapshot["liquidation_short_usd"] == 42000.0
    assert snapshot["liquidation_long_usd"] != snapshot["liquidation_short_usd"]
    assert snapshot["liquidation_volume"] == 57000.0


@pytest.mark.parametrize("interval", ["5m", "15m", "30m", "1h", "4h"])
def test_open_interest_change_pct_uses_the_exact_window_when_available(interval):
    responses = {
        "open-interest": [{
            "open_interest_usd": "100",
            f"open_interest_change_percent_{interval}": "3.5",
        }],
        "funding-rate": [{"close": "0.01"}],
        "liquidation": [{"liquidation_usd": "20"}],
        "taker-buy-sell": [{"aggregated_buy_volume_usd": "180", "aggregated_sell_volume_usd": "120"}],
        "orderbook": [{"aggregated_bids_usd": "60", "aggregated_asks_usd": "40"}],
        "aggregated-cvd": [{"cum_vol_delta": "12"}],
    }

    def transport(path, params, timeout):
        return {"code": 0, "data": next(value for key, value in responses.items() if key in path)}

    adapter = CoinGlassProductionAdapter(lambda: "secret", transport=transport, requests_per_second=100000)
    snapshot = adapter.derivatives_snapshot("BTC", interval)
    assert snapshot["open_interest_change_pct"] == 3.5


@pytest.mark.parametrize(
    ("interval", "nearest_window"),
    [("1m", "5m"), ("3m", "5m"), ("6h", "4h"), ("8h", "4h"), ("12h", "4h"), ("1d", "24h"), ("1w", "24h")],
)
def test_open_interest_change_pct_falls_back_to_nearest_available_window(interval, nearest_window):
    responses = {
        "open-interest": [{
            "open_interest_usd": "100",
            f"open_interest_change_percent_{nearest_window}": "7.25",
        }],
        "funding-rate": [{"close": "0.01"}],
        "liquidation": [{"liquidation_usd": "20"}],
        "taker-buy-sell": [{"aggregated_buy_volume_usd": "180", "aggregated_sell_volume_usd": "120"}],
        "orderbook": [{"aggregated_bids_usd": "60", "aggregated_asks_usd": "40"}],
        "aggregated-cvd": [{"cum_vol_delta": "12"}],
    }

    def transport(path, params, timeout):
        return {"code": 0, "data": next(value for key, value in responses.items() if key in path)}

    adapter = CoinGlassProductionAdapter(lambda: "secret", transport=transport, requests_per_second=100000)
    snapshot = adapter.derivatives_snapshot("BTC", interval)
    assert snapshot["open_interest_change_pct"] == 7.25
    assert adapter.OPEN_INTEREST_CHANGE_WINDOW[interval] == nearest_window


def test_coinglass_current_price_uses_binance_pair_market():
    def transport(path, params, timeout):
        assert path == "/api/futures/pairs-markets"
        assert params == {"symbol": "BTC"}
        return {"code": 0, "data": [
            {"exchange_name": "OKX", "instrument_id": "BTC-USDT-SWAP", "current_price": 64_300},
            {"exchange_name": "Binance", "instrument_id": "BTCUSDT", "current_price": "64321.5"},
        ]}

    adapter = CoinGlassProductionAdapter(lambda: "secret", transport=transport, requests_per_second=100000)

    assert adapter.latest_current_price("BTC") == 64_321.5


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


def test_telegram_grid_cancellation_cannot_render_as_entry_ready():
    sent = []

    class Transport:
        async def send_message(self, chat_id, text):
            sent.append((chat_id, text))

    run = AnalysisRun("BTC", {})
    now = run.requested_at
    market = SimpleNamespace(
        price=65_000,
        interval="15m",
        metadata={"price_type": "current", "price_source": "coinglass"},
    )
    result = PipelineResult(
        run.run_id, run.correlation_id, "BTC", PipelineStage.COMPLETED,
        PipelineContext(run, {"market_data": market}),
        PipelineStatistics(1, {}, {}, 1), None, None, now, now,
    )
    notifier = TelegramNotifier(Transport(), "42")

    asyncio.run(notifier.deliver_grid_cancellation(result, "signal score fell below threshold"))

    message = sent[0][1]
    assert "Monatise GRID ENTRY CANCELLED: BTC" in message
    assert "Current CoinGlass price: 65,000" in message
    assert "ENTRY READY" not in message


def test_telegram_grid_replacement_combines_cancellation_and_directional_setup():
    sent = []

    class Transport:
        async def send_message(self, chat_id, text):
            sent.append((chat_id, text))
            return 42

    run = AnalysisRun("BTC", {})
    now = run.requested_at
    outputs = {
        "decision": SimpleNamespace(
            direction=SimpleNamespace(value="long"),
            classification=SimpleNamespace(value="trend"),
            conviction=0.8,
            reasons=(),
            metadata={"signed_signal_score": 8, "minimum_signal_score": 7},
        ),
        "market_data": SimpleNamespace(price=65_000, interval="15m", quality=SimpleNamespace(source="CoinGlass")),
    }
    result = PipelineResult(
        run.run_id, run.correlation_id, "BTC", PipelineStage.COMPLETED,
        PipelineContext(run, outputs), PipelineStatistics(1, {}, {}, 14), None, None, now, now,
    )

    message_id = asyncio.run(TelegramNotifier(Transport(), "42").deliver_grid_replacement(result))

    assert message_id == 42
    assert "GRID ENTRY CANCELLED" in sent[0][1]
    assert "replaced by the directional setup" in sent[0][1]
    assert "directional setup: BTC LONG" in sent[0][1]


def test_telegram_directional_validity_is_rendered():
    run = AnalysisRun("BTC", {})
    # Keep the assertion away from the exact 60-second boundary. The
    # formatter reads the clock independently, so using requested_at could
    # produce either "1 min" or "<1 min" depending on clock precision.
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    signal = SimpleNamespace(pattern="bullish_engulfing", confidence=0.9, evidence_score=0.9, age_candles=3)
    outputs = {
        "decision": SimpleNamespace(
            direction=SimpleNamespace(value="long"),
            classification=SimpleNamespace(value="trend"),
            conviction=0.8,
            reasons=(),
            metadata={"signed_signal_score": 8, "minimum_signal_score": 7},
        ),
        "market_data": SimpleNamespace(price=65_000, interval="1m", quality=SimpleNamespace(source="CoinGlass")),
        "price_action": SimpleNamespace(
            status=SimpleNamespace(value="confirmed"),
            confirming_signals=(signal,),
            conflicting_signals=(),
            strongest_confirming_pattern="bullish_engulfing",
            aggregate_confidence=0.9,
            aligned_family_count=1,
            reasons=(),
        ),
    }
    result = PipelineResult(
        run.run_id, run.correlation_id, "BTC", PipelineStage.COMPLETED,
        PipelineContext(run, outputs), PipelineStatistics(1, {}, {}, 14), None, None, now, now,
    )

    message = TelegramNotifier.format(result)

    assert "Remaining validity:" in message
    assert "Remaining validity: 0 min" not in message


@pytest.mark.parametrize(
    ("direction", "score", "entry", "stop", "target"),
    [
        ("long", 8, 65000.0, 63500.0, 68000.0),
        ("short", -8, 65000.0, 66500.0, 62000.0),
    ],
)
def test_telegram_completed_directional_setup_contains_actionable_levels_and_coinglass_source(
    direction, score, entry, stop, target
):
    run = AnalysisRun("BTC", {})
    now = run.requested_at
    outputs = {
        "decision": SimpleNamespace(
            direction=SimpleNamespace(value=direction),
            classification=SimpleNamespace(value="trend"),
            conviction=0.78,
            reasons=("bullish structure confirmed", "positive derivatives flow"),
            metadata={"signed_signal_score": score, "grid_signal_score": 2, "minimum_signal_score": 7},
        ),
        "market_data": SimpleNamespace(price=entry, metadata={"price_type": "current", "price_source": "coinglass"}, quality=SimpleNamespace(source="CoinGlass futures price history")),
    }
    result = PipelineResult(
        run.run_id, run.correlation_id, "BTC", PipelineStage.COMPLETED,
        PipelineContext(run, outputs), PipelineStatistics(1, {}, {}, 20), None, None, now, now,
    )

    message = TelegramNotifier.format(result)

    assert f"Monatise directional setup: BTC {direction.upper()} (TREND)" in message
    assert "Current CoinGlass price: 65,000" in message
    assert "Projected entry: 65,000" in message
    assert f"Invalidation: {entry * (0.98 if direction == 'long' else 1.02):,.0f}" in message
    assert f"Target: {entry * (1.04 if direction == 'long' else 0.96):,.0f}" in message
    assert "Confidence: 78%" in message
    assert f"Score: {score:+d}/10" in message
    assert "CoinGlass futures price history" in message


def test_telegram_no_trade_message_is_explicit_and_explained():
    run = AnalysisRun("BTC", {})
    now = run.requested_at
    decision = SimpleNamespace(
        classification=SimpleNamespace(value="no_trade"),
        reasons=("insufficient directional conviction", "conflicting order flow"),
        blockers=("market structure is unstable",),
        metadata={"signed_signal_score": 6, "grid_signal_score": 2, "minimum_signal_score": 7},
    )
    result = PipelineResult(
        run.run_id, run.correlation_id, "BTC", PipelineStage.BLOCKED,
        PipelineContext(run, {"decision": decision, "market_data": SimpleNamespace(price=65_000, metadata={"price_type": "current", "price_source": "coinglass"})}), PipelineStatistics(1, {}, {}, 11),
        None, "decision", now, now,
    )

    message = TelegramNotifier.format(result)

    assert "Monatise NO_TRADE: BTC" in message
    assert "Current CoinGlass price: 65,000" in message
    assert "stages 11/20" in message
    assert "insufficient directional conviction" in message
    assert "Score: +6/10 | trade threshold: ±7" in message
    assert "Blocked by: market structure is unstable" in message
    assert f"Run: {run.run_id}" in message


def test_telegram_legacy_grid_analysis_fails_closed():
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
        "market_data": SimpleNamespace(price=65000.0, metadata={"price_type": "current", "price_source": "coinglass"}, quality=SimpleNamespace(source="CoinGlass futures price history")),
    }
    result = PipelineResult(
        run.run_id, run.correlation_id, "BTC", PipelineStage.COMPLETED,
        PipelineContext(run, outputs), PipelineStatistics(1, {}, {}, 20), None, None, now, now,
    )

    message = TelegramNotifier.format(result)

    assert "Monatise NO_TRADE: BTC" in message
    assert "Current CoinGlass price: 65,000" in message
    assert "GRID" not in message
    assert "Buy levels:" not in message
    assert "Sell levels:" not in message


@pytest.mark.parametrize(("status", "expected"), (
    ("confirmed", "Entry confirmation: bullish_engulfing | confidence 82% | aligned families 1 | age 0 candle(s)"),
    ("conflict", "Entry: WAIT — conflicting evidence: bullish bullish_engulfing | bearish bearish_engulfing"),
    ("expired", "Entry: WAIT — previous trigger expired; a fresh price-action trigger is required"),
    ("invalidated", "Entry: WAIT — price-action setup invalidated; a new setup is required"),
    ("pending", "Entry: WAIT — waiting for fixed entry context"),
))
def test_telegram_legacy_grid_never_renders_confirmation_status(status, expected):
    run = AnalysisRun("BTC", {})
    now = run.requested_at
    bullish = SimpleNamespace(family=SimpleNamespace(value="candlestick"), pattern="bullish_engulfing", direction=SimpleNamespace(value="bullish"), confidence=0.8, age_candles=0)
    bearish = SimpleNamespace(family=SimpleNamespace(value="candlestick"), pattern="bearish_engulfing", direction=SimpleNamespace(value="bearish"), confidence=0.8, age_candles=0)
    price_action = SimpleNamespace(
        status=SimpleNamespace(value=status),
        confirming_signals=(bullish,) if status in {"confirmed", "conflict"} else (),
        conflicting_signals=(bearish,) if status == "conflict" else (),
        strongest_confirming_pattern="bullish_engulfing",
        aggregate_confidence=0.82,
        aligned_family_count=1,
        reasons=("waiting for fixed entry context",),
    )
    outputs = {
        "decision": SimpleNamespace(direction=SimpleNamespace(value="two_sided"), classification=SimpleNamespace(value="grid"), conviction=0.8, reasons=(), metadata={"grid_signal_score": 8}),
        "market_data": SimpleNamespace(price=65_000, interval="15m", quality=SimpleNamespace(source="CoinGlass")),
        "price_action": price_action,
    }
    result = PipelineResult(run.run_id, run.correlation_id, "BTC", PipelineStage.COMPLETED, PipelineContext(run, outputs), PipelineStatistics(1, {}, {}, 14), None, None, now, now)
    message = TelegramNotifier.format(result)
    assert "Monatise NO_TRADE: BTC" in message
    assert "ENTRY CONFIRMATION" not in message
    assert expected not in message
    assert "executed" not in message.lower()


def test_telegram_directional_setup_ignores_legacy_risk_rejection():
    run = AnalysisRun("BTC", {})
    now = run.requested_at
    outputs = {
        "decision": SimpleNamespace(
            direction=SimpleNamespace(value="long"),
            classification=SimpleNamespace(value="trend"),
            conviction=0.8,
            reasons=("directional evidence qualified",),
            metadata={"signed_signal_score": 8, "grid_signal_score": 1, "minimum_signal_score": 7},
        ),
        "risk_validation": SimpleNamespace(
            decision=SimpleNamespace(value="rejected"),
            validated_entry=65_000,
            validated_invalidation=66_000,
            validated_target=68_000,
            reward_risk=None,
            signal_expires_at=now,
            issues=(SimpleNamespace(message="stop is on the wrong side of entry"),),
        ),
        "market_data": SimpleNamespace(interval="15m", quality=SimpleNamespace(source="CoinGlass")),
    }
    result = PipelineResult(
        run.run_id, run.correlation_id, "BTC", PipelineStage.BLOCKED,
        PipelineContext(run, outputs), PipelineStatistics(1, {}, {}, 12), None, "risk_validation", now, now,
    )

    message = TelegramNotifier.format(result)

    assert "Monatise directional setup: BTC LONG (TREND)" in message
    assert "Projected entry:" in message
    assert "RISK BLOCKED" not in message
    assert "Risk review:" not in message


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
