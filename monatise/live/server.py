from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from monatise.analysis.context import context_assets, grid_instruction, indicator_snapshot
from monatise.analysis.fibonacci import analyze_fibonacci
from monatise.analysis.fvg import analyze_fvg
from monatise.adapters.coinglass import CoinGlassAdapter
from monatise.adapters.hyperliquid import HyperliquidAdapter
from monatise.live.config import RuntimeConfig
from monatise.live.emailer import EmailDeliveryError, expose_dev_reset_code, send_password_reset_code
from monatise.live.service import JsonEncoder, TradingService
from monatise.live.users import User, UserCredentials, UserStore, encryption_key_configured

COMMODITY_WATCHLIST = ("GOLD", "CL", "BRENTOIL")
FOREX_WATCHLIST = ("EURUSD", "GBPUSD", "USDJPY", "XAG")
STOCK_WATCHLIST = ("SPX", "NDX", "NASDAQ", "AAPL", "TSLA", "NVDA")


def _is_email(value: str) -> bool:
    value = value.strip()
    return "@" in value and "." in value.rsplit("@", 1)[-1] and " " not in value


def _market_data_adapter(config: RuntimeConfig, symbol: str):  # noqa: ANN202
    if config.data_feed == "coinglass":
        try:
            return CoinGlassAdapter(config), "CoinGlass futures price history"
        except Exception:  # noqa: BLE001
            if symbol.split("-", 1)[0].upper() not in {"GOLD", "XAU", "CL", "BRENTOIL"}:
                raise
    return HyperliquidAdapter(config), "Hyperliquid candleSnapshot"


class TenantServices:
    def __init__(self, base_config: RuntimeConfig, store: UserStore) -> None:
        self.base_config = base_config
        self.store = store
        self._services: dict[int, TradingService] = {}
        self._lock = threading.Lock()

    def service_for_user(self, user: User) -> TradingService:
        with self._lock:
            service = self._services.get(user.id)
            if service is not None:
                return service
            credentials = self.store.credentials_for_user(user.id)
            if credentials is None:
                raise ValueError("save private sync details before starting private sync")
            settings = self.store.settings_for_user(user.id)
            config = replace(
                self.base_config,
                symbol=settings.selected_symbol,
                account_address=credentials.account_address,
                chart_interval=settings.chart_interval,
                signal_session_window=settings.signal_session_window,
                leverage=settings.leverage,
                order_quote_size=settings.order_quote_size,
                max_order_notional=settings.max_order_notional,
                max_total_notional=settings.max_total_notional,
                max_position_value=settings.max_position_value,
                london_commodity_only=settings.london_commodity_only,
                max_daily_loss_pct=settings.max_daily_loss_pct,
                secret_key=credentials.secret_key,
                session_guard_minutes=settings.session_guard_minutes,
                stale_grid_cancel=settings.stale_grid_cancel,
            )
            service = TradingService(config)
            self._services[user.id] = service
            return service

    def reset_user(self, user_id: int) -> None:
        with self._lock:
            service = self._services.pop(user_id, None)
        if service is not None:
            service.stop()


def settings_payload(settings) -> dict:  # noqa: ANN001
    return {
        "chartInterval": settings.chart_interval,
        "signalSessionWindow": settings.signal_session_window,
        "leverage": settings.leverage,
        "orderQuoteSize": settings.order_quote_size,
        "maxOrderNotional": settings.max_order_notional,
        "maxTotalNotional": settings.max_total_notional,
        "maxPositionValue": settings.max_position_value,
        "londonCommodityOnly": settings.london_commodity_only,
        "maxDailyLossPct": settings.max_daily_loss_pct,
        "sessionGuardMinutes": settings.session_guard_minutes,
        "staleGridCancel": settings.stale_grid_cancel,
    }


