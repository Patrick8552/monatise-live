from __future__ import annotations

import base64

from monatise.adapters.backpack import BackpackAdapter, BackpackCredentials, backpack_signing_payload
from monatise.live.config import RuntimeConfig


def test_backpack_symbol_mapping_defaults_and_env(monkeypatch) -> None:
    adapter = BackpackAdapter(RuntimeConfig())

    assert adapter.exchange_symbol("BTC") == "BTC_USDC_PERP"
    assert adapter.exchange_symbol("SOL_USDC") == "SOL_USDC"

    monkeypatch.setenv("BACKPACK_SYMBOL_MAP", "gold=XAU_USDC_PERP")
    assert adapter.exchange_symbol("gold") == "XAU_USDC_PERP"


def test_backpack_candles_parse_public_klines(monkeypatch) -> None:
    adapter = BackpackAdapter(RuntimeConfig())

    def fake_get_json(path, params=None):  # noqa: ANN001
        assert path == "/api/v1/klines"
        assert params["symbol"] == "BTC_USDC_PERP"
        assert params["interval"] == "5m"
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
