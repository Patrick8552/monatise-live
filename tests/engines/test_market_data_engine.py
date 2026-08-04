from datetime import datetime, timezone

from monatise.core.models import Candle
from monatise.engines.market_data.engine import MarketDataEngine
from monatise.engines.market_data.models import DataStatus, MarketDataRequest


NOW = datetime(2026, 8, 1, 3, 0, tzinfo=timezone.utc)


class GoodProvider:
    def latest_price(self, symbol: str) -> float:
        return 100.5

    def candles(self, symbol: str, limit: int, interval: str = "1h") -> list[Candle]:
        return [
            Candle("2026-08-01T02:58:00+00:00", 99, 101, 98, 100, 10),
            Candle("2026-08-01T02:59:00+00:00", 100, 102, 99, 100.5, 12),
        ]


class BrokenProvider:
    def latest_price(self, symbol: str) -> float:
        raise RuntimeError("feed unavailable")

    def candles(self, symbol: str, limit: int, interval: str = "1h") -> list[Candle]:
        return []


class DegradedProvider(GoodProvider):
    def candles(self, symbol: str, limit: int, interval: str = "1h") -> list[Candle]:
        return [Candle("2026-08-01T00:00:00+00:00", 99, 101, 98, 100, 10)]


class CandleOnlyProvider(GoodProvider):
    def latest_price(self, symbol: str) -> float:
        raise RuntimeError("ticker endpoint unavailable")


class DerivativesProvider:
    def derivatives_snapshot(self, symbol: str) -> dict[str, float | None]:
        return {
            "open_interest": 1_000_000,
            "funding_rate": 0.0001,
            "liquidations": None,
        }


def test_ready_snapshot() -> None:
    engine = MarketDataEngine(
        {"primary": GoodProvider()},
        derivatives_provider=DerivativesProvider(),
        clock=lambda: NOW,
    )

    snapshot = engine.collect(
        MarketDataRequest(symbol="BTC", interval="1m", max_age_seconds=120)
    )

    assert snapshot.quality.status is DataStatus.READY
    assert snapshot.price == 100.5
    assert snapshot.quality.source == "primary"
    assert snapshot.derivatives["liquidations"] is None
    assert snapshot.is_trade_analysis_ready is True


def test_falls_back_after_provider_failure() -> None:
    engine = MarketDataEngine(
        {"primary": BrokenProvider(), "fallback": GoodProvider()},
        clock=lambda: NOW,
    )

    snapshot = engine.collect(
        MarketDataRequest(
            symbol="BTC",
            interval="1m",
            max_age_seconds=120,
            preferred_source="primary",
        )
    )

    assert snapshot.quality.status is DataStatus.READY
    assert snapshot.quality.source == "fallback"
    assert snapshot.metadata["fallback_used"] is True
    assert any("provider error" in issue for issue in snapshot.quality.issues)


def test_ready_fallback_is_preferred_over_degraded_primary() -> None:
    engine = MarketDataEngine(
        {"primary": DegradedProvider(), "fallback": GoodProvider()},
        clock=lambda: NOW,
    )

    snapshot = engine.collect(MarketDataRequest("BTC", interval="1m", max_age_seconds=120))

    assert snapshot.quality.status is DataStatus.READY
    assert snapshot.quality.source == "fallback"
    assert snapshot.metadata["fallback_used"] is True


def test_latest_candle_close_recovers_from_ticker_endpoint_failure() -> None:
    engine = MarketDataEngine({"candles": CandleOnlyProvider()}, clock=lambda: NOW)

    snapshot = engine.collect(MarketDataRequest("BTC", interval="1m", max_age_seconds=120))

    assert snapshot.quality.status is DataStatus.READY
    assert snapshot.price == 100.5
    assert any("used latest candle close" in issue for issue in snapshot.quality.issues)


def test_stale_snapshot_is_degraded() -> None:
    engine = MarketDataEngine(
        {"primary": GoodProvider()},
        clock=lambda: datetime(2026, 8, 1, 4, 0, tzinfo=timezone.utc),
    )

    snapshot = engine.collect(
        MarketDataRequest(symbol="BTC", interval="1m", max_age_seconds=120)
    )

    assert snapshot.quality.status is DataStatus.DEGRADED
    assert snapshot.is_trade_analysis_ready is False


def test_no_provider_data_returns_no_data() -> None:
    engine = MarketDataEngine(
        {"primary": BrokenProvider()},
        clock=lambda: NOW,
    )

    snapshot = engine.collect(MarketDataRequest(symbol="BTC"))

    assert snapshot.quality.status is DataStatus.NO_DATA
    assert snapshot.price is None
    assert snapshot.candles == ()
