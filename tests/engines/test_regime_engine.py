from datetime import datetime, timezone

from monatise.core.models import Candle
from monatise.engines.macro.models import (
    MacroAssessment,
    MacroBias,
    MacroRiskState,
)
from monatise.engines.market_data.models import (
    DataQuality,
    DataStatus,
    MarketSnapshot,
)
from monatise.engines.regime.engine import RegimeEngine
from monatise.engines.regime.models import (
    RegimeRequest,
    RegimeState,
)


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def make_snapshot(closes: list[float]) -> MarketSnapshot:
    candles = []
    for index, close in enumerate(closes):
        candles.append(
            Candle(
                timestamp=f"2026-08-01T{index:02d}:00:00+00:00",
                open=close - 0.5,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                volume=100 + index,
            )
        )
    return MarketSnapshot(
        symbol="BTCUSDT",
        interval="1h",
        price=closes[-1],
        candles=tuple(candles),
        quality=DataQuality(
            status=DataStatus.READY,
            source="test",
            observed_at=NOW,
            latest_candle_at=NOW,
            age_seconds=0,
        ),
    )


def test_uptrend_regime() -> None:
    closes = [100 + index * 1.5 for index in range(60)]
    result = RegimeEngine().assess(
        RegimeRequest(market=make_snapshot(closes))
    )
    assert result.state is RegimeState.TREND_UP
    assert result.permits_liquidity_analysis is True


def test_range_regime() -> None:
    closes = [100 + ((index % 4) - 1.5) * 0.4 for index in range(60)]
    result = RegimeEngine().assess(
        RegimeRequest(market=make_snapshot(closes))
    )
    assert result.state in {
        RegimeState.RANGE,
        RegimeState.COMPRESSION,
    }
    assert result.prefers_grid_logic is True


def test_macro_event_lock_forces_unstable() -> None:
    closes = [100 + index * 1.5 for index in range(60)]
    macro = MacroAssessment(
        symbol="BTCUSDT",
        bias=MacroBias.BULLISH,
        risk_state=MacroRiskState.EVENT_LOCK,
        conviction=0.8,
        score=0.7,
        reasons=("US CPI event lock",),
    )
    result = RegimeEngine().assess(
        RegimeRequest(
            market=make_snapshot(closes),
            macro=macro,
        )
    )
    assert result.state is RegimeState.UNSTABLE
    assert result.permits_liquidity_analysis is False


def test_insufficient_candles_returns_unknown() -> None:
    result = RegimeEngine().assess(
        RegimeRequest(
            market=make_snapshot([100, 101, 102]),
        )
    )
    assert result.state is RegimeState.UNKNOWN
    assert result.score == 0.0


def test_exactly_slow_window_candles_still_insufficient_for_baseline() -> None:
    # baseline_returns is drawn from a returns series of length
    # len(candles)-1, so slow_window (default 50) candles yields only
    # slow_window-1 returns -- one short of what slow_window is supposed to
    # guarantee. Requires slow_window+1 candles.
    closes = [100 + index * 1.5 for index in range(50)]
    result = RegimeEngine().assess(RegimeRequest(market=make_snapshot(closes)))
    assert result.state is RegimeState.UNKNOWN

    closes = [100 + index * 1.5 for index in range(51)]
    result = RegimeEngine().assess(RegimeRequest(market=make_snapshot(closes)))
    assert result.state is not RegimeState.UNKNOWN
