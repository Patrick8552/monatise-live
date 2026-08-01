from datetime import datetime, timedelta, timezone

from monatise.core.models import Candle
from monatise.engines.market_data.models import (
    DataQuality,
    DataStatus,
    MarketSnapshot,
)
from monatise.engines.supply_demand.engine import SupplyDemandEngine
from monatise.engines.supply_demand.models import (
    ZoneFreshness,
    ZoneRequest,
    ZoneType,
)


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def make_candles() -> tuple[Candle, ...]:
    candles: list[Candle] = []
    start = datetime(2026, 7, 29, tzinfo=timezone.utc)

    price = 100.0
    for index in range(25):
        # Normal candles before the first base.
        if index < 6:
            open_price = price
            close = price - 0.8
            high = max(open_price, close) + 0.4
            low = min(open_price, close) - 0.4

        # Demand base.
        elif index in {6, 7}:
            open_price = 95.0 + (index - 6) * 0.1
            close = 95.1 - (index - 6) * 0.05
            high = 95.5
            low = 94.5

        # Strong rally departure.
        elif index in {8, 9, 10}:
            open_price = 95.2 + (index - 8) * 2.1
            close = open_price + 2.0
            high = close + 0.5
            low = open_price - 0.3

        # Later supply base.
        elif index in {14, 15}:
            open_price = 108.0 + (index - 14) * 0.1
            close = 108.1 - (index - 14) * 0.05
            high = 108.5
            low = 107.5

        # Strong drop departure.
        elif index in {16, 17, 18}:
            open_price = 107.8 - (index - 16) * 2.1
            close = open_price - 2.0
            high = open_price + 0.3
            low = close - 0.5

        else:
            open_price = 101.0 + ((index % 3) - 1) * 0.3
            close = open_price + 0.1
            high = open_price + 0.6
            low = open_price - 0.6

        price = close
        candles.append(
            Candle(
                timestamp=(start + timedelta(hours=index)).isoformat(),
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=100 + index,
            )
        )

    return tuple(candles)


def make_snapshot() -> MarketSnapshot:
    candles = make_candles()
    return MarketSnapshot(
        symbol="BTCUSDT",
        interval="1h",
        price=101.0,
        candles=candles,
        quality=DataQuality(
            status=DataStatus.READY,
            source="test",
            observed_at=NOW,
            latest_candle_at=NOW,
            age_seconds=0.0,
        ),
    )


def test_maps_demand_and_supply_zones() -> None:
    result = SupplyDemandEngine().assess(
        ZoneRequest(
            market=make_snapshot(),
            minimum_impulse_atr=1.0,
        )
    )

    assert result.has_valid_zones is True
    assert any(
        zone.zone_type is ZoneType.DEMAND
        for zone in result.demand_zones
    )
    assert any(
        zone.zone_type is ZoneType.SUPPLY
        for zone in result.supply_zones
    )


def test_invalidated_zones_are_removed() -> None:
    snapshot = make_snapshot()
    candles = list(snapshot.candles)
    candles.append(
        Candle(
            timestamp="2026-08-01T13:00:00+00:00",
            open=95.0,
            high=95.2,
            low=90.0,
            close=90.5,
            volume=200,
        )
    )

    modified = MarketSnapshot(
        symbol=snapshot.symbol,
        interval=snapshot.interval,
        price=90.5,
        candles=tuple(candles),
        quality=snapshot.quality,
    )

    result = SupplyDemandEngine().assess(
        ZoneRequest(
            market=modified,
            minimum_impulse_atr=1.0,
        )
    )

    assert all(
        zone.freshness is not ZoneFreshness.INVALIDATED
        for zone in result.demand_zones
    )


def test_zone_output_does_not_create_trade_signal() -> None:
    result = SupplyDemandEngine().assess(
        ZoneRequest(
            market=make_snapshot(),
            minimum_impulse_atr=1.0,
        )
    )

    assert not hasattr(result, "entry")
    assert not hasattr(result, "stop_loss")
    assert not hasattr(result, "target")
    assert not hasattr(result, "order")
