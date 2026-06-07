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
