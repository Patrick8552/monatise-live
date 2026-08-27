from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class YahooForexError(RuntimeError):
    pass


class YahooForexAdapter:
    """Read-only spot-FX candles used for analysis, never execution pricing."""

    BASE_URLS = (
        "https://query1.finance.yahoo.com/v8/finance/chart",
        "https://query2.finance.yahoo.com/v8/finance/chart",
    )

    def __init__(self, *, timeout: float = 10.0) -> None:
        self.timeout = timeout

    def candles(self, symbol: str, *, interval: str, range_: str, limit: int = 240) -> list[dict[str, Any]]:
        if not symbol.endswith("=X") or interval not in {"15m", "1h", "1d"}:
            raise YahooForexError("unsupported Yahoo forex request")
        failures: list[str] = []
        for base_url in self.BASE_URLS:
            url = f"{base_url}/{quote(symbol, safe='=')}?{urlencode({'interval': interval, 'range': range_})}"
            request = Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 Monatise/1.0"})
            try:
                with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - fixed Yahoo hosts
                    payload = json.loads(response.read().decode("utf-8"))
                result = payload["chart"]["result"][0]
                timestamps = result["timestamp"]
                quote_rows = result["indicators"]["quote"][0]
            except HTTPError as exc:
                failures.append(f"HTTP {exc.code}")
                continue
            except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                failures.append(type(exc).__name__)
                continue
            except (KeyError, IndexError, TypeError):
                failures.append("incomplete response")
                continue
            rows: list[dict[str, Any]] = []
            for index, timestamp in enumerate(timestamps):
                try:
                    values = {key: quote_rows[key][index] for key in ("open", "high", "low", "close")}
                except (KeyError, IndexError, TypeError):
                    continue
                if any(value is None for value in values.values()):
                    continue
                rows.append({
                    "t": datetime.fromtimestamp(int(timestamp), timezone.utc).isoformat(),
                    "o": float(values["open"]), "h": float(values["high"]),
                    "l": float(values["low"]), "c": float(values["close"]),
                })
            if len(rows) >= 60:
                return rows[-max(60, min(limit, 500)):]
            failures.append("insufficient candles")
        detail = ", ".join(failures) if failures else "unknown upstream failure"
        raise YahooForexError(f"Yahoo forex data unavailable: {detail}")
