import json

import monatise.adapters.flashalpha as flashalpha_module
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
        return Response({
            "symbol": "SPY",
            "underlying_price": 597.5,
            "as_of": "2026-02-28T16:30:45Z",
            "gamma_flip": 595.25,
            "net_gex": 2850000000,
            "net_gex_label": "positive",
        })
    monkeypatch.setattr(flashalpha_module, "urlopen", fake_urlopen)
    context = FlashAlphaAdapter("token").context("spy")
    assert context["symbol"] == "SPY"
    assert context["net_gex_label"] == "positive"
    assert context["gamma_flip"] == 595.25
    assert requests[0].full_url.endswith("/v1/exposure/gex/SPY")
    assert requests[0].headers["X-api-key"] == "token"


def test_flashalpha_context_raises_when_not_configured():
    try:
        FlashAlphaAdapter("").context("SPY")
    except FlashAlphaAdapterError:
        return
    raise AssertionError("expected FlashAlphaAdapterError when unconfigured")
