from monatise.analysis.fvg import analyze_fvg
from monatise.core.models import Candle


def test_fvg_analysis_finds_active_bullish_gap() -> None:
    candles = [
        Candle("1", open=96, high=100, low=94, close=98),
        Candle("2", open=98, high=103, low=97, close=102),
        Candle("3", open=106, high=112, low=105, close=110),
        Candle("4", open=110, high=114, low=102, close=111),
    ]

    analysis = analyze_fvg("BTC", "15m", candles, mark=108)

    assert analysis.active_count == 1
    assert analysis.bias == "bullish"
    assert analysis.nearest_gap is not None
    assert analysis.nearest_gap.direction == "bullish"
    assert analysis.nearest_gap.low == 100
    assert analysis.nearest_gap.high == 105
    assert analysis.nearest_gap.midpoint == 102.5
    assert analysis.nearest_gap.distance_to_mark == 3


def test_fvg_analysis_finds_active_bearish_gap() -> None:
    candles = [
        Candle("1", open=108, high=110, low=100, close=102),
        Candle("2", open=102, high=104, low=96, close=98),
        Candle("3", open=94, high=95, low=88, close=90),
        Candle("4", open=90, high=97, low=86, close=92),
    ]

    analysis = analyze_fvg("BTC", "5m", candles, mark=97)

    assert analysis.active_count == 1
    assert analysis.bias == "bearish"
    assert analysis.nearest_gap is not None
    assert analysis.nearest_gap.direction == "bearish"
    assert analysis.nearest_gap.low == 95
    assert analysis.nearest_gap.high == 100
    assert analysis.nearest_gap.distance_to_mark == 0


def test_fvg_analysis_excludes_filled_gap_from_active_list() -> None:
    candles = [
        Candle("1", open=96, high=100, low=94, close=98),
        Candle("2", open=98, high=103, low=97, close=102),
        Candle("3", open=106, high=112, low=105, close=110),
        Candle("4", open=110, high=114, low=99, close=101),
    ]

    analysis = analyze_fvg("BTC", "15m", candles, mark=101)

    assert analysis.active_count == 0
    assert analysis.bias == "balanced"
    assert analysis.nearest_gap is None
    assert analysis.gaps == []
