from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class FinnhubAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class FinnhubAdapter:
    api_key: str
    base_url: str = "https://finnhub.io/api/v1"
    timeout: float = 10

    @classmethod
    def from_env(cls) -> "FinnhubAdapter":
        return cls(os.getenv("FINNHUB_API_KEY", "").strip(), os.getenv("FINNHUB_API_BASE", "https://finnhub.io/api/v1").rstrip("/"))

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def context(self, symbol: str) -> dict[str, Any]:
        ticker = symbol.upper()
        today = date.today()
        quote = self._get("/quote", {"symbol": ticker})
        news = self._get("/company-news", {"symbol": ticker, "from": (today - timedelta(days=7)).isoformat(), "to": today.isoformat()})
        recommendations = self._get("/stock/recommendation", {"symbol": ticker})
        earnings = self._get("/calendar/earnings", {"symbol": ticker, "from": today.isoformat(), "to": (today + timedelta(days=7)).isoformat()})
        earnings_rows = earnings.get("earningsCalendar", []) if isinstance(earnings, dict) else []
        return {
            "source": "Finnhub",
            "quote": quote if isinstance(quote, dict) else {},
            "news": [row for row in news if isinstance(row, dict)][:10] if isinstance(news, list) else [],
            "recommendations": [row for row in recommendations if isinstance(row, dict)][:3] if isinstance(recommendations, list) else [],
            "earnings": [row for row in earnings_rows if isinstance(row, dict)][:5] if isinstance(earnings_rows, list) else [],
        }

    def _get(self, path: str, query: dict[str, Any]) -> Any:
        if not self.configured:
            raise FinnhubAdapterError("Finnhub is not configured")
        request = Request(
            f"{self.base_url}{path}?{urlencode(query)}",
            headers={"Accept": "application/json", "X-Finnhub-Token": self.api_key, "User-Agent": "Monatise/1.0"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise FinnhubAdapterError(f"Finnhub HTTP {error.code}") from error
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise FinnhubAdapterError(f"Finnhub unavailable: {type(error).__name__}") from error
