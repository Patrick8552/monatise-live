from monatise.analysis.fibonacci import analyze_fibonacci
from monatise.core.models import Candle


def test_fibonacci_analysis_builds_retracements_and_extensions() -> None:
    candles = [
        Candle("1", open=100, high=105, low=95, close=102),
        Candle("2", open=102, high=110, low=101, close=108),
        Candle("3", open=108, high=120, low=107, close=118),
        Candle("4", open=118, high=121, low=112, close=115),
        Candle("5", open=115, high=116, low=109, close=114),
    ]

    analysis = analyze_fibonacci("BTC", "1h", candles, mark=114)

    assert analysis.trend == "up"
    assert analysis.swing_high == 121
    assert analysis.swing_low == 95
    assert analysis.grid_floor < analysis.mark < analysis.grid_ceiling
    assert len(analysis.levels) == 7
    assert analysis.nearest_level.kind in {"retracement", "extension"}
    assert analysis.take_profit.kind == "retracement"
    assert analysis.take_profit.price == 114.864
    assert analysis.take_profit.price > analysis.mark


def test_fibonacci_analysis_uses_fast_take_profit_for_downtrend() -> None:
    candles = [
        Candle("1", open=120, high=125, low=118, close=122),
        Candle("2", open=122, high=123, low=110, close=112),
        Candle("3", open=112, high=114, low=100, close=104),
        Candle("4", open=104, high=108, low=99, close=103),
        Candle("5", open=103, high=107, low=101, close=102),
    ]

    analysis = analyze_fibonacci("BTC", "1h", candles, mark=110)

    assert analysis.trend == "down"
    assert analysis.take_profit.kind == "retracement"
    assert analysis.take_profit.price == 108.932
    assert analysis.take_profit.price < analysis.mark
