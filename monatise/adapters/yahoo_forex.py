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

    BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"

    def __init__(self, *, timeout: float = 10.0) -> None:
        self.timeout = timeout

    def candles(self, symbol: str, *, interval: str, range_: str, limit: int = 240) -> list[dict[str, Any]]:
        if not symbol.endswith("=X") or interval not in {"15m", "1h", "1d"}:
            raise YahooForexError("unsupported Yahoo forex request")
        url = f"{self.BASE_URL}/{quote(symbol, safe='=')}?{urlencode({'interval': interval, 'range': range_})}"
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "Monatise/1.0"})
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - fixed Yahoo host
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise YahooForexError(f"Yahoo forex data unavailable: {type(exc).__name__}") from exc
        try:
            result = payload["chart"]["result"][0]
            timestamps = result["timestamp"]
            quote_rows = result["indicators"]["quote"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise YahooForexError("Yahoo forex response is incomplete") from exc
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
        if len(rows) < 60:
            raise YahooForexError("Yahoo forex response has insufficient candles")
        return rows[-max(60, min(limit, 500)):]
