from types import SimpleNamespace
import pytest
from monatise.adapters.alpaca_gamma import AlpacaGammaProvider
from monatise.adapters.alpaca import AlpacaAdapterError
from monatise.application.gamma_reconstruction import GammaQualityError


def test_opra_forced_and_access_denial_backed_off_across_symbols():
    calls = []

    def fetch(path, query):
        calls.append((path, query))
        raise AlpacaAdapterError("Alpaca HTTP 403")

    provider = AlpacaGammaProvider(SimpleNamespace(_get=fetch))
    with pytest.raises(GammaQualityError, match="opra_access_denied"):
        provider.chain("SNOW")
    with pytest.raises(GammaQualityError, match="opra_access_denied_backoff"):
        provider.chain("AMD")
    assert len(calls) == 1 and calls[0][1]["feed"] == "opra"
    assert "indicative" not in str(calls)


def test_pagination_collects_all_pages_and_never_uses_filtered_updates():
    queries = []

    def fetch(query):
        queries.append(query)
        return (
            {"snapshots": {"B": {}}}
            if query.get("page_token")
            else {"snapshots": {"A": {}}, "next_page_token": "next"}
        )

    rows = AlpacaGammaProvider._pages(
        fetch, {"feed": "opra"}, "snapshots", __import__("time").monotonic()
    )
    assert set(rows) == {"A", "B"} and queries[1]["page_token"] == "next"
    assert not any("updated_since" in q for q in queries)


@pytest.mark.parametrize(
    "payload",
    [
        {"snapshots": {}, "next_page_token": ""},
        {"snapshots": []},
        {"snapshots": {"A": {}}, "next_page_token": "repeat"},
    ],
)
def test_incomplete_or_duplicate_pages_fail_closed(payload):
    with pytest.raises(GammaQualityError):
        AlpacaGammaProvider._pages(
            lambda q: payload, {}, "snapshots", __import__("time").monotonic()
        )


def test_contracts_and_snapshots_do_not_invent_pricing_inputs():
    calls = []

    def get(path, query):
        calls.append(query)
        return {"snapshots": {"SNOW-call": {}}}

    def absolute(url):
        calls.append(url)
        return {"option_contracts": [{"symbol": "SNOW-call", "open_interest": "5"}]}

    provider = AlpacaGammaProvider(
        SimpleNamespace(
            _get=get,
            _get_absolute=absolute,
            trading_base_url="https://paper-api.alpaca.markets",
        )
    )
    with pytest.raises(GammaQualityError, match="verified_pricing_inputs_unavailable"):
        provider.chain("SNOW")
    assert "expiration_date_lte=2099-12-31" in calls[1]
