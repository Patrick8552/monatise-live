"""Read-only X recent-search adapter for macro and Bitcoin whale monitoring."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class XMacroPost:
    post_id: str
    text: str
    author_id: str
    created_at: datetime
    url: str
    category: str
    severity: str


class XMacroAdapter:
    """Fetches public X posts only; it has no write or account-management methods."""

    API_URL = "https://api.x.com/2/tweets/search/recent"
    WHALE_TERMS = (
        "sold bitcoin", "sells bitcoin", "selling bitcoin", "btc sale",
        "bitcoin sale", "exchange inflow", "deposited btc", "transferred btc to",
    )
    MACRO_TERMS = (
        "federal reserve", "interest rate", "cpi", "inflation", "nonfarm payroll",
        "tariff", "treasury yield", "bitcoin etf", "sec bitcoin",
    )

    def __init__(self, token_provider: Callable[[], str], *, timeout_seconds: float = 15.0) -> None:
        self._token_provider = token_provider
        self.timeout_seconds = timeout_seconds

    async def recent(self, query: str, *, max_results: int = 25) -> tuple[XMacroPost, ...]:
        return await asyncio.to_thread(self._recent, query, max_results)

    def _recent(self, query: str, max_results: int) -> tuple[XMacroPost, ...]:
        token = self._token_provider().strip()
        if not token:
            raise RuntimeError("X credential is unavailable")
        params = urlencode({
            "query": query,
            "max_results": min(100, max(10, int(max_results))),
            "tweet.fields": "author_id,created_at,public_metrics",
        })
        request = Request(
            f"{self.API_URL}?{params}",
            headers={"authorization": f"Bearer {token}", "user-agent": "monatise-readonly-x-monitor/1.0"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                if response.status >= 300:
                    raise RuntimeError("X recent-search request was rejected")
                payload = json.loads(response.read().decode())
        except Exception as exc:
            raise RuntimeError("X recent-search request failed") from exc
        rows = payload.get("data", [])
        return tuple(post for row in rows if (post := self._parse(row)) is not None)

    @classmethod
    def _parse(cls, row: dict[str, Any]) -> XMacroPost | None:
        post_id = str(row.get("id", "")).strip()
        text = " ".join(str(row.get("text", "")).split())
        if not post_id or not text:
            return None
        lowered = text.casefold()
        category = "btc_whale_sale" if any(term in lowered for term in cls.WHALE_TERMS) else "macro"
        if category == "macro" and not any(term in lowered for term in cls.MACRO_TERMS):
            return None
        metrics = row.get("public_metrics") or {}
        engagement = sum(int(metrics.get(key, 0) or 0) for key in ("like_count", "retweet_count", "reply_count", "quote_count"))
        severity = "critical" if category == "btc_whale_sale" else ("high" if engagement >= 100 else "watch")
        created_raw = str(row.get("created_at", "")).replace("Z", "+00:00")
        try:
            created_at = datetime.fromisoformat(created_raw).astimezone(timezone.utc)
        except ValueError:
            created_at = datetime.now(timezone.utc)
        author_id = str(row.get("author_id", "")).strip()
        return XMacroPost(post_id, text, author_id, created_at, f"https://x.com/i/web/status/{post_id}", category, severity)
