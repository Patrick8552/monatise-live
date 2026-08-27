from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class FlashAlphaAdapterError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "provider_unavailable",
        status_code: int | None = None,
        rate_limit: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.rate_limit = dict(rate_limit or {})


@dataclass(frozen=True)
class FlashAlphaAdapter:
    api_key: str
    base_url: str = "https://lab.flashalpha.com"
    timeout: float = 10
    telemetry: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

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
        _raise_for_provider_payload(gex, expected=("underlying_price", "gamma_flip", "net_gex"))
        levels_response = self._get(f"/v1/exposure/levels/{encoded}")
        _raise_for_provider_payload(levels_response, expected=("levels", "underlying_price", "gamma_flip", "call_wall", "put_wall"))
        payload = gex if isinstance(gex, dict) else {}
        levels_payload = levels_response if isinstance(levels_response, dict) else {}
        levels = levels_payload.get("levels") if isinstance(levels_payload.get("levels"), dict) else {}
        return {
            "source": "FlashAlpha",
            "symbol": ticker,
            "as_of": levels_payload.get("as_of") or payload.get("as_of"),
            "underlying_price": levels_payload.get("underlying_price") or payload.get("underlying_price"),
            "gamma_flip": _level_value(levels.get("gamma_flip") or levels_payload.get("gamma_flip") or payload.get("gamma_flip")),
            "call_wall": _level_value(levels.get("call_wall") or levels_payload.get("call_wall") or payload.get("call_wall")),
            "put_wall": _level_value(levels.get("put_wall") or levels_payload.get("put_wall") or payload.get("put_wall")),
            "zero_dte_magnet": levels.get("zero_dte_magnet"),
            "net_gex": payload.get("net_gex"),
            "net_gex_label": payload.get("net_gex_label"),
        }

    def account(self) -> dict[str, Any]:
        """Return a sanitized account/quota view without identity fields."""
        payload, metadata = self._get_with_metadata("/v1/account")
        if not isinstance(payload, dict):
            raise FlashAlphaAdapterError("FlashAlpha returned malformed account data", code="provider_incomplete")
        result = {
            "status": "healthy",
            "plan": _text(payload.get("plan")),
            "daily_limit": _quota_value(payload.get("daily_limit")),
            "usage_today": _integer(payload.get("usage_today")),
            "remaining": _quota_value(payload.get("remaining")),
            "resets_at": _text(payload.get("resets_at") or payload.get("reset_at")),
            "rate_limit": metadata["rate_limit"],
        }
        self.telemetry.update({key: value for key, value in result.items() if value is not None})
        return result

    def probe(self, symbol: str = "AAPL") -> dict[str, Any]:
        """Make one authenticated provider request and return only diagnostics."""
        ticker = normalize_flashalpha_symbol(symbol)
        try:
            payload, metadata = self._get_with_metadata(f"/v1/exposure/gex/{quote(ticker, safe='')}")
            _raise_for_provider_payload(payload, expected=("underlying_price", "gamma_flip", "net_gex"))
            result = {
                "status": "healthy",
                "symbol": ticker,
                "http_status": metadata["http_status"],
                "rate_limit": metadata["rate_limit"],
            }
        except FlashAlphaAdapterError as error:
            result = {
                "status": error.code,
                "symbol": ticker,
                "http_status": error.status_code,
                "rate_limit": error.rate_limit,
            }
        self.telemetry.update({
            "status": result["status"],
            "last_probe_symbol": ticker,
            "last_probe_http_status": result["http_status"],
            "last_checked_at": datetime.now(timezone.utc).isoformat(),
            **result["rate_limit"],
        })
        return result

    def diagnose(self, symbol: str = "AAPL") -> dict[str, Any]:
        """Check the deployed credential's account and one direct symbol call."""
        try:
            account = self.account()
        except FlashAlphaAdapterError as error:
            account = {
                "status": error.code,
                "http_status": error.status_code,
                "rate_limit": error.rate_limit,
            }
        probe = self.probe(symbol)
        health = probe["status"] if probe["status"] != "healthy" else account["status"]
        result = {
            "status": health,
            "configured": self.configured,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "account": account,
            "probe": probe,
            "requests_per_analysis": 2,
        }
        self.telemetry.update({"status": health, "checked_at": result["checked_at"]})
        return result

    def health_snapshot(self) -> dict[str, Any]:
        """Return cached telemetry. This method never consumes provider quota."""
        return {"configured": self.configured, **self.telemetry}

    def _get(self, path: str, query: dict[str, Any] | None = None) -> Any:
        payload, _metadata = self._get_with_metadata(path, query)
        return payload

    def _get_with_metadata(self, path: str, query: dict[str, Any] | None = None) -> tuple[Any, dict[str, Any]]:
        if not self.configured:
            raise FlashAlphaAdapterError("FlashAlpha is not configured", code="auth_failed")
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        request = Request(
            url,
            headers={"Accept": "application/json", "X-Api-Key": self.api_key, "User-Agent": "Monatise/1.0"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                rate_limit = _rate_limit_headers(getattr(response, "headers", {}))
                self.telemetry.update(rate_limit)
                return json.loads(response.read().decode("utf-8")), {
                    "http_status": int(getattr(response, "status", 200)),
                    "rate_limit": rate_limit,
                }
        except HTTPError as error:
            rate_limit = _rate_limit_headers(getattr(error, "headers", {}))
            self.telemetry.update(rate_limit)
            code = {
                401: "auth_failed",
                403: "tier_restricted",
                404: "provider_unsupported",
                429: "rate_limited",
            }.get(error.code, "provider_down" if error.code >= 500 else "provider_unavailable")
            raise FlashAlphaAdapterError(
                f"FlashAlpha HTTP {error.code}", code=code, status_code=error.code, rate_limit=rate_limit,
            ) from error
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            code = "provider_timeout" if isinstance(error, TimeoutError) else "provider_down"
            raise FlashAlphaAdapterError(f"FlashAlpha unavailable: {type(error).__name__}", code=code) from error


def normalize_flashalpha_symbol(symbol: str) -> str:
    ticker = symbol.strip().upper()
    if not ticker:
        raise FlashAlphaAdapterError("FlashAlpha symbol is required")
    return ticker if ticker.endswith("=F") else ticker


def _level_value(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("strike") or value.get("level") or value.get("value")
    return value


def _raise_for_provider_payload(payload: Any, *, expected: tuple[str, ...]) -> None:
    if not isinstance(payload, dict) or any(payload.get(key) is not None for key in expected):
        return
    detail = " ".join(
        str(payload.get(key) or "") for key in ("detail", "error", "message", "status")
    ).casefold()
    if not detail.strip():
        return
    if any(term in detail for term in ("rate", "limit", "quota", "too many")):
        raise FlashAlphaAdapterError("FlashAlpha rate limit exceeded", code="rate_limited")
    if any(term in detail for term in ("plan", "tier", "entitlement", "upgrade", "access", "permission")):
        raise FlashAlphaAdapterError("FlashAlpha unsupported for the current account tier", code="tier_restricted")
    raise FlashAlphaAdapterError("FlashAlpha returned an unavailable provider payload", code="provider_unavailable")


def _header(headers: Any, name: str) -> str | None:
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return None
    value = getter(name)
    return str(value).strip() if value is not None and str(value).strip() else None


def _rate_limit_headers(headers: Any) -> dict[str, Any]:
    limit = _quota_value(_header(headers, "X-RateLimit-Limit"))
    remaining = _quota_value(_header(headers, "X-RateLimit-Remaining"))
    reset = _header(headers, "X-RateLimit-Reset")
    retry_after = _integer(_header(headers, "Retry-After"))
    result = {
        "daily_limit": limit,
        "remaining": remaining,
        "reset_epoch": _integer(reset),
        "retry_after_seconds": retry_after,
    }
    return {key: value for key, value in result.items() if value is not None}


def _quota_value(value: Any) -> int | str | None:
    if value is None:
        return None
    text = str(value).strip().casefold()
    if text == "unlimited":
        return "unlimited"
    try:
        return int(text)
    except ValueError:
        return None


def _integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    return str(value).strip() if value is not None and str(value).strip() else None
