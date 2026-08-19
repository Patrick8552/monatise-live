from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class AlpacaAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class AlpacaMarketDataAdapter:
    api_key: str
    api_secret: str
    base_url: str = "https://data.alpaca.markets"
    feed: str = "iex"
    timeout: float = 12
    trading_base_url: str = "https://paper-api.alpaca.markets"

    @classmethod
    def from_env(cls) -> "AlpacaMarketDataAdapter":
        return cls(
            os.getenv("ALPACA_API_KEY", "").strip(),
            os.getenv("ALPACA_API_SECRET", "").strip(),
            os.getenv("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets").rstrip("/"),
            os.getenv("ALPACA_DATA_FEED", "iex").strip() or "iex",
            float(os.getenv("ALPACA_TIMEOUT_SECONDS", "12")),
            os.getenv("ALPACA_TRADING_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/"),
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def stock_snapshot(self, symbol: str) -> dict[str, Any]:
        return self._get(f"/v2/stocks/{symbol.upper()}/snapshot", {"feed": self.feed})

    def stock_bars(self, symbol: str, timeframe: str = "1Hour", limit: int = 200) -> list[dict[str, Any]]:
        lookback_days = 365 if timeframe.strip().casefold() in {"1day", "day", "1d"} else 45
        start = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        payload = self._get(
            f"/v2/stocks/{symbol.upper()}/bars",
            {"timeframe": timeframe, "start": start, "limit": min(max(limit, 30), 1000), "sort": "desc", "feed": self.feed},
        )
        rows = payload.get("bars", []) if isinstance(payload, dict) else []
        # Descending order makes the limited page the most recent page.  The
        # analysis engine expects chronological order for ATR and breakouts.
        return list(reversed([row for row in rows if isinstance(row, dict)]))

    def active_stock_assets(self) -> list[dict[str, Any]]:
        payload = self._get_absolute(
            f"{self.trading_base_url}/v2/assets?{urlencode({'status': 'active', 'asset_class': 'us_equity'})}"
        )
        return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []

    def stock_snapshots(self, symbols: tuple[str, ...]) -> dict[str, dict[str, Any]]:
        clean = tuple(dict.fromkeys(str(symbol).upper().strip() for symbol in symbols if str(symbol).strip()))
        if not clean:
            return {}
        payload = self._get("/v2/stocks/snapshots", {"symbols": ",".join(clean), "feed": self.feed})
        snapshots = payload.get("snapshots", payload) if isinstance(payload, dict) else {}
        return {str(symbol).upper(): value for symbol, value in snapshots.items() if isinstance(value, dict)} if isinstance(snapshots, dict) else {}

    def _get(self, path: str, query: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise AlpacaAdapterError("Alpaca market data is not configured")
        request = Request(
            f"{self.base_url}{path}?{urlencode(query)}",
            headers={"Accept": "application/json", "APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.api_secret, "User-Agent": "Monatise/1.0"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise AlpacaAdapterError(f"Alpaca HTTP {error.code}") from error
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise AlpacaAdapterError(f"Alpaca market data unavailable: {type(error).__name__}") from error
        if not isinstance(payload, dict):
            raise AlpacaAdapterError("Alpaca returned an invalid payload")
        return payload

    def _get_absolute(self, url: str) -> Any:
        if not self.configured:
            raise AlpacaAdapterError("Alpaca market data is not configured")
        request = Request(
            url,
            headers={"Accept": "application/json", "APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.api_secret, "User-Agent": "Monatise/1.0"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise AlpacaAdapterError(f"Alpaca HTTP {error.code}") from error
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise AlpacaAdapterError(f"Alpaca market data unavailable: {type(error).__name__}") from error
