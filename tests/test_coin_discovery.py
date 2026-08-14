import asyncio
from types import SimpleNamespace

import pytest

from monatise.application.deployment import OrchestrationRuntime
from monatise.application.workflows import TelegramNotifier


def test_price_change_parser_accepts_coinglass_24h_shape():
    assert OrchestrationRuntime._price_change_24h({"price_change_percent_24h": "18.25"}) == 18.25
    assert OrchestrationRuntime._price_change_24h({"price_change_24h": -21}) == -21.0


def test_price_change_parser_fails_closed():
    assert OrchestrationRuntime._price_change_24h({"price_change_percent_24h": "unknown"}) is None
    assert OrchestrationRuntime._price_change_24h({}) is None


def test_coinglass_supported_coin_normalization():
    adapter = SimpleNamespace()
    from monatise.adapters.coinglass_production import CoinGlassProductionAdapter
    instance = object.__new__(CoinGlassProductionAdapter)
    instance.dashboard_query = lambda path, params: {"code": "0", "data": ["btc", "NEW", "BTC", ""]}
    assert instance.supported_futures_coins() == ("BTC", "NEW")


class _AlertRedis:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, **kwargs):
        if kwargs.get("nx") and key in self.values:
            return False
        self.values[key] = (value, kwargs.get("ex"))
        return True

    async def get(self, key):
        entry = self.values.get(key)
        return entry[0] if entry else None

    async def delete(self, key):
        self.values.pop(key, None)


def test_coin_alert_is_only_deduplicated_after_delivery():
    class Telegram:
        async def coin_discovery_notification(self, message):
            assert message == "new coin"

    runtime = object.__new__(OrchestrationRuntime)
    runtime.environment = {"MONATISE_REDIS_NAMESPACE": "test"}
    runtime.redis = _AlertRedis()
    runtime.telegram = Telegram()

    assert asyncio.run(runtime._deliver_coin_alert("new:ABC", "new coin", ttl_seconds=604800)) is True
    assert runtime.redis.values["test:coin-alert:new:ABC"] == ("delivered", 604800)
    assert asyncio.run(runtime._deliver_coin_alert("new:ABC", "new coin", ttl_seconds=604800)) is False


def test_failed_coin_alert_releases_reservation_for_retry():
    class Telegram:
        async def coin_discovery_notification(self, message):
            raise RuntimeError("temporary Telegram failure")

    runtime = object.__new__(OrchestrationRuntime)
    runtime.environment = {"MONATISE_REDIS_NAMESPACE": "test"}
    runtime.redis = _AlertRedis()
    runtime.telegram = Telegram()

    with pytest.raises(RuntimeError, match="temporary Telegram failure"):
        asyncio.run(runtime._deliver_coin_alert("new:ABC", "new coin", ttl_seconds=604800))
    assert "test:coin-alert:new:ABC" not in runtime.redis.values


def test_analyze_volatile_movers_respects_cap_and_delivers_dynamic_analysis():
    class Telegram:
        def __init__(self):
            self.delivered = []

        async def dynamic_analysis_notification(self, message):
            self.delivered.append(message)

    class Runtime(OrchestrationRuntime):
        pass

    runtime = Runtime.__new__(Runtime)
    runtime.redis = _AlertRedis()
    runtime.telegram = Telegram()
    runtime.calls = []

    async def analyse_dynamic_coinglass(symbol, *, interval, source):
        runtime.calls.append((symbol, interval, source))
        return {
            "symbol": symbol, "interval": interval, "classification": "trend", "direction": "long",
            "provenance": {"instrument": f"{symbol}USDT", "exchange": "Binance", "source": "CoinGlass"},
            "evidence": {"current_price": 1.23}, "data_quality": {"passed": True, "failures": [], "warnings": []},
            "entry_zone": {"low": 1.1, "high": 1.2}, "entry_trigger": "confirmed retest",
            "invalidation": 1.0, "targets": [1.5], "reward_risk": 2.0,
            "score": 8, "score_threshold": 7, "volatility_assessment": "continuation requires confirmation",
            "expires_at": "2026-08-13T00:00:00+00:00", "run_id": "run-1",
        }

    runtime.analyse_dynamic_coinglass = analyse_dynamic_coinglass

    movers = [("PEPE", 42.0), ("WIF", -30.0), ("BONK", 25.0)]
    analyzed = asyncio.run(runtime._analyze_volatile_movers(movers, True, 2, "1h", 21_600, "test"))

    assert analyzed == 2
    assert [symbol for symbol, _interval, _source in runtime.calls] == ["PEPE", "WIF"]
    assert len(runtime.telegram.delivered) == 2
    assert "Monatise dynamic scan: PEPE LONG (TREND)" in runtime.telegram.delivered[0]


def test_analyze_volatile_movers_disabled_by_config():
    runtime = OrchestrationRuntime.__new__(OrchestrationRuntime)
    analyzed = asyncio.run(runtime._analyze_volatile_movers([("PEPE", 42.0)], False, 5, "1h", 21_600, "test"))
    assert analyzed == 0


