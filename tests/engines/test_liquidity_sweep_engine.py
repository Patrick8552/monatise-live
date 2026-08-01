from datetime import datetime, timezone

from monatise.core.models import Candle
from monatise.engines.liquidity.models import (
    LiquidityAssessment,
    LiquidityLevel,
    LiquidityLevelType,
    LiquiditySide,
    LiquidityStrength,
)
from monatise.engines.liquidity_sweep.engine import LiquiditySweepEngine
from monatise.engines.liquidity_sweep.models import (
    SweepDirection,
    SweepRequest,
    SweepStatus,
)
from monatise.engines.market_data.models import (
    DataQuality,
    DataStatus,
    MarketSnapshot,
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


def level(price: float, side: LiquiditySide) -> LiquidityLevel:
    return LiquidityLevel(
        price=price,
        side=side,
        level_type=(
            LiquidityLevelType.EQUAL_HIGHS
            if side is LiquiditySide.BUY_SIDE
            else LiquidityLevelType.EQUAL_LOWS
        ),
        strength=LiquidityStrength.HIGH,
        touches=3,
        distance_pct=0.01,
        first_index=1,
        last_index=5,
    )


def test_confirmed_buy_side_sweep() -> None:
    candles = (
        Candle("2026-08-01T10:00:00+00:00", 99, 100, 98, 99.5, 10),
        Candle("2026-08-01T11:00:00+00:00", 100, 105, 99, 100.2, 12),
    )
    market = MarketSnapshot(
        symbol="BTCUSDT",
        interval="1h",
        price=100.2,
        candles=candles,
        quality=quality(),
    )
    liquidity = LiquidityAssessment(
        symbol="BTCUSDT",
        current_price=100.2,
        buy_side_levels=(level(103, LiquiditySide.BUY_SIDE),),
        sell_side_levels=(),
        nearest_buy_side=level(103, LiquiditySide.BUY_SIDE),
        nearest_sell_side=None,
        reasons=(),
    )

    result = LiquiditySweepEngine().assess(
        SweepRequest(
            market=market,
            liquidity=liquidity,
            minimum_wick_ratio=0.35,
        )
    )

    assert result.has_confirmed_sweep is True
    assert result.strongest_event is not None
    assert result.strongest_event.direction is SweepDirection.BUY_SIDE_TAKEN
    assert result.strongest_event.status is SweepStatus.CONFIRMED


def test_confirmed_sell_side_sweep() -> None:
    candles = (
        Candle("2026-08-01T10:00:00+00:00", 101, 102, 100, 100.5, 10),
        Candle("2026-08-01T11:00:00+00:00", 100, 101, 95, 99.8, 12),
    )
    market = MarketSnapshot(
        symbol="ETHUSDT",
        interval="1h",
        price=99.8,
        candles=candles,
        quality=quality(),
    )
    sell_level = level(97, LiquiditySide.SELL_SIDE)
    liquidity = LiquidityAssessment(
        symbol="ETHUSDT",
        current_price=99.8,
        buy_side_levels=(),
        sell_side_levels=(sell_level,),
        nearest_buy_side=None,
        nearest_sell_side=sell_level,
        reasons=(),
    )

    result = LiquiditySweepEngine().assess(
        SweepRequest(
            market=market,
            liquidity=liquidity,
            minimum_wick_ratio=0.35,
        )
    )

    assert result.has_confirmed_sweep is True
    assert result.strongest_event is not None
    assert result.strongest_event.direction is SweepDirection.SELL_SIDE_TAKEN


def test_breach_without_rejection_is_invalid_or_possible() -> None:
    candles = (
        Candle("2026-08-01T11:00:00+00:00", 102, 106, 101, 105.5, 12),
    )
    market = MarketSnapshot(
        symbol="SOLUSDT",
        interval="1h",
        price=105.5,
        candles=candles,
        quality=quality(),
    )
    buy_level = level(103, LiquiditySide.BUY_SIDE)
    liquidity = LiquidityAssessment(
        symbol="SOLUSDT",
        current_price=105.5,
        buy_side_levels=(buy_level,),
        sell_side_levels=(),
        nearest_buy_side=buy_level,
        nearest_sell_side=None,
        reasons=(),
    )

    result = LiquiditySweepEngine().assess(
        SweepRequest(
            market=market,
            liquidity=liquidity,
            minimum_wick_ratio=0.35,
        )
    )

    assert result.strongest_event is not None
    assert result.strongest_event.status in {
        SweepStatus.POSSIBLE,
        SweepStatus.INVALID,
    }


def test_no_breach_returns_no_events() -> None:
    candles = (
        Candle("2026-08-01T11:00:00+00:00", 100, 101, 99, 100.5, 12),
    )
    market = MarketSnapshot(
        symbol="BTCUSDT",
        interval="1h",
        price=100.5,
        candles=candles,
        quality=quality(),
    )
    buy_level = level(110, LiquiditySide.BUY_SIDE)
    liquidity = LiquidityAssessment(
        symbol="BTCUSDT",
        current_price=100.5,
        buy_side_levels=(buy_level,),
        sell_side_levels=(),
        nearest_buy_side=buy_level,
        nearest_sell_side=None,
        reasons=(),
    )

    result = LiquiditySweepEngine().assess(
        SweepRequest(market=market, liquidity=liquidity)
    )

    assert result.events == ()
    assert result.strongest_event is None
