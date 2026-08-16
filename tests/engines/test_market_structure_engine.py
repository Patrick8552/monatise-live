from datetime import datetime, timedelta, timezone

from monatise.core.models import Candle
from monatise.engines.market_data.models import (
    DataQuality,
    DataStatus,
    MarketSnapshot,
)
from monatise.engines.market_structure.engine import MarketStructureEngine
from monatise.engines.market_structure.models import (
    BreakType,
    MarketStructureRequest,
    StructureBias,
    StructureState,
)


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def quality() -> DataQuality:
    return DataQuality(
        status=DataStatus.READY,
        source="test",
        observed_at=NOW,
        latest_candle_at=NOW,
        age_seconds=0.0,
    )


def snapshot_from_prices(prices: list[tuple[float, float, float, float]]) -> MarketSnapshot:
    start = datetime(2026, 7, 31, tzinfo=timezone.utc)
    candles = tuple(
        Candle(
            timestamp=(start + timedelta(hours=index)).isoformat(),
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=100 + index,
        )
        for index, (open_price, high, low, close) in enumerate(prices)
    )
    return MarketSnapshot(
        symbol="BTCUSDT",
        interval="1h",
        price=candles[-1].close,
        candles=candles,
        quality=quality(),
    )


def test_bullish_bos_is_detected() -> None:
    prices = [
        (100, 102, 99, 101),
        (101, 104, 100, 103),
        (103, 105, 101, 102),
        (102, 103, 98, 99),
        (99, 101, 97, 100),
        (100, 106, 99, 105),
        (105, 107, 103, 104),
        (104, 105, 100, 101),
        (101, 103, 99, 102),
        (102, 110, 101, 109),
    ]

    result = MarketStructureEngine().assess(
        MarketStructureRequest(
            market=snapshot_from_prices(prices),
            swing_window=1,
            displacement_body_ratio=0.5,
        )
    )

    assert any(
        event.break_type is BreakType.BULLISH_BOS
        for event in result.events
    )
    assert result.bias is StructureBias.BULLISH


def test_bearish_choch_is_detected_after_bullish_structure() -> None:
    prices = [
        (100, 102, 99, 101),
        (101, 104, 100, 103),
        (103, 105, 101, 102),
        (102, 103, 99, 100),
        (100, 106, 99, 105),
        (105, 107, 103, 106),
        (106, 107, 102, 103),
        (103, 104, 100, 101),
        (101, 102, 96, 97),
    ]

    result = MarketStructureEngine().assess(
        MarketStructureRequest(
            market=snapshot_from_prices(prices),
            swing_window=1,
            displacement_body_ratio=0.5,
        )
    )

    assert any(
        event.break_type is BreakType.BEARISH_CHOCH
        for event in result.events
    )
    assert result.state in {
        StructureState.BEARISH_REVERSAL,
        StructureState.TRANSITION,
    }


def test_failed_break_is_identified() -> None:
    prices = [
        (100, 102, 99, 101),
        (101, 104, 100, 103),
        (103, 105, 101, 102),
        (102, 103, 98, 99),
        (99, 101, 97, 100),
        (100, 106, 99, 105),
        (105, 110, 104, 109),
        (109, 110, 101, 102),
    ]

    result = MarketStructureEngine().assess(
        MarketStructureRequest(
            market=snapshot_from_prices(prices),
            swing_window=1,
            displacement_body_ratio=0.5,
            failed_break_window=2,
        )
    )

    assert any(
        event.break_type is BreakType.FAILED_BULLISH_BREAK
        for event in result.events
    )


def test_insufficient_structure_returns_unknown() -> None:
    prices = [
        (100, 101, 99, 100),
        (100, 101, 99, 100),
        (100, 101, 99, 100),
    ]

    result = MarketStructureEngine().assess(
        MarketStructureRequest(
            market=snapshot_from_prices(prices),
            swing_window=1,
        )
    )

    assert result.bias is StructureBias.UNKNOWN
    assert result.state is StructureState.UNKNOWN
    assert result.confidence == 0.0


def test_plateau_swings_tolerates_float_noise_in_equal_highs() -> None:
    # Two highs that are conceptually equal but differ by float-parsing
    # noise (e.g. 100.0 vs 100.00000000001) must still be recognized as an
    # equal-high plateau, not silently missed by strict == comparison.
    def candle(high: float) -> Candle:
        return Candle("2026-08-01T00:00:00+00:00", high - 1, high, high - 2, high - 0.5, 10)

    candles = [candle(95.0), candle(100.0), candle(100.0 + 1e-10), candle(95.0), candle(90.0), candle(90.0)]

    result = MarketStructureEngine._plateau_swings(candles, "high", 1)

    # The plateau spans indices 1-2; the recorded value is the run's first
    # (index 1) high, with the run's last index (2).
    assert result == [(2, 100.0)]
