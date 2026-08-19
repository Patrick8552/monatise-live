from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class FlashAlphaAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class FlashAlphaAdapter:
    api_key: str
    base_url: str = "https://lab.flashalpha.com"
    timeout: float = 10

    @classmethod
    def from_env(cls) -> "FlashAlphaAdapter":
        return cls(
            os.getenv("FLASHALPHA_API_KEY", "").strip(),
            os.getenv("FLASHALPHA_API_BASE", "https://lab.flashalpha.com").rstrip("/"),
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def context(self, symbol: str) -> dict[str, Any]:
        ticker = symbol.upper()
        gex = self._get(f"/v1/exposure/gex/{ticker}")
        payload = gex if isinstance(gex, dict) else {}
        return {
            "source": "FlashAlpha",
            "symbol": ticker,
            "as_of": payload.get("as_of"),
            "underlying_price": payload.get("underlying_price"),
            "gamma_flip": payload.get("gamma_flip"),
            "net_gex": payload.get("net_gex"),
            "net_gex_label": payload.get("net_gex_label"),
        }

    def _get(self, path: str, query: dict[str, Any] | None = None) -> Any:
        if not self.configured:
            raise FlashAlphaAdapterError("FlashAlpha is not configured")
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        request = Request(
            url,
            headers={"Accept": "application/json", "X-Api-Key": self.api_key, "User-Agent": "Monatise/1.0"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise FlashAlphaAdapterError(f"FlashAlpha HTTP {error.code}") from error
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise FlashAlphaAdapterError(f"FlashAlpha unavailable: {type(error).__name__}") from error
