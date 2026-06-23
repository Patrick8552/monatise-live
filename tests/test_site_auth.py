from monatise.live.server import requires_site_auth


def test_market_data_routes_require_site_authentication() -> None:
    for path in (
        "/api/markets",
        "/api/assets",
        "/api/candles",
        "/api/analysis/fibonacci",
        "/api/context/radar",
        "/api/coinglass/context",
        "/api/coinglass/proxy/api/futures/open-interest/exchange-list",
    ):
        assert requires_site_auth(path)


def test_auth_bootstrap_routes_remain_public() -> None:
    for path in (
        "/api/health",
        "/api/operator",
        "/api/me",
        "/api/login",
        "/api/register",
        "/api/password-reset/request",
        "/api/tradingview/webhook",
    ):
        assert not requires_site_auth(path)
