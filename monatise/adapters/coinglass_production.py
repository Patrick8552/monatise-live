"""Resilient, read-only CoinGlass market intelligence adapter."""

from __future__ import annotations

import json
import random
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from monatise.core.models import Candle


class CoinGlassError(RuntimeError):
    pass


@dataclass(frozen=True)
class CoinGlassHealth:
    healthy: bool
    last_success_at: float | None
    consecutive_failures: int
    cache_entries: int


class CoinGlassProductionAdapter:
    """Fetches and normalizes data only; it contains no analytical rules."""

    SUPPORTED_INTERVALS = ("1m", "3m", "5m", "15m", "30m", "1h", "4h", "6h", "8h", "12h", "1d", "1w")

    ENDPOINTS = {
        "pairs_markets": "/api/futures/pairs-markets",
        "price_history": "/api/futures/price/history",
        "open_interest": "/api/futures/open-interest/exchange-list",
        "funding_rate": "/api/futures/funding-rate/oi-weight-history",
        "liquidations": "/api/futures/liquidation/aggregated-history",
        "volume": "/api/futures/aggregated-taker-buy-sell-volume/history",
        "order_book": "/api/futures/orderbook/aggregated-ask-bids-history",
        "cvd": "/api/futures/aggregated-cvd/history",
    }

    PAIRS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
    DASHBOARD_PATHS = {
        "/api/article/list": {"start_time", "end_time", "language", "page", "per_page"},
        "/api/futures/aggregated-cvd/history": {"exchange_list", "symbol", "interval", "limit", "start_time", "end_time", "unit"},
        "/api/futures/aggregated-taker-buy-sell-volume/history": {"exchange_list", "symbol", "interval", "limit", "start_time", "end_time", "unit"},
        "/api/futures/cvd/history": {"exchange", "symbol", "interval", "limit", "start_time", "end_time", "unit"},
        "/api/futures/funding-rate/exchange-list": set(),
        "/api/futures/funding-rate/history": {"exchange", "symbol", "interval", "limit", "start_time", "end_time"},
        "/api/futures/funding-rate/oi-weight-history": {"symbol", "interval", "limit", "start_time", "end_time"},
        "/api/futures/global-long-short-account-ratio/history": {"exchange", "symbol", "interval", "limit", "start_time", "end_time"},
        "/api/futures/liquidation/aggregated-map": {"symbol", "range"},
        "/api/futures/liquidation/aggregated-history": {"exchange_list", "symbol", "interval", "limit"},
        "/api/futures/liquidation/exchange-list": {"symbol", "range"},
        "/api/futures/liquidation/order": {"exchange", "symbol", "min_liquidation_amount", "start_time", "end_time"},
        "/api/futures/liquidation/max-pain": {"range"},
        "/api/futures/open-interest/aggregated-history": {"symbol", "interval", "limit", "start_time", "end_time", "unit"},
        "/api/futures/open-interest/exchange-list": {"symbol"},
        "/api/futures/open-interest/history": {"exchange", "symbol", "interval", "limit", "start_time", "end_time", "unit"},
        "/api/futures/orderbook/aggregated-ask-bids-history": {"exchange_list", "symbol", "interval", "limit", "start_time", "end_time", "range"},
        "/api/futures/orderbook/ask-bids-history": {"exchange", "symbol", "interval", "limit", "start_time", "end_time", "range"},
        "/api/futures/orderbook/large-limit-order": {"exchange", "symbol"},
        "/api/futures/orderbook/v2/large-limit-order-history": {"exchange", "symbol", "start_time", "end_time"},
        "/api/futures/price/history": {"exchange", "symbol", "interval", "limit", "start_time", "end_time"},
        "/api/futures/supported-coins": set(),
        "/api/futures/coins-price-change": set(),
        "/api/futures/avg-true-range/list": set(),
        "/api/futures/top-long-short-account-ratio/history": {"exchange", "symbol", "interval", "limit", "start_time", "end_time"},
        "/api/futures/top-long-short-position-ratio/history": {"exchange", "symbol", "interval", "limit", "start_time", "end_time"},
        "/api/index/fear-greed-history": set(),
    }

    def __init__(self, credential_provider: Callable[[], str], *, base_url: str = "https://open-api-v4.coinglass.com", timeout_seconds: float = 15.0, maximum_attempts: int = 3, requests_per_second: float = 4.0, cache_ttl_seconds: float = 30.0, transport: Callable[[str, dict[str, str], float], dict[str, Any]] | None = None, observer: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        if maximum_attempts < 1 or timeout_seconds <= 0 or requests_per_second <= 0 or cache_ttl_seconds < 0:
            raise ValueError("invalid CoinGlass resilience configuration")
        self._credential_provider = credential_provider
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._attempts = maximum_attempts
        self._minimum_interval = 1.0 / requests_per_second
        self._ttl = cache_ttl_seconds
        self._transport = transport or self._http_get
        self._observer = observer or (lambda _event, _fields: None)
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = threading.RLock()
        self._last_request = 0.0
        self._last_success: float | None = None
        # Readiness represents the essential market feed, not every optional
        # enrichment dataset. Some CoinGlass plans legitimately omit order-book
        # or CVD history while price candles remain fully operational.
        self._critical_failures = 0

    def open_interest(self, symbol: str) -> Any:
        return self._fetch("open_interest", symbol)

    def latest_price(self, symbol: str) -> float:
        candles = self.candles(symbol, 2, "1h")
        if not candles:
            raise CoinGlassError("CoinGlass returned no price data")
        return candles[-1].close

    def latest_current_price(self, symbol: str) -> float:
        coin = self._crypto_symbol(symbol)
        rows = self._fetch("pairs_markets", coin)
        if not isinstance(rows, list):
            raise CoinGlassError("CoinGlass pairs markets data must be a list")
        expected_pair = self.PAIRS.get(coin, f"{coin}USDT")
        for row in rows:
            if not isinstance(row, dict):
                continue
            exchange = str(row.get("exchange_name", "")).casefold()
            instrument = str(row.get("instrument_id", "")).upper()
            if exchange == "binance" and instrument == expected_pair:
                try:
                    return float(row["current_price"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise CoinGlassError("CoinGlass returned an invalid current price") from exc
        raise CoinGlassError(f"CoinGlass returned no Binance current price for {expected_pair}")

    def candles(self, symbol: str, limit: int, interval: str = "1h") -> list[Candle]:
        coin = self._crypto_symbol(symbol)
        data = self._fetch(
            "price_history",
            coin,
            params={
                "exchange": "Binance",
                "symbol": self.PAIRS.get(coin, f"{coin}USDT"),
                "interval": interval,
                "limit": str(max(2, min(1000, int(limit)))),
            },
        )
        if not isinstance(data, list):
            raise CoinGlassError("CoinGlass price history must be a list")
        result: list[Candle] = []
        for item in data[-limit:]:
            if not isinstance(item, dict):
                raise CoinGlassError("CoinGlass candle must be an object")
            try:
                timestamp = str(item.get("time") or item.get("timestamp") or "")
                if timestamp.isdigit():
                    value = int(timestamp)
                    if value > 10_000_000_000:
                        value //= 1000
                    from datetime import datetime, timezone
                    timestamp = datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
                candle = Candle(
                    timestamp=timestamp,
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    volume=float(item.get("volume_usd", item.get("volume", 0.0))),
                )
                candle.validate()
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise CoinGlassError("CoinGlass returned a malformed candle") from exc
            result.append(candle)
        return result

    def funding_rate(self, symbol: str) -> Any:
        return self._fetch("funding_rate", symbol)

    def liquidations(self, symbol: str) -> Any:
        return self._fetch("liquidations", symbol)

    def volume(self, symbol: str) -> Any:
        return self._fetch("volume", symbol)

    def order_book(self, symbol: str) -> Any:
        return self._fetch("order_book", symbol)

    def cvd(self, symbol: str) -> Any:
        return self._fetch("cvd", symbol)

    def dashboard_query(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        """Execute one allowlisted, read-only dashboard query with server credentials."""
        allowed = self.DASHBOARD_PATHS.get(path)
        if allowed is None:
            raise ValueError("unsupported CoinGlass dashboard dataset")
        if set(params) - allowed or any(len(key) > 32 or len(value) > 128 for key, value in params.items()):
            raise ValueError("invalid CoinGlass dashboard parameters")
        cache_key = f"dashboard:{path}:{tuple(sorted(params.items()))}"
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and now - cached[0] <= self._ttl:
                self._observe("coinglass.cache_hit", {"dataset": path})
                return deepcopy(cached[1])
        last_error: Exception | None = None
        for attempt in range(1, self._attempts + 1):
            try:
                self._rate_limit()
                payload = self._transport(path, dict(params), self._timeout)
                if not isinstance(payload, dict) or str(payload.get("code")) not in {"0", "200"}:
                    raise CoinGlassError(str(payload.get("msg") or payload.get("message") or "CoinGlass rejected request") if isinstance(payload, dict) else "CoinGlass returned an invalid response")
                with self._lock:
                    self._cache[cache_key] = (time.monotonic(), deepcopy(payload))
                    self._last_success = time.time()
                self._observe("coinglass.request", {"dataset": path, "attempt": attempt, "success": True})
                return deepcopy(payload)
            except Exception as exc:
                last_error = exc
                self._observe("coinglass.request", {"dataset": path, "attempt": attempt, "success": False, "error": type(exc).__name__})
                if attempt < self._attempts:
                    time.sleep(min(2.0, 0.2 * 2 ** (attempt - 1)) + random.uniform(0, 0.05))
        raise CoinGlassError("CoinGlass dashboard request failed") from last_error

    def supported_futures_coins(self) -> tuple[str, ...]:
        payload = self.dashboard_query("/api/futures/supported-coins", {})
        rows = payload.get("data", [])
        if not isinstance(rows, list):
            raise CoinGlassError("CoinGlass supported coins must be a list")
        return tuple(dict.fromkeys(str(row).strip().upper() for row in rows if str(row).strip()))

    def futures_price_changes(self) -> tuple[dict[str, Any], ...]:
        payload = self.dashboard_query("/api/futures/coins-price-change", {})
        rows = payload.get("data", [])
        if not isinstance(rows, list):
            raise CoinGlassError("CoinGlass price changes must be a list")
        return tuple(row for row in rows if isinstance(row, dict))

    def derivatives_snapshot(self, symbol: str) -> dict[str, float | None]:
        symbol = self._crypto_symbol(symbol)
        volume = self.volume(symbol)
        order_book = self.order_book(symbol)
        return {
            "open_interest": self._extract_number(self.open_interest(symbol), ("open_interest_usd", "openInterest", "open_interest", "value")),
            "funding_rate": self._extract_number(self.funding_rate(symbol), ("close", "fundingRate", "funding_rate", "value")),
            "liquidation_volume": self._extract_number(self.liquidations(symbol), ("liquidation_usd", "liquidationUsd", "liquidation_volume", "value")),
            "derivatives_volume": self._sum_numbers(volume, ("aggregated_buy_volume_usd", "taker_buy_volume_usd"), ("aggregated_sell_volume_usd", "taker_sell_volume_usd")),
            "order_book_imbalance": self._order_book_imbalance(order_book),
            "cvd": self._extract_number(self.cvd(symbol), ("cum_vol_delta", "cvd", "value")),
        }

    def health(self) -> CoinGlassHealth:
        with self._lock:
            return CoinGlassHealth(self._last_success is not None and self._critical_failures == 0, self._last_success, self._critical_failures, len(self._cache))

    def _fetch(self, dataset: str, symbol: str, *, params: dict[str, str] | None = None) -> Any:
        coin = self._crypto_symbol(symbol)
        request_params = dict(params or self._dataset_params(dataset, coin))
        key = f"{dataset}:{coin}:{tuple(sorted(request_params.items()))}"
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached and now - cached[0] <= self._ttl:
                self._observe("coinglass.cache_hit", {"dataset": dataset})
                return deepcopy(cached[1])
        params = {"symbol": coin}
        last_error: Exception | None = None
        for attempt in range(1, self._attempts + 1):
            try:
                self._rate_limit()
                payload = self._transport(self.ENDPOINTS[dataset], request_params, self._timeout)
                if str(payload.get("code")) not in {"0", "200"}:
                    raise CoinGlassError(str(payload.get("msg") or payload.get("message") or "CoinGlass rejected request"))
                data = payload.get("data", [])
                if not isinstance(data, (dict, list)):
                    raise CoinGlassError("CoinGlass data must be an object or array")
                with self._lock:
                    self._cache[key] = (time.monotonic(), deepcopy(data))
                    self._last_success = time.time()
                    if dataset == "price_history":
                        self._critical_failures = 0
                self._observe("coinglass.request", {"dataset": dataset, "attempt": attempt, "success": True})
                return deepcopy(data)
            except Exception as exc:
                last_error = exc
                self._observe("coinglass.request", {"dataset": dataset, "attempt": attempt, "success": False, "error": type(exc).__name__})
                if attempt < self._attempts:
                    time.sleep(min(2.0, 0.2 * 2 ** (attempt - 1)) + random.uniform(0, 0.05))
        if dataset == "price_history":
            with self._lock:
                self._critical_failures += 1
        raise CoinGlassError(f"CoinGlass {dataset} request failed") from last_error

    def _dataset_params(self, dataset: str, coin: str) -> dict[str, str]:
        pair = self.PAIRS.get(coin, f"{coin}USDT")
        if dataset == "pairs_markets":
            return {"symbol": coin}
        if dataset == "open_interest":
            return {"symbol": coin}
        if dataset == "funding_rate":
            return {"symbol": coin, "interval": "1h", "limit": "2"}
        if dataset == "liquidations":
            return {
                "exchange_list": "Binance",
                "symbol": coin,
                "interval": "1h",
                "limit": "2",
            }
        if dataset in {"volume", "cvd"}:
            return {"exchange_list": "Binance", "symbol": coin, "interval": "1h", "limit": "2"}
        if dataset == "order_book":
            return {"exchange_list": "Binance", "symbol": coin, "interval": "1h", "limit": "2", "range": "1"}
        if dataset == "price_history":
            return {"exchange": "Binance", "symbol": pair, "interval": "1h", "limit": "2"}
        raise CoinGlassError("unsupported CoinGlass dataset")

    def _http_get(self, path: str, params: dict[str, str], timeout: float) -> dict[str, Any]:
        key = self._credential_provider()
        if not key:
            raise CoinGlassError("CoinGlass credential is unavailable")
        request = Request(f"{self._base_url}{path}?{urlencode(params)}", headers={"accept": "application/json", "CG-API-KEY": key}, method="GET")
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            value = json.loads(response.read().decode("utf-8"))
        if not isinstance(value, dict):
            raise CoinGlassError("CoinGlass returned an invalid response")
        return value

    def _rate_limit(self) -> None:
        with self._lock:
            delay = self._minimum_interval - (time.monotonic() - self._last_request)
            if delay > 0:
                time.sleep(delay)
            self._last_request = time.monotonic()

    def _observe(self, event: str, fields: dict[str, Any]) -> None:
        try:
            self._observer(event, fields)
        except Exception:
            # Telemetry must never change provider availability or response data.
            return

    @staticmethod
    def _crypto_symbol(symbol: str) -> str:
        if not isinstance(symbol, str):
            raise ValueError("crypto symbol must be a string")
        clean = "".join(char for char in symbol.strip().upper() if char.isalpha())
        fiat = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"}
        if len(clean) == 6 and clean[:3] in fiat and clean[3:] in fiat:
            raise ValueError("crypto symbols only")
        for quote in ("USDT", "USDC", "BUSD", "USD"):
            if clean.endswith(quote) and len(clean) > len(quote):
                clean = clean[:-len(quote)]
                break
        if not clean or clean in fiat:
            raise ValueError("crypto symbols only")
        return clean

    @classmethod
    def _extract_number(cls, value: Any, keys: tuple[str, ...]) -> float | None:
        if isinstance(value, list):
            value = value[-1] if value else None
        if isinstance(value, dict):
            for key in keys:
                if key in value:
                    try:
                        return float(value[key])
                    except (TypeError, ValueError):
                        return None
            for child in value.values():
                found = cls._extract_number(child, keys)
                if found is not None:
                    return found
        return None

    @classmethod
    def _sum_numbers(cls, value: Any, left_keys: tuple[str, ...], right_keys: tuple[str, ...]) -> float | None:
        left = cls._extract_number(value, left_keys)
        right = cls._extract_number(value, right_keys)
        if left is None or right is None:
            return cls._extract_number(value, ("volumeUsd", "volume", "value"))
        return left + right

    @classmethod
    def _order_book_imbalance(cls, value: Any) -> float | None:
        direct = cls._extract_number(value, ("imbalance", "value"))
        if direct is not None:
            return direct
        bids = cls._extract_number(value, ("aggregated_bids_usd", "bids_usd"))
        asks = cls._extract_number(value, ("aggregated_asks_usd", "asks_usd"))
        if bids is None or asks is None or bids + asks <= 0:
            return None
        return (bids - asks) / (bids + asks)
