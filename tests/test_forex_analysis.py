from datetime import datetime, timedelta, timezone

import pytest

from monatise.adapters.yahoo_forex import YahooForexAdapter, YahooForexError
from monatise.application.forex_analysis import build_forex_analysis


NOW = datetime(2026, 8, 27, 16, 0, tzinfo=timezone.utc)


def bars(count: int = 80, *, minutes: int = 15, price: float = 1.165) -> list[dict[str, object]]:
    start = NOW - timedelta(minutes=minutes * (count - 1))
    return [
        {
            "t": (start + timedelta(minutes=minutes * index)).isoformat(),
            "o": price, "h": price + 0.0002, "l": price - 0.0002, "c": price,
        }
        for index in range(count)
    ]


def test_sufficient_but_unaligned_forex_data_is_suppressed_not_incomplete():
    result = build_forex_analysis(
        "EURUSD=X", bars(minutes=60), bars(), now=NOW,
    )
    assert result["decision"] == "NO_TRADE"
    assert result["setup_status"] == "suppressed"
    assert result["analysis_provider"] == "yahoo_finance"
    assert result["execution"] == {"enabled": False, "orders_placed": 0}
    assert result["market_observed_at"] == NOW.isoformat()


@pytest.mark.parametrize("symbol,interval", [("BTC-USD", "15m"), ("EURUSD=X", "5m")])
def test_yahoo_forex_adapter_rejects_non_fx_or_unsupported_intervals(symbol, interval):
    with pytest.raises(YahooForexError, match="unsupported"):
        YahooForexAdapter().candles(symbol, interval=interval, range_="5d")
