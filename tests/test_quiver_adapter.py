import json

import monatise.adapters.quiver as quiver_module
from monatise.adapters.quiver import QuiverAdapter, normalize_quiver_symbol, summarize_quiver_context


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_quiver_symbol_normalization_keeps_stock_and_etf_symbols() -> None:
    assert normalize_quiver_symbol("NASDAQ:NVDA") == "NVDA"
    assert normalize_quiver_symbol("qqq") == "QQQ"
    assert normalize_quiver_symbol("IXIC") == "NASDAQ"


def test_quiver_context_summarizes_mocked_dataset_rows(monkeypatch) -> None:  # noqa: ANN001
    requested_urls = []

    def fake_urlopen(request, timeout=8):  # noqa: ANN001, ARG001
        url = request.full_url
        requested_urls.append(url)
        if "congresstrading" in url:
            return FakeResponse([{"Ticker": "NVDA", "Transaction": "Purchase"}])
        if "insiders" in url:
            return FakeResponse([{"Ticker": "NVDA", "Transaction": "Buy"}, {"Ticker": "NVDA", "Transaction": "Sale"}])
        if "govcontracts" in url:
            return FakeResponse({"data": [{"Ticker": "NVDA", "Amount": 1000000}]})
        if "offexchange" in url:
            return FakeResponse([{"Ticker": "NVDA", "DPI": 0.42}])
        return FakeResponse([])

    monkeypatch.setattr(quiver_module, "urlopen", fake_urlopen)
    context = QuiverAdapter(api_key="secret").context("NVDA")

    assert context["configured"] is True
    assert context["available"] is True
    assert context["summary"]["bias"] == "supportive"
    assert context["summary"]["score"] >= 4
    assert len(context["datasets"]["insider"]) == 2
    assert "secret" not in str(context)
    assert any("/beta/historical/congresstrading/NVDA" in url for url in requested_urls)
    assert any("/beta/live/insiders?ticker=NVDA" in url for url in requested_urls)
    assert any("/beta/historical/govcontracts/NVDA" in url for url in requested_urls)
    assert any("/beta/historical/offexchange/NVDA" in url for url in requested_urls)
    assert any("/beta/live/quivernews?ticker=NVDA" in url for url in requested_urls)


def test_quiver_context_degrades_when_key_missing() -> None:
    context = QuiverAdapter(api_key="").context("AAPL")

    assert context["configured"] is False
    assert context["available"] is False
    assert context["summary"]["bias"] == "neutral"
    assert "QUIVER_API_KEY" in context["summary"]["detail"]


def test_quiver_summary_handles_empty_rows() -> None:
    summary = summarize_quiver_context("SPY", {"congress": [], "insider": []})

    assert summary["bias"] == "neutral"
    assert summary["score"] == 0
    assert summary["cautions"]
