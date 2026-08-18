"""Resilient, read-only CoinGlass market intelligence adapter."""

from __future__ import annotations

import json
import random
import re
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


@dataclass(frozen=True)
class CoinGlassFuturesAsset:
    base_asset: str
    instrument: str
    exchange: str
    quote_asset: str
    source: str
    supported_coins_observed_at: str
    market_observed_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "base_asset": self.base_asset,
            "instrument": self.instrument,
            "exchange": self.exchange,
            "quote_asset": self.quote_asset,
            "source": self.source,
            "supported_coins_observed_at": self.supported_coins_observed_at,
            "market_observed_at": self.market_observed_at,
        }


class CoinGlassProductionAdapter:
    """Fetches and normalizes data only; it contains no analytical rules."""

    SUPPORTED_INTERVALS = ("1m", "3m", "5m", "15m", "30m", "1h", "4h", "6h", "8h", "12h", "1d", "1w")

    # /api/futures/open-interest/exchange-list only ever exposes six discrete
    # change windows (5m/15m/30m/1h/4h/24h) -- confirmed exhaustive against the
    # documented response shape, not just an example. Every SUPPORTED_INTERVALS
    # entry maps to its exact window where one exists, otherwise the nearest
    # available window, so no analysis interval silently loses OI-change data.
    OPEN_INTEREST_CHANGE_WINDOW = {
        "1m": "5m", "3m": "5m", "5m": "5m",
        "15m": "15m", "30m": "30m", "1h": "1h",
        "4h": "4h", "6h": "4h", "8h": "4h", "12h": "4h",
        "1d": "24h", "1w": "24h",
    }

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
        "/api/futures/supported-exchange-pairs": {"exchange"},
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
        self._resolved_assets: dict[str, CoinGlassFuturesAsset] = {}

    def resolve_futures_asset(self, value: str) -> CoinGlassFuturesAsset:
        """Resolve a user ticker to a verified CoinGlass futures market."""
        base, requested_pair = self._requested_crypto_asset(value)
        if requested_pair is None:
            with self._lock:
                cached_resolution = self._resolved_assets.get(base)
            if cached_resolution is not None:
                return cached_resolution
        observed_at = self._utc_timestamp()
        supported = set(self.supported_futures_coins())
        if base not in supported:
            raise ValueError(f"CoinGlass does not list {base} as a supported futures coin")
        instruments = self.supported_exchange_pairs()
        verified = {
            (exchange.casefold(), instrument.upper()): (row_base, quote)
            for exchange, instrument, row_base, quote in instruments
            if row_base == base
        }
        rows = self._fetch("pairs_markets", base)
        if not isinstance(rows, list):
            raise CoinGlassError("CoinGlass pairs markets data must be a list")
        candidates: list[tuple[float, str, str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            instrument = str(row.get("instrument_id") or row.get("symbol") or "").strip().upper()
            exchange = str(row.get("exchange_name") or row.get("exchange") or "").strip()
            row_base = str(row.get("base_asset") or base).strip().upper()
            quote = str(row.get("quote_asset") or "").strip().upper()
            if not quote and instrument.startswith(base):
                quote = instrument[len(base):].removesuffix("PERP").strip("-_/")
            authoritative = verified.get((exchange.casefold(), instrument))
            if authoritative is None or authoritative != (row_base, quote):
                continue
            if row_base != base or not instrument or not exchange or quote not in {"USDT", "USDC", "USD"}:
                continue
            if requested_pair and instrument.replace("-", "").replace("_", "").replace("/", "") != requested_pair:
                continue
            price = self._safe_positive(row.get("current_price"))
            if price is None:
                continue
            activity = self._safe_positive(row.get("volume_usd") or row.get("volume_24h_usd") or row.get("turnover_24h")) or 0.0
            candidates.append((activity, exchange, instrument, quote))
        if not candidates:
            raise ValueError(f"CoinGlass returned no usable futures market for {value.strip().upper()}")
        candidates.sort(key=lambda item: (-item[0], item[1].casefold(), item[2]))
        if len(candidates) > 1 and candidates[0][0] == candidates[1][0] == 0 and (candidates[0][2], candidates[0][3]) != (candidates[1][2], candidates[1][3]):
            raise ValueError(f"ambiguous CoinGlass futures symbol: {value.strip().upper()}")
        _, exchange, instrument, quote = candidates[0]
        resolved = CoinGlassFuturesAsset(base, instrument, exchange, quote, "CoinGlass futures supported-coins + supported-exchange-pairs + pairs-markets", observed_at, self._utc_timestamp())
        with self._lock:
            self._resolved_assets[base] = resolved
        return resolved

    def _resolved(self, symbol: str) -> CoinGlassFuturesAsset | None:
        with self._lock:
            return self._resolved_assets.get(self._crypto_symbol(symbol))

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
        resolved = self._resolved(coin)
        expected_pair = resolved.instrument if resolved else self.PAIRS.get(coin, f"{coin}USDT")
        expected_exchange = resolved.exchange.casefold() if resolved else "binance"
        for row in rows:
            if not isinstance(row, dict):
                continue
            exchange = str(row.get("exchange_name", "")).casefold()
            instrument = str(row.get("instrument_id", "")).upper()
            if exchange == expected_exchange and instrument == expected_pair:
                try:
                    return float(row["current_price"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise CoinGlassError("CoinGlass returned an invalid current price") from exc
        raise CoinGlassError(f"CoinGlass returned no {expected_exchange} current price for {expected_pair}")

    def candles(self, symbol: str, limit: int, interval: str = "1h") -> list[Candle]:
        coin = self._crypto_symbol(symbol)
        resolved = self._resolved(coin)
        data = self._fetch(
            "price_history",
            coin,
            params={
                "exchange": resolved.exchange if resolved else "Binance",
                "symbol": resolved.instrument if resolved else self.PAIRS.get(coin, f"{coin}USDT"),
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

    def funding_rate(self, symbol: str, interval: str = "1h") -> Any:
        return self._fetch("funding_rate", symbol, interval=interval)

    def liquidations(self, symbol: str, interval: str = "1h") -> Any:
        return self._fetch("liquidations", symbol, interval=interval)

    def volume(self, symbol: str, interval: str = "1h") -> Any:
        return self._fetch("volume", symbol, interval=interval)

    def order_book(self, symbol: str, interval: str = "1h") -> Any:
        return self._fetch("order_book", symbol, interval=interval)

    def cvd(self, symbol: str, interval: str = "1h") -> Any:
        return self._fetch("cvd", symbol, interval=interval)

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

    def supported_exchange_pairs(self) -> tuple[tuple[str, str, str, str], ...]:
        """Return authoritative (exchange, instrument, base, quote) futures tuples."""
        payload = self.dashboard_query("/api/futures/supported-exchange-pairs", {})
        data = payload.get("data", {})
        if not isinstance(data, dict):
            raise CoinGlassError("CoinGlass supported exchange pairs must be an object")
        result: list[tuple[str, str, str, str]] = []
        for exchange, rows in data.items():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                instrument = str(row.get("instrument_id") or "").strip().upper()
                base = str(row.get("base_asset") or "").strip().upper()
                quote = str(row.get("quote_asset") or "").strip().upper()
                if exchange and instrument and base and quote:
                    result.append((str(exchange).strip(), instrument, base, quote))
        return tuple(result)

    def futures_price_changes(self) -> tuple[dict[str, Any], ...]:
        payload = self.dashboard_query("/api/futures/coins-price-change", {})
        rows = payload.get("data", [])
        if not isinstance(rows, list):
            raise CoinGlassError("CoinGlass price changes must be a list")
        return tuple(row for row in rows if isinstance(row, dict))

    def derivatives_snapshot(self, symbol: str, interval: str = "1h") -> dict[str, float | None]:
        symbol = self._crypto_symbol(symbol)
        # Every dataset below is fetched at the requested analysis interval,
        # not a fixed 1h -- otherwise a 15m/4h/1d analysis would silently
        # judge order flow against 1h-old context regardless of what was asked.
        volume = self.volume(symbol, interval)
        order_book = self.order_book(symbol, interval)
        cvd_history = self.cvd(symbol, interval)
        cvd_keys = ("cum_vol_delta", "cvd", "value")
        open_interest_rows = self.open_interest(symbol)
        oi_window = self.OPEN_INTEREST_CHANGE_WINDOW.get(interval, "1h")
        liquidation_history = self.liquidations(symbol, interval)
        long_liquidation = self._extract_number(liquidation_history, ("aggregated_long_liquidation_usd", "long_liquidation_usd"))
        short_liquidation = self._extract_number(liquidation_history, ("aggregated_short_liquidation_usd", "short_liquidation_usd"))
        return {
            "open_interest": self._extract_number(open_interest_rows, ("open_interest_usd", "openInterest", "open_interest", "value")),
            # Percentage change over the nearest CoinGlass-supported window to
            # the requested interval (see OPEN_INTEREST_CHANGE_WINDOW) -- CoinGlass
            # only exposes 5m/15m/30m/1h/4h/24h change fields, never an absolute
            # level mislabeled as a change. open_interest itself has no interval
            # parameter (it's a live cross-exchange snapshot, not a history).
            "open_interest_change_pct": self._extract_number(open_interest_rows, (f"open_interest_change_percent_{oi_window}",)),
            "funding_rate": self._extract_number(self.funding_rate(symbol, interval), ("close", "fundingRate", "funding_rate", "value")),
            "liquidation_volume": (long_liquidation or 0.0) + (short_liquidation or 0.0) if (long_liquidation is not None or short_liquidation is not None) else self._extract_number(liquidation_history, ("liquidation_usd", "liquidationUsd", "liquidation_volume", "value")),
            "liquidation_long_usd": long_liquidation,
            "liquidation_short_usd": short_liquidation,
            "derivatives_volume": self._sum_numbers(volume, ("aggregated_buy_volume_usd", "taker_buy_volume_usd"), ("aggregated_sell_volume_usd", "taker_sell_volume_usd")),
            "order_book_imbalance": self._order_book_imbalance(order_book),
            "cvd": self._extract_number(cvd_history, cvd_keys),
            # Net order-flow direction over the fetched window (last minus first
            # observed cumulative volume delta) -- distinct from the single
            # latest "cvd" point above, which carries no directional history.
            "cvd_delta": self._extract_delta(cvd_history, cvd_keys),
        }

    @staticmethod
    def _utc_timestamp() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _safe_positive(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    @staticmethod
    def _requested_crypto_asset(value: str) -> tuple[str, str | None]:
        if not isinstance(value, str):
            raise ValueError("crypto symbol must be a string")
        raw = value.strip().upper()
        if not raw or len(raw) > 32 or not re.fullmatch(r"[A-Z0-9]+(?:[-_/][A-Z0-9]+)?", raw):
            raise ValueError("malformed crypto ticker or pair")
        compact = raw.replace("-", "").replace("_", "").replace("/", "")
        fiat = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"}
        if len(compact) == 6 and compact[:3] in fiat and compact[3:] in fiat:
            raise ValueError("forex markets are not supported")
        for quote in ("USDT", "USDC", "USD"):
            if compact.endswith(quote) and len(compact) > len(quote):
                base = compact[:-len(quote)]
                if base in fiat:
                    raise ValueError("forex markets are not supported")
                return base, compact
        if compact in fiat or not re.fullmatch(r"[A-Z0-9]{2,20}", compact):
            raise ValueError("unsupported crypto ticker")
        return compact, None

    def health(self) -> CoinGlassHealth:
        with self._lock:
            return CoinGlassHealth(self._last_success is not None and self._critical_failures == 0, self._last_success, self._critical_failures, len(self._cache))

    def _fetch(self, dataset: str, symbol: str, *, params: dict[str, str] | None = None, interval: str = "1h") -> Any:
        coin = self._crypto_symbol(symbol)
        request_params = dict(params or self._dataset_params(dataset, coin, interval))
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

    def _dataset_params(self, dataset: str, coin: str, interval: str = "1h") -> dict[str, str]:
        resolved = self._resolved(coin)
        pair = resolved.instrument if resolved else self.PAIRS.get(coin, f"{coin}USDT")
        exchange = resolved.exchange if resolved else "Binance"
        if dataset == "pairs_markets":
            return {"symbol": coin}
        if dataset == "open_interest":
            return {"symbol": coin}
        if dataset == "funding_rate":
            return {"symbol": coin, "interval": interval, "limit": "2"}
        if dataset == "liquidations":
            return {
                "exchange_list": exchange,
                "symbol": coin,
                "interval": interval,
                "limit": "2",
            }
        if dataset in {"volume", "cvd"}:
            return {"exchange_list": exchange, "symbol": coin, "interval": interval, "limit": "2"}
        if dataset == "order_book":
            return {"exchange_list": exchange, "symbol": coin, "interval": interval, "limit": "2", "range": "1"}
        if dataset == "price_history":
            return {"exchange": exchange, "symbol": pair, "interval": interval, "limit": "2"}
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
    def _extract_delta(cls, value: Any, keys: tuple[str, ...]) -> float | None:
        """Net change across a fetched history window (last row minus first row)."""
        if not isinstance(value, list) or len(value) < 2:
            return None
        first = cls._extract_number(value[0], keys)
        last = cls._extract_number(value[-1], keys)
        if first is None or last is None:
            return None
        return last - first

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
