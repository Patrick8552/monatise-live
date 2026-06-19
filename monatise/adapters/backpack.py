from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from monatise.core.models import Candle, Fill, Order
from monatise.core.ports import ExecutionPort, MarketDataPort
from monatise.live.config import RuntimeConfig
from monatise.live.secrets import secret_value


BACKPACK_REST_BASE = "https://api.backpack.exchange"
BACKPACK_WS_BASE = "wss://ws.backpack.exchange"
DEFAULT_SYMBOL_MAP = {
    "BTC": "BTC_USDC_PERP",
    "ETH": "ETH_USDC_PERP",
    "SOL": "SOL_USDC_PERP",
}
SUPPORTED_INTERVALS = {"1m", "5m", "15m", "1h", "4h", "1d"}


@dataclass(frozen=True)
class BackpackCredentials:
    api_key: str
    secret_key: str


class BackpackAdapter(MarketDataPort, ExecutionPort):
    """Backpack exchange scaffold.

    Public market data is available now. Execution methods intentionally remain
    disabled until private account mapping, permissions, and risk handling are
    reviewed for Backpack separately from Hyperliquid.
    """

    def __init__(self, config: RuntimeConfig, credentials: BackpackCredentials | None = None) -> None:
        self.config = config
        self.credentials = credentials or BackpackCredentials(
            api_key=secret_value("BACKPACK_API_KEY", ""),
            secret_key=secret_value("BACKPACK_SECRET_KEY", ""),
        )
        self.base_url = os.getenv("BACKPACK_REST_BASE", BACKPACK_REST_BASE).rstrip("/")

    def markets(self) -> list[dict[str, Any]]:
        payload = self._get_json("/api/v1/markets")
        if not isinstance(payload, list):
            raise RuntimeError("Backpack markets response was not a list")
        return payload

    def ticker(self, symbol: str) -> dict[str, Any]:
        payload = self._get_json("/api/v1/ticker", {"symbol": self.exchange_symbol(symbol)})
        if not isinstance(payload, dict):
            raise RuntimeError("Backpack ticker response was not an object")
        return payload

    def latest_price(self, symbol: str) -> float:
        ticker = self.ticker(symbol)
        for key in ("lastPrice", "markPrice", "price"):
            value = ticker.get(key)
            if value not in (None, ""):
                return float(value)
        raise RuntimeError("Backpack ticker did not include a usable price")

    def candles(self, symbol: str, limit: int, interval: str = "1h") -> list[Candle]:
        if interval not in SUPPORTED_INTERVALS:
            raise ValueError("unsupported Backpack candle interval")
        if limit <= 0:
            raise ValueError("candle limit must be positive")
        payload = self._get_json(
            "/api/v1/klines",
            {"symbol": self.exchange_symbol(symbol), "interval": interval, "limit": str(min(limit, 1000))},
        )
        if not isinstance(payload, list):
            raise RuntimeError("Backpack klines response was not a list")
        candles = [_parse_kline(row) for row in payload][-limit:]
        for candle in candles:
            candle.validate()
        return candles

    def place_orders(self, orders: list[Order]) -> list[dict]:
        raise RuntimeError("Backpack execution is scaffolded but disabled until account mapping and risk review are complete")

    def cancel_orders(self, order_ids: list[str]) -> None:
        if order_ids:
            raise RuntimeError("Backpack execution is scaffolded but disabled until account mapping and risk review are complete")

    def fills(self, symbol: str) -> list[Fill]:
        raise RuntimeError("Backpack private fills are scaffolded but disabled until account mapping and risk review are complete")

    def exchange_symbol(self, symbol: str) -> str:
        raw = symbol.strip().upper().replace("-", "_").replace("/", "_")
        env_map = _symbol_map_from_env()
        if raw in env_map:
            return env_map[raw]
        if raw in DEFAULT_SYMBOL_MAP:
            return DEFAULT_SYMBOL_MAP[raw]
        if raw.endswith("_USDC") or raw.endswith("_USDC_PERP"):
            return raw
        return f"{raw}_USDC_PERP"

    def sign_headers(
        self,
        *,
        instruction: str,
        params: dict[str, Any] | None = None,
        timestamp_ms: int | None = None,
        window_ms: int = 5000,
    ) -> dict[str, str]:
        if not self.credentials.api_key or not self.credentials.secret_key:
            raise RuntimeError("BACKPACK_API_KEY and BACKPACK_SECRET_KEY are required for private Backpack signing")
        timestamp_ms = timestamp_ms or int(time.time() * 1000)
        signing_payload = backpack_signing_payload(
            instruction=instruction,
            params=params or {},
            timestamp_ms=timestamp_ms,
            window_ms=window_ms,
        )
        private_key = Ed25519PrivateKey.from_private_bytes(_decode_secret_key(self.credentials.secret_key))
        signature = private_key.sign(signing_payload.encode("utf-8"))
        return {
            "X-API-Key": self.credentials.api_key,
            "X-Signature": base64.b64encode(signature).decode("utf-8"),
            "X-Timestamp": str(timestamp_ms),
            "X-Window": str(window_ms),
        }

    def _get_json(self, path: str, params: dict[str, str] | None = None) -> Any:
        query = f"?{urlencode(params)}" if params else ""
        request = Request(f"{self.base_url}{path}{query}", headers={"accept": "application/json"}, method="GET")
        with urlopen(request, timeout=15) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))


def backpack_signing_payload(
    *,
    instruction: str,
    params: dict[str, Any],
    timestamp_ms: int,
    window_ms: int,
) -> str:
    fields = {"instruction": instruction, **{key: value for key, value in params.items() if value is not None}}
    sorted_fields = sorted((str(key), str(value)) for key, value in fields.items())
    sorted_fields.extend([("timestamp", str(timestamp_ms)), ("window", str(window_ms))])
    return "&".join(f"{key}={value}" for key, value in sorted_fields)


def _parse_kline(row: dict[str, Any]) -> Candle:
    timestamp = row.get("start") or row.get("timestamp") or row.get("time") or row.get("t")
    return Candle(
        timestamp=str(timestamp),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row.get("volume", 0.0)),
    )


def _decode_secret_key(value: str) -> bytes:
    value = value.strip()
    try:
        decoded = base64.b64decode(value)
    except Exception as error:  # noqa: BLE001
        raise RuntimeError("BACKPACK_SECRET_KEY must be base64 encoded") from error
    if len(decoded) != 32:
        raise RuntimeError("BACKPACK_SECRET_KEY must decode to a 32-byte ED25519 private key")
    return decoded


def _symbol_map_from_env() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in os.getenv("BACKPACK_SYMBOL_MAP", "").split(","):
        key, _, value = item.partition("=")
        if key.strip() and value.strip():
            mapping[key.strip().upper()] = value.strip().upper()
    return mapping
