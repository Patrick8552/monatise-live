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
        "/api/coinglass/context",
        "/api/quiver/context",
    ):
        assert not requires_site_auth(path)


def test_platform_routes_do_not_require_paid_access() -> None:
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


def test_platform_static_routes_are_served_to_guests() -> None:
    class Handler(MonatiseHandler):
        def _current_user(self):  # noqa: ANN202
            return None

        def _require_user(self):  # noqa: ANN202
            raise AssertionError("static dashboard routes should redirect guests without writing a 401 first")

        def _redirect(self, location: str) -> None:
            raise AssertionError(f"open dashboard unexpectedly redirected to {location}")

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
