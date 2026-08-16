from dataclasses import replace
from datetime import datetime, timedelta, timezone

from monatise.core.models import Candle
from monatise.engines.fibonacci_liquidity.engine import FibonacciLiquidityEngine
from monatise.engines.fibonacci_liquidity.models import (
    AnchorQuality,
    FibonacciDirection,
    FibonacciLevelType,
    FibonacciRequest,
    FibonacciZoneType,
)
from monatise.engines.market_data.models import (
    DataQuality,
    DataStatus,
    MarketSnapshot,
)
from monatise.engines.market_structure.models import (
    MarketStructureAssessment,
    StructureBias,
    StructureState,
)


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def make_market(price: float = 118.0) -> MarketSnapshot:
    start = datetime(2026, 7, 29, tzinfo=timezone.utc)
    candles = []
    for index in range(40):
        base = 100 + index * 0.5
        candles.append(
            Candle(
                timestamp=(start + timedelta(hours=index)).isoformat(),
                open=base,
                high=base + 1.2,
                low=base - 1.0,
                close=base + 0.5,
                volume=100 + index,
            )
        )
    return MarketSnapshot(
        symbol="BTCUSDT",
        interval="1h",
        price=price,
        candles=tuple(candles),
        quality=DataQuality(
            status=DataStatus.READY,
            source="test",
            observed_at=NOW,
            latest_candle_at=NOW,
            age_seconds=0,
        ),
    )


def bullish_structure() -> MarketStructureAssessment:
    return MarketStructureAssessment(
        symbol="BTCUSDT",
        bias=StructureBias.BULLISH,
        state=StructureState.BULLISH_CONTINUATION,
        events=(),
        latest_event=None,
        swing_highs=((10, 110.0), (30, 122.0)),
        swing_lows=((5, 98.0), (20, 105.0)),
        confidence=0.85,
        reasons=(),
    )


def test_selects_scored_primary_anchor() -> None:
    result = FibonacciLiquidityEngine().assess(
        FibonacciRequest(
            market=make_market(),
            structure=bullish_structure(),
            minimum_anchor_range_atr=1.0,
        )
    )

    assert result.direction is FibonacciDirection.BULLISH
    assert result.has_valid_anchor is True
    assert result.primary_anchor is not None
    assert result.primary_anchor.quality in {
        AnchorQuality.HIGH,
        AnchorQuality.MEDIUM,
        AnchorQuality.LOW,
    }


def test_maps_extended_retracement_set() -> None:
    result = FibonacciLiquidityEngine().assess(
        FibonacciRequest(
            market=make_market(),
            structure=bullish_structure(),
            minimum_anchor_range_atr=1.0,
        )
    )

    ratios = {level.ratio for level in result.retracement_levels}
    assert {0.382, 0.5, 0.618, 0.705, 0.786, 0.886}.issubset(ratios)


def test_builds_ote_and_deep_retracement_zones() -> None:
    result = FibonacciLiquidityEngine().assess(
        FibonacciRequest(
            market=make_market(),
            structure=bullish_structure(),
            minimum_anchor_range_atr=1.0,
        )
    )

    zone_types = {zone.zone_type for zone in result.zones}
    assert FibonacciZoneType.OTE in zone_types
    assert FibonacciZoneType.DEEP_RETRACEMENT in zone_types


def test_exposes_invalidation_level() -> None:
    result = FibonacciLiquidityEngine().assess(
        FibonacciRequest(
            market=make_market(),
            structure=bullish_structure(),
            minimum_anchor_range_atr=1.0,
        )
    )

    assert result.invalidation_level is not None
    assert result.invalidation_level.level_type is FibonacciLevelType.INVALIDATION
    assert result.invalidation_level.price < result.primary_anchor.start_price


def test_rejects_low_structure_confidence() -> None:
    structure = MarketStructureAssessment(
        symbol="BTCUSDT",
        bias=StructureBias.BULLISH,
        state=StructureState.BULLISH_CONTINUATION,
        events=(),
        latest_event=None,
        swing_highs=((10, 110.0), (30, 122.0)),
        swing_lows=((5, 98.0), (20, 105.0)),
        confidence=0.2,
        reasons=(),
    )

    result = FibonacciLiquidityEngine().assess(
        FibonacciRequest(
            market=make_market(),
            structure=structure,
            minimum_structure_confidence=0.45,
        )
    )

    assert result.has_valid_anchor is False
    assert result.direction is FibonacciDirection.UNKNOWN


def test_rejects_insufficient_candles_instead_of_using_a_noisy_atr() -> None:
    # _atr(candles, 14) needs 15 candles for a full window; fewer than that
    # must fail closed rather than silently compute ATR from a shorter,
    # statistically meaningless sample.
    market = make_market()
    market = replace(market, candles=market.candles[:5])

    result = FibonacciLiquidityEngine().assess(
        FibonacciRequest(
            market=market,
            structure=bullish_structure(),
        )
    )

    assert result.has_valid_anchor is False
    assert result.direction is FibonacciDirection.UNKNOWN
    assert any("insufficient candles" in reason for reason in result.reasons)


def test_engine_remains_non_executable() -> None:
    result = FibonacciLiquidityEngine().assess(
        FibonacciRequest(
            market=make_market(),
            structure=bullish_structure(),
            minimum_anchor_range_atr=1.0,
        )
    )

    assert not hasattr(result, "entry")
    assert not hasattr(result, "stop_loss")
    assert not hasattr(result, "target")
    assert not hasattr(result, "order")
