import json

import monatise.adapters.flashalpha as flashalpha_module
import pytest
from monatise.adapters.flashalpha import FlashAlphaAdapter, FlashAlphaAdapterError


class Response:
    def __init__(self, payload): self.payload = payload
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
    context = FlashAlphaAdapter("token").context("spy")
    assert context["symbol"] == "SPY"
    assert context["net_gex_label"] == "positive"
    assert context["gamma_flip"] == 595.25
    assert context["call_wall"] == 600
    assert [request.full_url.rsplit("/", 1)[0].rsplit("/", 1)[-1] for request in requests] == ["gex", "levels"]
    assert all(request.headers["X-api-key"] == "token" for request in requests)


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
