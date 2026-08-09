import json
from datetime import datetime, timedelta, timezone
from urllib.error import URLError

import monatise.adapters.quiver as quiver_module
from monatise.adapters.quiver import QuiverAdapter, normalize_quiver_symbol, summarize_quiver_context


NOW = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)


def recent(days: int = 0) -> str:
    return (NOW - timedelta(days=days)).isoformat()


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
            return FakeResponse([{"Ticker": "NVDA", "Transaction": "Purchase", "ReportDate": datetime.now(timezone.utc).date().isoformat()}])
        if "insiders" in url:
            return FakeResponse([{"Ticker": "NVDA", "Transaction": "Buy", "Date": datetime.now(timezone.utc).isoformat()}, {"Ticker": "NVDA", "Transaction": "Sale", "Date": datetime.now(timezone.utc).isoformat()}])
        if "govcontracts" in url:
            return FakeResponse({"data": [{"Ticker": "NVDA", "Amount": 1000000}]})
        if "offexchange" in url:
            return FakeResponse([{"Ticker": "NVDA", "DPI": 0.42}])
        return FakeResponse([])

    monkeypatch.setattr(quiver_module, "urlopen", fake_urlopen)
    context = QuiverAdapter(api_key="secret").context("NVDA")

    assert context["configured"] is True
    assert context["available"] is True
    assert context["summary"]["bias"] == "watch"
    assert context["summary"]["score"] == 1
    assert context["summary"]["authority"] == "Quiver insider and Congress activity"
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


def test_quiver_summary_scores_sales_as_cautious() -> None:
    summary = summarize_quiver_context("NVDA", {"congress": [{"Transaction": "Sale", "ReportDate": recent(5)}] * 3, "insider": [{"TransactionCode": "S", "AcquiredDisposedCode": "D", "Date": recent(2)}] * 2}, now=NOW)
    assert summary["score"] == -4
    assert summary["bias"] == "cautious"


def test_quiver_summary_ignores_non_market_insider_acquisitions() -> None:
    summary = summarize_quiver_context("NVDA", {"congress": [], "insider": [{"TransactionCode": "A", "AcquiredDisposedCode": "A", "Date": recent(2)}] * 5}, now=NOW)
    assert summary["score"] == 0
    assert summary["activity"]["insiderBuys"] == 0


def test_quiver_summary_excludes_stale_or_undated_authority_rows() -> None:
    summary = summarize_quiver_context(
        "NVDA",
        {
            "congress": [
                {"Transaction": "Purchase", "ReportDate": recent(10)},
                {"Transaction": "Purchase", "ReportDate": recent(120)},
                {"Transaction": "Purchase"},
            ],
            "insider": [
                {"TransactionCode": "P", "Date": recent(5)},
                {"TransactionCode": "S", "Date": recent(40)},
                {"TransactionCode": "S", "Date": "invalid"},
            ],
        },
        now=NOW,
    )
    assert summary["score"] == 2
    assert summary["activity"] == {"congressBuys": 1, "congressSales": 0, "insiderBuys": 1, "insiderSales": 0}
    assert summary["freshness_days"] == {"congress": 90, "insider": 30}


def test_auxiliary_rows_do_not_mask_authoritative_dataset_failure(monkeypatch) -> None:  # noqa: ANN001
    def fake_urlopen(request, timeout=8):  # noqa: ANN001, ARG001
        if "congresstrading" in request.full_url or "insiders" in request.full_url:
            raise URLError("timeout")
        return FakeResponse([{"Ticker": "NVDA"}])

    monkeypatch.setattr(quiver_module, "urlopen", fake_urlopen)
    context = QuiverAdapter(api_key="secret").context("NVDA")
    assert context["available"] is False
    assert context["dataset_health"]["congress"]["ok"] is False
    assert context["dataset_health"]["news"]["ok"] is True
