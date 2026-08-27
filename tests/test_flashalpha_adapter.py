import json
from io import BytesIO
from urllib.error import HTTPError

import monatise.adapters.flashalpha as flashalpha_module
import pytest
from monatise.adapters.flashalpha import FlashAlphaAdapter, FlashAlphaAdapterError


class Response:
    def __init__(self, payload, *, headers=None, status=200):
        self.payload, self.headers, self.status = payload, headers or {}, status
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self): return json.dumps(self.payload).encode()


def test_flashalpha_context_uses_header_auth_and_returns_gex_summary(monkeypatch):
    requests = []
    def fake_urlopen(request, timeout=10):
        requests.append(request)
        if "/levels/" in request.full_url:
            return Response({"symbol": "SPY", "underlying_price": 597.5, "levels": {"gamma_flip": 595.25, "call_wall": 600, "put_wall": 590}})
        return Response({"symbol": "SPY", "underlying_price": 597.5, "net_gex": 2850000000, "net_gex_label": "positive"})
    monkeypatch.setattr(flashalpha_module, "urlopen", fake_urlopen)
    adapter = FlashAlphaAdapter("token")
    context = adapter.context("spy")
    assert context["symbol"] == "SPY"
    assert context["net_gex_label"] == "positive"
    assert context["gamma_flip"] == 595.25
    assert context["call_wall"] == 600
    assert [request.full_url.rsplit("/", 1)[0].rsplit("/", 1)[-1] for request in requests] == ["gex", "levels"]
    assert all(request.headers["X-api-key"] == "token" for request in requests)
    assert adapter.health_snapshot()["status"] == "healthy"


def test_flashalpha_futures_symbol_is_url_encoded(monkeypatch):
    requests = []
    def fake_urlopen(request, timeout=10):
        requests.append(request)
        return Response({"symbol": "ES=F", "underlying_price": 6500, "levels": {"gamma_flip": 6450}} if "/levels/" in request.full_url else {"net_gex": 1})
    monkeypatch.setattr(flashalpha_module, "urlopen", fake_urlopen)
    context = FlashAlphaAdapter("token").context("ES=F")
    assert context["symbol"] == "ES=F"
    assert all("ES%3DF" in request.full_url for request in requests)


def test_flashalpha_context_raises_when_not_configured():
    try:
        FlashAlphaAdapter("").context("SPY")
    except FlashAlphaAdapterError:
        return
    raise AssertionError("expected FlashAlphaAdapterError when unconfigured")


def test_flashalpha_context_maps_quota_payload_to_explicit_failure(monkeypatch):
    monkeypatch.setattr(
        flashalpha_module,
        "urlopen",
        lambda request, timeout=10: Response({"detail": "Daily API quota limit exceeded"}),
    )
    with pytest.raises(FlashAlphaAdapterError, match="rate limit"):
        FlashAlphaAdapter("token").context("AAPL")


def test_flashalpha_context_maps_tier_payload_to_unsupported_failure(monkeypatch):
    monkeypatch.setattr(
        flashalpha_module,
        "urlopen",
        lambda request, timeout=10: Response({"message": "Upgrade your plan to access this symbol"}),
    )
    with pytest.raises(FlashAlphaAdapterError, match="current account tier"):
        FlashAlphaAdapter("token").context("ES=F")


def test_flashalpha_diagnostic_returns_sanitized_account_and_rate_headers(monkeypatch):
    requests = []
    headers = {
        "X-RateLimit-Limit": "2500", "X-RateLimit-Remaining": "1842",
        "X-RateLimit-Reset": "1787875200",
    }

    def fake_urlopen(request, timeout=10):
        requests.append(request.full_url)
        if request.full_url.endswith("/v1/account"):
            return Response({
                "user_id": "private-id", "email": "private@example.test", "plan": "growth",
                "daily_limit": "2500", "usage_today": 658, "remaining": "1842",
                "resets_at": "2026-08-28T00:00:00Z",
            }, headers=headers)
        return Response({"symbol": "AAPL", "underlying_price": 314, "net_gex": 1}, headers=headers)

    monkeypatch.setattr(flashalpha_module, "urlopen", fake_urlopen)
    result = FlashAlphaAdapter("token").diagnose("AAPL")

    assert result["status"] == "healthy"
    assert result["account"] == {
        "status": "healthy", "plan": "growth", "daily_limit": 2500,
        "usage_today": 658, "remaining": 1842, "resets_at": "2026-08-28T00:00:00Z",
        "rate_limit": {"daily_limit": 2500, "remaining": 1842, "reset_epoch": 1787875200},
    }
    assert result["probe"]["http_status"] == 200
    assert "email" not in json.dumps(result) and "user_id" not in json.dumps(result)
    assert requests == [
        "https://lab.flashalpha.com/v1/account",
        "https://lab.flashalpha.com/v1/exposure/gex/AAPL",
    ]


def test_flashalpha_probe_distinguishes_real_429_and_retry_headers(monkeypatch):
    def fake_urlopen(request, timeout=10):
        raise HTTPError(
            request.full_url, 429, "Too Many Requests",
            {"X-RateLimit-Limit": "5", "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1787875200", "Retry-After": "3600"},
            BytesIO(b'{"error":"Quota exceeded"}'),
        )

    monkeypatch.setattr(flashalpha_module, "urlopen", fake_urlopen)
    result = FlashAlphaAdapter("token").probe("AAPL")

    assert result == {
        "status": "rate_limited", "symbol": "AAPL", "http_status": 429,
        "rate_limit": {"daily_limit": 5, "remaining": 0, "reset_epoch": 1787875200, "retry_after_seconds": 3600},
    }
