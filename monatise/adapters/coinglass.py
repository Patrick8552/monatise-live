from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from monatise.core.models import Candle
from monatise.live.config import RuntimeConfig
from monatise.live.secrets import secret_value


COINGLASS_BASE_URL = "https://open-api-v4.coinglass.com"
COINGLASS_SYMBOLS = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "HYPE": "HYPEUSDT",
    "BNB": "BNBUSDT",
    "XRP": "XRPUSDT",
    "DOGE": "DOGEUSDT",
}


class CoinGlassAdapter:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self.api_key = secret_value("COINGLASS_API_KEY", "") or secret_value("MONATISE_COINGLASS_API_KEY", "")
        self.exchange = secret_value("COINGLASS_EXCHANGE", "Binance")
        self.exchange_list = secret_value("COINGLASS_EXCHANGE_LIST", self.exchange)
        if not self.api_key:
            raise RuntimeError("COINGLASS_API_KEY is required for CoinGlass data feeds")

    def candles(self, symbol: str, limit: int, interval: str = "1h") -> list[Candle]:
        data = self._get(
            "/api/futures/price/history",
            {
                "exchange": self.exchange,
                "symbol": self._pair(symbol),
                "interval": interval,
                "limit": max(1, min(1000, int(limit))),
            },
        )
        candles = [_parse_price_candle(raw) for raw in data]
        candles = candles[-limit:]
        for candle in candles:
            candle.validate()
        return candles

    def open_interest(self, symbol: str) -> list[dict[str, Any]]:
        return self._get("/api/futures/open-interest/exchange-list", {"symbol": self._coin(symbol)})

    def account_subscription(self) -> dict[str, Any]:
        data = self._get("/api/user/account/subscription", {})
        return dict(data) if isinstance(data, dict) else {}

    def liquidation_history(self, symbol: str, limit: int = 24, interval: str = "1h") -> list[dict[str, Any]]:
        return self._get(
            "/api/futures/liquidation/aggregated-history",
            {
                "exchange_list": self.exchange_list,
                "symbol": self._coin(symbol),
                "interval": interval,
                "limit": max(1, min(1000, int(limit))),
            },
        )

    def _get(self, path: str, params: dict[str, Any]) -> Any:  # noqa: ANN401
        query = urlencode({key: value for key, value in params.items() if value not in {None, ""}})
        request = Request(
            f"{COINGLASS_BASE_URL}{path}?{query}",
            headers={"accept": "application/json", "CG-API-KEY": self.api_key},
            method="GET",
        )
        try:
            with urlopen(request, timeout=15) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as error:
            raise RuntimeError(f"CoinGlass request failed for {path}") from error
        if str(payload.get("code")) not in {"0", "200"}:
            message = str(payload.get("msg") or payload.get("message") or "CoinGlass request failed")
            if "upgrade plan" in message.lower():
                raise CoinGlassPlanError(message)
            raise RuntimeError(message)
        return payload.get("data", [])

    def _coin(self, symbol: str) -> str:
        coin = symbol.split("-", 1)[0].upper()
        if coin in {"GOLD", "XAU", "CL", "BRENTOIL"}:
            raise ValueError(f"{coin} is not a CoinGlass crypto futures coin")
        return coin

    def _pair(self, symbol: str) -> str:
        coin = self._coin(symbol)
        return COINGLASS_SYMBOLS.get(coin, f"{coin}USDT")


def _parse_price_candle(raw: dict[str, Any]) -> Candle:
    return Candle(
        timestamp=str(raw.get("time", "")),
        open=float(raw["open"]),
        high=float(raw["high"]),
        low=float(raw["low"]),
        close=float(raw["close"]),
        volume=float(raw.get("volume_usd", 0.0)),
    )


class CoinGlassPlanError(RuntimeError):
    pass