def test_analyze_volatile_movers_releases_cooldown_on_analysis_failure():
    runtime = OrchestrationRuntime.__new__(OrchestrationRuntime)
    runtime.redis = _AlertRedis()

    class Telegram:
        async def dynamic_analysis_notification(self, message):
            raise AssertionError("should not deliver a failed analysis")

    runtime.telegram = Telegram()

    async def analyse_dynamic_coinglass(symbol, *, interval, source):
        raise ValueError("CoinGlass does not list SCAM as a supported futures coin")

    runtime.analyse_dynamic_coinglass = analyse_dynamic_coinglass

    analyzed = asyncio.run(runtime._analyze_volatile_movers([("SCAM", 99.0)], True, 5, "1h", 21_600, "test"))

    assert analyzed == 0
    assert "test:coin-alert:analysis:SCAM" not in runtime.redis.values


def test_analyze_volatile_movers_is_cooldown_gated_across_calls():
    runtime = OrchestrationRuntime.__new__(OrchestrationRuntime)
    runtime.redis = _AlertRedis()

    class Telegram:
        def __init__(self):
            self.delivered = []

        async def dynamic_analysis_notification(self, message):
            self.delivered.append(message)

    runtime.telegram = Telegram()
    calls = []

    async def analyse_dynamic_coinglass(symbol, *, interval, source):
        calls.append(symbol)
        return {"symbol": symbol, "classification": "no_trade", "data_quality": {"passed": True}}

    runtime.analyse_dynamic_coinglass = analyse_dynamic_coinglass

    asyncio.run(runtime._analyze_volatile_movers([("PEPE", 42.0)], True, 5, "1h", 21_600, "test"))
    asyncio.run(runtime._analyze_volatile_movers([("PEPE", 45.0)], True, 5, "1h", 21_600, "test"))

    assert calls == ["PEPE"]  # second call is still within the cooldown window


def test_format_dynamic_analysis_shows_zone_targets_and_never_an_entry_field():
    message = TelegramNotifier.format_dynamic_analysis({
        "symbol": "PEPE", "interval": "1h", "classification": "trend", "direction": "long",
        "provenance": {"instrument": "PEPEUSDT", "exchange": "Binance", "source": "CoinGlass"},
        "evidence": {"current_price": 0.00001234},
        "data_quality": {"passed": True, "failures": [], "warnings": []},
        "entry_zone": {"low": 0.0000121, "high": 0.0000125}, "entry_trigger": "confirmed retest",
        "invalidation": 0.0000119, "targets": [0.0000140], "reward_risk": 2.1,
        "score": 8, "score_threshold": 7, "volatility_assessment": "note",
        "expires_at": "2026-08-13T00:00:00+00:00", "run_id": "run-1",
    })

    assert "Monatise dynamic scan: PEPE LONG (TREND)" in message
    assert "Resolved market: PEPEUSDT on Binance" in message
    assert "Entry zone:" in message
    assert "trigger required, not an automatic entry" in message
    assert '"entry"' not in message
    assert "Run: run-1" in message


def test_format_dynamic_analysis_shows_the_full_grid_plan_and_grid_score():
    message = TelegramNotifier.format_dynamic_analysis({
        "symbol": "DOGE", "interval": "15m", "classification": "grid", "direction": "two_sided",
        "provenance": {"instrument": "DOGEUSDT", "exchange": "Binance", "source": "CoinGlass"},
        "evidence": {"current_price": 0.0699},
        "data_quality": {"passed": True, "failures": [], "warnings": []},
        "entry_trigger": "confirmed by net CoinGlass order flow (CVD)",
        "grid_plan": {
            "center": 0.0699, "buy_levels": [0.06972, 0.06946], "sell_levels": [0.07018, 0.07047],
            "lower_boundary": 0.06946, "upper_boundary": 0.07047,
            "lower_invalidation": 0.06932, "upper_invalidation": 0.07061,
            "spacing": 0.00013, "levels_per_side": 2,
        },
        "score": -2, "grid_score": 8, "score_threshold": 7,
        "run_id": "run-3",
    })

    assert "Monatise dynamic scan: DOGE TWO_SIDED (GRID)" in message
    assert "Center: 0.0699" in message
    assert "Buy levels: 0.06972 | 0.06946" in message
    assert "Sell levels: 0.07018 | 0.07047" in message
    assert "Boundaries: 0.06946 — 0.07047" in message
    assert "Invalidation: below 0.06932 or above 0.07061" in message
    # The grid classification is qualified by grid_score (8, above threshold),
    # not the unrelated signed score (-2) -- showing -2 here would make an
    # actionable grid look like it's failing its own threshold.
    assert "Score: 8/10" in message
    assert "Score: -2/10" not in message
    assert '"entry"' not in message


def test_format_dynamic_analysis_shows_quality_failures_for_no_trade():
    message = TelegramNotifier.format_dynamic_analysis({
        "symbol": "SCAM", "interval": "1h", "classification": "no_trade", "direction": "none",
        "provenance": {}, "evidence": {},
        "data_quality": {"passed": False, "failures": ["insufficient candle history: 20/120"], "warnings": []},
        "score": 1, "score_threshold": 7, "run_id": "run-2",
    })

    assert "Monatise dynamic scan: SCAM NONE (NO_TRADE)" in message
    assert "Status: NO_TRADE — quality gate failed" in message
    assert "insufficient candle history" in message
