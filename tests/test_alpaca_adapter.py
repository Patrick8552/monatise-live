import json

import monatise.adapters.alpaca as alpaca_module
from monatise.adapters.alpaca import AlpacaMarketDataAdapter


class Response:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self): return json.dumps(self.payload).encode()


def test_alpaca_bars_use_market_data_auth_and_iex(monkeypatch):
    requests = []
    def fake_urlopen(request, timeout=12):
        requests.append(request)
        return Response({"bars": [{"h": 11, "l": 9, "c": 10}]})
    monkeypatch.setattr(alpaca_module, "urlopen", fake_urlopen)
    rows = AlpacaMarketDataAdapter("key", "secret").stock_bars("NVDA")
    assert rows[0]["c"] == 10
    assert "feed=iex" in requests[0].full_url
    assert requests[0].headers["Apca-api-key-id"] == "key"
    assert requests[0].headers["Apca-api-secret-key"] == "secret"
