from datetime import datetime, timezone

from monatise.core.models import Candle
from monatise.engines.liquidity.engine import LiquidityEngine
from monatise.engines.liquidity.models import (
    LiquidityLevelType,
    LiquidityRequest,
    LiquiditySide,
)
from monatise.engines.market_data.models import (
    DataQuality,
    DataStatus,
    MarketSnapshot,
)


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def make_snapshot() -> MarketSnapshot:
    candles = []
    for index in range(60):
        base = 100 + ((index % 10) - 5) * 0.4
        high = base + 1.0
        low = base - 1.0

        if index in {10, 20, 30, 40}:
            high = 105.0
        if index in {15, 25, 35, 45}:
            low = 95.0

        candles.append(
            Candle(
                timestamp=f"2026-08-01T{index:02d}:00:00+00:00",
                open=base,
                high=high,
                low=low,
                close=base + 0.1,
                volume=100 + index,
            )
        )

    return MarketSnapshot(
        symbol="BTCUSDT",
        interval="1h",
        price=100.0,
        candles=tuple(candles),
        quality=DataQuality(
            status=DataStatus.READY,
            source="test",
            observed_at=NOW,
            latest_candle_at=NOW,
            age_seconds=0.0,
        ),
    )


def test_maps_two_sided_liquidity() -> None:
    result = LiquidityEngine().assess(
        LiquidityRequest(market=make_snapshot())
    )

    assert result.has_mapped_liquidity is True
    assert result.balanced is True
    assert result.nearest_buy_side is not None
    assert result.nearest_sell_side is not None
    assert result.nearest_buy_side.side is LiquiditySide.BUY_SIDE
    assert result.nearest_sell_side.side is LiquiditySide.SELL_SIDE


def test_detects_equal_highs_and_lows() -> None:
    result = LiquidityEngine().assess(
        LiquidityRequest(market=make_snapshot())
    )

    buy_types = {level.level_type for level in result.buy_side_levels}
    sell_types = {level.level_type for level in result.sell_side_levels}

    assert LiquidityLevelType.EQUAL_HIGHS in buy_types or LiquidityLevelType.CLUSTER_HIGH in buy_types
    assert LiquidityLevelType.EQUAL_LOWS in sell_types or LiquidityLevelType.CLUSTER_LOW in sell_types


def test_levels_are_correctly_positioned_around_price() -> None:
    result = LiquidityEngine().assess(
        LiquidityRequest(market=make_snapshot())
    )

    assert all(level.price > result.current_price for level in result.buy_side_levels)
    assert all(level.price < result.current_price for level in result.sell_side_levels)


def test_insufficient_history_raises() -> None:
    snapshot = make_snapshot()
    short_snapshot = MarketSnapshot(
        symbol=snapshot.symbol,
        interval=snapshot.interval,
        price=snapshot.price,
        candles=snapshot.candles[:10],
        quality=snapshot.quality,
    )

    try:
        LiquidityEngine().assess(
            LiquidityRequest(market=short_snapshot)
        )
    except ValueError as exc:
        assert "insufficient candles" in str(exc)
    else:
        raise AssertionError("expected insufficient candle error")
