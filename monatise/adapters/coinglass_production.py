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

    ENDPOINTS = {
        "open_interest": "/api/futures/open-interest/exchange-list",
        "funding_rate": "/api/futures/funding-rate/oi-weight-history",
        "liquidations": "/api/futures/liquidation/aggregated-history",
        "volume": "/api/futures/volume/history",
        "order_book": "/api/futures/orderbook/ask-bids-history",
        "cvd": "/api/futures/taker-buy-sell-volume/history",
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
        self._failures = 0

    def open_interest(self, symbol: str) -> Any:
        return self._fetch("open_interest", symbol)

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

    def derivatives_snapshot(self, symbol: str) -> dict[str, float | None]:
        symbol = self._crypto_symbol(symbol)
        return {
            "open_interest": self._extract_number(self.open_interest(symbol), ("openInterest", "open_interest", "value")),
            "funding_rate": self._extract_number(self.funding_rate(symbol), ("fundingRate", "funding_rate", "value")),
            "liquidation_volume": self._extract_number(self.liquidations(symbol), ("liquidationUsd", "liquidation_volume", "value")),
            "derivatives_volume": self._extract_number(self.volume(symbol), ("volumeUsd", "volume", "value")),
            "order_book_imbalance": self._extract_number(self.order_book(symbol), ("imbalance", "value")),
            "cvd": self._extract_number(self.cvd(symbol), ("cvd", "value")),
        }

    def health(self) -> CoinGlassHealth:
        with self._lock:
            return CoinGlassHealth(self._last_success is not None and self._failures == 0, self._last_success, self._failures, len(self._cache))

    def _fetch(self, dataset: str, symbol: str) -> Any:
        coin = self._crypto_symbol(symbol)
        key = f"{dataset}:{coin}"
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
                payload = self._transport(self.ENDPOINTS[dataset], params, self._timeout)
                if str(payload.get("code")) not in {"0", "200"}:
                    raise CoinGlassError(str(payload.get("msg") or payload.get("message") or "CoinGlass rejected request"))
                data = payload.get("data", [])
                if not isinstance(data, (dict, list)):
                    raise CoinGlassError("CoinGlass data must be an object or array")
                with self._lock:
                    self._cache[key] = (time.monotonic(), deepcopy(data))
                    self._last_success = time.time()
                    self._failures = 0
                self._observe("coinglass.request", {"dataset": dataset, "attempt": attempt, "success": True})
                return deepcopy(data)
            except Exception as exc:
                last_error = exc
                with self._lock:
                    self._failures += 1
                self._observe("coinglass.request", {"dataset": dataset, "attempt": attempt, "success": False, "error": type(exc).__name__})
                if attempt < self._attempts:
                    time.sleep(min(2.0, 0.2 * 2 ** (attempt - 1)) + random.uniform(0, 0.05))
        raise CoinGlassError(f"CoinGlass {dataset} request failed") from last_error

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
