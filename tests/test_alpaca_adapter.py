import json
from urllib.parse import parse_qs, urlparse

import pytest

import monatise.adapters.alpaca as alpaca_module
from monatise.adapters.alpaca import AlpacaMarketDataAdapter, AlpacaAdapterError


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


def test_alpaca_bars_use_market_data_auth_and_iex(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout=12):
        requests.append(request)
        return Response(
            {"bars": [{"h": 12, "l": 10, "c": 11}, {"h": 11, "l": 9, "c": 10}]}
        )

    monkeypatch.setattr(alpaca_module, "urlopen", fake_urlopen)
    rows = AlpacaMarketDataAdapter("key", "secret").stock_bars("NVDA")
    assert rows[0]["c"] == 10
    assert "feed=iex" in requests[0].full_url
    assert "sort=desc" in requests[0].full_url
    assert requests[0].headers["Apca-api-key-id"] == "key"
    assert requests[0].headers["Apca-api-secret-key"] == "secret"


def test_calendar_range_uses_provider_holidays_and_early_closes(monkeypatch):
    requests = []
    rows = [{"date": "2026-11-27", "open": "09:30", "close": "13:00"}]

    def get(request, timeout):
        requests.append(request)
        return Response(rows)

    monkeypatch.setattr(alpaca_module, "urlopen", get)
    adapter = AlpacaMarketDataAdapter("key", "secret")
    assert adapter.market_calendar("2026-11-25", "2026-11-30") == rows
    assert parse_qs(urlparse(requests[-1].full_url).query) == {
        "start": ["2026-11-25"],
        "end": ["2026-11-30"],
    }
    adapter.market_calendar("2026-11-27")
    assert parse_qs(urlparse(requests[-1].full_url).query)["end"] == ["2026-11-27"]


def test_calendar_does_not_silently_drop_malformed_sessions(monkeypatch):
    monkeypatch.setattr(
        alpaca_module, "urlopen", lambda *args, **kwargs: Response([None])
    )
    with pytest.raises(AlpacaAdapterError, match="invalid row"):
        AlpacaMarketDataAdapter("key", "secret").market_calendar("2026-09-15")
