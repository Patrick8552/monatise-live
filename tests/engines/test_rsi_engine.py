from datetime import datetime, timedelta, timezone

from monatise.core.models import Candle
from monatise.engines.market_data.models import (
    DataQuality,
    DataStatus,
    MarketSnapshot,
)
from monatise.engines.rsi.engine import RSIEngine
from monatise.engines.rsi.models import (
    RSIBias,
    RSICondition,
    RSIRequest,
)


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def snapshot(closes: list[float]) -> MarketSnapshot:
    start = datetime(2026, 7, 30, tzinfo=timezone.utc)
    candles = tuple(
        Candle(
            timestamp=(start + timedelta(hours=index)).isoformat(),
            open=close - 0.4,
            high=close + 1.0,
            low=close - 1.0,
            close=close,
            volume=100 + index,
        )
        for index, close in enumerate(closes)
    )
    return MarketSnapshot(
        symbol="BTCUSDT",
        interval="1h",
        price=closes[-1],
        candles=candles,
        quality=DataQuality(
            status=DataStatus.READY,
            source="test",
            observed_at=NOW,
            latest_candle_at=NOW,
            age_seconds=0,
        ),
    )


def test_rising_market_produces_bullish_rsi() -> None:
    closes = [100 + index * 0.8 for index in range(50)]
    result = RSIEngine().assess(
        RSIRequest(market=snapshot(closes))
    )

    assert result.current_rsi is not None
    assert result.bias in {RSIBias.BULLISH, RSIBias.CONFLICTED}
    assert result.condition in {
        RSICondition.BULLISH_MOMENTUM,
        RSICondition.OVERBOUGHT,
    }


def test_falling_market_produces_bearish_rsi() -> None:
    closes = [150 - index * 0.8 for index in range(50)]
    result = RSIEngine().assess(
        RSIRequest(market=snapshot(closes))
    )

    assert result.current_rsi is not None
    assert result.bias in {RSIBias.BEARISH, RSIBias.CONFLICTED}
    assert result.condition in {
        RSICondition.BEARISH_MOMENTUM,
        RSICondition.OVERSOLD,
    }


def test_overbought_is_not_trade_instruction() -> None:
    closes = [100 + index for index in range(50)]
    result = RSIEngine().assess(
        RSIRequest(market=snapshot(closes))
    )

    assert result.condition is RSICondition.OVERBOUGHT
    assert any(
        "not a standalone short signal" in reason
        for reason in result.reasons
    )
    assert not hasattr(result, "entry")
    assert not hasattr(result, "stop_loss")
    assert not hasattr(result, "order")


def test_insufficient_history_returns_unavailable() -> None:
    result = RSIEngine().assess(
        RSIRequest(
            market=snapshot([100, 101, 102]),
            divergence_lookback=20,
        )
    )

    assert result.condition is RSICondition.UNAVAILABLE
    assert result.usable is False


def test_flat_market_returns_neutral_rsi() -> None:
    result = RSIEngine().assess(
        RSIRequest(
            market=snapshot([100.0] * 50),
        )
    )

    assert result.current_rsi == 50.0
    assert result.condition is RSICondition.NEUTRAL
    assert result.bias is RSIBias.NEUTRAL
