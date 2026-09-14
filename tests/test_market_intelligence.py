import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from monatise.application.ftmo_registry import FTMO_REGISTRY
from monatise.application.market_intelligence import (
    FuturesMarketIntelligenceCoordinator,
    StockMarketIntelligenceCoordinator,
    validate_candles,
)


NOW = datetime(2026, 8, 27, 15, tzinfo=timezone.utc)


def bars(minutes: int, *, count: int = 80, end: datetime = NOW - timedelta(minutes=15)) -> list[dict]:
    start = end - timedelta(minutes=minutes * (count - 1))
    return [
        {
            "t": (start + timedelta(minutes=minutes * index)).isoformat(),
            "o": 100 + index * 0.1,
            "h": 101 + index * 0.1,
            "l": 99 + index * 0.1,
            "c": 100.5 + index * 0.1,
            "v": 1000 + index,
        }
        for index in range(count)
    ]


class Alpaca:
    def __init__(self, *, failure: Exception | None = None, hourly=None, trigger=None):
        self.failure, self.hourly, self.trigger, self.calls = failure, hourly or bars(60), trigger or bars(15), []

    def stock_bars(self, symbol, timeframe, limit=200):
        self.calls.append(("bars", symbol, timeframe, limit))
        if self.failure:
            raise self.failure
        minutes = {"4Hour": 240, "1Hour": 60, "15Min": 15, "5Min": 5, "1Min": 1}[timeframe]
        return bars(minutes, end=NOW - timedelta(minutes=minutes * 2))

    def market_calendar(self, day):
        return [{"date": day, "open": "09:30", "close": "16:00"}]

    def stock_snapshot(self, symbol):
        self.calls.append(("snapshot", symbol))
        if self.failure:
            raise self.failure
        return {"latestQuote": {"bp": 107.9, "ap": 108.1}}


class Quiver:
    def __init__(self, *, available=True, score=3):
        self.available, self.score = available, score

    def context(self, symbol):
        return {
            "symbol": symbol, "source": "Quiver Quantitative", "available": self.available,
            "summary": {"score": self.score, "drivers": ["fresh alternative-data evidence"]},
        }


class Finnhub:
    def __init__(self, *, failure: Exception | None = None):
        self.failure = failure

    def context(self, symbol):
        if self.failure:
            raise self.failure
        return {"source": "Finnhub", "quote": {"c": 108}, "news": [{}], "recommendations": [], "earnings": []}


class FlashAlpha:
    def __init__(self, *, failure: Exception | None = None, bullish=True, mutation: str | None = None):
        self.failure, self.bullish, self.mutation = failure, bullish, mutation

    def context(self, symbol):
        if self.failure:
            raise self.failure
        price, flip = (108, 106) if self.bullish else (104, 106)
        result = {
            "source": "FlashAlpha", "symbol": symbol, "as_of": (NOW - timedelta(minutes=5)).isoformat(),
            "underlying_price": price, "gamma_flip": flip, "call_wall": 115,
            "put_wall": 95, "net_gex": 1, "net_gex_label": "positive",
        }
        if self.mutation == "stale":
            result["as_of"] = (NOW - timedelta(hours=2)).isoformat()
        elif self.mutation == "missing_wall":
            result.pop("call_wall")
        return result


def test_stock_coordinator_uses_verified_roles_and_never_yahoo():
    coordinator = StockMarketIntelligenceCoordinator(Alpaca(), Quiver(), Finnhub(), FlashAlpha(), environment={})
    result = asyncio.run(coordinator.analyse("AAPL", instrument=FTMO_REGISTRY.resolve("AAPL"), now=NOW))
    providers = {item["provider"]: item for item in result["analysis_sources"]}
    assert providers["alpaca"]["status"] == "used"
    assert providers["quiver"]["affected_score"] is False
    assert providers["finnhub"]["role"] == "supplemental_intelligence"
    assert providers["flashalpha"]["role"] == "positioning_context"
    assert providers["flashalpha"]["affected_score"] is False
    assert providers["alpaca"]["role"] == "primary_candle_analysis"
    assert providers["alpaca"]["affected_score"] is True
    assert providers["ftmo_mt5"]["status"] == "not_requested"
    assert "yahoo" not in str(result).casefold()
    assert result["analysis_provider"] == "alpaca"
    assert providers["alpaca"]["timeframes"]["1h"]["candle_count"] == 80
    assert result["analysis_timeframe"] == "1h" and result["trigger_timeframe"] == "5m"


