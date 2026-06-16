import os

import monatise.adapters.coinglass as coinglass_module
from monatise.adapters.coinglass import CoinGlassAdapter, CoinGlassPlanError
from monatise.live.config import RuntimeConfig


class FakeResponse:
    def __init__(self, payload: str) -> None:
        self.payload = payload.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:  # noqa: ANN002
        return None

    def read(self) -> bytes:
        return self.payload


def test_coinglass_candles_use_price_history_endpoint(monkeypatch) -> None:  # noqa: ANN001
    captured = {}
    old_key = os.environ.get("COINGLASS_API_KEY")
    os.environ["COINGLASS_API_KEY"] = "test-key"

    def fake_urlopen(request, timeout=0):  # noqa: ANN001, ANN202
        captured["url"] = request.full_url
        captured["headers"] = request.headers
        captured["timeout"] = timeout
        return FakeResponse(
            """
            {
              "code": "0",
              "data": [
                {"time": 1, "open": "100", "high": "105", "low": "99", "close": "104", "volume_usd": "12"},
                {"time": 2, "open": "104", "high": "108", "low": "103", "close": "107", "volume_usd": "8"}
              ]
            }
            """
        )

    monkeypatch.setattr(coinglass_module, "urlopen", fake_urlopen)
    try:
        candles = CoinGlassAdapter(RuntimeConfig()).candles("BTC", 2, "1h")
    finally:
        _restore_env("COINGLASS_API_KEY", old_key)

    assert len(candles) == 2
    assert candles[-1].close == 107
    assert "/api/futures/price/history" in captured["url"]
    assert "symbol=BTCUSDT" in captured["url"]
    assert captured["headers"]["Cg-api-key"] == "test-key"


def test_coinglass_routes_forex_symbol_to_supported_instrument(monkeypatch) -> None:  # noqa: ANN001
    captured = {}
    old_key = os.environ.get("COINGLASS_API_KEY")
    os.environ["COINGLASS_API_KEY"] = "test-key"

    def fake_exchange_pairs(self):  # noqa: ANN001, ANN202
        return {
            "Binance": [{"instrument_id": "BTCUSDT", "base_asset": "BTC", "quote_asset": "USDT"}],
            "Gate": [{"instrument_id": "EURUSD_USDT", "base_asset": "EURUSD", "quote_asset": "USDT"}],
        }

    def fake_urlopen(request, timeout=0):  # noqa: ANN001, ANN202
        captured["url"] = request.full_url
        return FakeResponse(
            """
            {
              "code": "0",
              "data": [
                {"time": 1, "open": "1.10", "high": "1.12", "low": "1.09", "close": "1.11", "volume_usd": "12"}
              ]
            }
            """
        )

    monkeypatch.setattr(CoinGlassAdapter, "_exchange_pairs", fake_exchange_pairs)
    monkeypatch.setattr(coinglass_module, "urlopen", fake_urlopen)
    try:
        candles = CoinGlassAdapter(RuntimeConfig()).candles("EURUSD", 1, "4h")
    finally:
        _restore_env("COINGLASS_API_KEY", old_key)

    assert candles[0].close == 1.11
    assert "exchange=Gate" in captured["url"]
    assert "symbol=EURUSD_USDT" in captured["url"]


def test_coinglass_upgrade_plan_response_has_specific_error(monkeypatch) -> None:  # noqa: ANN001
    old_key = os.environ.get("COINGLASS_API_KEY")
    os.environ["COINGLASS_API_KEY"] = "test-key"

    def fake_urlopen(request, timeout=0):  # noqa: ANN001, ANN202
        return FakeResponse('{"code":"401","msg":"Upgrade plan"}')

    monkeypatch.setattr(coinglass_module, "urlopen", fake_urlopen)
    try:
        adapter = CoinGlassAdapter(RuntimeConfig())
        try:
            adapter.candles("BTC", 2, "4h")
        except CoinGlassPlanError as error:
            assert "Upgrade plan" in str(error)
        else:
            raise AssertionError("expected plan-blocked response to raise CoinGlassPlanError")
    finally:
        _restore_env("COINGLASS_API_KEY", old_key)


def test_coinglass_context_services_use_expected_endpoints(monkeypatch) -> None:  # noqa: ANN001
    captured: list[str] = []
    old_key = os.environ.get("COINGLASS_API_KEY")
    os.environ["COINGLASS_API_KEY"] = "test-key"

    def fake_exchange_pairs(self):  # noqa: ANN001, ANN202
        return {"Binance": [{"instrument_id": "BTCUSDT", "base_asset": "BTC", "quote_asset": "USDT"}]}

    def fake_urlopen(request, timeout=0):  # noqa: ANN001, ANN202
        captured.append(request.full_url)
        return FakeResponse('{"code":"0","data":[]}')

    monkeypatch.setattr(CoinGlassAdapter, "_exchange_pairs", fake_exchange_pairs)
    monkeypatch.setattr(coinglass_module, "urlopen", fake_urlopen)
    try:
        adapter = CoinGlassAdapter(RuntimeConfig())
        adapter.funding_rate("BTC")
        adapter.open_interest("BTC")
        adapter.liquidation_history("BTC", limit=24, interval="1h")
        adapter.fear_greed()
    finally:
        _restore_env("COINGLASS_API_KEY", old_key)

    assert any("/api/futures/funding-rate/oi-weight-history" in url and "symbol=BTCUSDT" in url for url in captured)
    assert any("/api/futures/open-interest/exchange-list" in url and "symbol=BTC" in url for url in captured)
    assert any("/api/futures/liquidation/aggregated-history" in url and "interval=1h" in url for url in captured)
    assert any("/api/index/fear-greed-history" in url for url in captured)


def _restore_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value
