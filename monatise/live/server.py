from __future__ import annotations

import json
import hashlib
import hmac
import threading
import time
import urllib.error
import urllib.request
from dataclasses import replace
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from monatise.analysis.fibonacci import analyze_fibonacci
from monatise.adapters.hyperliquid import HyperliquidAdapter
from monatise.live.config import RuntimeConfig
from monatise.live.secrets import secret_value
from monatise.live.service import JsonEncoder, TradingService
from monatise.live.users import User, UserCredentials, UserStore, encryption_key_configured


PLAN_PRICES = {
    "free": {"amount": 0, "currency": "USD"},
    "pro": {"amount": 29, "currency": "USD"},
}

COMMODITY_WATCHLIST = ("GOLD", "CL", "BRENTOIL")
FOREX_WATCHLIST = ("EURUSD", "GBPUSD", "USDJPY", "XAG")
STOCK_WATCHLIST = ("SPX", "NDX", "NASDAQ", "AAPL", "TSLA", "NVDA")


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
                raise ValueError("save Hyperliquid credentials before starting live trading")
            settings = self.store.settings_for_user(user.id)
            config = replace(
                self.base_config,
                symbol=settings.selected_symbol,
                account_address=credentials.account_address,
                secret_key=credentials.secret_key,
            )
            service = TradingService(config)
            self._services[user.id] = service
            return service

    def reset_user(self, user_id: int) -> None:
        with self._lock:
            service = self._services.pop(user_id, None)
        if service is not None:
            service.stop()


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


