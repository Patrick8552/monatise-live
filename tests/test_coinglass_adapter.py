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


def test_coinglass_rejects_non_crypto_coin(monkeypatch) -> None:  # noqa: ANN001
    old_key = os.environ.get("COINGLASS_API_KEY")
    os.environ["COINGLASS_API_KEY"] = "test-key"
    try:
        adapter = CoinGlassAdapter(RuntimeConfig())
        try:
            adapter.candles("GOLD", 2, "1h")
        except ValueError as error:
            assert "not a CoinGlass crypto futures coin" in str(error)
        else:
            raise AssertionError("expected non-crypto CoinGlass symbol to fail")
    finally:
        _restore_env("COINGLASS_API_KEY", old_key)


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


def _restore_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value
