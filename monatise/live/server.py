from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from urllib.parse import urlparse

from monatise.adapters.hyperliquid import HyperliquidAdapter
from monatise.live.config import RuntimeConfig
from monatise.live.service import JsonEncoder, TradingService
from monatise.live.users import User, UserCredentials, UserStore


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
        self._updated_at = 0.0
        self._lock = threading.Lock()

    def snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            if now - self._updated_at > 2:
                if self._adapter is None:
                    self._adapter = HyperliquidAdapter(self.config)
                self._prices = self._adapter.latest_prices(self.config.assets)
                self._updated_at = now
            return {
                "assets": [
                    {"symbol": symbol, "price": self._prices.get(symbol)}
                    for symbol in self.config.assets
                ],
                "updatedAt": self._updated_at,
            }


class MonatiseHandler(SimpleHTTPRequestHandler):
    tenants: TenantServices
    market_feed: MarketFeed
    store: UserStore
    app_dir: Path

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
            try:
                settings = self.store.save_subscription_plan(user.id, str(payload.get("plan", "")))
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
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

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
            f"monatise_session={token}; Path=/; Max-Age=1209600; SameSite=Lax; HttpOnly"
        )

    def _clear_session_cookie(self) -> None:
        self._pending_cookie = "monatise_session=; Path=/; Max-Age=0; SameSite=Lax; HttpOnly"

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


def main() -> int:
    config = RuntimeConfig.from_env()
    store = UserStore()
    tenants = TenantServices(config, store)
    market_feed = MarketFeed(config)
    app_dir = Path(__file__).resolve().parents[2] / "app"

    class Handler(MonatiseHandler):
        pass

    Handler.store = store
    Handler.tenants = tenants
    Handler.market_feed = market_feed
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
