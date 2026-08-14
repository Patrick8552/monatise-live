import asyncio

from monatise.application.deployment import STOCK_SCAN_SYMBOLS, OrchestrationRuntime
from monatise.application.workflows import TelegramNotifier


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


def _stock_outcome(symbol, **overrides):
    result = {
        "asset": symbol, "asset_class": "stock", "decision": "BUY_WATCH", "score": 4, "score_threshold": 2,
        "reason_code": "ALTERNATIVE_DATA_SUPPORTIVE", "reasons": ["insider buying"], "cautions": [],
        "additional_context": {}, "execution": {"enabled": False, "orders_placed": 0},
        "setup_status": "watch",
    }
    result.update(overrides)
    return result


def test_analyze_stocks_delivers_a_notification_for_every_fixed_symbol():
    class Telegram:
        def __init__(self):
            self.delivered = []

        async def stock_analysis_notification(self, message):
            self.delivered.append(message)

    runtime = OrchestrationRuntime.__new__(OrchestrationRuntime)
    runtime.redis = _AlertRedis()
    runtime.telegram = Telegram()
    runtime.calls = []

    async def analyse_stock(symbol):
        runtime.calls.append(symbol)
        return _stock_outcome(symbol)

    runtime.analyse_stock = analyse_stock

    analyzed = asyncio.run(runtime._analyze_stocks(STOCK_SCAN_SYMBOLS, 21_600, "test"))

    assert analyzed == len(STOCK_SCAN_SYMBOLS)
    assert set(runtime.calls) == set(STOCK_SCAN_SYMBOLS)
    assert len(runtime.telegram.delivered) == len(STOCK_SCAN_SYMBOLS)
    assert any("Monatise stock scan: AAPL (BUY WATCH)" in message for message in runtime.telegram.delivered)


def test_analyze_stocks_notifies_even_on_no_trade_matching_crypto_behavior():
    class Telegram:
        def __init__(self):
            self.delivered = []

        async def stock_analysis_notification(self, message):
            self.delivered.append(message)

    runtime = OrchestrationRuntime.__new__(OrchestrationRuntime)
    runtime.redis = _AlertRedis()
    runtime.telegram = Telegram()

    async def analyse_stock(symbol):
        return _stock_outcome(symbol, decision="NO_TRADE", score=0, setup_status=None)

    runtime.analyse_stock = analyse_stock

    analyzed = asyncio.run(runtime._analyze_stocks(("AAPL",), 21_600, "test"))

    assert analyzed == 1
    assert "Monatise stock scan: AAPL (NO TRADE)" in runtime.telegram.delivered[0]


def test_analyze_stocks_releases_cooldown_on_analysis_failure():
    runtime = OrchestrationRuntime.__new__(OrchestrationRuntime)
    runtime.redis = _AlertRedis()

    class Telegram:
        async def stock_analysis_notification(self, message):
            raise AssertionError("should not deliver a failed analysis")

    runtime.telegram = Telegram()

    async def analyse_stock(symbol):
        raise RuntimeError("Quiver context unavailable")

    runtime.analyse_stock = analyse_stock

    analyzed = asyncio.run(runtime._analyze_stocks(("AAPL",), 21_600, "test"))

    assert analyzed == 0
    assert "test:stock-alert:analysis:AAPL" not in runtime.redis.values


def test_analyze_stocks_is_cooldown_gated_across_calls():
    runtime = OrchestrationRuntime.__new__(OrchestrationRuntime)
    runtime.redis = _AlertRedis()

    class Telegram:
        def __init__(self):
            self.delivered = []

        async def stock_analysis_notification(self, message):
            self.delivered.append(message)

    runtime.telegram = Telegram()
    calls = []

    async def analyse_stock(symbol):
        calls.append(symbol)
        return _stock_outcome(symbol)

    runtime.analyse_stock = analyse_stock

    asyncio.run(runtime._analyze_stocks(("AAPL",), 21_600, "test"))
    asyncio.run(runtime._analyze_stocks(("AAPL",), 21_600, "test"))

    assert calls == ["AAPL"]  # second call is still within the cooldown window


def test_format_stock_analysis_shows_watch_state_when_unconfirmed():
    message = TelegramNotifier.format_stock_analysis(_stock_outcome(
        "TSLA", reasons=["14 Congress trade updates", "20 lobbying disclosures"], cautions=["Government contracts context is undated"],
    ))

    assert "Monatise stock scan: TSLA (BUY WATCH)" in message
    assert "Quiver score: +4/10 | threshold: ±2" in message
    assert "Evidence:" in message and "14 Congress trade updates" in message
    assert "Cautions:" in message and "Government contracts context is undated" in message
    assert "Price confirmation pending; no entry or stop is active." in message
    assert "No trade was executed" in message
    assert "Entry:" not in message


def test_format_stock_analysis_shows_confirmed_levels():
    message = TelegramNotifier.format_stock_analysis(_stock_outcome(
        "NVDA", setup_status="confirmed", entry=180.5, stop_loss=175.0, target=195.0, reward_risk=2.5,
        level_source="Alpaca market data",
        additional_context={"quote": 181.2, "news_count": 12},
    ))

    assert "Monatise stock scan: NVDA (BUY WATCH)" in message
    assert "Entry: $180.50" in message
    assert "Stop: $175.00" in message
    assert "Target: $195.00" in message
    assert "Reward/risk: 2.50" in message
    assert "Finnhub validation: $181.20 | 12 recent news items" in message


def test_format_stock_analysis_no_trade_shows_no_entry_fields():
    message = TelegramNotifier.format_stock_analysis(_stock_outcome(
        "SPY", decision="NO_TRADE", score=0, reason_code="CONFLUENCE_BELOW_THRESHOLD", reasons=[], setup_status=None,
    ))

    assert "Monatise stock scan: SPY (NO TRADE)" in message
    assert "Entry:" not in message
    assert "Price confirmation pending" not in message
