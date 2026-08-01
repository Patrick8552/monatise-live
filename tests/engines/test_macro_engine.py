from datetime import datetime, timedelta, timezone

from monatise.engines.macro.engine import MacroEngine
from monatise.engines.macro.models import (
    MacroBias,
    MacroEvent,
    MacroEventImpact,
    MacroRequest,
    MacroRiskState,
)


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


class Provider:
    def __init__(self, factors=None, events=None):
        self._factors = factors or {}
        self._events = events or []

    def context_snapshot(self, symbol: str):
        return self._factors

    def economic_events(self):
        return self._events


def test_crypto_bullish_macro_environment() -> None:
    engine = MacroEngine(
        Provider(
            factors={
                "dxy_change_pct": -0.6,
                "us10y_change_bps": -0.4,
                "real_yield_change_bps": -0.5,
                "vix_change_pct": -0.3,
                "nasdaq_change_pct": 0.6,
                "usd_liquidity_score": 0.7,
                "risk_sentiment_score": 0.7,
                "stablecoin_market_cap_change_pct": 0.4,
                "btc_etf_flow_score": 0.8,
                "total_crypto_market_cap_change_pct": 0.6,
            }
        )
    )

    result = engine.assess(
        MacroRequest(symbol="BTCUSDT", observed_at=NOW)
    )

    assert result.bias is MacroBias.BULLISH
    assert result.risk_state is MacroRiskState.NORMAL
    assert result.conviction > 0


def test_non_crypto_symbol_is_rejected() -> None:
    engine = MacroEngine(Provider(factors={"dxy_change_pct": -0.5}))

    result = engine.assess(
        MacroRequest(symbol="EURUSD", observed_at=NOW)
    )

    assert result.bias is MacroBias.UNKNOWN
    assert result.risk_state is MacroRiskState.DATA_UNAVAILABLE
    assert result.blocks_new_analysis is True
    assert "crypto assets only" in result.reasons[0]


def test_crypto_usd_pair_is_supported() -> None:
    engine = MacroEngine(Provider(factors={"dxy_change_pct": -0.5}))

    result = engine.assess(MacroRequest(symbol="BTCUSD", observed_at=NOW))

    assert result.risk_state is MacroRiskState.NORMAL
    assert result.metadata["engine_scope"] == "crypto_only"


def test_high_impact_us_event_locks_crypto_analysis() -> None:
    event = MacroEvent(
        name="US CPI",
        scheduled_at=NOW + timedelta(minutes=10),
        impact=MacroEventImpact.CRITICAL,
        currency="USD",
    )
    engine = MacroEngine(
        Provider(
            factors={"dxy_change_pct": -0.2},
            events=[event],
        )
    )

    result = engine.assess(
        MacroRequest(
            symbol="ETHUSDT",
            observed_at=NOW,
            event_lock_before_minutes=30,
            event_lock_after_minutes=60,
        )
    )

    assert result.risk_state is MacroRiskState.EVENT_LOCK
    assert result.blocks_new_analysis is True
    assert len(result.active_events) == 1


def test_missing_data_is_unknown_not_neutral() -> None:
    engine = MacroEngine(Provider(factors={}))

    result = engine.assess(
        MacroRequest(symbol="SOLUSDT", observed_at=NOW)
    )

    assert result.bias is MacroBias.UNKNOWN
    assert result.risk_state is MacroRiskState.ELEVATED
    assert result.conviction == 0.0


def test_btc_dominance_context_is_symbol_aware() -> None:
    engine = MacroEngine(
        Provider(
            factors={
                "btc_dominance_change_pct": 0.8,
                "total_crypto_market_cap_change_pct": 0.2,
            }
        )
    )

    result = engine.assess(
        MacroRequest(symbol="SOLUSDT", observed_at=NOW)
    )

    assert any("pressure altcoin" in reason for reason in result.reasons)