def test_alpaca_failure_blocks_snapshot_only_stock_analysis():
    coordinator = StockMarketIntelligenceCoordinator(
        Alpaca(failure=RuntimeError("Alpaca HTTP 429")), Quiver(), Finnhub(), FlashAlpha(), environment={},
    )
    result = asyncio.run(coordinator.analyse("AAPL", instrument=FTMO_REGISTRY.resolve("AAPL"), now=NOW))
    providers = {item["provider"]: item for item in result["analysis_sources"]}
    assert result["decision"] == "INSUFFICIENT_MARKET_DATA"
    assert result["analysis_provider"] == "alpaca"
    assert result["publication_valid"] is False
    assert "429" in result["reason_code"]
    assert result["ftmo_execution_quote"]["status"] == "not_requested"


def test_optional_context_failure_degrades_without_replacing_candle_analysis():
    coordinator = StockMarketIntelligenceCoordinator(
        Alpaca(), Quiver(available=False), Finnhub(failure=TimeoutError()), FlashAlpha(), environment={},
    )
    result = asyncio.run(coordinator.analyse("AAPL", instrument=FTMO_REGISTRY.resolve("AAPL"), now=NOW))
    providers = {item["provider"]: item for item in result["analysis_sources"]}
    assert result["decision"] != "INSUFFICIENT_MARKET_DATA"
    assert providers["alpaca"]["status"] == "used"
    assert providers["quiver"]["status"] == "degraded"
    assert providers["finnhub"]["status"] == "degraded"
    assert providers["flashalpha"]["status"] == "used"
    assert result["provider_consensus"] == "PARTIAL"


def test_required_positioning_context_failure_still_fails_closed():
    coordinator = StockMarketIntelligenceCoordinator(
        Alpaca(), Quiver(), Finnhub(), FlashAlpha(failure=RuntimeError("FlashAlpha HTTP 429")), environment={},
    )
    result = asyncio.run(coordinator.analyse("AAPL", instrument=FTMO_REGISTRY.resolve("AAPL"), now=NOW))
    assert result["decision"] == "INSUFFICIENT_MARKET_DATA"
    assert result["reason_code"] == "provider_rate_limited"
    assert result["fallback_status"] == "no_verified_fallback"
    assert result["ftmo_execution_quote"]["status"] == "not_requested"


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [("stale", "provider_stale"), ("missing_wall", "provider_incomplete")],
)
def test_invalid_flashalpha_primary_payload_fails_stock_analysis_closed(mutation, reason_code):
    coordinator = StockMarketIntelligenceCoordinator(
        Alpaca(), Quiver(), Finnhub(), FlashAlpha(mutation=mutation), environment={},
    )
    result = asyncio.run(coordinator.analyse("AAPL", instrument=FTMO_REGISTRY.resolve("AAPL"), now=NOW))
    assert result["decision"] == "INSUFFICIENT_MARKET_DATA"
    assert result["reason_code"] == reason_code
    assert result["analysis_provider"] == "alpaca"


def test_non_flashalpha_stock_is_rejected_without_calling_supporting_providers():
    alpaca = Alpaca()
    coordinator = StockMarketIntelligenceCoordinator(alpaca, Quiver(), Finnhub(), FlashAlpha(), environment={})
    result = asyncio.run(coordinator.analyse("ADS.DE", instrument=FTMO_REGISTRY.resolve("ADSGn"), now=NOW))
    assert result["decision"] == "INSUFFICIENT_MARKET_DATA"
    assert result["reason_code"] == "provider_unsupported"
    assert alpaca.calls == []


@pytest.mark.parametrize("mutation", ["future", "duplicate", "impossible", "stale"])
def test_candle_quality_rejects_invalid_series(mutation):
    rows = bars(15)
    if mutation == "future":
        rows[-1]["t"] = (NOW + timedelta(minutes=1)).isoformat()
    elif mutation == "duplicate":
        rows[-1]["t"] = rows[-2]["t"]
    elif mutation == "impossible":
        rows[-1]["l"] = rows[-1]["h"] + 1
    else:
        rows = bars(15, end=NOW - timedelta(days=5))
    with pytest.raises(ValueError):
        validate_candles(rows, provider="alpaca", symbol="AAPL", timeframe="15m", now=NOW)


