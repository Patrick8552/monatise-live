from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


QUIVER_BASE_URL = "https://api.quiverquant.com"
QUIVER_TIMEOUT_SECONDS = 8
QUIVER_STOCK_SYMBOLS = {"AAPL", "TSLA", "NVDA", "QQQ", "SPY"}
QUIVER_INDEX_SYMBOLS = {"SPX", "NDX", "NASDAQ"}


class QuiverAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class QuiverAdapter:
    api_key: str = ""
    base_url: str = QUIVER_BASE_URL
    timeout: float = QUIVER_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> "QuiverAdapter":
        return cls(
            api_key=os.getenv("QUIVER_API_KEY", "").strip(),
            base_url=os.getenv("QUIVER_API_BASE", QUIVER_BASE_URL).rstrip("/"),
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def context(self, symbol: str) -> dict:
        ticker = normalize_quiver_symbol(symbol)
        if not ticker:
            return unavailable_context(symbol, "unsupported symbol")
        if not self.configured:
            return unavailable_context(ticker, "set QUIVER_API_KEY")
        if ticker in QUIVER_INDEX_SYMBOLS:
            return unavailable_context(ticker, "Quiver context is for single stocks and ETFs")

        datasets = {
            "congress": self._optional_get(f"/beta/live/congresstrading/{ticker}"),
            "insider": self._optional_get(f"/beta/live/insiders/{ticker}"),
            "governmentContracts": self._optional_get(f"/beta/live/govcontracts/{ticker}"),
            "lobbying": self._optional_get(f"/beta/live/lobbying/{ticker}"),
            "offExchange": self._optional_get(f"/beta/live/offexchange/{ticker}"),
            "news": self._optional_get(f"/beta/live/news/{ticker}"),
        }
        summary = summarize_quiver_context(ticker, datasets)
        return {
            "symbol": ticker,
            "source": "Quiver Quantitative",
            "configured": True,
            "available": any(isinstance(rows, list) and rows for rows in datasets.values()),
            "datasets": datasets,
            "summary": summary,
        }

    def _optional_get(self, path: str) -> list[dict]:
        try:
            payload = self._get(path)
        except QuiverAdapterError:
            return []
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)][:20]
        if isinstance(payload, dict):
            rows = payload.get("data") or payload.get("results") or payload.get("items") or []
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)][:20]
            return [payload]
        return []

    def _get(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                body = response.read().decode("utf-8")
        except HTTPError as error:
            raise QuiverAdapterError(f"Quiver HTTP {error.code}") from error
        except (TimeoutError, URLError, OSError) as error:
            raise QuiverAdapterError(f"Quiver unavailable: {error}") from error
        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            raise QuiverAdapterError("Quiver returned non-JSON data") from error


def normalize_quiver_symbol(symbol: str) -> str:
    raw = str(symbol or "").upper().strip()
    if ":" in raw:
        raw = raw.rsplit(":", 1)[-1]
    clean = "".join(character for character in raw if character.isalnum())
    aliases = {"IXIC": "NASDAQ"}
    return aliases.get(clean, clean[:12])


def unavailable_context(symbol: str, reason: str) -> dict:
    return {
        "symbol": normalize_quiver_symbol(symbol),
        "source": "Quiver Quantitative",
        "configured": False,
        "available": False,
        "reason": reason,
        "datasets": {},
        "summary": {
            "bias": "neutral",
            "score": 0,
            "drivers": [],
            "cautions": [reason],
            "detail": reason,
        },
    }


def summarize_quiver_context(symbol: str, datasets: dict[str, list[dict]]) -> dict:
    drivers: list[str] = []
    cautions: list[str] = []
    score = 0

    congress_count = len(datasets.get("congress") or [])
    insider_count = len(datasets.get("insider") or [])
    contract_count = len(datasets.get("governmentContracts") or [])
    lobbying_count = len(datasets.get("lobbying") or [])
    off_exchange_count = len(datasets.get("offExchange") or [])
    news_count = len(datasets.get("news") or [])

    if congress_count:
        score += min(2, congress_count)
        drivers.append(f"{congress_count} Congress trade update{'s' if congress_count != 1 else ''}")
    if insider_count:
        score += min(2, insider_count)
        drivers.append(f"{insider_count} insider activity item{'s' if insider_count != 1 else ''}")
    if contract_count:
        score += min(2, contract_count)
        drivers.append(f"{contract_count} government contract item{'s' if contract_count != 1 else ''}")
    if lobbying_count:
        score += 1
        drivers.append(f"{lobbying_count} lobbying disclosure{'s' if lobbying_count != 1 else ''}")
    if off_exchange_count:
        score += 1
        drivers.append("off-exchange flow available")
    if news_count:
        drivers.append(f"{news_count} Quiver news item{'s' if news_count != 1 else ''}")

    if not drivers:
        cautions.append("No fresh Quiver alternative-data rows returned")

    bias = "supportive" if score >= 4 else "watch" if score > 0 else "neutral"
    detail = (
        f"{symbol} Quiver context: {', '.join(drivers[:4])}."
        if drivers
        else f"{symbol} Quiver context has no fresh alternative-data rows."
    )
    return {
        "bias": bias,
        "score": min(10, score),
        "drivers": drivers,
        "cautions": cautions,
        "detail": detail,
    }
