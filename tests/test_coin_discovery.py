import asyncio
from types import SimpleNamespace

from monatise.application.deployment import OrchestrationRuntime
from monatise.application.universe_discovery import rank_significant_futures_universe
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


def test_significant_universe_filters_and_ranks_directional_liquid_markets():
    rows = [
        {"symbol": "PEPE", "volume_usd": 50_000_000, "open_interest_usd": 8_000_000,
         "price_change_percent_5m": 0.4, "price_change_percent_15m": 0.8, "price_change_percent_1h": 1.2, "price_change_percent_24h": 5},
        {"symbol": "WIF", "volume_usd": 40_000_000, "open_interest_usd": 7_000_000,
         "price_change_percent_5m": -0.5, "price_change_percent_15m": -0.9, "price_change_percent_1h": -1.4, "price_change_percent_24h": -6},
        {"symbol": "USDC", "volume_usd": 999_000_000, "open_interest_usd": 99_000_000,
         "price_change_percent_5m": 2, "price_change_percent_15m": 2, "price_change_percent_1h": 2},
        {"symbol": "ABC3L", "volume_usd": 99_000_000, "open_interest_usd": 9_000_000,
         "price_change_percent_5m": 2, "price_change_percent_15m": 2, "price_change_percent_1h": 2},
        {"symbol": "DUST", "volume_usd": 10_000, "open_interest_usd": 5_000,
         "price_change_percent_5m": 10, "price_change_percent_15m": 10, "price_change_percent_1h": 10},
    ]

    ranked = rank_significant_futures_universe({"PEPE", "WIF", "USDC", "ABC3L", "DUST"}, rows)

    assert {item.symbol for item in ranked} == {"PEPE", "WIF"}
    assert {item.direction for item in ranked} == {"long", "short"}
    assert all(item.score > 0 for item in ranked)


def test_significant_universe_rejects_conflicting_timeframes_and_honors_limit():
    rows = [
        {"symbol": "A", "volume_usd": 50_000_000, "open_interest_usd": 8_000_000,
         "price_change_percent_5m": 1, "price_change_percent_15m": -1, "price_change_percent_1h": 0},
        {"symbol": "B", "volume_usd": 60_000_000, "open_interest_usd": 9_000_000,
         "price_change_percent_5m": 1, "price_change_percent_15m": 1, "price_change_percent_1h": 1},
        {"symbol": "C", "volume_usd": 70_000_000, "open_interest_usd": 10_000_000,
         "price_change_percent_5m": -1, "price_change_percent_15m": -1, "price_change_percent_1h": -1},
    ]

    ranked = rank_significant_futures_universe({"A", "B", "C"}, rows, limit=1)

    assert len(ranked) == 1
    assert ranked[0].symbol in {"B", "C"}


def test_significant_universe_accepts_real_coinglass_directional_volume_shape():
    rows = [{
        "symbol": "ETH", "open_interest_usd": 9_998_188_964,
        "long_volume_usd_24h": 5_837_517_935, "short_volume_usd_24h": 5_776_311_057,
        "price_change_percent_5m": -0.05, "price_change_percent_15m": -0.06,
        "price_change_percent_1h": -0.48, "price_change_percent_24h": -0.5,
        "open_interest_change_percent_15m": -0.14, "volume_change_percent_1h": -1.23,
    }]

    ranked = rank_significant_futures_universe({"ETH"}, rows)

    assert len(ranked) == 1
    assert ranked[0].direction == "short"
    assert ranked[0].volume_usd == 11_613_828_992
    assert ranked[0].volume_change_15m == -1.23


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


def test_format_dynamic_analysis_rejects_legacy_grid_payloads():
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

    assert "Monatise dynamic scan: DOGE NONE (NO_TRADE)" in message
    assert "Center:" not in message
    assert "Buy levels:" not in message
    assert "Sell levels:" not in message
    assert "Boundaries:" not in message
    assert "Score: -2/10" in message
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