class PaymentGateway:
    def config(self) -> dict:
        recipient = self._recipient_name()
        stripe_ready = bool(secret_value("STRIPE_SECRET_KEY", "")) and bool(secret_value("STRIPE_WEBHOOK_SECRET", ""))
        flutterwave_ready = bool(secret_value("FLUTTERWAVE_SECRET_KEY", ""))
        crypto_address = secret_value("MONATISE_CRYPTO_PAYMENT_ADDRESS", "")
        crypto_network = os.getenv("MONATISE_CRYPTO_PAYMENT_NETWORK", "USDC on Arbitrum or HyperEVM")
        return {
            "recipient": recipient,
            "rails": {
                "stripe": {
                    "configured": stripe_ready,
                    "destination": f"{recipient} Stripe merchant account",
                    "webhookConfigured": bool(secret_value("STRIPE_WEBHOOK_SECRET", "")),
                },
                "flutterwave": {
                    "configured": flutterwave_ready,
                    "destination": f"{recipient} Flutterwave merchant account",
                },
                "crypto": {
                    "configured": bool(crypto_address),
                    "destination": crypto_address,
                    "network": crypto_network,
                },
            },
        }

    def checkout(self, user: User, payload: dict) -> dict:
        plan = str(payload.get("plan", "pro")).lower()
        method = str(payload.get("method", "flutterwave")).lower()
        price = PLAN_PRICES.get(plan)
        if price is None:
            raise ValueError("unknown subscription plan")
        if plan == "free":
            return {"provider": "internal", "status": "active", "plan": "free"}
        if method in {"flutterwave", "fiat"}:
            return self._flutterwave_checkout(user, plan, price, payload)
        if method == "stripe":
            return self._stripe_checkout(user, plan, price, payload)
        if method == "crypto":
            return self._crypto_checkout(user, plan, price)
        raise ValueError("unknown payment method")

    def _stripe_checkout(self, user: User, plan: str, price: dict, payload: dict) -> dict:
        secret_key = secret_value("STRIPE_SECRET_KEY", "")
        destination = self._destination("stripe")
        if not secret_key:
            return {
                "provider": "stripe",
                "status": "setup_required",
                "message": "STRIPE_SECRET_KEY is not configured",
                "destination": destination,
            }
        if not secret_value("STRIPE_WEBHOOK_SECRET", ""):
            return {
                "provider": "stripe",
                "status": "setup_required",
                "message": "STRIPE_WEBHOOK_SECRET is required before accepting Stripe payments",
                "destination": destination,
            }
        host = os.getenv("MONATISE_PUBLIC_URL", "https://monatise-live.onrender.com").rstrip("/")
        form = {
            "mode": "subscription",
            "success_url": f"{host}/?payment=stripe_success",
            "cancel_url": f"{host}/?payment=stripe_cancelled",
            "client_reference_id": f"{user.id}:{plan}",
            "customer_email": str(payload.get("email") or f"{user.username}@monatise.local"),
            "metadata[user_id]": str(user.id),
            "metadata[plan]": plan,
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": str(payload.get("currency", price["currency"])).lower(),
            "line_items[0][price_data][unit_amount]": str(int(price["amount"]) * 100),
            "line_items[0][price_data][recurring][interval]": "month",
            "line_items[0][price_data][product_data][name]": f"Monatise {plan.title()}",
        }
        request = urllib.request.Request(
            "https://api.stripe.com/v1/checkout/sessions",
            data=urlencode(form).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {secret_key}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            details = error.read().decode("utf-8")
            raise ValueError(f"Stripe checkout failed: {details}") from error
        url = result.get("url")
        if not url:
            raise ValueError("Stripe did not return a checkout URL")
        return {
            "provider": "stripe",
            "status": "redirect",
            "checkoutUrl": url,
            "sessionId": result.get("id"),
            "destination": destination,
        }

    def _flutterwave_checkout(self, user: User, plan: str, price: dict, payload: dict) -> dict:
        secret_key = secret_value("FLUTTERWAVE_SECRET_KEY", "")
        public_key = secret_value("FLUTTERWAVE_PUBLIC_KEY", "")
        destination = self._destination("flutterwave")
        if not secret_key:
            return {
                "provider": "flutterwave",
                "status": "setup_required",
                "message": "FLUTTERWAVE_SECRET_KEY is not configured",
                "publicKeyConfigured": bool(public_key),
                "destination": destination,
            }

        host = os.getenv("MONATISE_PUBLIC_URL", "https://monatise-live.onrender.com").rstrip("/")
        tx_ref = f"monatise-{user.id}-{plan}-{int(time.time())}"
        body = {
            "tx_ref": tx_ref,
            "amount": price["amount"],
            "currency": str(payload.get("currency", price["currency"])).upper(),
            "redirect_url": f"{host}/api/payments/flutterwave/callback",
            "customer": {
                "email": str(payload.get("email") or f"{user.username}@monatise.local"),
                "name": user.username,
            },
            "customizations": {
                "title": "Monatise",
                "description": f"{plan.title()} subscription",
            },
        }
        request = urllib.request.Request(
            "https://api.flutterwave.com/v3/payments",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {secret_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            details = error.read().decode("utf-8")
            raise ValueError(f"Flutterwave checkout failed: {details}") from error
        link = result.get("data", {}).get("link")
        if not link:
            raise ValueError("Flutterwave did not return a checkout link")
        return {
            "provider": "flutterwave",
            "status": "redirect",
            "checkoutUrl": link,
            "txRef": tx_ref,
            "destination": destination,
        }

    def _crypto_checkout(self, user: User, plan: str, price: dict) -> dict:
        address = secret_value("MONATISE_CRYPTO_PAYMENT_ADDRESS", "")
        network = os.getenv("MONATISE_CRYPTO_PAYMENT_NETWORK", "USDC on Arbitrum or HyperEVM")
        return {
            "provider": "crypto",
            "status": "pending",
            "plan": plan,
            "amount": price["amount"],
            "currency": "USDC",
            "network": network,
            "address": address,
            "destination": address,
            "recipient": self._recipient_name(),
            "reference": f"monatise-{user.id}-{plan}",
            "setupRequired": not bool(address),
        }

    def _recipient_name(self) -> str:
        return os.getenv("MONATISE_PAYMENT_RECEIVER_NAME", "Monatise").strip() or "Monatise"

    def _destination(self, rail: str) -> dict:
        return {"recipient": self._recipient_name(), "rail": rail}


class MonatiseHandler(SimpleHTTPRequestHandler):
    tenants: TenantServices
    market_feed: MarketFeed
    payment_gateway: PaymentGateway
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
        if parsed.path == "/api/analysis/fibonacci":
            query = parse_qs(parsed.query)
            symbol = str(query.get("symbol", [self.config.symbol])[0]).strip().upper()
            interval = str(query.get("interval", ["1h"])[0]).strip() or "1h"
            try:
                limit = max(20, min(240, int(query.get("limit", ["120"])[0])))
                adapter = HyperliquidAdapter(self.config)
                candles = adapter.candles(symbol, limit, interval=interval)
                mark = adapter.latest_price(symbol)
                self._json(
                    {
                        "analysis": analyze_fibonacci(symbol, interval, candles, mark=mark).to_dict(),
                        "candles": [candle.__dict__ for candle in candles],
                    }
                )
            except Exception as error:  # noqa: BLE001
                self._error(502, str(error))
            return
        if parsed.path == "/api/payments/config":
            self._json(self.payment_gateway.config())
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
                }
            )
            return
        if parsed.path == "/api/payments/flutterwave/callback":
            params = parse_qs(parsed.query)
            status = params.get("status", ["unknown"])[0]
            self._redirect(f"/?payment={status}")
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
                        "requires": ["Hyperliquid credentials"],
                        "events": [{"timestamp": 0, "level": "warn", "message": str(error)}],
                    }
                )
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/payments/stripe/webhook" and not self._valid_request_origin():
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
                self._json({"authenticated": True, "username": user.username, "credentialsConfigured": False})
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
            self._json(
                {
                    "authenticated": True,
                    "username": user.username,
                    "credentialsConfigured": self.store.has_credentials(user.id),
                }
            )
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
                    }
                )
            except ValueError as error:
                self._error(400, str(error))
            return
        if parsed.path == "/api/subscription":
            user = self._require_user()
            if user is None:
                return
            payload = self._read_json()
            plan = str(payload.get("plan", "")).strip().lower()
            if plan != "free":
                self._error(402, "paid plans must be activated through verified checkout")
                return
            try:
                settings = self.store.save_subscription_plan(user.id, plan)
                self._json(
                    {
                        "subscription": {
                            "plan": settings.subscription_plan,
                            "status": settings.subscription_status,
                        }
                    }
                )
            except ValueError as error:
                self._error(400, str(error))
            return
        if parsed.path == "/api/payments/stripe/webhook":
            self._handle_stripe_webhook()
            return
        if parsed.path == "/api/payments/checkout":
            user = self._require_user()
            if user is None:
                return
            payload = self._read_json()
            try:
                checkout = self.payment_gateway.checkout(user, payload)
                if checkout.get("provider") == "internal":
                    settings = self.store.save_subscription_plan(user.id, str(checkout["plan"]))
                    checkout["subscription"] = {
                        "plan": settings.subscription_plan,
                        "status": settings.subscription_status,
                    }
                self._json(checkout)
            except ValueError as error:
                self._error(400, str(error))
            return
        if parsed.path == "/api/start":
            user = self._require_user()
            if user is None:
                return
            settings = self.store.settings_for_user(user.id)
            if (
                self.tenants.base_config.mode == "live"
                and self.tenants.base_config.network == "mainnet"
                and settings.subscription_plan != "pro"
            ):
                self._error(402, "Pro is required before starting mainnet live trading")
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
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
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

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def _handle_stripe_webhook(self) -> None:
        body = self._read_body()
        secret = secret_value("STRIPE_WEBHOOK_SECRET", "")
        if not secret:
            self._error(503, "Stripe webhook secret is not configured")
            return
        if not self._valid_stripe_signature(body, secret):
            self._error(400, "invalid Stripe signature")
            return
        try:
            event = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self._error(400, "invalid webhook payload")
            return
        if event.get("type") == "checkout.session.completed":
            session = event.get("data", {}).get("object", {})
            plan = session.get("metadata", {}).get("plan", "")
            user_id = session.get("metadata", {}).get("user_id", "")
            if not user_id or not plan:
                reference = str(session.get("client_reference_id", ""))
                user_id, _, plan = reference.partition(":")
            if user_id.isdigit() and plan:
                try:
                    self.store.save_subscription_plan(int(user_id), plan)
                except ValueError:
                    pass
        self._json({"received": True})

    def _valid_stripe_signature(self, body: bytes, secret: str) -> bool:
        header = self.headers.get("Stripe-Signature", "")
        values = dict(part.split("=", 1) for part in header.split(",") if "=" in part)
        timestamp = values.get("t", "")
        signature = values.get("v1", "")
        if not timestamp or not signature:
            return False
        payload = timestamp.encode("utf-8") + b"." + body
        expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

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
            "/api/credentials": (6, 60),
            "/api/payments/checkout": (12, 60),
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
    payment_gateway = PaymentGateway()
    app_dir = Path(__file__).resolve().parents[2] / "app"

    class Handler(MonatiseHandler):
        pass

    Handler.store = store
    Handler.tenants = tenants
    Handler.market_feed = market_feed
    Handler.payment_gateway = payment_gateway
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
