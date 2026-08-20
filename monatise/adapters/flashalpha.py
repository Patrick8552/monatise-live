from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
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
        ticker = normalize_flashalpha_symbol(symbol)
        encoded = quote(ticker, safe="")
        gex = self._get(f"/v1/exposure/gex/{encoded}")
        levels_response = self._get(f"/v1/exposure/levels/{encoded}")
        payload = gex if isinstance(gex, dict) else {}
        levels_payload = levels_response if isinstance(levels_response, dict) else {}
        levels = levels_payload.get("levels") if isinstance(levels_payload.get("levels"), dict) else {}
        return {
            "source": "FlashAlpha",
            "symbol": ticker,
            "as_of": levels_payload.get("as_of") or payload.get("as_of"),
            "underlying_price": levels_payload.get("underlying_price") or payload.get("underlying_price"),
            "gamma_flip": levels.get("gamma_flip") or payload.get("gamma_flip"),
            "call_wall": levels.get("call_wall"),
            "put_wall": levels.get("put_wall"),
            "zero_dte_magnet": levels.get("zero_dte_magnet"),
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


def normalize_flashalpha_symbol(symbol: str) -> str:
    ticker = symbol.strip().upper()
    if not ticker:
        raise FlashAlphaAdapterError("FlashAlpha symbol is required")
    return ticker if ticker.endswith("=F") else ticker