class MarketFeed:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self._adapter: HyperliquidAdapter | None = None
        self._prices: dict[str, float] = {}
        self._all_prices: dict[str, float] = {}
        self._updated_at = 0.0
        self._lock = threading.Lock()

    def snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            if now - self._updated_at > 2:
                if self._adapter is None:
                    self._adapter = HyperliquidAdapter(self.config)
                self._all_prices = self._adapter.all_prices()
                self._prices = {
                    symbol: self._all_prices[symbol]
                    for symbol in self.config.assets
                    if symbol in self._all_prices
                }
                self._updated_at = now
            builder = [
                {"symbol": coin, "price": price, "tradable": True}
                for coin, price in sorted(self._all_prices.items())
                if ":" in coin
            ][:18]
            return {
                "assets": [
                    {"symbol": symbol, "price": self._prices.get(symbol)}
                    for symbol in self.config.assets
                ],
                "groups": {
                    "crypto": [
                        {"symbol": symbol, "price": self._prices.get(symbol), "tradable": symbol in self._prices}
                        for symbol in self.config.assets
                    ],
                    "builder": builder,
                    "commodities": self._watchlist(COMMODITY_WATCHLIST),
                    "forex": self._watchlist(FOREX_WATCHLIST),
                    "stocks": self._watchlist(STOCK_WATCHLIST),
                },
                "updatedAt": self._updated_at,
            }

    def _watchlist(self, symbols: tuple[str, ...]) -> list[dict]:
        return [
            {"symbol": symbol, "price": self._all_prices.get(symbol), "tradable": symbol in self._all_prices}
            for symbol in symbols
        ]


