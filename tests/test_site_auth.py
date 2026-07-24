from __future__ import annotations

import io

from monatise.live.server import MonatiseHandler, requires_platform_access, requires_site_auth


def test_market_data_routes_are_open() -> None:
    for path in (
        "/api/markets",
        "/api/assets",
        "/api/candles",
        "/api/analysis/fibonacci",
        "/api/context/radar",
        "/api/memecoins/discover",
        "/api/memecoins/token",
    ):
        assert not requires_site_auth(path)


def test_sensitive_and_commercial_routes_require_login() -> None:
    for path in (
        "/api/status",
        "/api/coinglass/context",
        "/api/quiver/context",
        "/api/tradingview/signals",
        "/api/coinglass/proxy/api/futures/price/history",
    ):
        assert requires_platform_access(path)


def test_public_pages_and_analysis_do_not_require_login() -> None:
    for path in (
        "/coinglass-dashboard.html",
        "/dashboard/",
        "/dashboard/index.html",
        "/api/markets",
        "/api/assets",
        "/api/candles",
        "/api/analysis/fibonacci",
        "/api/context/radar",
    ):
        assert not requires_platform_access(path)


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


def test_openclaw_bearer_token_is_required(monkeypatch) -> None:
    monkeypatch.setenv("MONATISE_OPENCLAW_TOKEN", "read-only-secret")
    handler = MonatiseHandler.__new__(MonatiseHandler)
    handler.headers = {"Authorization": "Bearer read-only-secret"}

    assert handler._openclaw_authorized()

    handler.headers = {"Authorization": "Bearer wrong-secret"}
    handler._error = lambda status, message: setattr(handler, "authorization_error", (status, message))

    assert not handler._openclaw_authorized()
    assert handler.authorization_error[0] == 401


def test_dashboard_and_service_worker_disable_stale_browser_caching(monkeypatch) -> None:
    monkeypatch.setattr("http.server.SimpleHTTPRequestHandler.end_headers", lambda self: None)
    handler = MonatiseHandler.__new__(MonatiseHandler)
    captured = []
    handler.path = "/index.html?v=latest"
    handler.send_header = lambda key, value: captured.append((key, value))

    MonatiseHandler.end_headers(handler)

    assert ("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0") in captured
    assert ("Pragma", "no-cache") in captured


def test_platform_static_routes_are_served_to_guests() -> None:
    class Handler(MonatiseHandler):
        def _current_user(self):  # noqa: ANN202
            return None

        def _require_user(self):  # noqa: ANN202
            raise AssertionError("open dashboard should not require login")

        def send_response(self, code, message=None):  # noqa: ANN001, ANN201
            self.response_code = code

        def send_header(self, keyword, value):  # noqa: ANN001, ANN201
            pass

        def end_headers(self):  # noqa: ANN201
            pass

        def copyfile(self, source, outputfile):  # noqa: ANN001, ANN201
            pass

        def send_head(self):  # noqa: ANN201
            self.response_code = 200
            return io.BytesIO(b"")

        wfile = io.BytesIO()

    handler = Handler.__new__(Handler)
    handler.path = "/coinglass-dashboard.html"

    handler.do_GET()

    assert handler.response_code == 200