def test_futures_coordinator_preserves_flashalpha_and_ftmo_separation():
    coordinator = FuturesMarketIntelligenceCoordinator(FlashAlpha(), environment={})
    result = asyncio.run(coordinator.analyse(FTMO_REGISTRY.resolve("XAU/USD"), now=NOW))
    providers = {item["provider"]: item for item in result["analysis_sources"]}
    assert result["analysis_provider"] == "flashalpha"
    assert result["analysis_instrument"] == "GC=F"
    assert result["provider_consensus"] == "PARTIAL"
    assert providers["flashalpha"]["status"] == "used"
    assert providers["ftmo_mt5"]["status"] == "not_requested"
    assert "bid" not in result and "ask" not in result
    assert result["expires_at"] == (NOW + timedelta(minutes=30)).isoformat()


def test_futures_provider_failure_returns_insufficient_market_data():
    coordinator = FuturesMarketIntelligenceCoordinator(FlashAlpha(failure=RuntimeError("FlashAlpha HTTP 403")), environment={})
    result = asyncio.run(coordinator.analyse(FTMO_REGISTRY.resolve("US500.cash"), now=NOW))
    assert result["decision"] == "INSUFFICIENT_MARKET_DATA"
    assert result["reason_code"] == "provider_unsupported"
    assert result["ftmo_execution_quote"]["status"] == "not_requested"


def test_request_latency_does_not_make_fresh_stock_context_future_data(monkeypatch):
    import monatise.application.market_intelligence as module
    class ReceiptClock(datetime):
        calls=0
        @classmethod
        def now(cls, tz=None):
            cls.calls+=1
            return NOW + timedelta(seconds=0 if cls.calls==1 else 2)
    class LiveFlash(FlashAlpha):
        def context(self,symbol):
            value=super().context(symbol);value['as_of']=(NOW+timedelta(seconds=1)).isoformat();return value
    class Hierarchy:
        async def analyse(self,*args,**kwargs):
            return {'setup_status':'not_confirmed','analysis_sources':[],'direction':'NONE'}
        async def invalidate(self,*args):
            raise AssertionError('valid receipt-time context must reach candle analysis')
    monkeypatch.setattr(module,'datetime',ReceiptClock)
    coordinator=StockMarketIntelligenceCoordinator(Alpaca(),Quiver(),Finnhub(),LiveFlash(),environment={},hierarchy=Hierarchy())
    result=asyncio.run(coordinator.analyse('AAPL',instrument=FTMO_REGISTRY.resolve('AAPL')))
    assert result['setup_status']=='not_confirmed'


def test_request_latency_does_not_make_fresh_index_context_future_data(monkeypatch):
    import monatise.application.market_intelligence as module
    class ReceiptClock(datetime):
        calls=0
        @classmethod
        def now(cls,tz=None):
            cls.calls+=1
            return NOW+timedelta(seconds=0 if cls.calls==1 else 2)
    class LiveFlash(FlashAlpha):
        def context(self,symbol):
            value=super().context(symbol);value['as_of']=(NOW+timedelta(seconds=1)).isoformat();return value
    class Hierarchy:
        async def analyse(self,*args,**kwargs):
            return {'setup_status':'not_confirmed','analysis_sources':[]}
        async def invalidate(self,*args):
            raise AssertionError('fresh context incorrectly invalidated')
    monkeypatch.setattr(module,'datetime',ReceiptClock)
    for symbol in ['US100.cash','US500.cash']:
        ReceiptClock.calls=0
        coordinator=FuturesMarketIntelligenceCoordinator(LiveFlash(),environment={},hierarchy=Hierarchy())
        assert asyncio.run(coordinator.analyse(FTMO_REGISTRY.resolve(symbol)))['setup_status']=='not_confirmed'


def test_genuinely_future_context_still_fails_closed():
    class FutureFlash(FlashAlpha):
        def context(self,symbol):
            value=super().context(symbol);value['as_of']=(NOW+timedelta(minutes=10)).isoformat();return value
    coordinator=StockMarketIntelligenceCoordinator(Alpaca(),Quiver(),Finnhub(),FutureFlash(),environment={})
    assert asyncio.run(coordinator.analyse('AAPL',now=NOW))['decision']=='INSUFFICIENT_MARKET_DATA'
