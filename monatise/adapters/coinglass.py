from __future__ import annotations

import json
import time
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
PREFERRED_EXCHANGES = ("Binance", "Gate", "MEXC", "Bybit", "OKX", "Hyperliquid")
PAIR_CACHE_TTL_SECONDS = 900


class CoinGlassAdapter:
    _pairs_cache: tuple[float, dict[str, list[dict[str, Any]]]] = (0.0, {})

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self.api_key = secret_value("COINGLASS_API_KEY", "") or secret_value("MONATISE_COINGLASS_API_KEY", "")
        self.exchange = secret_value("COINGLASS_EXCHANGE", "Binance")
        self.exchange_list = secret_value("COINGLASS_EXCHANGE_LIST", self.exchange)
        if not self.api_key:
            raise RuntimeError("COINGLASS_API_KEY is required for CoinGlass data feeds")

    def candles(self, symbol: str, limit: int, interval: str = "1h") -> list[Candle]:
        exchange, pair = self._market(symbol)
        data = self._get(
            "/api/futures/price/history",
            {
                "exchange": exchange,
                "symbol": pair,
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

    def funding_rate(self, symbol: str) -> list[dict[str, Any]]:
        exchange, pair = self._market(symbol)
        return self._get("/api/futures/funding-rate/oi-weight-history", {"exchange": exchange, "symbol": pair})

    def fear_greed(self) -> list[dict[str, Any]]:
        return self._get("/api/index/fear-greed-history", {})

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

    def supported_assets(self) -> list[dict[str, Any]]:
        pairs = self._exchange_pairs()
        by_symbol: dict[str, dict[str, Any]] = {}
        for exchange in _ordered_exchanges(self.exchange, tuple(pairs)):
            for row in pairs.get(exchange, []):
                symbol = str(row.get("base_asset", "")).upper()
                instrument = str(row.get("instrument_id", ""))
                if not symbol or not instrument or symbol in by_symbol:
                    continue
                by_symbol[symbol] = {
                    "symbol": symbol,
                    "exchange": exchange,
                    "instrument": instrument,
                    "quote": row.get("quote_asset", ""),
                    "tradable": True,
                }
        return sorted(by_symbol.values(), key=lambda asset: asset["symbol"])

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
        return coin

    def _pair(self, symbol: str) -> str:
        coin = self._coin(symbol)
        return COINGLASS_SYMBOLS.get(coin, f"{coin}USDT")

    def _market(self, symbol: str) -> tuple[str, str]:
        coin = self._coin(symbol)
        pairs = self._exchange_pairs()
        for exchange in _ordered_exchanges(self.exchange, tuple(pairs)):
            match = _best_instrument_match(coin, pairs.get(exchange, []), preferred_pair=self._pair(symbol))
            if match:
                return exchange, match
        return self.exchange, self._pair(symbol)

    def _exchange_pairs(self) -> dict[str, list[dict[str, Any]]]:
        now = time.time()
        cached_at, cached = self.__class__._pairs_cache
        if cached and now - cached_at < PAIR_CACHE_TTL_SECONDS:
            return cached
        data = self._get("/api/futures/supported-exchange-pairs", {})
        pairs = dict(data) if isinstance(data, dict) else {}
        self.__class__._pairs_cache = (now, pairs)
        return pairs


def _ordered_exchanges(primary: str, available: tuple[str, ...]) -> tuple[str, ...]:
    ordered = []
    for exchange in (primary, *PREFERRED_EXCHANGES, *available):
        if exchange and exchange not in ordered:
            ordered.append(exchange)
    return tuple(ordered)


def _best_instrument_match(coin: str, rows: list[dict[str, Any]], preferred_pair: str) -> str:
    matches = [row for row in rows if str(row.get("base_asset", "")).upper() == coin]
    if not matches:
        return ""
    for row in matches:
        if str(row.get("instrument_id", "")).upper() == preferred_pair.upper():
            return str(row.get("instrument_id", ""))
    for quote in ("USDT", "USD"):
        for row in matches:
            if str(row.get("quote_asset", "")).upper() == quote:
                return str(row.get("instrument_id", ""))
    return str(matches[0].get("instrument_id", ""))


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
