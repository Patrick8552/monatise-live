import json
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError

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


def test_yahoo_forex_adapter_falls_back_to_second_fixed_host(monkeypatch):
    payload = {
        "chart": {"result": [{
            "timestamp": list(range(1_700_000_000, 1_700_000_000 + 60 * 900, 900)),
            "indicators": {"quote": [{
                key: [1.16 + index / 100_000 for index in range(60)]
                for key in ("open", "high", "low", "close")
            }]},
        }]},
    }

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self): return json.dumps(payload).encode()

    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        if len(calls) == 1:
            raise HTTPError(request.full_url, 429, "rate limited", {}, None)
        return Response()

    monkeypatch.setattr("monatise.adapters.yahoo_forex.urlopen", fake_urlopen)
    result = YahooForexAdapter(timeout=7).candles("EURUSD=X", interval="15m", range_="5d")
    assert len(result) == 60
    assert calls[0][0].startswith(YahooForexAdapter.BASE_URLS[0])
    assert calls[1][0].startswith(YahooForexAdapter.BASE_URLS[1])
    assert calls[1][1] == 7