class MonatiseHandler(SimpleHTTPRequestHandler):
    tenants: TenantServices
    market_feed: MarketFeed
    store: UserStore
    config: RuntimeConfig
    app_dir: Path
    rate_limits: dict[str, list[float]] = {}
    rate_lock = threading.Lock()

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, directory=str(self.app_dir), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._json({"ok": True})
            return
        if parsed.path == "/api/markets":
            try:
                self._json(self.market_feed.snapshot())
            except Exception as error:  # noqa: BLE001
                self._error(502, str(error))
            return
        if parsed.path == "/api/candles":
            query = parse_qs(parsed.query)
            symbol = str(query.get("symbol", [self.config.symbol])[0]).strip().upper()
            interval = str(query.get("interval", ["15m"])[0]).strip() or "15m"
            try:
                limit = max(5, min(240, int(query.get("limit", ["120"])[0])))
                adapter, source = _market_data_adapter(self.config, symbol)
                candles = adapter.candles(symbol, limit, interval=interval)
                self._json(
                    {
                        "candles": [candle.__dict__ for candle in candles],
                        "interval": interval,
                        "source": source,
                        "symbol": symbol,
                    }
                )
            except Exception as error:  # noqa: BLE001
                self._error(502, str(error))
            return
        if parsed.path == "/api/analysis/fibonacci":
            query = parse_qs(parsed.query)
            symbol = str(query.get("symbol", [self.config.symbol])[0]).strip().upper()
            interval = str(query.get("interval", ["15m"])[0]).strip() or "15m"
            try:
                limit = max(20, min(240, int(query.get("limit", ["120"])[0])))
                adapter, source = _market_data_adapter(self.config, symbol)
                candles = adapter.candles(symbol, limit, interval=interval)
                mark = candles[-1].close
                if isinstance(adapter, HyperliquidAdapter):
                    mark = adapter.latest_price(symbol)
                self._json(
                    {
                        "analysis": analyze_fibonacci(symbol, interval, candles, mark=mark).to_dict(),
                        "candles": [candle.__dict__ for candle in candles],
                        "fvg": analyze_fvg(symbol, interval, candles, mark=mark).to_dict(),
                        "source": source,
                    }
                )
            except Exception as error:  # noqa: BLE001
                self._error(502, str(error))
            return
        if parsed.path == "/api/context/radar":
            query = parse_qs(parsed.query)
            symbol = str(query.get("symbol", [self.config.symbol])[0]).strip().upper()
            interval = str(query.get("interval", ["15m"])[0]).strip() or "15m"
            try:
                limit = max(50, min(240, int(query.get("limit", ["120"])[0])))
                adapter, source = _market_data_adapter(self.config, symbol)
                candles = adapter.candles(symbol, limit, interval=interval)
                indicators = indicator_snapshot(candles)
                prices = HyperliquidAdapter(self.config).all_prices()
                instruction = grid_instruction(indicators)
                self._json(
                    {
                        "symbol": symbol,
                        "interval": interval,
                        "source": source,
                        "indicator": indicators.__dict__,
                        "instruction": instruction,
                        "contextAssets": context_assets(symbol, prices),
                        "sources": [
                            {
                                "label": "Hyperliquid candleSnapshot",
                                "url": "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint",
                            },
                            {
                                "label": "EIA Weekly Petroleum Status Report",
                                "url": "https://www.eia.gov/petroleum/supply/weekly/index.php",
                            },
                            {
                                "label": "ICE U.S. Dollar Index",
                                "url": "https://www.ice.com/market-data/indices/currency-indices",
                            },
                            {
                                "label": "CME FedWatch",
                                "url": "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
                            },
                        ],
                    }
                )
            except Exception as error:  # noqa: BLE001
                self._error(502, str(error))
            return
        if parsed.path == "/api/coinglass/context":
            query = parse_qs(parsed.query)
            symbol = str(query.get("symbol", [self.config.symbol])[0]).strip().upper()
            interval = str(query.get("interval", ["1h"])[0]).strip() or "1h"
            try:
                adapter = CoinGlassAdapter(self.config)
                self._json(
                    {
                        "symbol": symbol,
                        "source": "CoinGlass",
                        "openInterest": adapter.open_interest(symbol),
                        "liquidations": adapter.liquidation_history(symbol, limit=24, interval=interval),
                    }
                )
            except Exception as error:  # noqa: BLE001
                self._error(502, str(error))
            return
        if parsed.path == "/api/me":
            user = self._current_user()
            if user is None:
                self._json({"authenticated": False})
                return
            settings = self.store.settings_for_user(user.id)
            self._json(
                {
                    "authenticated": True,
                    "username": user.username,
                    "credentialsConfigured": self.store.has_credentials(user.id),
                    "selectedSymbol": settings.selected_symbol,
                    "subscription": {
                        "plan": settings.subscription_plan,
                        "status": settings.subscription_status,
                    },
                    "tradingRules": settings_payload(settings),
                }
            )
            return
        if parsed.path == "/api/status":
            user = self._require_user()
            if user is None:
                return
            try:
                service = self.tenants.service_for_user(user)
                self._json(service.snapshot())
            except ValueError as error:
                self._json(
                    {
                        "running": False,
                        "mode": self.tenants.base_config.mode,
                        "network": self.tenants.base_config.network,
                        "symbol": self.store.settings_for_user(user.id).selected_symbol,
                        "riskStatus": str(error),
                        "requires": ["Private sync details"],
                        "events": [{"timestamp": 0, "level": "warn", "message": str(error)}],
                    }
                )
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not self._valid_request_origin():
            self._error(403, "invalid request origin")
            return
        if self._rate_limited(parsed.path):
            self._error(429, "too many requests")
            return
        if parsed.path == "/api/register":
            payload = self._read_json()
            try:
                user = self.store.create_user(str(payload.get("username", "")), str(payload.get("password", "")))
                self._set_session_cookie(self.store.create_session(user.id))
                settings = self.store.settings_for_user(user.id)
                self._json(
                    {
                        "authenticated": True,
                        "username": user.username,
                        "credentialsConfigured": False,
                        "selectedSymbol": settings.selected_symbol,
                        "subscription": {
                            "plan": settings.subscription_plan,
                            "status": settings.subscription_status,
                        },
                        "tradingRules": settings_payload(settings),
                    }
                )
            except ValueError as error:
                self._error(400, str(error))
            return
        if parsed.path == "/api/login":
            payload = self._read_json()
            user = self.store.authenticate(str(payload.get("username", "")), str(payload.get("password", "")))
            if user is None:
                self._error(401, "invalid username or password")
                return
            self._set_session_cookie(self.store.create_session(user.id))
            settings = self.store.settings_for_user(user.id)
            self._json(
                {
                    "authenticated": True,
                    "username": user.username,
                    "credentialsConfigured": self.store.has_credentials(user.id),
                    "selectedSymbol": settings.selected_symbol,
                    "subscription": {
                        "plan": settings.subscription_plan,
                        "status": settings.subscription_status,
                    },
                    "tradingRules": settings_payload(settings),
                }
            )
            return
        if parsed.path == "/api/password-reset/request":
            payload = self._read_json()
            username = str(payload.get("username", "")).strip().lower()
            if not _is_email(username):
                self._error(400, "enter the email used for this profile")
                return
            reset = self.store.create_password_reset_code(username)
            response = {"message": "If that email exists, a reset code has been sent."}
            if reset is not None:
                try:
                    send_password_reset_code(reset.user.username, reset.code)
                except EmailDeliveryError as error:
                    if not expose_dev_reset_code():
                        self._error(503, str(error))
                        return
                if expose_dev_reset_code():
                    response["devResetCode"] = reset.code
            self._json(response)
            return
        if parsed.path == "/api/password-reset/complete":
            payload = self._read_json()
            try:
                user = self.store.reset_password_with_code(
                    str(payload.get("username", "")),
                    str(payload.get("resetCode", "")),
                    str(payload.get("password", "")),
                )
            except ValueError as error:
                self._error(400, str(error))
                return
            if user is None:
                self._error(400, "reset code is invalid or expired")
                return
            self.tenants.reset_user(user.id)
            self._set_session_cookie(self.store.create_session(user.id))
            settings = self.store.settings_for_user(user.id)
            self._json(
                {
                    "authenticated": True,
                    "username": user.username,
                    "credentialsConfigured": self.store.has_credentials(user.id),
                    "selectedSymbol": settings.selected_symbol,
                    "subscription": {
                        "plan": settings.subscription_plan,
                        "status": settings.subscription_status,
                    },
                    "tradingRules": settings_payload(settings),
                }
            )
            return
        if parsed.path == "/api/password-recovery-code":
            self._error(410, "saved recovery codes have been replaced by email reset codes")
            return
        if parsed.path == "/api/logout":
            token = self._session_token()
            if token:
                self.store.delete_session(token)
            self._clear_session_cookie()
            self._json({"authenticated": False})
            return
        if parsed.path == "/api/credentials":
            user = self._require_user()
            if user is None:
                return
            payload = self._read_json()
            try:
                self.store.save_credentials(
                    user.id,
                    UserCredentials(
                        account_address=str(payload.get("accountAddress", "")),
                        secret_key=str(payload.get("secretKey", "")),
                    ),
                )
                self.tenants.reset_user(user.id)
                self._json({"credentialsConfigured": True})
            except ValueError as error:
                self._error(400, str(error))
            return
        if parsed.path == "/api/settings":
            user = self._require_user()
            if user is None:
                return
            payload = self._read_json()
            try:
                settings = self.store.save_selected_symbol(user.id, str(payload.get("selectedSymbol", "")))
                self.tenants.reset_user(user.id)
                self._json(
                    {
                        "selectedSymbol": settings.selected_symbol,
                        "subscription": {
                            "plan": settings.subscription_plan,
                            "status": settings.subscription_status,
                        },
                        "tradingRules": settings_payload(settings),
                    }
                )
            except ValueError as error:
                self._error(400, str(error))
            return
        if parsed.path == "/api/trading-rules":
            user = self._require_user()
            if user is None:
                return
            payload = self._read_json()
            try:
                settings = self.store.save_trading_rules(
                    user.id,
                    chart_interval=str(payload.get("chartInterval", "")),
                    signal_session_window=str(payload.get("signalSessionWindow", "london_new_york")),
                    london_commodity_only=bool(payload.get("londonCommodityOnly", True)),
                    max_daily_loss_pct=float(payload.get("maxDailyLossPct", 0.05)),
                    session_guard_minutes=int(payload.get("sessionGuardMinutes", 60)),
                    stale_grid_cancel=bool(payload.get("staleGridCancel", True)),
                    order_quote_size=float(payload.get("orderQuoteSize", 25)),
                    max_total_notional=float(payload.get("maxTotalNotional", 5000)),
                    max_position_value=float(payload.get("maxPositionValue", 5000)),
                )
                self.tenants.reset_user(user.id)
                self._json({"tradingRules": settings_payload(settings)})
            except (TypeError, ValueError) as error:
                self._error(400, str(error))
            return
        if parsed.path == "/api/start":
            user = self._require_user()
            if user is None:
                return
            try:
                self._json(self.tenants.service_for_user(user).start())
            except ValueError as error:
                self._error(400, str(error))
            return
        if parsed.path == "/api/stop":
            user = self._require_user()
            if user is None:
                return
            try:
                self._json(self.tenants.service_for_user(user).stop())
            except ValueError as error:
                self._error(400, str(error))
            return
        self.send_error(404, "not found")

    def _read_json(self) -> dict:
        data = self._read_body()
        if not data:
            return {}
        return json.loads(data.decode("utf-8"))

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _current_user(self) -> User | None:
        return self.store.user_for_session(self._session_token())

    def _require_user(self) -> User | None:
        user = self._current_user()
        if user is not None:
            return user
        self._error(401, "login required")
        return None

    def _session_token(self) -> str:
        for part in self.headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "monatise_session":
                return value
        return ""

    def _set_session_cookie(self, token: str) -> None:
        self._pending_cookie = (
            f"monatise_session={token}; Path=/; Max-Age=1209600; SameSite=Lax; HttpOnly{self._secure_cookie_suffix()}"
        )

    def _clear_session_cookie(self) -> None:
        self._pending_cookie = f"monatise_session=; Path=/; Max-Age=0; SameSite=Lax; HttpOnly{self._secure_cookie_suffix()}"

    def _secure_cookie_suffix(self) -> str:
        public_url = os.getenv("MONATISE_PUBLIC_URL", "")
        if public_url.startswith("https://") or os.getenv("MONATISE_SECURE_COOKIES", "").lower() == "true":
            return "; Secure"
        return ""

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' https://cdnjs.cloudflare.com; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self' https://checkout.stripe.com https://api.flutterwave.com https://*.flutterwave.com",
        )
        if os.getenv("MONATISE_PUBLIC_URL", "").startswith("https://"):
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        super().end_headers()

    def _json(self, payload: dict) -> None:
        body = json.dumps(payload, cls=JsonEncoder).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if hasattr(self, "_pending_cookie"):
            self.send_header("Set-Cookie", self._pending_cookie)
            delattr(self, "_pending_cookie")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        body = json.dumps({"error": message}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if hasattr(self, "_pending_cookie"):
            self.send_header("Set-Cookie", self._pending_cookie)
            delattr(self, "_pending_cookie")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _valid_request_origin(self) -> bool:
        origin = self.headers.get("Origin") or self.headers.get("Referer")
        if not origin:
            return True
        origin_host = urlparse(origin).netloc
        if not origin_host:
            return False
        allowed_hosts = {
            self.headers.get("Host", ""),
            self.headers.get("X-Forwarded-Host", ""),
            urlparse(os.getenv("MONATISE_PUBLIC_URL", "")).netloc,
        }
        return origin_host in {host for host in allowed_hosts if host}

    def _rate_limited(self, path: str) -> bool:
        limits = {
            "/api/login": (10, 60),
            "/api/register": (6, 60),
            "/api/password-reset/request": (4, 60),
            "/api/password-reset/complete": (8, 60),
            "/api/password-recovery-code": (3, 60),
            "/api/credentials": (6, 60),
            "/api/start": (6, 60),
            "/api/stop": (12, 60),
        }
        limit, window = limits.get(path, (60, 60))
        forwarded = self.headers.get("X-Forwarded-For", "")
        client = forwarded.split(",", 1)[0].strip() or self.client_address[0]
        key = f"{client}:{path}"
        now = time.time()
        with self.rate_lock:
            attempts = [stamp for stamp in self.rate_limits.get(key, []) if now - stamp < window]
            if len(attempts) >= limit:
                self.rate_limits[key] = attempts
                return True
            attempts.append(now)
            self.rate_limits[key] = attempts
        return False


def main() -> int:
    config = RuntimeConfig.from_env()
    if config.mode == "live" and config.network == "mainnet" and not encryption_key_configured():
        raise RuntimeError("MONATISE_ENCRYPTION_KEY is required for live mainnet credential storage")
    store = UserStore()
    tenants = TenantServices(config, store)
    market_feed = MarketFeed(replace(config, account_address="", secret_key=""))
    app_dir = Path(__file__).resolve().parents[2] / "app"

    class Handler(MonatiseHandler):
        pass

    Handler.store = store
    Handler.tenants = tenants
    Handler.market_feed = market_feed
    Handler.config = config
    Handler.app_dir = app_dir

    port = int(os.getenv("MONATISE_PORT", os.getenv("PORT", "4174")))
    host = os.getenv("MONATISE_HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Monatise backend running at http://{host}:{port}", flush=True)
    print(f"mode={config.mode} network={config.network} multi_user=true", flush=True)
    print(f"auth_db={store.path}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
