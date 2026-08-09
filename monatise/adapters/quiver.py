from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
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

        requests = {
            "congress": (f"/beta/historical/congresstrading/{ticker}", None),
            "insider": ("/beta/live/insiders", {"ticker": ticker, "page_size": 20}),
            "governmentContracts": (f"/beta/historical/govcontracts/{ticker}", None),
            "lobbying": (f"/beta/historical/lobbying/{ticker}", {"page_size": 20}),
            "offExchange": (f"/beta/historical/offexchange/{ticker}", None),
            "news": ("/beta/live/quivernews", {"ticker": ticker, "page_size": 20}),
        }
        results = {name: self._optional_get(path, query) for name, (path, query) in requests.items()}
        datasets = {name: result[0] for name, result in results.items()}
        dataset_health = {name: {"ok": result[1], "error": result[2]} for name, result in results.items()}
        authority_healthy = all(dataset_health[name]["ok"] for name in ("congress", "insider"))
        authority_has_rows = any(datasets[name] for name in ("congress", "insider"))
        summary = summarize_quiver_context(ticker, datasets)
        return {
            "symbol": ticker,
            "source": "Quiver Quantitative",
            "configured": True,
            "available": authority_healthy and authority_has_rows,
            "datasets": datasets,
            "dataset_health": dataset_health,
            "summary": summary,
        }

    def _optional_get(self, path: str, query: dict[str, Any] | None = None) -> tuple[list[dict], bool, str | None]:
        try:
            payload = self._get(path, query)
        except QuiverAdapterError as error:
            return [], False, str(error)
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)][:20], True, None
        if isinstance(payload, dict):
            rows = payload.get("data") or payload.get("results") or payload.get("items") or []
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)][:20], True, None
            return [payload], True, None
        return [], True, None

    def _get(self, path: str, query: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": "Monatise/1.0",
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

    congress_rows = datasets.get("congress") or []
    purchases = sum(str(row.get("Transaction", "")).casefold() in {"purchase", "buy"} for row in congress_rows)
    sales = sum(str(row.get("Transaction", "")).casefold() in {"sale", "sell"} for row in congress_rows)
    insider_rows = datasets.get("insider") or []
    def insider_side(row: dict) -> int:
        transaction_code = str(row.get("TransactionCode", "")).upper().strip()
        transaction = str(row.get("Transaction", "")).casefold().strip()
        if transaction_code == "P" or transaction in {"buy", "purchase", "open market purchase"}:
            return 1
        if transaction_code == "S" or transaction in {"sell", "sale", "open market sale"}:
            return -1
        return 0

    insider_sides = [insider_side(row) for row in insider_rows]
    insider_buys = insider_sides.count(1)
    insider_sales = insider_sides.count(-1)

    if congress_count:
        score += max(-2, min(2, purchases - sales))
        drivers.append(f"{congress_count} Congress trade update{'s' if congress_count != 1 else ''}")
    if insider_count:
        score += max(-2, min(2, insider_buys - insider_sales))
        drivers.append(f"{insider_count} insider activity item{'s' if insider_count != 1 else ''}")
    if contract_count:
        drivers.append(f"{contract_count} government contract item{'s' if contract_count != 1 else ''}")
    if lobbying_count:
        drivers.append(f"{lobbying_count} lobbying disclosure{'s' if lobbying_count != 1 else ''}")
    if off_exchange_count:
        drivers.append("off-exchange flow available")
    if news_count:
        drivers.append(f"{news_count} Quiver news item{'s' if news_count != 1 else ''}")

    if not drivers:
        cautions.append("No fresh Quiver alternative-data rows returned")

    bias = "supportive" if score >= 2 else "cautious" if score <= -2 else "watch" if score else "neutral"
    detail = (
        f"{symbol} Quiver context: {', '.join(drivers[:4])}."
        if drivers
        else f"{symbol} Quiver context has no fresh alternative-data rows."
    )
    return {
        "bias": bias,
        "score": max(-10, min(10, score)),
        "activity": {"congressBuys": purchases, "congressSales": sales, "insiderBuys": insider_buys, "insiderSales": insider_sales},
        "authority": "Quiver insider and Congress activity",
        "drivers": drivers,
        "cautions": cautions,
        "detail": detail,
    }
