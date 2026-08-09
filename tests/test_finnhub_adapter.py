import json

import monatise.adapters.finnhub as finnhub_module
from monatise.adapters.finnhub import FinnhubAdapter


class Response:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self): return json.dumps(self.payload).encode()


def test_finnhub_context_uses_header_auth_and_collects_enrichment(monkeypatch):
    requests = []
    def fake_urlopen(request, timeout=10):
        requests.append(request)
        if "/quote?" in request.full_url: return Response({"c": 220})
        if "/company-news?" in request.full_url: return Response([{"headline": "news"}])
        return Response([{"buy": 10, "hold": 3}])
    monkeypatch.setattr(finnhub_module, "urlopen", fake_urlopen)
    context = FinnhubAdapter("token").context("NVDA")
    assert context["quote"]["c"] == 220 and len(context["news"]) == 1
    assert requests[0].headers["X-finnhub-token"] == "token"
