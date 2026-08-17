from __future__ import annotations

import base64
from urllib.error import URLError

import pytest

import monatise.adapters.backpack as backpack_module
from monatise.adapters.backpack import BackpackAdapter, BackpackCredentials, backpack_signing_payload
from monatise.live.config import RuntimeConfig


def test_backpack_symbol_mapping_defaults_and_env(monkeypatch) -> None:
    adapter = BackpackAdapter(RuntimeConfig())

    assert adapter.exchange_symbol("BTC") == "BTC_USDC_PERP"
    assert adapter.exchange_symbol("SOL_USDC") == "SOL_USDC"

    monkeypatch.setenv("BACKPACK_SYMBOL_MAP", "btc=BTC_USDC_PERP")
    assert adapter.exchange_symbol("btc") == "BTC_USDC_PERP"


def test_backpack_candles_parse_public_klines(monkeypatch) -> None:
    adapter = BackpackAdapter(RuntimeConfig())

    def fake_get_json(path, params=None):  # noqa: ANN001
        assert path == "/api/v1/klines"
        assert params["symbol"] == "BTC_USDC_PERP"
        assert params["interval"] == "5m"
        assert int(params["endTime"]) > int(params["startTime"])
        assert "limit" not in params
        return [
            {
                "start": "2026-06-19T00:00:00Z",
                "open": "100",
                "high": "110",
                "low": "95",
                "close": "105",
                "volume": "12.5",
            }
        ]

    monkeypatch.setattr(adapter, "_get_json", fake_get_json)

    candles = adapter.candles("BTC", 1, "5m")

    assert candles[0].close == 105
    assert candles[0].volume == 12.5


def test_backpack_candles_skip_malformed_rows_instead_of_crashing(monkeypatch) -> None:
    # A row with a null OHLC field or a missing key must not take down the
    # whole candle fetch.
    adapter = BackpackAdapter(RuntimeConfig())

    def fake_get_json(path, params=None):  # noqa: ANN001
        return [
            {"start": "1", "open": "100", "high": "105", "low": "99", "close": "104", "volume": None},
            {"start": "2", "open": None, "high": "108", "low": "103", "close": "107", "volume": "8"},
            {"start": "3", "high": "108", "low": "103", "close": "107", "volume": "8"},
            {"start": "4", "open": "110", "high": "112", "low": "109", "close": "111", "volume": "5"},
        ]

    monkeypatch.setattr(adapter, "_get_json", fake_get_json)

    candles = adapter.candles("BTC", 4, "5m")

    # Rows 2 and 3 (null open, missing open) are skipped; 1 and 4 survive.
    assert [candle.close for candle in candles] == [104, 111]
    assert candles[0].volume == 0.0


def test_backpack_mark_price_uses_dedicated_public_feed(monkeypatch) -> None:
    adapter = BackpackAdapter(RuntimeConfig())

    def fake_get_json(path, params=None):  # noqa: ANN001
        assert path == "/api/v1/markPrices"
        assert params is None
        return [
            {"symbol": "ETH_USDC_PERP", "markPrice": "3500.1"},
            {"symbol": "BTC_USDC_PERP", "markPrice": "64321.25"},
        ]

    monkeypatch.setattr(adapter, "_get_json", fake_get_json)

    assert adapter.latest_mark_price("BTC") == 64321.25


def test_backpack_get_json_wraps_network_errors(monkeypatch) -> None:
    adapter = BackpackAdapter(RuntimeConfig())

    def fake_urlopen(request, timeout=0):  # noqa: ANN001, ANN202
        raise URLError("connection refused")

    monkeypatch.setattr(backpack_module, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="Backpack request failed"):
        adapter._get_json("/api/v1/klines")


def test_backpack_get_json_wraps_non_json_response(monkeypatch) -> None:
    adapter = BackpackAdapter(RuntimeConfig())

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:  # noqa: ANN002
            return None

        def read(self) -> bytes:
            return b"<html>not json</html>"

    monkeypatch.setattr(backpack_module, "urlopen", lambda request, timeout=0: FakeResponse())  # noqa: ANN001

    with pytest.raises(RuntimeError, match="non-JSON response"):
        adapter._get_json("/api/v1/klines")


def test_backpack_signing_payload_is_stable() -> None:
    payload = backpack_signing_payload(
        instruction="orderExecute",
        params={"symbol": "BTC_USDC_PERP", "side": "Bid"},
        timestamp_ms=1_000,
        window_ms=5_000,
    )

    assert payload == "instruction=orderExecute&side=Bid&symbol=BTC_USDC_PERP&timestamp=1000&window=5000"


def test_backpack_sign_headers_uses_ed25519_key() -> None:
    secret = base64.b64encode(b"1" * 32).decode("utf-8")
    adapter = BackpackAdapter(
        RuntimeConfig(),
        credentials=BackpackCredentials(api_key="public-key", secret_key=secret),
    )

    headers = adapter.sign_headers(instruction="orderExecute", params={"symbol": "BTC_USDC_PERP"}, timestamp_ms=1_000)

    assert headers["X-API-Key"] == "public-key"
    assert headers["X-Timestamp"] == "1000"
    assert headers["X-Window"] == "5000"
    assert base64.b64decode(headers["X-Signature"])
