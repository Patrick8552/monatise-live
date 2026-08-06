from datetime import datetime, timezone

from monatise.core.models import Candle
from monatise.engines.market_data.models import DataQuality, DataStatus, MarketSnapshot
from monatise.engines.price_action import PriceActionEngine, PriceActionFamily, PriceActionRequest


def market(candles):
    now = datetime.now(timezone.utc)
    return MarketSnapshot("BTC", "15m", candles[-1].close, tuple(candles), DataQuality(DataStatus.READY, "test", now, now, 0))


def test_registers_all_requested_price_action_families():
    candles = [Candle(str(i), 100, 102, 98, 101, 10) for i in range(8)]
    result = PriceActionEngine().assess(PriceActionRequest(market(candles)))
    assert set(result.registered_families) == set(PriceActionFamily)
    assert result.entry_confirmation_required is True


def test_detects_bullish_engulfing_confirmation():
    candles = [Candle(str(i), 100, 102, 98, 101, 10) for i in range(6)]
    candles.extend([Candle("6", 101, 102, 98, 99, 10), Candle("7", 98.5, 102, 98, 101.5, 12)])
    result = PriceActionEngine().assess(PriceActionRequest(market(candles)))
    assert result.has_confirmation
    assert any(signal.pattern == "bullish_engulfing" for signal in result.confirmed_signals)


def test_detects_wyckoff_spring():
    candles = [Candle(str(i), 100, 102, 98, 101, 10) for i in range(20)]
    candles.append(Candle("20", 99, 101, 96, 99, 15))
    result = PriceActionEngine().assess(PriceActionRequest(market(candles)))
    assert any(signal.family is PriceActionFamily.WYCKOFF and signal.pattern == "spring" for signal in result.confirmed_signals)
