from types import SimpleNamespace

from monatise.application.deployment import OrchestrationRuntime


def test_price_change_parser_accepts_coinglass_24h_shape():
    assert OrchestrationRuntime._price_change_24h({"price_change_percent_24h": "18.25"}) == 18.25
    assert OrchestrationRuntime._price_change_24h({"price_change_24h": -21}) == -21.0


def test_price_change_parser_fails_closed():
    assert OrchestrationRuntime._price_change_24h({"price_change_percent_24h": "unknown"}) is None
    assert OrchestrationRuntime._price_change_24h({}) is None


def test_coinglass_supported_coin_normalization():
    adapter = SimpleNamespace()
    from monatise.adapters.coinglass_production import CoinGlassProductionAdapter
    instance = object.__new__(CoinGlassProductionAdapter)
    instance.dashboard_query = lambda path, params: {"code": "0", "data": ["btc", "NEW", "BTC", ""]}
    assert instance.supported_futures_coins() == ("BTC", "NEW")
