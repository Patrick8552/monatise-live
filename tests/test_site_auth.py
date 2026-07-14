from monatise.live.server import requires_platform_access, requires_site_auth


def test_market_data_routes_require_site_authentication() -> None:
    for path in (
        "/api/markets",
        "/api/assets",
        "/api/candles",
        "/api/analysis/fibonacci",
        "/api/context/radar",
        "/api/coinglass/context",
        "/api/quiver/context",
    ):
        assert requires_site_auth(path)


def test_platform_routes_require_paid_access() -> None:
    for path in (
        "/coinglass-dashboard.html",
        "/dashboard/",
        "/dashboard/index.html",
        "/api/status",
        "/api/markets",
        "/api/assets",
        "/api/candles",
        "/api/analysis/fibonacci",
        "/api/context/radar",
        "/api/coinglass/context",
        "/api/quiver/context",
        "/api/tradingview/signals",
        "/api/coinglass/proxy/api/futures/price/history",
    ):
        assert requires_platform_access(path)


def test_auth_bootstrap_routes_remain_public() -> None:
    for path in (
        "/api/health",
        "/api/operator",
        "/api/me",
        "/api/login",
        "/api/register",
        "/api/login-code/request",
        "/api/login-code/complete",
        "/api/password-reset/request",
        "/api/tradingview/webhook",
    ):
        assert not requires_site_auth(path)
        assert not requires_platform_access(path)
