from datetime import datetime, timezone

from monatise.core.models import Candle
from monatise.engines.liquidity.models import (
    LiquidityLevel,
    LiquidityLevelType,
    LiquiditySide,
    LiquidityStrength,
)
from monatise.engines.liquidity_sweep.models import (
    SweepAssessment,
    SweepDirection,
    SweepEvent,
    SweepStatus,
)
from monatise.engines.market_data.models import (
    DataQuality,
    DataStatus,
    MarketSnapshot,
)
from monatise.engines.reclaim.engine import ReclaimEngine
from monatise.engines.reclaim.models import (
    ReclaimDirection,
    ReclaimRequest,
    ReclaimStatus,
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


def sell_side_level() -> LiquidityLevel:
    return LiquidityLevel(
        price=100.0,
        side=LiquiditySide.SELL_SIDE,
        level_type=LiquidityLevelType.EQUAL_LOWS,
        strength=LiquidityStrength.HIGH,
        touches=3,
        distance_pct=0.01,
        first_index=1,
        last_index=3,
    )


def buy_side_level() -> LiquidityLevel:
    return LiquidityLevel(
        price=110.0,
        side=LiquiditySide.BUY_SIDE,
        level_type=LiquidityLevelType.EQUAL_HIGHS,
        strength=LiquidityStrength.HIGH,
        touches=3,
        distance_pct=0.01,
        first_index=1,
        last_index=3,
    )


def test_confirmed_bullish_reclaim_after_sell_side_sweep() -> None:
    candles = (
        Candle("2026-08-01T09:00:00+00:00", 101, 102, 100, 101, 10),
        Candle("2026-08-01T10:00:00+00:00", 100, 101, 96, 99, 12),
        Candle("2026-08-01T11:00:00+00:00", 99, 103, 98.5, 102, 14),
        Candle("2026-08-01T12:00:00+00:00", 102, 105, 101, 104, 15),
    )
    market = MarketSnapshot(
        symbol="BTCUSDT",
        interval="1h",
        price=104,
        candles=candles,
        quality=quality(),
    )
    level = sell_side_level()
    sweep_event = SweepEvent(
        level=level,
        direction=SweepDirection.SELL_SIDE_TAKEN,
        status=SweepStatus.CONFIRMED,
        candle_index=1,
        breach_price=96,
        close_price=99,
        breach_pct=0.04,
        wick_ratio=0.6,
        close_back_inside=True,
        reasons=("confirmed",),
    )
    sweep = SweepAssessment(
        symbol="BTCUSDT",
        events=(sweep_event,),
        strongest_event=sweep_event,
        reasons=(),
    )

    result = ReclaimEngine().assess(
        ReclaimRequest(
            market=market,
            sweep=sweep,
            minimum_body_ratio=0.4,
        )
    )

    assert result.has_confirmed_reclaim is True
    assert result.strongest_event is not None
    assert result.strongest_event.direction is ReclaimDirection.BULLISH_RECLAIM


def test_confirmed_bearish_reclaim_after_buy_side_sweep() -> None:
    candles = (
        Candle("2026-08-01T09:00:00+00:00", 108, 109, 107, 108, 10),
        Candle("2026-08-01T10:00:00+00:00", 109, 114, 108, 111, 12),
        Candle("2026-08-01T11:00:00+00:00", 111, 111.5, 106, 107, 14),
        Candle("2026-08-01T12:00:00+00:00", 107, 108, 103, 104, 15),
    )
    market = MarketSnapshot(
        symbol="ETHUSDT",
        interval="1h",
        price=104,
        candles=candles,
        quality=quality(),
    )
    level = buy_side_level()
    sweep_event = SweepEvent(
        level=level,
        direction=SweepDirection.BUY_SIDE_TAKEN,
        status=SweepStatus.CONFIRMED,
        candle_index=1,
        breach_price=114,
        close_price=111,
        breach_pct=0.036,
        wick_ratio=0.5,
        close_back_inside=True,
        reasons=("confirmed",),
    )
    sweep = SweepAssessment(
        symbol="ETHUSDT",
        events=(sweep_event,),
        strongest_event=sweep_event,
        reasons=(),
    )

    result = ReclaimEngine().assess(
        ReclaimRequest(
            market=market,
            sweep=sweep,
            minimum_body_ratio=0.4,
        )
    )

    assert result.has_confirmed_reclaim is True
    assert result.strongest_event is not None
    assert result.strongest_event.direction is ReclaimDirection.BEARISH_RECLAIM


def test_failed_reclaim_when_price_never_regains_level() -> None:
    candles = (
        Candle("2026-08-01T10:00:00+00:00", 100, 101, 96, 98, 12),
        Candle("2026-08-01T11:00:00+00:00", 98, 99, 95, 96, 14),
        Candle("2026-08-01T12:00:00+00:00", 96, 98, 94, 95, 15),
    )
    market = MarketSnapshot(
        symbol="SOLUSDT",
        interval="1h",
        price=95,
        candles=candles,
        quality=quality(),
    )
    level = sell_side_level()
    sweep_event = SweepEvent(
        level=level,
        direction=SweepDirection.SELL_SIDE_TAKEN,
        status=SweepStatus.CONFIRMED,
        candle_index=0,
        breach_price=96,
        close_price=98,
        breach_pct=0.04,
        wick_ratio=0.5,
        close_back_inside=True,
        reasons=("confirmed",),
    )
    sweep = SweepAssessment(
        symbol="SOLUSDT",
        events=(sweep_event,),
        strongest_event=sweep_event,
        reasons=(),
    )

    result = ReclaimEngine().assess(
        ReclaimRequest(market=market, sweep=sweep)
    )

    assert result.has_failed_reclaim is True
    assert result.strongest_event is not None
    assert result.strongest_event.status is ReclaimStatus.FAILED


def test_no_sweep_events_returns_empty_assessment() -> None:
    market = MarketSnapshot(
        symbol="BTCUSDT",
        interval="1h",
        price=100,
        candles=(
            Candle("2026-08-01T10:00:00+00:00", 99, 101, 98, 100, 10),
        ),
        quality=quality(),
    )
    sweep = SweepAssessment(
        symbol="BTCUSDT",
        events=(),
        strongest_event=None,
        reasons=(),
    )

    result = ReclaimEngine().assess(
        ReclaimRequest(market=market, sweep=sweep)
    )

    assert result.events == ()
    assert result.strongest_event is None
