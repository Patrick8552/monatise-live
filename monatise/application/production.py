"""Production-facing, analysis-only ASGI entrypoint for Monatise."""

from __future__ import annotations

import hashlib
import hmac
import base64
import json
import logging
import mimetypes
import asyncio
import re
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
import secrets
from time import monotonic, time
from typing import Any, Mapping
from urllib.parse import parse_qs

from dataclasses import asdict
from decimal import Decimal

from monatise.adapters.quiver import QuiverAdapter, normalize_quiver_symbol
from monatise.analysis.context import context_assets, grid_instruction, indicator_snapshot
from monatise.analysis.fibonacci import analyze_fibonacci
from monatise.analysis.fvg import analyze_fvg
from monatise.analysis.liquidity_clusters import estimate_liquidation_clusters
from monatise.analysis.tradingview import TRADINGVIEW_FRESH_SECONDS, TRADINGVIEW_SNAPSHOT_LOCK_SECONDS, normalize_alert_symbol
from monatise.adapters.coinglass_production import CoinGlassProductionAdapter
from monatise.application.deployment import OrchestrationASGI, OrchestrationRuntime, TelegramCommandTransition, TradingViewAlertDuplicate
from monatise.application.ftmo_registry import FTMOAssetClass, FTMO_REGISTRY
from monatise.application.ftmo_master import (
    FTMOBridgeAuthenticator,
    FTMOMasterError,
    format_proposal,
    format_status as format_ftmo_master_status,
)
from monatise.application.stock_analysis import refresh_setup_validity
from monatise.application.market_session import classify_market_session
from monatise.application.telegram_analysis import (
    TelegramAnalysisError,
    format_analysis,
    normalize_analysis,
    request_identity,
    resolve_telegram_instrument,
    signal_identity,
    symbol_key,
)
from monatise.engines.market_data import MarketDataEngine, MarketDataRequest
from monatise.core.models import Candle


LOGGER = logging.getLogger("monatise.production")
PRODUCTION_APPLICATION = "monatise.application.production:app"
PRODUCTION_API_VERSION = "v1"
DEDICATED_TELEGRAM_DELIVERY_MODE = "dedicated_render_webhook"


class TelegramLeaseLost(RuntimeError):
    """Raised when a worker no longer owns a Telegram command lease."""


def telegram_webhook_secret(token: str) -> str:
    return hashlib.sha256(f"monatise-telegram-webhook:{token}".encode()).hexdigest()


def configured_telegram_webhook_secret(environment: Mapping[str, str]) -> str:
    """Return the dedicated Render bot webhook secret without exposing it."""
    explicit = str(environment.get("MONATISE_TELEGRAM_WEBHOOK_SECRET", "")).strip()
    if explicit:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", explicit):
            raise ValueError("MONATISE_TELEGRAM_WEBHOOK_SECRET has an invalid format")
        return explicit
    token = str(environment.get("MONATISE_TELEGRAM_BOT_TOKEN", "")).strip()
    return telegram_webhook_secret(token) if token else ""


class ProductionRuntime(OrchestrationRuntime):
    async def start(self) -> None:
        LOGGER.info(
            "monatise production startup application=%s mode=%s environment=%s commit=%s api_version=%s",
            PRODUCTION_APPLICATION,
            self.environment.get("MONATISE_MODE", "unknown"),
            self.environment.get("MONATISE_ENVIRONMENT", "unknown"),
            self.environment.get("RENDER_GIT_COMMIT", self.environment.get("MONATISE_GIT_COMMIT", "unknown")),
            PRODUCTION_API_VERSION,
        )
        LOGGER.info("validating production safety configuration")
        if self.environment.get("MONATISE_ENVIRONMENT", "").strip().casefold() != "production":
            raise ValueError("MONATISE_ENVIRONMENT must be production")
        required = {
            "MONATISE_MODE": "paper",
            "MONATISE_NETWORK": "paper",
            "MONATISE_EXECUTION_ENABLED": "false",
            "MONATISE_AUTONOMOUS_EXECUTION": "false",
            "MONATISE_EXECUTION_ADAPTER_ENABLED": "false",
            "MONATISE_ALLOW_LIVE_ORDERS": "false",
            "MONATISE_OPENCLAW_EXECUTION_ALLOWED": "false",
            "MONATISE_TELEGRAM_EXECUTION_ALLOWED": "false",
            "MONATISE_GOVERNANCE_KILL_SWITCH_ENABLED": "true",
            "MONATISE_AUDIT_LOGGING_ENABLED": "true",
        }
        invalid = [key for key, value in required.items() if self.environment.get(key, "").strip().casefold() != value]
        if invalid:
            raise ValueError("production safety configuration is missing or invalid: " + ", ".join(invalid))
        LOGGER.info("production safety configuration validated")
        await super().start()
        await self._register_telegram_webhook()

    async def _register_telegram_webhook(self) -> None:
        token = self.environment.get("MONATISE_TELEGRAM_BOT_TOKEN", "").strip()
        public_url = self.environment.get("MONATISE_PUBLIC_URL", "").strip().rstrip("/")
        inbound_enabled = self.environment.get("MONATISE_TELEGRAM_INBOUND_ENABLED", "false").strip().casefold() in {"1", "true", "yes", "on", "enabled"}
        dedicated = self.environment.get("MONATISE_TELEGRAM_BOT_DELIVERY_MODE", "").strip().casefold() == DEDICATED_TELEGRAM_DELIVERY_MODE
        configured = inbound_enabled and dedicated and self.telegram is not None and bool(token and public_url.startswith("https://"))
        status = {"status": "ok", "enabled": configured, "execution_enabled": False}
        if not configured:
            status["registration"] = "not_configured"
            status["dedicated_bot_confirmed"] = dedicated
            self.dependencies["telegram_inbound"] = status
            return
        secret_token = configured_telegram_webhook_secret(self.environment)
        try:
            registered = await self.telegram.register_webhook(f"{public_url}/api/telegram/webhook", secret_token)
        except Exception as exc:
            LOGGER.warning("Telegram webhook registration failed", extra={"error_type": type(exc).__name__})
            status.update({"status": "degraded", "registration": "failed"})
        else:
            status.update({"status": "ok" if registered else "degraded", "registration": "registered" if registered else "rejected"})
        self.dependencies["telegram_inbound"] = status

    def readiness(self) -> tuple[bool, dict[str, Any]]:
        # During a zero-downtime deploy the live instance owns the scheduler
        # lock until Render cuts traffic over.  The replacement is a healthy
        # contender and acquires leadership after the old instance shuts down;
        # requiring this process to be leader would deadlock every redeploy.
        return super().readiness()


class ProductionASGI(OrchestrationASGI):
    TELEGRAM_LEASE_SECONDS = 120
    TELEGRAM_HEARTBEAT_SECONDS = 30
    TELEGRAM_WEBHOOK_VERIFY_SECONDS = 60
    MARKET_SYMBOLS = {"BTC", "ETH", "SOL", "XRP", "DOGE", "BNB"}
    MARKET_INTERVALS = set(CoinGlassProductionAdapter.SUPPORTED_INTERVALS)
    INTERVAL_MAX_AGE_SECONDS = {
        "1m": 120, "3m": 360, "5m": 600, "15m": 1_800, "30m": 3_600,
        "1h": 7_200, "4h": 28_800, "6h": 43_200, "8h": 57_600,
        "12h": 86_400, "1d": 172_800, "1w": 1_209_600,
    }
    STOCK_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9._-]{0,11}$", re.IGNORECASE)
    TELEGRAM_COMMAND_PATTERN = re.compile(r"^/(?:analyse|analyze|analysis)(?:@[A-Za-z0-9_]+)?(?:\s+(.+))?$", re.IGNORECASE)
    TELEGRAM_ALIAS_PATTERN = re.compile(r"^/(gold)(?:@[A-Za-z0-9_]+)?$", re.IGNORECASE)

    def __init__(self, runtime: OrchestrationRuntime | None = None, static_dir: Path | None = None) -> None:
        super().__init__(runtime or ProductionRuntime())
        self.static_dir = (static_dir or Path(__file__).resolve().parents[2] / "app").resolve()
        self._market_rate_windows: dict[str, tuple[int, int]] = {}
        self._openclaw_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
        self._openclaw_inflight: dict[tuple[str, str], asyncio.Task[dict[str, Any]]] = {}
        self._public_analysis_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
        self._public_analysis_inflight: dict[tuple[str, str], asyncio.Task[dict[str, Any]]] = {}
        self._quiver_web_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._quiver_web_inflight: dict[str, asyncio.Task[dict[str, Any]]] = {}
        self._market_summary_cache: tuple[float, dict[str, Any]] | None = None
        self._telegram_worker: asyncio.Task[None] | None = None
        self._telegram_webhook_monitor: asyncio.Task[None] | None = None
        self._quote_lifecycle_worker: asyncio.Task[None] | None = None

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "lifespan":
            await self._lifespan(receive, send)
            return
        path = scope.get("path", "")
        if scope.get("type") == "http" and path == "/api/telegram/webhook":
            if scope.get("method", "GET").upper() != "POST":
                await self._respond(send, 405, {"status": "method_not_allowed"})
                return
            code, payload = await self._telegram_webhook(scope, receive)
            await self._respond(send, code, payload)
            return
        if scope.get("type") == "http" and path.startswith("/api/ftmo/bridge/"):
            code, payload = await self._ftmo_bridge_request(scope, receive)
            await self._respond(send, code, payload)
            return
        if scope.get("type") == "http" and path == "/api/health":
            if scope.get("method", "GET").upper() not in {"GET", "HEAD"}:
                await self._respond(send, 405, {"status": "method_not_allowed"})
                return
            await self._respond(send, 200, {
                "ok": True, "status": "alive", "telegram": await self._telegram_queue_telemetry(),
                "execution_enabled": False,
            })
            return
        if scope.get("type") == "http" and path == "/api/x/status":
            if scope.get("method", "GET").upper() not in {"GET", "HEAD"}:
                await self._respond(send, 405, {"status": "method_not_allowed"})
                return
            accounts = tuple(dict.fromkeys(
                item.strip().lstrip("@")
                for item in self.runtime.environment.get("MONATISE_X_WATCH_ACCOUNTS", "").split(",")
                if item.strip()
            ))
            connect_url = self.runtime.environment.get("MONATISE_X_OAUTH_CONNECT_URL", "").strip()
            connected = self.runtime.x_macro is not None
            await self._respond(send, 200, {
                "connected": connected,
                "monitoring": connected and self.runtime.dependencies.get("x_macro", {}).get("enabled") is True,
                "authorization": "read_only",
                "watch_accounts": list(accounts),
                "connect_url": connect_url,
                "execution_enabled": False,
            })
            return
        if scope.get("type") == "http" and path == "/api/assets":
            if scope.get("method", "GET").upper() != "GET":
                await self._respond(send, 405, {"status": "method_not_allowed"})
                return
            stocks = ("AAPL", "TSLA", "NVDA", "QQQ", "SPY")
            crypto = ("BTC", "ETH", "SOL")
            await self._respond(send, 200, {
                "assets": [
                    *({"symbol": symbol, "assetClass": "crypto", "tradable": False} for symbol in crypto),
                    *({"symbol": symbol, "assetClass": "stock", "tradable": False, "dataSource": "Quiver Quantitative"} for symbol in stocks),
                ],
                "groups": {"crypto": list(crypto), "stocks": list(stocks)},
                "execution_enabled": False,
            })
            return
        if scope.get("type") == "http" and path in {"/api/stocks/search", "/api/stocks/scanner"}:
            if scope.get("method", "GET").upper() != "GET":
                await self._respond(send, 405, {"status": "method_not_allowed"})
                return
            if self._market_rate_limited(scope, maximum=30):
                await self._respond(send, 429, {"status": "rate_limited"})
                return
            code, payload = await (self._stocks_search(scope) if path.endswith("/search") else self._stocks_scanner())
            await self._respond(send, code, payload)
            return
        if scope.get("type") == "http" and path.startswith("/api/stocks/") and path.endswith("/analysis"):
            if scope.get("method", "GET").upper() != "GET":
                await self._respond(send, 405, {"status": "method_not_allowed"})
                return
            if self._market_rate_limited(scope, maximum=20):
                await self._respond(send, 429, {"status": "rate_limited"})
                return
            symbol = path.removeprefix("/api/stocks/").removesuffix("/analysis").strip("/").upper()
            code, payload = await self._stock_analysis(symbol)
            await self._respond(send, code, payload)
            return
        if scope.get("type") == "http" and path == "/api/me":
            if scope.get("method", "GET").upper() != "GET":
                await self._respond(send, 405, {"status": "method_not_allowed"})
                return
            await self._respond(send, 200, {"authenticated": False, "credentialsConfigured": False, "execution_enabled": False})
            return
        if scope.get("type") == "http" and path == "/api/tradingview/webhook":
            if scope.get("method", "GET").upper() != "POST":
                await self._respond(send, 405, {"status": "method_not_allowed"})
                return
            if self._market_rate_limited(scope, maximum=120):
                await self._respond(send, 429, {"status": "rate_limited"})
                return
            code, payload = await self._tradingview_webhook(scope, receive)
            await self._respond(send, code, payload)
            return
        if scope.get("type") == "http" and path == "/api/tradingview/signals":
            if scope.get("method", "GET").upper() != "GET":
                await self._respond(send, 405, {"status": "method_not_allowed"})
                return
            if self._market_rate_limited(scope):
                await self._respond(send, 429, {"status": "rate_limited"})
                return
            code, payload = await self._tradingview_signals(scope)
            await self._respond(send, code, payload)
            return
        if scope.get("type") == "http" and path in {"/api/market/candles", "/api/operator"}:
            if scope.get("method", "GET").upper() != "GET":
                await self._respond(send, 405, {"status": "method_not_allowed"})
                return
            if path == "/api/market/candles" and self._market_rate_limited(scope):
                await self._respond(send, 429, {"status": "rate_limited"})
                return
            code, payload = await (self._market_candles(scope) if path == "/api/market/candles" else self._operator_status())
            await self._respond(send, code, payload)
            return
        if scope.get("type") == "http" and path in {
            "/api/markets",
            "/api/public/significant-universe",
            "/api/analysis/fibonacci",
            "/api/context/radar",
            "/api/coinglass/context",
            "/api/analysis/liquidity-clusters",
        }:
            if scope.get("method", "GET").upper() != "GET":
                await self._respond(send, 405, {"status": "method_not_allowed"})
                return
            if self._market_rate_limited(scope, maximum=120):
                await self._respond(send, 429, {"status": "rate_limited"})
                return
            handlers = {
                "/api/markets": self._market_summary,
                "/api/public/significant-universe": self._significant_universe,
                "/api/analysis/fibonacci": self._fibonacci_analysis,
                "/api/context/radar": self._context_radar,
                "/api/coinglass/context": self._coinglass_context,
                "/api/analysis/liquidity-clusters": self._liquidity_clusters,
            }
            code, payload = await handlers[path](scope)
            await self._respond(send, code, payload)
            return
        if scope.get("type") == "http" and path.startswith("/api/coinglass/proxy/"):
            if scope.get("method", "GET").upper() != "GET":
                await self._respond(send, 405, {"status": "method_not_allowed"})
                return
            if self._market_rate_limited(scope):
                await self._respond(send, 429, {"status": "rate_limited"})
                return
            code, payload = await self._coinglass_dashboard(scope)
            await self._respond(send, code, payload)
            return
        if scope.get("type") == "http" and scope.get("path") == "/api/analysis":
            if scope.get("method", "GET").upper() != "POST":
                await self._respond(send, 405, {"status": "method_not_allowed"})
                return
            code, payload = await self._production_analysis(scope, receive)
            await self._respond(send, code, payload)
            return
        if scope.get("type") == "http" and scope.get("path") == "/api/openclaw/status":
            if scope.get("method", "GET").upper() != "GET":
                await self._respond(send, 405, {"status": "method_not_allowed"})
                return
            code, payload = await self._openclaw_status(scope)
            await self._respond(send, code, payload)
            return
        if scope.get("type") == "http" and scope.get("path") == "/api/quiver/context":
            if scope.get("method", "GET").upper() != "GET":
                await self._respond(send, 405, {"status": "method_not_allowed"})
                return
            if self._market_rate_limited(scope, maximum=30):
                await self._respond(send, 429, {"status": "rate_limited"})
                return
            code, payload = await self._quiver_context_status(scope)
            await self._respond(send, code, payload)
            return
        if scope.get("type") == "http" and scope.get("path") == "/api/public/analysis":
            if scope.get("method", "GET").upper() != "GET":
                await self._respond(send, 405, {"status": "method_not_allowed"})
                return
            if self._market_rate_limited(scope, maximum=30):
                await self._respond(send, 429, {"status": "rate_limited"})
                return
            code, payload = await self._public_analysis_status(scope)
            await self._respond(send, code, payload)
            return
        if scope.get("type") == "http" and await self._serve_frontend(scope, send):
            return
        await super().__call__(scope, receive, send)

    async def _telegram_webhook(self, scope: dict[str, Any], receive: Any) -> tuple[int, dict[str, Any]]:
        token = self.runtime.environment.get("MONATISE_TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = self.runtime.environment.get("MONATISE_TELEGRAM_CHAT_ID", "").strip()
        inbound_enabled = self.runtime.environment.get("MONATISE_TELEGRAM_INBOUND_ENABLED", "false").strip().casefold() in {"1", "true", "yes", "on", "enabled"}
        dedicated = self.runtime.environment.get("MONATISE_TELEGRAM_BOT_DELIVERY_MODE", "").strip().casefold() == DEDICATED_TELEGRAM_DELIVERY_MODE
        if not inbound_enabled or not dedicated or not token or not chat_id or self.runtime.telegram is None:
            return 503, {"status": "unavailable"}
        headers = {key.decode().casefold(): value.decode() for key, value in scope.get("headers", ())}
        supplied = headers.get("x-telegram-bot-api-secret-token", "")
        expected_secret = configured_telegram_webhook_secret(self.runtime.environment)
        if not expected_secret or not secrets.compare_digest(supplied, expected_secret):
            return 401, {"status": "unauthorized"}
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if len(body) > 16_384:
                return 413, {"status": "request_too_large"}
            if not message.get("more_body", False):
                break
        try:
            update = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return 400, {"status": "invalid_update"}
        if not isinstance(update, dict):
            return 400, {"status": "invalid_update"}
        callback = update.get("callback_query") if isinstance(update.get("callback_query"), dict) else None
        message = update.get("message") if isinstance(update.get("message"), dict) else None
        if callback is not None:
            callback_message = callback.get("message") if isinstance(callback.get("message"), dict) else None
            callback_data = str(callback.get("data") or "")
            callback_match = re.fullmatch(r"ftmo:(approve|reject):([a-f0-9]{12})", callback_data)
            if callback_message is None or callback_match is None:
                return 200, {"status": "ignored"}
            message = callback_message
            text = f"/{callback_match.group(1)} {callback_match.group(2)}"
            sender = callback.get("from") if isinstance(callback.get("from"), dict) else {}
            callback_query_id = str(callback.get("id") or "")
        else:
            text = str((message or {}).get("text") or "").strip()
            sender = message.get("from") if isinstance(message, dict) and isinstance(message.get("from"), dict) else {}
            callback_query_id = ""
        if not isinstance(message, dict) or str((message.get("chat") or {}).get("id", "")) != chat_id:
            return 200, {"status": "ignored"}
        update_id = update.get("update_id")
        if not isinstance(update_id, int):
            return 400, {"status": "invalid_update"}
        if self.runtime.redis_coordination is None:
            return 503, {"status": "unavailable"}
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        queued = await self.runtime.redis_coordination.enqueue_telegram_command(update_id, {
            "update_id": update_id,
            "message_id": message.get("message_id"),
            "text": text,
            "user_id": str(sender.get("id", "")),
            "chat_type": str(chat.get("type", "")),
            "callback_query_id": callback_query_id,
        }, ttl_seconds=86_400)
        if not queued:
            return 200, {"status": "duplicate"}
        return 200, {"status": "accepted"}

    async def _lifespan(self, receive: Any, send: Any) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                try:
                    await self.runtime.start()
                    if self.runtime.dependencies.get("telegram_inbound", {}).get("enabled"):
                        await self.runtime.redis_coordination.recover_telegram_commands()
                        self._telegram_worker = asyncio.create_task(self._telegram_command_worker(), name="telegram-command-worker")
                        self._quote_lifecycle_worker = asyncio.create_task(
                            self._quote_lifecycle_worker_loop(), name="ftmo-quote-lifecycle-worker",
                        )
                        self._telegram_webhook_monitor = asyncio.create_task(
                            self._telegram_webhook_monitor_loop(), name="telegram-webhook-owner-monitor",
                        )
                except Exception as exc:
                    LOGGER.exception("application lifespan startup failed", extra={"error_type": type(exc).__name__})
                    await send({"type": "lifespan.startup.failed", "message": "startup_failed"})
                    return
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                if self._quote_lifecycle_worker is not None:
                    self._quote_lifecycle_worker.cancel()
                    with suppress(asyncio.CancelledError):
                        await self._quote_lifecycle_worker
                    self._quote_lifecycle_worker = None
                if self._telegram_worker is not None:
                    self._telegram_worker.cancel()
                    with suppress(asyncio.CancelledError):
                        await self._telegram_worker
                    self._telegram_worker = None
                if self._telegram_webhook_monitor is not None:
                    self._telegram_webhook_monitor.cancel()
                    with suppress(asyncio.CancelledError):
                        await self._telegram_webhook_monitor
                    self._telegram_webhook_monitor = None
                await self.runtime.shutdown()
                await send({"type": "lifespan.shutdown.complete"})
                return

    async def _telegram_webhook_monitor_loop(self) -> None:
        while True:
            await self._verify_telegram_webhook_ownership()
            await asyncio.sleep(self.TELEGRAM_WEBHOOK_VERIFY_SECONDS)

    async def _verify_telegram_webhook_ownership(self) -> bool:
        status = self.runtime.dependencies.setdefault("telegram_inbound", {})
        notifier = self.runtime.telegram
        inspect_webhook = getattr(notifier, "webhook_info", None)
        if inspect_webhook is None:
            return False
        expected = self.runtime.environment.get("MONATISE_PUBLIC_URL", "").strip().rstrip("/") + "/api/telegram/webhook"
        try:
            info = await inspect_webhook()
        except Exception as exc:
            status.update({
                "status": "degraded", "webhook_owner_verified": False,
                "webhook_verification_error_type": type(exc).__name__,
                "webhook_verified_at": datetime.now(timezone.utc).isoformat(),
            })
            return False
        actual = str((info or {}).get("url") or "")
        owned = bool(expected.startswith("https://") and actual == expected)
        status.update({
            "status": "ok" if owned else "degraded",
            "registration": "registered" if owned else "lost",
            "webhook_owner_verified": owned,
            "webhook_url": actual or None,
            "pending_update_count": int((info or {}).get("pending_update_count") or 0),
            "last_error_date": (info or {}).get("last_error_date"),
            "last_error_message": (info or {}).get("last_error_message"),
            "webhook_verified_at": datetime.now(timezone.utc).isoformat(),
        })
        status.pop("webhook_verification_error_type", None)
        return owned

    async def _telegram_command_worker(self) -> None:
        failures = 0
        while True:
            try:
                await self._process_telegram_command_once(timeout_seconds=1)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failures += 1
                status = self.runtime.dependencies.setdefault("telegram_inbound", {})
                status.update({
                    "status": "degraded", "worker": "retrying", "worker_error_type": type(exc).__name__,
                    "worker_error_at": datetime.now(timezone.utc).isoformat(),
                })
                LOGGER.exception("Telegram command worker failed; retrying", extra={"error_type": type(exc).__name__})
                await asyncio.sleep(min(30, 2 ** min(failures - 1, 5)))
            else:
                failures = 0
                status = self.runtime.dependencies.setdefault("telegram_inbound", {})
                status["worker"] = "running"
                if status.get("registration") == "registered":
                    status["status"] = "ok"
                status.pop("worker_error_type", None)

    async def _quote_lifecycle_worker_loop(self) -> None:
        failures = 0
        while True:
            try:
                processed = await self._process_quote_request_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failures += 1
                LOGGER.exception("FTMO quote lifecycle worker failed; retrying", extra={"error_type": type(exc).__name__})
                await asyncio.sleep(min(30, 2 ** min(failures - 1, 5)))
            else:
                failures = 0
                if not processed:
                    await asyncio.sleep(1)

    async def _process_quote_request_once(self, quote_request_id: str | None = None) -> bool:
        service = getattr(self.runtime, "ftmo_master", None)
        notifier = self.runtime.telegram
        if service is None or notifier is None or not hasattr(service, "process_quote_request"):
            return False
        repository = service.repository
        if quote_request_id:
            stored_request = await repository.quote_request(quote_request_id)
            requests = (stored_request[0],) if stored_request else ()
        else:
            requests = await service.pending_quote_requests()
        processed = False
        for request in requests:
            current_id = str(request.get("quote_request_id") or "")
            if not current_id:
                continue
            if request.get("state") in {"PROPOSAL_CREATED", "PROPOSAL_PUBLISHING"}:
                stored_proposal = await repository.proposal(str(request.get("proposal_id") or ""))
                result, proposal = request, stored_proposal[0] if stored_proposal else None
            else:
                result, proposal = await service.process_quote_request(current_id)
            if result.get("state") in {"FAILED", "EXPIRED"}:
                processed = True
            if proposal is None:
                continue
            proposal_message = format_proposal(proposal)
            message_id = proposal.get("telegram_message_id")
            if not isinstance(message_id, int) or isinstance(message_id, bool):
                claimed = await repository.claim_quote_publication(current_id, now=datetime.now(timezone.utc))
                if claimed is None:
                    continue
                try:
                    message_id = await self._send_owned_trade_proposal(
                        notifier, proposal_message, proposal["proposal_id"], None,
                    )
                    if isinstance(message_id, int) and not isinstance(message_id, bool):
                        await repository.attach_proposal_telegram_message(proposal["proposal_id"], message_id)
                except Exception:
                    await repository.update_quote_request(current_id, {
                        "state": "PROPOSAL_CREATED", "publication_claimed_at": None,
                    })
                    raise
            else:
                claimed = request
            published_at = datetime.now(timezone.utc)
            await repository.update_quote_request(current_id, {
                "state": "PROPOSAL_PUBLISHED", "telegram_message_id": message_id,
                "proposal_published_at": published_at.isoformat(),
            })
            await repository.update_telegram_analysis(str(claimed["analysis_id"]), {
                "lifecycle_state": "PROPOSAL_PUBLISHED", "proposal_telegram_message_id": message_id,
            })
            await repository.finish_telegram_analysis_request(str(claimed["telegram_request_id"]), {
                "status": "completed", "proposal_state": "PROPOSAL_PUBLISHED",
                "proposal_id": proposal["proposal_id"], "proposal_message": proposal_message,
                "proposal_telegram_message_id": message_id, "telegram_message_id": message_id,
                "resolved_mt5_symbol": proposal.get("symbol"),
                "quote_observed_at_utc": proposal.get("quote_observed_at_utc"),
                "quote_age_ms": proposal.get("quote_age_ms"),
            })
            await repository.audit("proposal_published", current_id, {
                "analysis_id": claimed["analysis_id"], "quote_request_id": current_id,
                "proposal_id": proposal["proposal_id"], "telegram_message_id": message_id,
            })
            processed = True
        return processed

    async def _process_telegram_command_once(self, *, timeout_seconds: int = 1) -> bool:
        coordination = self.runtime.redis_coordination
        payload = await coordination.dequeue_telegram_command(
            timeout_seconds=timeout_seconds, lease_seconds=self.TELEGRAM_LEASE_SECONDS,
        )
        if payload is None:
            return False
        heartbeat = asyncio.create_task(self._telegram_lease_heartbeat(coordination, payload), name="telegram-lease-heartbeat")
        previous_context = getattr(self, "_telegram_command_context", None)
        self._telegram_command_context = {
            "update_id": payload.get("update_id"),
            "message_id": payload.get("message_id"),
            "user_id": str(payload.get("user_id") or ""),
            "chat_type": str(payload.get("chat_type") or ""),
            "callback_query_id": str(payload.get("callback_query_id") or ""),
        }
        try:
            await self._handle_telegram_command(
                str(payload.get("text") or ""),
                ownership_check=lambda: coordination.renew_telegram_command(payload),
            )
        except TelegramLeaseLost:
            LOGGER.warning("Discarding stale Telegram command result", extra={"update_id": payload.get("update_id")})
        except asyncio.CancelledError:
            try:
                await coordination.release_telegram_command(payload)
            except Exception as exc:
                # The lease remains recoverable by Redis expiry; a transient
                # release failure must not prevent graceful process shutdown.
                LOGGER.warning("Telegram command release failed during shutdown", extra={"error_type": type(exc).__name__, "update_id": payload.get("update_id")})
            raise
        except Exception as exc:
            LOGGER.warning("Telegram command delivery failed; retrying", extra={"error_type": type(exc).__name__, "update_id": payload.get("update_id")})
            transition = await coordination.retry_telegram_command(payload)
            if transition is TelegramCommandTransition.DEAD_LETTERED:
                LOGGER.error("Telegram command moved to dead-letter queue", extra={"update_id": payload.get("update_id")})
            elif transition is TelegramCommandTransition.OWNERSHIP_LOST:
                LOGGER.warning("Telegram command retry rejected after lease loss", extra={"update_id": payload.get("update_id")})
            elif transition is TelegramCommandTransition.INVARIANT_VIOLATION:
                LOGGER.error("Telegram command retry blocked by Redis key-type invariant violation", extra={"update_id": payload.get("update_id")})
            await asyncio.sleep(1)
        else:
            if not await coordination.finish_telegram_command(payload):
                LOGGER.warning("Telegram command completion rejected after lease loss", extra={"update_id": payload.get("update_id")})
            callback_query_id = str(payload.get("callback_query_id") or "")
            if callback_query_id and self.runtime.telegram is not None:
                try:
                    await self.runtime.telegram.answer_callback_query(callback_query_id)
                except Exception as exc:
                    LOGGER.warning("Telegram callback acknowledgement failed", extra={"error_type": type(exc).__name__})
        finally:
            self._telegram_command_context = previous_context
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
        return True

    async def _telegram_lease_heartbeat(self, coordination: Any, payload: dict[str, Any]) -> None:
        while True:
            await asyncio.sleep(self.TELEGRAM_HEARTBEAT_SECONDS)
            try:
                renewed = await coordination.renew_telegram_command(payload, lease_seconds=self.TELEGRAM_LEASE_SECONDS)
            except Exception as exc:
                LOGGER.warning("Telegram lease heartbeat failed", extra={"error_type": type(exc).__name__, "update_id": payload.get("update_id")})
                return
            if not renewed:
                return

    @staticmethod
    async def _send_owned_telegram_response(notifier: Any, response: str, ownership_check: Any | None) -> Any:
        if ownership_check is not None and not await ownership_check():
            raise TelegramLeaseLost("Telegram command lease is no longer owned")
        return await notifier.command_response(response)

    @staticmethod
    async def _send_owned_trade_proposal(notifier: Any, response: str, proposal_id: str, ownership_check: Any | None) -> Any:
        if ownership_check is not None and not await ownership_check():
            raise TelegramLeaseLost("Telegram command lease is no longer owned")
        return await notifier.trade_proposal(response, proposal_id)

    async def _handle_telegram_command(self, text: str, *, ownership_check: Any | None = None) -> None:
        notifier = self.runtime.telegram
        if notifier is None:
            return
        help_text = (
            "Monatise commands\n"
            "Fresh analysis: /analyze EURUSD | XAUUSD | US100.cash | AAPL\n"
            "Asset classes: FTMO forex, futures-linked CFDs, and stocks only\n"
            "Alias: /gold | /analysis EURUSD\n"
            "FTMO: /status /bridge /account /positions /orders\n"
            "Trade preview: /trade XAUUSD buy market sl=LEVEL tp=LEVEL\n"
            "Control: /approve ID /reject ID /arm [seconds] /disarm /kill\n"
            "Management previews: /close ID /cancel ID /sl ID LEVEL /tp ID LEVEL /breakeven ID"
        )
        if re.fullmatch(r"/(?:start|help)(?:@[A-Za-z0-9_]+)?", text, re.IGNORECASE):
            await self._send_owned_telegram_response(notifier, help_text, ownership_check)
            return
        if re.match(r"^/(?:status|bridge|account|positions|orders|trade|close|cancel|sl|tp|breakeven|approve|reject|arm|disarm|kill)(?:@|\s|$)", text, re.IGNORECASE):
            if re.match(r"^/approve(?:@|\s|$)", text, re.IGNORECASE):
                service = getattr(self.runtime, "ftmo_master", None)
                context = getattr(self, "_telegram_command_context", None) or {}
                if service is not None and hasattr(service, "repository") and service.authorized(str(context.get("user_id") or ""), str(context.get("chat_type") or "")):
                    await self._send_owned_telegram_response(
                        notifier,
                        "APPROVAL RECEIVED\nChecking current FTMO market, identity, session, risk, and execution gates...",
                        ownership_check,
                    )
            response = await self._handle_ftmo_telegram_command(text)
            await self._send_owned_telegram_response(notifier, response, ownership_check)
            return
        match = self.TELEGRAM_COMMAND_PATTERN.fullmatch(text)
        alias = self.TELEGRAM_ALIAS_PATTERN.fullmatch(text)
        raw_asset = ((match.group(1) if match else None) or (alias.group(1) if alias else None) or "")
        parts = raw_asset.strip().upper().split()
        symbol = parts[0].lstrip("$") if parts else ""
        requested_class = parts[1].casefold() if len(parts) == 2 else None
        if not (match or alias) or not self.STOCK_SYMBOL_PATTERN.fullmatch(symbol) or len(parts) > 2 or requested_class not in {None, "forex", "stock"}:
            await self._send_owned_telegram_response(notifier, help_text, ownership_check)
            return
        await self._handle_telegram_analysis_request(symbol, requested_class=requested_class, ownership_check=ownership_check)

    async def _handle_telegram_analysis_request(self, requested_symbol: str, *, requested_class: str | None = None, ownership_check: Any | None = None) -> None:
        notifier = self.runtime.telegram
        service = getattr(self.runtime, "ftmo_master", None)
        context = getattr(self, "_telegram_command_context", None) or {}
        user_id = str(context.get("user_id") or "")
        chat_type = str(context.get("chat_type") or "")
        if notifier is None:
            return
        # Lightweight runtimes used by read-only integrations predate the FTMO
        # control plane. Keep their analysis-only behavior; production always
        # constructs the durable FTMO service before Telegram starts.
        if service is None:
            resolved_class, resolved_symbol = await self._telegram_asset_classification(requested_symbol, requested_class)
            if resolved_class == "crypto":
                raw = await asyncio.wait_for(
                    self.runtime.analyse(resolved_symbol, interval="15m", source="monatise.telegram.command", notify=False), timeout=90,
                )
                response = self._format_telegram_crypto_analysis(raw)
            elif resolved_class == "stock":
                response = self._format_telegram_stock_analysis(await asyncio.wait_for(self.runtime.analyse_stock(resolved_symbol), timeout=90))
            else:
                response = f"Monatise NO TRADE: {requested_symbol}\nReason: asset class is ambiguous or unsupported.\nExecution: disabled"
            await self._send_owned_telegram_response(notifier, response, ownership_check)
            return
        if service is not None and not service.authorized(user_id, chat_type):
            LOGGER.warning("Rejected unauthorized Telegram analysis request", extra={"chat_type": chat_type})
            await self._send_owned_telegram_response(
                notifier, "ANALYSIS NOT STARTED\nReason: Telegram user is not authorized.", ownership_check,
            )
            return

        update_id = context.get("update_id")
        chat_id = self.runtime.environment.get("MONATISE_TELEGRAM_CHAT_ID", "")
        request_id, analysis_id = request_identity(chat_id, update_id)
        repository = getattr(service, "repository", None)
        requested_at = datetime.now(timezone.utc)
        request_record = {
            "request_id": request_id,
            "analysis_id": analysis_id,
            "telegram_user": user_id,
            "telegram_chat_id": chat_id,
            "telegram_update_id": update_id,
            "telegram_message_id": context.get("message_id"),
            "telegram_bot_id": self.runtime.environment.get("MONATISE_TELEGRAM_BOT_TOKEN", "").partition(":")[0] or None,
            "telegram_delivery_mode": self.runtime.environment.get("MONATISE_TELEGRAM_BOT_DELIVERY_MODE", ""),
            "requested_instrument": requested_symbol,
            "requested_at": requested_at.isoformat(),
            "status": "processing",
            "autonomous_execution": False,
        }
        if repository is not None and hasattr(repository, "claim_telegram_analysis_request"):
            claimed = await repository.claim_telegram_analysis_request(request_record)
            if not claimed:
                previous = await repository.telegram_analysis_request(request_id)
                cached = previous[0] if previous else {}
                if cached.get("status") == "completed":
                    if cached.get("analysis_message"):
                        await self._send_owned_telegram_response(notifier, cached["analysis_message"], ownership_check)
                    if cached.get("proposal_message") and cached.get("proposal_id"):
                        await self._send_owned_trade_proposal(notifier, cached["proposal_message"], cached["proposal_id"], ownership_check)
                    return
                if cached.get("status") == "waiting_for_quote" and cached.get("analysis_message"):
                    await self._send_owned_telegram_response(notifier, cached["analysis_message"], ownership_check)
                    await self._process_quote_request_once(cached.get("quote_request_id"))
                    return
                persisted = await repository.telegram_analysis(analysis_id) if hasattr(repository, "telegram_analysis") else None
                if persisted is not None:
                    analysis_message = format_analysis(persisted)
                    if persisted.get("executable") and hasattr(service, "create_quote_request"):
                        persisted_resolved = resolve_telegram_instrument(
                            str(persisted.get("canonical_instrument") or requested_symbol),
                            getattr(self.runtime, "ftmo_registry", FTMO_REGISTRY),
                        )
                        expiry = datetime.fromisoformat(str(persisted["expires_at"]).replace("Z", "+00:00"))
                        quote_request = await service.create_quote_request(
                            analysis_id=analysis_id, telegram_request_id=request_id,
                            canonical_instrument=persisted_resolved.canonical,
                            ftmo_symbol=persisted_resolved.execution_registry_symbol,
                            deadline=expiry,
                        )
                        if quote_request.get("state") not in {"PROPOSAL_PUBLISHED", "FAILED", "EXPIRED"}:
                            analysis_message += (
                                "\nWAITING FOR FTMO QUOTE — analysis retained"
                                f"\nQuote request: {quote_request['quote_request_id']}"
                                f"\nFTMO symbol: {quote_request['ftmo_symbol']}"
                            )
                            await repository.finish_telegram_analysis_request(request_id, {
                                "status": "waiting_for_quote", "analysis_message": analysis_message,
                                "signal_id": persisted.get("signal_id"),
                                "quote_request_id": quote_request["quote_request_id"],
                                "proposal_state": quote_request.get("state"),
                            })
                            await self._send_owned_telegram_response(notifier, analysis_message, ownership_check)
                            await self._process_quote_request_once(quote_request["quote_request_id"])
                            return
                    matching = next((item for item in await repository.proposals() if item.get("analysis_id") == analysis_id), None)
                    proposal_message = format_proposal(matching) if matching is not None else None
                    await repository.finish_telegram_analysis_request(request_id, {
                        "status": "completed", "analysis_message": analysis_message,
                        "proposal_id": matching.get("proposal_id") if matching else None,
                        "signal_id": matching.get("signal_id") if matching else None,
                        "proposal_message": proposal_message,
                    })
                    await self._send_owned_telegram_response(notifier, analysis_message, ownership_check)
                    if matching is not None:
                        await self._send_owned_trade_proposal(notifier, proposal_message, matching["proposal_id"], ownership_check)
                    return
                interrupted = (
                    f"ANALYSIS FAILED\nRequest: {request_id}\n"
                    "Reason: The previous attempt was interrupted before a durable analysis completed.\n"
                    "Run a fresh analysis request. No trade proposal was created."
                )
                await repository.finish_telegram_analysis_request(request_id, {
                    "status": "completed", "analysis_message": interrupted, "error_type": "InterruptedAnalysis",
                })
                await self._send_owned_telegram_response(notifier, interrupted, ownership_check)
                return

        try:
            resolved = resolve_telegram_instrument(requested_symbol, getattr(self.runtime, "ftmo_registry", FTMO_REGISTRY))
            if resolved.asset_class is FTMOAssetClass.CRYPTO:
                raise TelegramAnalysisError("Crypto is disabled for FTMO Telegram. Use forex, futures-linked CFDs, or stocks.")
            if requested_class == "crypto" and resolved.asset_class is not FTMOAssetClass.CRYPTO:
                raise TelegramAnalysisError("Instrument mapping could not be verified for crypto.")
            if requested_class == "stock" and resolved.asset_class is not FTMOAssetClass.STOCK:
                raise TelegramAnalysisError("Instrument mapping could not be verified for stocks.")
            if requested_class == "forex" and resolved.asset_class is not FTMOAssetClass.FOREX:
                raise TelegramAnalysisError("Instrument mapping could not be verified for forex.")
        except (TelegramAnalysisError, KeyError, ValueError) as exc:
            response = f"ANALYSIS NOT STARTED\nInstrument: {requested_symbol}\nReason: {exc}"
            if repository is not None and hasattr(repository, "finish_telegram_analysis_request"):
                await repository.finish_telegram_analysis_request(request_id, {"status": "completed", "analysis_message": response})
            await self._send_owned_telegram_response(notifier, response, ownership_check)
            return

        await self._send_owned_telegram_response(
            notifier,
            f"Running fresh Monatise analysis for {resolved.canonical}...\nRequest: {request_id}",
            ownership_check,
        )
        analysis_started_at = datetime.now(timezone.utc)
        try:
            trade_mode = None
            if repository is not None:
                bridge = await repository.bridge()
                for bridge_symbol, quote in ((bridge or {}).get("quotes") or {}).items():
                    if symbol_key(bridge_symbol) == symbol_key(resolved.execution_registry_symbol):
                        trade_mode = (quote or {}).get("trade_mode")
                        break
            session = classify_market_session(
                analysis_started_at, instrument=resolved.instrument, trade_mode=trade_mode,
            ).to_dict()
            if resolved.asset_class is FTMOAssetClass.CRYPTO:
                raw = await asyncio.wait_for(
                    self.runtime.analyse(
                        resolved.analysis_symbol, correlation_id=analysis_id, interval="15m",
                        source="monatise.telegram.on_demand", notify=False,
                    ), timeout=90,
                )
            elif resolved.asset_class is FTMOAssetClass.STOCK:
                raw = await asyncio.wait_for(self.runtime.analyse_stock(resolved.analysis_symbol), timeout=90)
            elif resolved.asset_class is FTMOAssetClass.FOREX:
                raw = await asyncio.wait_for(self.runtime.analyse_forex(resolved.instrument), timeout=90)
            else:
                raw = await asyncio.wait_for(
                    self.runtime.analyse_ftmo_futures_instrument(resolved.instrument), timeout=90,
                )
            analysis_completed_at = datetime.now(timezone.utc)
            analysis = normalize_analysis(
                raw, resolved, request_id=request_id, analysis_id=analysis_id,
                requested_at=requested_at, started_at=analysis_started_at,
                completed_at=analysis_completed_at, session=session,
            )
            signal_id = signal_identity(request_id, analysis_id, analysis) if analysis["executable"] else None
            analysis.update({
                "telegram_bot_id": request_record["telegram_bot_id"],
                "telegram_chat_id": chat_id,
                "telegram_user_id": user_id,
                "telegram_update_id": update_id,
                "telegram_request_message_id": context.get("message_id"),
                "telegram_delivery_mode": request_record["telegram_delivery_mode"],
                "strategy_version": "monatise.telegram.on_demand.v2",
                "lifecycle_state": "ANALYSIS_CREATED",
            })
            if signal_id is not None:
                analysis["signal_id"] = signal_id
            if repository is not None and hasattr(repository, "save_telegram_analysis"):
                if hasattr(repository, "audit"):
                    await repository.audit("analysis_created", analysis_id, {
                        "analysis_id": analysis_id, "telegram_request_id": request_id,
                        "telegram_update_id": update_id,
                    })
                if not await repository.save_telegram_analysis(analysis):
                    raise RuntimeError("analysis identity was already persisted")
                if hasattr(repository, "update_telegram_analysis"):
                    analysis = await repository.update_telegram_analysis(analysis_id, {"lifecycle_state": "ANALYSIS_PERSISTED"})
                else:
                    analysis["lifecycle_state"] = "ANALYSIS_PERSISTED"
                if hasattr(repository, "audit"):
                    await repository.audit("analysis_persisted", analysis_id, {
                        "analysis_id": analysis_id, "telegram_request_id": request_id,
                    })
            analysis_message = format_analysis(analysis)
            proposal = None
            quote_request = None
            proposal_state = "NO_TRADE" if not analysis["qualified"] else "CONTEXT_ONLY"
            if analysis["executable"] and service is not None:
                expiry = datetime.fromisoformat(str(analysis["expires_at"]).replace("Z", "+00:00"))
                if hasattr(service, "create_quote_request"):
                    analysis = await repository.update_telegram_analysis(analysis_id, {
                        "lifecycle_state": "QUOTE_REQUIRED", "ftmo_symbol": resolved.execution_registry_symbol,
                    })
                    await repository.audit("quote_required", analysis_id, {
                        "analysis_id": analysis_id, "telegram_request_id": request_id,
                        "ftmo_symbol": resolved.execution_registry_symbol,
                    })
                    quote_request = await service.create_quote_request(
                        analysis_id=analysis_id, telegram_request_id=request_id,
                        canonical_instrument=resolved.canonical,
                        ftmo_symbol=resolved.execution_registry_symbol,
                        deadline=expiry, now=analysis_completed_at,
                    )
                    proposal_state = "WAITING_FOR_QUOTE"
                    analysis_message += (
                        "\nWAITING FOR FTMO QUOTE — analysis retained"
                        f"\nQuote request: {quote_request['quote_request_id']}"
                        f"\nFTMO symbol: {quote_request['ftmo_symbol']}"
                        "\nNative MT5 Bid/Ask will be validated before a proposal is published."
                    )
                else:
                    execution_symbol = await service.execution_symbol_for(resolved.instrument, now=analysis_completed_at)
                    zone = analysis.get("entry_zone") or {}
                    proposal = await service.create_signal_proposal(
                        telegram_request_id=request_id, analysis_id=analysis_id, signal_id=signal_id,
                        symbol=execution_symbol, direction=analysis["bias"], analysis_entry=analysis["entry"],
                        analysis_stop=analysis["stop_loss"], analysis_target=analysis["targets"][0],
                        source="monatise.telegram.on_demand", analysis_state=analysis["bias"],
                        confirmation_status="confirmed", analysis_provider=analysis["analysis_provider"],
                        analysis_instrument=analysis["analysis_instrument"], analysis_exchange=resolved.instrument.exchange,
                        analysis_observed_at=analysis_completed_at, signal_expires_at=expiry,
                        entry_zone_low=zone.get("low"), entry_zone_high=zone.get("high"),
                        strategy=f"Monatise on-demand {analysis.get('market_state')}", timeframe=analysis["timeframe"],
                        conviction=analysis["conviction"], recommended_risk_percent=analysis["recommended_risk_percent"],
                        evidence_bundle={"market_data_provenance": analysis["market_data_provenance"], "session": analysis["session"]},
                        now=analysis_completed_at,
                    )
                    proposal_state = "TRADE_PREVIEW_READY"
            proposal_message = format_proposal(proposal) if proposal is not None else None
            if repository is not None and hasattr(repository, "finish_telegram_analysis_request"):
                await repository.finish_telegram_analysis_request(request_id, {
                    "status": "waiting_for_quote" if quote_request else "completed",
                    "analysis_completed_at": analysis_completed_at.isoformat(),
                    "analysis_message": analysis_message,
                    "proposal_id": proposal.get("proposal_id") if proposal else None,
                    "signal_id": signal_id,
                    "proposal_message": proposal_message,
                    "proposal_state": proposal_state,
                    "quote_request_id": quote_request.get("quote_request_id") if quote_request else None,
                    "latest_quote_request_at": analysis_completed_at.isoformat() if quote_request else None,
                    "requested_symbol": resolved.execution_registry_symbol,
                })
        except Exception as exc:
            LOGGER.warning("Telegram command analysis failed", extra={"symbol": requested_symbol, "error_type": type(exc).__name__})
            analysis_message = (
                f"ANALYSIS FAILED\nInstrument: {resolved.canonical}\n"
                "Reason: Fresh market data or the Monatise decision pipeline is currently unavailable.\n"
                "No trade proposal created."
            )
            proposal = None
            proposal_message = None
            quote_request = None
            if repository is not None and hasattr(repository, "finish_telegram_analysis_request"):
                await repository.finish_telegram_analysis_request(request_id, {
                    "status": "completed", "analysis_completed_at": datetime.now(timezone.utc).isoformat(),
                    "analysis_message": analysis_message, "error_type": type(exc).__name__,
                })
        analysis_delivery = await self._send_owned_telegram_response(notifier, analysis_message, ownership_check)
        proposal_delivery = None
        if proposal is not None and proposal_message is not None:
            proposal_delivery = await self._send_owned_trade_proposal(
                notifier, proposal_message, proposal["proposal_id"], ownership_check,
            )
        if repository is not None and hasattr(repository, "finish_telegram_analysis_request"):
            publication = {
                "analysis_telegram_message_id": analysis_delivery if isinstance(analysis_delivery, int) and not isinstance(analysis_delivery, bool) else None,
                "proposal_telegram_message_id": proposal_delivery if isinstance(proposal_delivery, int) and not isinstance(proposal_delivery, bool) else None,
                "telegram_message_id": (
                    proposal_delivery if isinstance(proposal_delivery, int) and not isinstance(proposal_delivery, bool)
                    else analysis_delivery if isinstance(analysis_delivery, int) and not isinstance(analysis_delivery, bool)
                    else None
                ),
                "telegram_publish_at": datetime.now(timezone.utc).isoformat(),
            }
            await repository.finish_telegram_analysis_request(request_id, publication)
            if hasattr(repository, "update_telegram_analysis") and await repository.telegram_analysis(analysis_id):
                await repository.update_telegram_analysis(analysis_id, {
                    "analysis_telegram_message_id": publication["analysis_telegram_message_id"],
                })
            if proposal is not None and isinstance(proposal_delivery, int) and not isinstance(proposal_delivery, bool):
                attach = getattr(repository, "attach_proposal_telegram_message", None)
                if attach is not None:
                    await attach(proposal["proposal_id"], proposal_delivery)
        if quote_request is not None:
            await self._process_quote_request_once(quote_request["quote_request_id"])

    async def _handle_ftmo_telegram_command(self, text: str) -> str:
        service = getattr(self.runtime, "ftmo_master", None)
        context = getattr(self, "_telegram_command_context", None) or {}
        user_id = str(context.get("user_id") or "")
        chat_type = str(context.get("chat_type") or "")
        if service is None:
            return "Monatise FTMO control is unavailable. Execution is blocked."
        if not service.authorized(user_id, chat_type):
            LOGGER.warning("Rejected unauthorized FTMO Telegram command", extra={"chat_type": chat_type})
            return "Unauthorized FTMO control command. Execution is blocked."
        command_text = re.sub(r"^(/\w+)@[A-Za-z0-9_]+", r"\1", text.strip())
        parts = command_text.split()
        command = parts[0].casefold()
        try:
            if command in {"/status", "/bridge"}:
                return format_ftmo_master_status(await service.status())
            if command == "/account":
                bridge = await service.repository.bridge()
                if not bridge:
                    raise FTMOMasterError("FTMO bridge has never connected")
                return "\n".join((
                    "MONATISE FTMO ACCOUNT",
                    f"Account: {'*' * max(0, len(bridge['account_id']) - 4)}{bridge['account_id'][-4:]}",
                    f"Server: {bridge['server']} | Currency: {bridge['currency']}",
                    f"Balance: {bridge['balance']} | Equity: {bridge['equity']}",
                    f"Identity match: {bool(bridge['identity_match'])}",
                ))
            if command in {"/positions", "/orders"}:
                bridge = await service.repository.bridge()
                if not bridge:
                    raise FTMOMasterError("FTMO bridge has never connected")
                key = "positions" if command == "/positions" else "orders"
                values = bridge.get(key) or []
                if not values:
                    return f"MONATISE FTMO {key.upper()}\nNone reported by the current MT5 heartbeat."
                rows = [f"MONATISE FTMO {key.upper()}"]
                rows.extend(json.dumps(item, sort_keys=True, separators=(",", ":"))[:400] for item in values[:20])
                return "\n".join(rows)
            if command == "/trade":
                if len(parts) < 6:
                    raise FTMOMasterError("use /trade SYMBOL buy|sell market|limit|stop [entry=LEVEL] sl=LEVEL tp=LEVEL")
                symbol, side, order_type = parts[1:4]
                parameters = dict(item.split("=", 1) for item in parts[4:] if "=" in item)
                if "sl" not in parameters or "tp" not in parameters:
                    raise FTMOMasterError("trade preview requires sl=LEVEL and tp=LEVEL")
                proposal = await service.create_trade_proposal(
                    actor=user_id, symbol=symbol, side=side, order_type=order_type,
                    entry=parameters.get("entry"), stop_loss=parameters["sl"], take_profit=parameters["tp"],
                )
                return format_proposal(proposal)
            if command in {"/close", "/cancel", "/breakeven"}:
                if len(parts) != 2:
                    raise FTMOMasterError(f"use {command} TICKET")
                return format_proposal(await service.create_management_proposal(actor=user_id, operation=command[1:], target_id=parts[1]))
            if command in {"/sl", "/tp"}:
                if len(parts) != 3:
                    raise FTMOMasterError(f"use {command} TICKET LEVEL")
                return format_proposal(await service.create_management_proposal(actor=user_id, operation=command[1:], target_id=parts[1], value=parts[2]))
            if command == "/approve":
                if len(parts) != 2:
                    raise FTMOMasterError("use /approve PROPOSAL_ID")
                result = await service.approve(parts[1], user_id)
                if "execution_snapshot" not in result:
                    return f"FTMO command {result['command_id'][:12]} approved and queued for the account-bound MT5 EA."
                snapshot = result.get("execution_snapshot") or {}
                risk = result.get("risk_policy") or {}
                payload = result.get("payload") or {}
                return "\n".join((
                    "REVALIDATED",
                    f"Signal: {result.get('signal_id') or 'operator'} | Analysis: {result.get('analysis_id') or 'operator'}",
                    f"FTMO Bid/Ask: {snapshot.get('ftmo_bid') or 'unknown'} / {snapshot.get('ftmo_ask') or 'unknown'}",
                    f"Entry: {payload.get('entry') or 'unknown'} | Volume: {payload.get('volume') or 'unknown'} lots",
                    f"Risk: {Decimal(str(risk.get('actual_risk_fraction') or 0)) * 100:.2f}% (${risk.get('actual_risk_amount') or 'unknown'})",
                    f"Session: {(result.get('market_session') or {}).get('market_session') or 'UNKNOWN'}",
                    f"Command: {result['command_id'][:12]} — queued for the account-bound MT5 EA.",
                    "Autonomous execution remains OFF.",
                ))
            if command == "/reject":
                if len(parts) != 2:
                    raise FTMOMasterError("use /reject PROPOSAL_ID")
                await service.reject(parts[1], user_id)
                return f"FTMO proposal {parts[1]} rejected. No order was sent."
            if command == "/arm":
                seconds = int(parts[1]) if len(parts) == 2 else None
                return format_ftmo_master_status(await service.arm(user_id, seconds))
            if command == "/disarm":
                return format_ftmo_master_status(await service.disarm(user_id))
            if command == "/kill":
                return format_ftmo_master_status(await service.kill(user_id))
        except (FTMOMasterError, ValueError, RuntimeError) as exc:
            return f"Monatise FTMO BLOCKED\nReason: {exc}\nNo order was sent."
        return "Unknown FTMO command. Use /help."

    async def _ftmo_bridge_request(self, scope: dict[str, Any], receive: Any) -> tuple[int, dict[str, Any]]:
        service = getattr(self.runtime, "ftmo_master", None)
        if service is None or not service.configuration.bridge_secret:
            return 503, {"status": "unavailable", "reason": "FTMO bridge is not configured"}
        method = scope.get("method", "GET").upper()
        path = scope.get("path", "")
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if len(body) > 1_048_576:
                return 413, {"status": "request_too_large"}
            if not message.get("more_body", False):
                break
        headers = {key.decode().casefold(): value.decode() for key, value in scope.get("headers", ())}
        timestamp = headers.get("x-monatise-timestamp", "")
        nonce = headers.get("x-monatise-nonce", "")
        signature = headers.get("x-monatise-signature", "")
        try:
            FTMOBridgeAuthenticator.verify(service.configuration.bridge_secret, method, path, timestamp, nonce, body, signature)
            if not await service.repository.claim_nonce(nonce):
                raise FTMOMasterError("bridge nonce was already used")
            parsed = json.loads(body.decode()) if body else {}
            if not isinstance(parsed, dict):
                raise FTMOMasterError("bridge request must contain a JSON object")
            if path == "/api/ftmo/bridge/heartbeat" and method == "POST":
                result = await service.accept_bridge_heartbeat(parsed)
                for event in result.get("lifecycle_events") or ():
                    await self._notify_ftmo_lifecycle(event)
                return 200, result
            if path == "/api/ftmo/bridge/commands" and method == "GET":
                commands = await service.commands_for_bridge(limit=5)
                signed = []
                for command in commands:
                    canonical = json.dumps(command, sort_keys=True, separators=(",", ":"))
                    signed.append({
                        "payload_base64": base64.b64encode(canonical.encode()).decode(),
                        "signature": hmac.new(service.configuration.bridge_secret.encode(), canonical.encode(), hashlib.sha256).hexdigest(),
                    })
                return 200, {"status": "ready", "commands": signed, "count": len(signed)}
            match = re.fullmatch(r"/api/ftmo/bridge/commands/([a-f0-9]{64})/ack", path)
            if match and method == "POST":
                result = await service.acknowledge(match.group(1), parsed)
                if result.get("notification_required", True):
                    await self._notify_ftmo_command_result(result)
                return 200, {"status": "accepted", "command_status": result["status"]}
            return 404, {"status": "not_found"}
        except FTMOMasterError as exc:
            LOGGER.warning("FTMO bridge request rejected", extra={"path": path, "reason": str(exc)})
            return 401, {"status": "rejected", "reason": str(exc)}
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            return 400, {"status": "invalid_request", "reason": str(exc)}

    async def _send_ftmo_notification(self, lines: list[str]) -> None:
        notifier = getattr(self.runtime, "telegram", None)
        if notifier is None:
            return
        try:
            await notifier.command_response("\n".join(lines))
        except Exception as exc:
            # Broker acknowledgement must never be retried merely because a
            # secondary notification transport is unavailable.
            LOGGER.warning("FTMO Telegram lifecycle notification failed", extra={"error_type": type(exc).__name__})

    async def _notify_ftmo_command_result(self, command: Mapping[str, Any]) -> None:
        status = str(command.get("lifecycle_state") or command.get("status") or "MT5_RECEIVED").upper()
        payload = command.get("payload") if isinstance(command.get("payload"), Mapping) else {}
        provenance = command.get("analysis_provenance") if isinstance(command.get("analysis_provenance"), Mapping) else {}
        title = "FTMO EXECUTION FAILED" if status in {"EXECUTION_FAILED", "REJECTED", "BROKER_UNCERTAIN"} else "FTMO EXECUTION CONFIRMATION"
        lines = [
            title,
            f"Instrument: {payload.get('symbol') or 'unknown'} | Direction: {str(payload.get('side') or 'unknown').upper()}",
            f"Status: {status}",
            f"Requested: {command.get('requested_price') or payload.get('entry') or 'unknown'} | Fill: {command.get('fill_price') or 'pending'}",
            f"Volume: {command.get('executed_volume') or payload.get('volume') or 'unknown'} | SL: {command.get('executed_stop_loss') or payload.get('stop_loss') or 'unknown'} | TP: {command.get('executed_take_profit') or payload.get('take_profit') or 'unknown'}",
            f"Ticket: {command.get('broker_ticket') or 'pending'} | Retcode: {command.get('broker_retcode') or 'pending'}",
            f"Execution source: FTMO MT5 | Analysis source: {provenance.get('analysis_provider') or 'Monatise'} + Monatise",
        ]
        await self._send_ftmo_notification(lines)

    async def _notify_ftmo_lifecycle(self, event: Mapping[str, Any]) -> None:
        state = str(event.get("lifecycle_state") or "UNKNOWN").upper()
        lines = [
            f"FTMO {state.replace('_', ' ')}",
            f"Instrument: {event.get('symbol') or 'unknown'} | Direction: {str(event.get('side') or 'unknown').upper()}",
            f"Entry: {event.get('entry') or 'unknown'} | Volume: {event.get('volume') or 'unknown'}",
            f"SL: {event.get('stop_loss') or 'unknown'} | TP: {event.get('take_profit') or 'unknown'}",
            f"Ticket: {event.get('broker_ticket') or 'unknown'} | Unrealized P/L: {event.get('unrealized_profit') if event.get('unrealized_profit') is not None else 'n/a'}",
            f"Analysis source: {event.get('analysis_provider') or 'Monatise'} + Monatise | Status: {state}",
        ]
        await self._send_ftmo_notification(lines)

    async def _telegram_asset_classification(self, symbol: str, requested_class: str | None) -> tuple[str, str]:
        stock = next((item for item in FTMO_REGISTRY.for_asset_class(FTMOAssetClass.STOCK)
            if symbol.casefold() in {item.ftmo_symbol.casefold(), item.underlying_symbol.casefold(), (item.provider_symbol or "").casefold()}), None)
        crypto = next((item for item in FTMO_REGISTRY.for_asset_class(FTMOAssetClass.CRYPTO)
            if symbol.casefold() in {item.ftmo_symbol.casefold(), item.underlying_symbol.casefold()}), None)
        if requested_class == "stock":
            return ("stock", stock.underlying_symbol) if stock is not None else ("unknown", symbol)
        if requested_class == "crypto":
            return ("crypto", crypto.underlying_symbol) if crypto is not None else ("unknown", symbol)
        if stock is not None and crypto is None:
            return "stock", stock.underlying_symbol
        if crypto is not None and stock is None:
            return "crypto", crypto.underlying_symbol
        return "unknown", symbol

    @staticmethod
    def _format_telegram_crypto_analysis(analysis: dict[str, Any]) -> str:
        symbol = str(analysis.get("symbol") or "UNKNOWN")
        classification = str(analysis.get("classification") or "no_trade").upper()
        direction = str(analysis.get("direction") or "none").upper()
        confirmed = str(analysis.get("entry_confirmation_status") or "").casefold() == "confirmed"
        expires_at = analysis.get("expires_at")
        if expires_at:
            try:
                confirmed = confirmed and datetime.fromisoformat(str(expires_at).replace("Z", "+00:00")) > datetime.now(timezone.utc)
            except ValueError:
                confirmed = False
        actionable = classification not in {"NO_TRADE", "GRID", "TWO_SIDED"} and direction in {"LONG", "SHORT"} and confirmed
        if not actionable:
            reasons = list(analysis.get("blockers") or analysis.get("reasons") or analysis.get("price_action_reasons") or [])[:3]
            lines = [f"Monatise NO TRADE: {symbol}", f"Timeframe: {analysis.get('interval') or '15m'}", f"Score: {int(analysis.get('score') or 0):+d}/10 | threshold: ±{int(analysis.get('score_threshold') or 7)}"]
            if reasons:
                lines.append("Why: " + "; ".join(map(str, reasons)))
        else:
            lines = [f"Monatise {direction}: {symbol}", f"Timeframe: {analysis.get('interval') or '15m'}", f"Entry: {analysis.get('entry')}", f"Stop: {analysis.get('invalidation')}", f"Target: {analysis.get('target')}", f"Score: {int(analysis.get('score') or 0):+d}/10"]
        lines.append("Execution: disabled")
        return "\n".join(lines)

    @staticmethod
    def _format_telegram_stock_analysis(analysis: dict[str, Any]) -> str:
        symbol = str(analysis.get("asset") or "UNKNOWN")
        confirmed = analysis.get("setup_status") == "confirmed"
        decision = str(analysis.get("decision") or "NO_TRADE")
        actionable = confirmed and decision in {"BUY_WATCH", "SELL_WATCH"}
        if not actionable:
            reasons = list(analysis.get("cautions") or analysis.get("reasons") or [])[:3]
            lines = [f"Monatise NO TRADE: {symbol}", f"Score: {int(analysis.get('score') or 0):+d}/10 | threshold: ±{int(analysis.get('score_threshold') or 3)}"]
            if reasons:
                lines.append("Why: " + "; ".join(map(str, reasons)))
        else:
            direction = "LONG" if decision == "BUY_WATCH" else "SHORT"
            lines = [f"Monatise {direction}: {symbol}", f"Entry: {analysis.get('entry')}", f"Stop: {analysis.get('stop_loss')}", f"Target: {analysis.get('target')}", f"Score: {int(analysis.get('score') or 0):+d}/10"]
        lines.append("Execution: disabled")
        return "\n".join(lines)
    def _market_rate_limited(self, scope: dict[str, Any], *, maximum: int = 120) -> bool:
        client = scope.get("client") or ("unknown", 0)
        address = str(client[0])
        window = int(time()) // 60
        previous_window, count = self._market_rate_windows.get(address, (window, 0))
        if previous_window != window:
            count = 0
        count += 1
        self._market_rate_windows[address] = (window, count)
        if len(self._market_rate_windows) > 2048:
            self._market_rate_windows = {key: value for key, value in self._market_rate_windows.items() if value[0] == window}
        return count > maximum

    async def _stocks_search(self, scope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        query = parse_qs(scope.get("query_string", b"").decode())
        term = str(query.get("q", [""])[0]).strip().upper()
        if len(term) > 40:
            return 400, {"status": "invalid_request", "reason": "search query is too long"}
        matches = [{
            "symbol": item.ftmo_symbol, "ftmo_symbol": item.ftmo_symbol,
            "underlying_symbol": item.underlying_symbol, "name": item.display_name,
            "exchange": item.exchange, "asset_class": "stock", "tradable": False,
        } for item in FTMO_REGISTRY.for_asset_class(FTMOAssetClass.STOCK)
            if not term or term.casefold() in item.ftmo_symbol.casefold()
            or term.casefold() in item.underlying_symbol.casefold()
            or term.casefold() in item.display_name.casefold()
        ][:10]
        return 200, {"status": "ready", "query": term, "results": matches, "execution_enabled": False}

    async def _stock_analysis(self, symbol: str) -> tuple[int, dict[str, Any]]:
        if not self.STOCK_SYMBOL_PATTERN.fullmatch(symbol):
            return 400, {"status": "invalid_request", "reason": "unsupported stock symbol"}
        instrument = next((item for item in FTMO_REGISTRY.for_asset_class(FTMOAssetClass.STOCK)
            if symbol.casefold() in {item.ftmo_symbol.casefold(), item.underlying_symbol.casefold(), (item.provider_symbol or "").casefold()}), None)
        if instrument is None:
            return 400, {"status": "invalid_request", "reason": "stock is not in the FTMO registry"}
        if instrument.market_data_provider != "alpaca" or not instrument.provider_symbol:
            return 503, {"status": "provider_unavailable", "symbol": instrument.ftmo_symbol, "reason": "FTMO stock market-data mapping is unavailable; failed closed"}
        try:
            analysis, cache_hit = await asyncio.wait_for(self._cached_openclaw_stock_analysis((instrument.provider_symbol, "1h")), timeout=30)
            analysis = refresh_setup_validity(analysis)
        except (TypeError, ValueError) as exc:
            return 400, {"status": "invalid_request", "reason": str(exc)}
        except Exception as exc:
            LOGGER.warning("stock analysis unavailable", extra={"symbol": symbol, "error_type": type(exc).__name__})
            return 503, {"status": "analysis_unavailable", "symbol": symbol, "error_type": type(exc).__name__}
        return 200, {
            "status": "ready", "symbol": instrument.ftmo_symbol, "ftmo_symbol": instrument.ftmo_symbol,
            "underlying_symbol": instrument.underlying_symbol, "exchange": instrument.exchange,
            "company_name": instrument.display_name,
            "analysis": analysis, "cache_hit": cache_hit, "execution_enabled": False,
        }

    async def _stocks_scanner(self) -> tuple[int, dict[str, Any]]:
        dependency = getattr(self.runtime, "dependencies", {}).get("ftmo_stock_scan", {})
        latest = dependency.get("last_result") or {}
        results = latest.get("results") if isinstance(latest, dict) else []
        if not isinstance(results, list):
            results = []
        return 200, {
            "status": "ready" if dependency.get("last_success_at") else "warming",
            "generated_at": dependency.get("last_success_at") or datetime.now(timezone.utc).isoformat(), "refresh_seconds": 120,
            "results": results, "providers": ["Alpaca", "FlashAlpha", "Quiver Quantitative", "Finnhub"],
            "universe_size": len(FTMO_REGISTRY.for_asset_class(FTMOAssetClass.STOCK)),
            "registry_version": FTMO_REGISTRY.for_asset_class(FTMOAssetClass.STOCK)[0].registry_version,
            "execution_enabled": False,
        }

    def _openclaw_cache_ttl(self) -> float:
        raw_ttl = self.runtime.environment.get("MONATISE_OPENCLAW_CACHE_TTL_SECONDS", "300")
        try:
            return min(max(float(raw_ttl), 0.0), 900.0)
        except ValueError:
            return 300.0

    def _openclaw_cached(self, cache_key: tuple[str, str]) -> dict[str, Any] | None:
        cached = self._openclaw_cache.get(cache_key)
        if cached is None:
            return None
        if monotonic() - cached[0] >= self._openclaw_cache_ttl():
            self._openclaw_cache.pop(cache_key, None)
            return None
        return cached[1]

    def _store_openclaw_cache(self, cache_key: tuple[str, str], analysis: dict[str, Any]) -> None:
        self._openclaw_cache[cache_key] = (monotonic(), analysis)
        if len(self._openclaw_cache) > 256:
            oldest = min(self._openclaw_cache, key=lambda key: self._openclaw_cache[key][0])
            self._openclaw_cache.pop(oldest, None)

    async def _operator_status(self) -> tuple[int, dict[str, Any]]:
        configured = self.runtime.coinglass is not None and bool(self.runtime.environment.get("COINGLASS_API_KEY", "").strip())
        return 200, {
            "integrations": {"coinglass": {
                "configured": configured,
                "exchange": "Binance",
                "api_version": "v4",
                "intervals": list(CoinGlassProductionAdapter.SUPPORTED_INTERVALS),
                "datasets": sorted(CoinGlassProductionAdapter.DASHBOARD_PATHS),
            }},
            "telegram": await self._telegram_queue_telemetry(),
            "execution_enabled": False,
        }

    async def _telegram_queue_telemetry(self) -> dict[str, Any]:
        coordination = self.runtime.redis_coordination
        if coordination is None or not hasattr(coordination, "telegram_queue_metrics"):
            metrics = {
                "redis": "unavailable", "pending_depth": None, "active_lease_count": None,
                "retry_count": None, "dead_letter_count": None, "last_success_at": None,
                "oldest_queued_age_seconds": None, "dlq_overflow_count": None,
                "invariant_violation_count": None, "counter_corruption_count": None,
                "counter_corruption_keys": [], "queue_status": "degraded",
            }
        else:
            metrics = await coordination.telegram_queue_metrics()
        dependency = getattr(self.runtime, "dependencies", {}).get("telegram_inbound", {})
        running = self._telegram_worker is not None and not self._telegram_worker.done()
        worker_state = "running" if running else "stopped"
        if running and dependency.get("worker") == "retrying":
            worker_state = "redis_retrying"
        return {
            **metrics,
            "worker": worker_state,
            "worker_error_type": dependency.get("worker_error_type"),
            "worker_error_at": dependency.get("worker_error_at"),
            "registration": dependency.get("registration", "not_configured"),
        }

    async def _market_summary(self, _scope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        now = monotonic()
        if self._market_summary_cache is not None and now - self._market_summary_cache[0] < 5:
            return 200, {**self._market_summary_cache[1], "cache_hit": True}
        provider = self.runtime.coinglass
        if provider is None:
            return 503, {"status": "unavailable", "dataset": "markets"}

        async def current_price(symbol: str) -> dict[str, Any] | None:
            try:
                price = await asyncio.to_thread(provider.latest_current_price, symbol)
            except Exception as exc:
                LOGGER.warning("market summary price unavailable", extra={"symbol": symbol, "error_type": type(exc).__name__})
                return None
            return {"symbol": symbol, "price": float(price), "source": "coinglass", "assetClass": "crypto", "tradable": False}

        assets = [item for item in await asyncio.gather(*(current_price(symbol) for symbol in ("BTC", "ETH", "SOL"))) if item is not None]
        if not assets:
            return 503, {"status": "unavailable", "dataset": "markets", "source": "coinglass"}
        payload = {
            "status": "ready",
            "assets": assets,
            "groups": {
                "crypto": [item["symbol"] for item in assets],
                "stocks": [item.ftmo_symbol for item in FTMO_REGISTRY.for_asset_class(FTMOAssetClass.STOCK)],
                "futures_linked": [item.ftmo_symbol for item in FTMO_REGISTRY.for_asset_class(FTMOAssetClass.FUTURES_LINKED)],
            },
            "source": "coinglass",
            "cache_hit": False,
            "execution_enabled": False,
        }
        self._market_summary_cache = (now, payload)
        return 200, payload

    async def _significant_universe(self, _scope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if self.runtime.redis is None:
            return 503, {"status": "unavailable", "candidates": [], "execution_enabled": False}
        namespace = self.runtime.environment.get("MONATISE_REDIS_NAMESPACE", "monatise:production-analysis")
        raw = await self.runtime.redis.get(f"{namespace}:ftmo:crypto:ranked:v1")
        try:
            candidates = json.loads(raw) if raw else []
        except (TypeError, ValueError):
            candidates = []
        if not isinstance(candidates, list):
            candidates = []
        scan_completed = bool(getattr(self.runtime, "dependencies", {}).get("ftmo_crypto_scan", {}).get("last_success_at"))
        return 200, {"status": "ready" if candidates or scan_completed else "warming", "candidates": candidates[:20], "source": "FTMO crypto registry with CoinGlass intelligence", "execution_enabled": False}

    async def _analysis_candles(self, scope: dict[str, Any], *, minimum: int) -> tuple[int, dict[str, Any] | list[Candle], str, str]:
        query = parse_qs(scope.get("query_string", b"").decode())
        symbol = str(query.get("symbol", ["BTC"])[0]).strip().upper()
        interval = str(query.get("interval", ["1h"])[0]).strip() or "1h"
        try:
            requested_limit = int(query.get("limit", ["120"])[0])
        except ValueError:
            return 400, {"status": "invalid_request", "reason": "limit must be an integer"}, symbol, interval
        limit = max(minimum, min(200, requested_limit))
        candle_scope = {**scope, "query_string": f"symbol={symbol}&interval={interval}&limit={limit}".encode()}
        code, payload = await self._market_candles(candle_scope)
        if code != 200:
            return code, payload, symbol, interval
        candles = [
            Candle(
                datetime.fromtimestamp(float(row["time"]) / 1000, tz=timezone.utc).isoformat(),
                float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]), float(row.get("volume", 0)),
            )
            for row in payload["candles"]
        ]
        return 200, candles, symbol, interval

    async def _fibonacci_analysis(self, scope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        code, result, symbol, interval = await self._analysis_candles(scope, minimum=20)
        if code != 200:
            return code, result if isinstance(result, dict) else {"status": "unavailable"}
        candles = result
        assert isinstance(candles, list)
        try:
            mark = candles[-1].close
            return 200, {
                "analysis": analyze_fibonacci(symbol, interval, candles, mark=mark).to_dict(),
                "fvg": analyze_fvg(symbol, interval, candles, mark=mark).to_dict(),
                "source": "coinglass",
                "execution_enabled": False,
            }
        except (TypeError, ValueError) as exc:
            return 422, {"status": "analysis_unavailable", "reason": str(exc)}

    async def _context_radar(self, scope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        code, result, symbol, interval = await self._analysis_candles(scope, minimum=50)
        if code != 200:
            return code, result if isinstance(result, dict) else {"status": "unavailable"}
        candles = result
        assert isinstance(candles, list)
        try:
            indicators = indicator_snapshot(candles)
            mark = candles[-1].close
            return 200, {
                "symbol": symbol,
                "interval": interval,
                "source": "coinglass",
                "indicator": indicators.__dict__,
                "instruction": grid_instruction(indicators),
                "contextAssets": context_assets(symbol, {symbol: mark}),
                "execution_enabled": False,
            }
        except (TypeError, ValueError) as exc:
            return 422, {"status": "analysis_unavailable", "reason": str(exc)}

    @staticmethod
    def _coinglass_rows(payload: Any) -> list[dict[str, Any]]:
        data = payload.get("data", []) if isinstance(payload, dict) else []
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in ("list", "data", "rows"):
                rows = data.get(key)
                if isinstance(rows, list):
                    return [item for item in rows if isinstance(item, dict)]
            return [data]
        return []

    async def _coinglass_context(self, scope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        query = parse_qs(scope.get("query_string", b"").decode())
        symbol = str(query.get("symbol", ["BTC"])[0]).strip().upper()
        interval = str(query.get("interval", ["1h"])[0]).strip() or "1h"
        if symbol not in self.MARKET_SYMBOLS or interval not in self.MARKET_INTERVALS:
            return 400, {"status": "invalid_request", "reason": "unsupported symbol or interval"}
        provider = self.runtime.coinglass
        if provider is None:
            return 503, {"status": "unavailable", "source": "coinglass"}
        datasets = {
            "fundingRate": ("/api/futures/funding-rate/exchange-list", {}),
            "openInterest": ("/api/futures/open-interest/exchange-list", {"symbol": symbol}),
            "liquidations": ("/api/futures/liquidation/aggregated-history", {"exchange_list": "Binance", "symbol": symbol, "interval": interval, "limit": "24"}),
            "fearGreed": ("/api/index/fear-greed-history", {}),
        }

        async def load(name: str, path: str, params: dict[str, str]) -> tuple[str, list[dict[str, Any]], str | None]:
            try:
                payload = await asyncio.to_thread(provider.dashboard_query, path, params)
                return name, self._coinglass_rows(payload), None
            except Exception as exc:
                LOGGER.warning("CoinGlass context dataset unavailable", extra={"dataset": name, "error_type": type(exc).__name__})
                return name, [], type(exc).__name__

        results = await asyncio.gather(*(load(name, path, params) for name, (path, params) in datasets.items()))
        rows = {name: data for name, data, _error in results}
        funding_asset = next((item for item in rows["fundingRate"] if str(item.get("symbol", "")).upper() == symbol), None)
        if funding_asset is not None:
            stablecoin_rows = funding_asset.get("stablecoin_margin_list", [])
            rows["fundingRate"] = [item for item in stablecoin_rows if isinstance(item, dict)]
        unavailable = [{"feature": name, "reason": error} for name, _data, error in results if error]
        return 200, {
            "symbol": symbol,
            "interval": interval,
            "source": "CoinGlass",
            "available": not unavailable,
            "unavailable": unavailable,
            **rows,
            "execution_enabled": False,
        }

    async def _liquidity_clusters(self, scope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        query = parse_qs(scope.get("query_string", b"").decode())
        symbol = str(query.get("symbol", ["BTC"])[0]).strip().upper()
        interval = str(query.get("interval", ["1h"])[0]).strip() or "1h"
        if symbol not in self.MARKET_SYMBOLS or interval not in self.MARKET_INTERVALS:
            return 400, {"status": "invalid_request", "reason": "unsupported symbol or interval"}
        provider = self.runtime.coinglass
        if provider is None:
            return 503, {"status": "unavailable", "source": "coinglass"}
        try:
            price = await asyncio.to_thread(provider.latest_current_price, symbol)
            derivatives = await asyncio.to_thread(provider.derivatives_snapshot, symbol, interval)
        except Exception as exc:
            LOGGER.warning("liquidity cluster inputs unavailable: %s (%s: %s)", symbol, type(exc).__name__, exc.__cause__ or exc)
            return 503, {"status": "unavailable", "source": "coinglass"}
        cluster_map = estimate_liquidation_clusters(
            price=float(price) if price is not None else None,
            open_interest_usd=derivatives.get("open_interest"),
            funding_rate=derivatives.get("funding_rate"),
        )
        if cluster_map is None:
            return 503, {"status": "unavailable", "reason": "insufficient inputs for liquidity cluster estimate"}
        return 200, {
            "symbol": symbol,
            "interval": interval,
            "price": price,
            "source": "modeled",
            "methodology": (
                "Estimated by spreading open interest across standard leverage tiers "
                "(5x-100x). This is a heuristic model, not CoinGlass's measured "
                "liquidation heatmap, which requires a Professional-tier API plan."
            ),
            "magnetBias": cluster_map.magnet_bias,
            "nearestLongCluster": asdict(cluster_map.nearest_long_cluster) if cluster_map.nearest_long_cluster else None,
            "nearestShortCluster": asdict(cluster_map.nearest_short_cluster) if cluster_map.nearest_short_cluster else None,
            "clusters": [asdict(cluster) for cluster in cluster_map.clusters],
            "execution_enabled": False,
        }

    async def _market_candles(self, scope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        query = parse_qs(scope.get("query_string", b"").decode())
        symbol = str(query.get("symbol", ["BTC"])[0]).strip().upper()
        interval = str(query.get("interval", ["30m"])[0]).strip()
        try:
            limit = int(query.get("limit", ["96"])[0])
        except ValueError:
            return 400, {"status": "invalid_request", "reason": "limit must be an integer"}
        if symbol not in self.MARKET_SYMBOLS or interval not in self.MARKET_INTERVALS or not 2 <= limit <= 200:
            return 400, {"status": "invalid_request", "reason": "unsupported symbol, interval, or limit"}
        providers = (
            self.runtime.market_data_providers()
            if callable(getattr(self.runtime, "market_data_providers", None))
            else {
                name: provider
                for name, provider in (
                    ("coinglass", getattr(self.runtime, "coinglass", None)),
                    ("backpack_public", getattr(self.runtime, "backpack", None)),
                )
                if provider is not None
            }
        )
        if not providers:
            return 503, {"status": "unavailable", "dataset": "candles"}
        try:
            max_age = self.INTERVAL_MAX_AGE_SECONDS[interval]
            snapshot = await asyncio.to_thread(
                MarketDataEngine(providers).collect,
                MarketDataRequest(symbol, interval=interval, candle_limit=limit, max_age_seconds=max_age),
            )
            if not snapshot.quality.usable:
                raise RuntimeError("no market-data provider returned usable candles")
            candles = snapshot.candles
        except Exception as exc:
            LOGGER.warning("market candles unavailable", extra={"symbol": symbol, "interval": interval, "error_type": type(exc).__name__})
            return 503, {"status": "unavailable", "dataset": "candles", "source": "market_data", "error_type": type(exc).__name__}
        rows = []
        try:
            for candle in candles:
                raw_timestamp = str(candle.timestamp).strip()
                if raw_timestamp.isdigit():
                    epoch = int(raw_timestamp)
                    if epoch > 10_000_000_000:
                        epoch /= 1000
                    timestamp = datetime.fromtimestamp(epoch, tz=timezone.utc)
                else:
                    timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                rows.append({"time": int(timestamp.timestamp() * 1000), "open": candle.open, "high": candle.high, "low": candle.low, "close": candle.close, "volume": candle.volume})
        except (ValueError, OverflowError, OSError) as exc:
            LOGGER.warning("market candles unavailable", extra={"symbol": symbol, "interval": interval, "error_type": type(exc).__name__})
            return 503, {"status": "unavailable", "dataset": "candles", "source": "market_data", "error_type": type(exc).__name__}
        return 200, {
            "status": "ready",
            "quality_status": snapshot.quality.status.value,
            "symbol": symbol,
            "interval": interval,
            "source": snapshot.quality.source,
            "fallback_used": bool(snapshot.metadata.get("fallback_used")),
            "candles": rows,
            "execution_enabled": False,
        }

    async def _coinglass_dashboard(self, scope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if self.runtime.coinglass is None:
            return 503, {"status": "unavailable", "source": "coinglass"}
        prefix = "/api/coinglass/proxy"
        upstream_path = scope.get("path", "")[len(prefix):]
        if upstream_path not in CoinGlassProductionAdapter.DASHBOARD_PATHS:
            return 400, {"status": "invalid_request", "reason": "unsupported CoinGlass dashboard dataset"}
        query = {key: str(values[0]) for key, values in parse_qs(scope.get("query_string", b"").decode()).items() if values}
        try:
            payload = await asyncio.to_thread(self.runtime.coinglass.dashboard_query, upstream_path, query)
        except ValueError as exc:
            return 400, {"status": "invalid_request", "reason": str(exc)}
        except Exception as exc:
            # dashboard_query's final raise carries a generic message but chains
            # the real per-attempt failure (often CoinGlass's own rejection
            # reason) as __cause__. There is no formatter configured anywhere
            # in this app that prints logging "extra" fields, so put the
            # detail directly in the message -- otherwise every dashboard
            # failure prints identically and the real reason is unrecoverable.
            LOGGER.warning("CoinGlass dashboard dataset unavailable: %s (%s: %s)", upstream_path, type(exc).__name__, exc.__cause__ or exc)
            return 503, {"status": "unavailable", "source": "coinglass", "dataset": upstream_path, "error_type": type(exc).__name__}
        return 200, payload

    async def _openclaw_status(self, scope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        token = self.runtime.environment.get("MONATISE_OPENCLAW_TOKEN", "").strip()
        if not token:
            return 503, {"status": "unavailable", "reason": "openclaw_not_configured"}
        headers = {key.decode().casefold(): value.decode() for key, value in scope.get("headers", ())}
        scheme, _, supplied = headers.get("authorization", "").partition(" ")
        if scheme.casefold() != "bearer" or not secrets.compare_digest(supplied.strip(), token):
            return 401, {"status": "unauthorized"}
        if self._market_rate_limited(scope, maximum=12):
            return 429, {"status": "rate_limited"}

        query = parse_qs(scope.get("query_string", b"").decode())
        symbol = str(query.get("symbol", [self.runtime.environment.get("MONATISE_SYMBOL", "BTC")])[0]).strip().upper()
        interval = str(query.get("interval", ["1h"])[0]).strip() or "1h"
        stock_symbols = {"AAPL", "TSLA", "NVDA", "QQQ", "SPY"}
        if interval not in self.MARKET_INTERVALS:
            return 400, {"status": "invalid_request", "reason": "unsupported interval"}
        cache_key = (symbol, interval)
        try:
            if symbol in stock_symbols:
                analysis, cache_hit = await self._cached_openclaw_stock_analysis(cache_key)
            elif symbol in {"BTC", "ETH", "SOL"}:
                analysis, cache_hit = await self._cached_openclaw_analysis(cache_key)
            else:
                analysis, cache_hit = await self._cached_openclaw_dynamic_analysis(cache_key)
        except (TypeError, ValueError) as exc:
            return 400, {"status": "invalid_request", "reason": str(exc)}
        except Exception as exc:
            LOGGER.exception("OpenClaw analysis failed", extra={"error_type": type(exc).__name__})
            return 503, {"status": "analysis_unavailable", "error_type": type(exc).__name__}
        return 200, {
            "ok": True,
            "service": "monatise-live",
            "access": "openclaw_read_only",
            "symbol": symbol,
            "interval": interval,
            "analysis": analysis,
            "cache_hit": cache_hit,
            "execution_enabled": False,
            "capabilities": {
                "readOnly": True,
                "analysis": True,
                "telegramNotification": self.runtime.telegram is not None,
                "liveOrders": False,
                "configurationWrites": False,
                "deploymentWrites": False,
            },
        }

    async def _cached_openclaw_dynamic_analysis(self, cache_key: tuple[str, str]) -> tuple[dict[str, Any], bool]:
        cached = self._openclaw_cached(cache_key)
        if cached is not None:
            return cached, True
        task = self._openclaw_inflight.get(cache_key)
        joined_existing = task is not None
        if task is None:
            task = asyncio.create_task(self.runtime.analyse_dynamic_coinglass(cache_key[0], interval=cache_key[1]))
            self._openclaw_inflight[cache_key] = task
        try:
            analysis = await asyncio.shield(task)
        finally:
            if task.done() and self._openclaw_inflight.get(cache_key) is task:
                self._openclaw_inflight.pop(cache_key, None)
        self._store_openclaw_cache(cache_key, analysis)
        return analysis, joined_existing

    async def _public_analysis_status(self, scope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        query = parse_qs(scope.get("query_string", b"").decode())
        symbol = str(query.get("symbol", ["BTC"])[0]).strip().upper()
        interval = str(query.get("interval", ["1h"])[0]).strip()
        if symbol not in {"BTC", "ETH", "SOL"} or interval not in self.MARKET_INTERVALS:
            return 400, {"status": "invalid_request", "reason": "unsupported symbol or interval"}
        cache_key = (symbol, interval)
        cached = self._public_analysis_cache.get(cache_key)
        now = monotonic()
        if cached is not None and now - cached[0] < 300:
            return 200, {"ok": True, "source": "monatise-live", "interval": interval, "analysis": cached[1], "cache_hit": True, "execution_enabled": False}
        task = self._public_analysis_inflight.get(cache_key)
        if task is None:
            task = asyncio.create_task(self.runtime.analyse(symbol, interval=interval, source="monatise.web", notify=False))
            self._public_analysis_inflight[cache_key] = task
        try:
            timeout_seconds = max(0.01, float(self.runtime.environment.get("MONATISE_PUBLIC_ANALYSIS_TIMEOUT_SECONDS", "60")))
            analysis = await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)
        except TimeoutError:
            LOGGER.warning("public analysis still processing", extra={"symbol": symbol, "interval": interval})
            return 200, {
                "ok": True,
                "source": "monatise-live",
                "interval": interval,
                "analysis": {
                    "symbol": symbol,
                    "status": "processing",
                    "classification": "no_trade",
                    "direction": "none",
                    "completed_stages": 0,
                    "stage_total": 14,
                    "blocked_by": "pipeline_processing",
                    "reasons": ["Production pipeline is still processing; fail-closed NO TRADE until confirmation completes."],
                    "execution_enabled": False,
                },
                "cache_hit": False,
                "processing": True,
                "execution_enabled": False,
            }
        except Exception as exc:
            LOGGER.exception("public analysis failed", extra={"error_type": type(exc).__name__})
            return 503, {"status": "analysis_unavailable", "error_type": type(exc).__name__}
        finally:
            if task.done():
                self._public_analysis_inflight.pop(cache_key, None)
        self._public_analysis_cache[cache_key] = (monotonic(), analysis)
        return 200, {"ok": True, "source": "monatise-live", "interval": interval, "analysis": analysis, "cache_hit": False, "execution_enabled": False}

    async def _quiver_context_status(self, scope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        query = parse_qs(scope.get("query_string", b"").decode())
        symbol = normalize_quiver_symbol(str(query.get("symbol", [""])[0]))
        if symbol not in {"AAPL", "TSLA", "NVDA", "QQQ", "SPY"}:
            return 400, {"status": "invalid_request", "reason": "unsupported Quiver stock or ETF"}
        cached = self._quiver_web_cache.get(symbol)
        now = monotonic()
        if cached is not None and now - cached[0] < 120:
            return 200, {**cached[1], "cache_hit": True}
        task = self._quiver_web_inflight.get(symbol)
        if task is None:
            task = asyncio.create_task(asyncio.to_thread(QuiverAdapter.from_env().context, symbol))
            self._quiver_web_inflight[symbol] = task
        try:
            context = await asyncio.shield(task)
        except Exception as exc:
            LOGGER.warning("Quiver web context unavailable", extra={"symbol": symbol, "error_type": type(exc).__name__})
            return 503, {"status": "unavailable", "source": "Quiver Quantitative"}
        finally:
            if task.done() and self._quiver_web_inflight.get(symbol) is task:
                self._quiver_web_inflight.pop(symbol, None)
        datasets = context.get("datasets") if isinstance(context.get("datasets"), dict) else {}
        health = context.get("dataset_health") if isinstance(context.get("dataset_health"), dict) else {}
        summary = context.get("summary") if isinstance(context.get("summary"), dict) else {}
        dataset_counts = {name: len(rows) if isinstance(rows, list) else 0 for name, rows in datasets.items()}
        dataset_counts.update({name: int(count) for name, count in summary.get("fresh_counts", {}).items() if name in {"congress", "insider"}})
        payload = {
            "symbol": symbol,
            "source": "Quiver Quantitative",
            "configured": bool(context.get("configured")),
            "available": bool(context.get("available")),
            "summary": summary,
            "datasetCounts": dataset_counts,
            "datasetMeta": summary.get("dataset_freshness", {}),
            "datasetHealth": {name: bool(item.get("ok")) for name, item in health.items() if isinstance(item, dict)},
            "cache_hit": False,
        }
        self._quiver_web_cache[symbol] = (monotonic(), payload)
        return 200, payload

    async def _cached_openclaw_analysis(self, cache_key: tuple[str, str]) -> tuple[dict[str, Any], bool]:
        cached = self._openclaw_cached(cache_key)
        if cached is not None:
            return cached, True

        task = self._openclaw_inflight.get(cache_key)
        joined_existing = task is not None
        if task is None:
            task = asyncio.create_task(self.runtime.analyse(cache_key[0], interval=cache_key[1], source="monatise.openclaw"))
            self._openclaw_inflight[cache_key] = task
        try:
            analysis = await asyncio.shield(task)
        finally:
            if task.done() and self._openclaw_inflight.get(cache_key) is task:
                self._openclaw_inflight.pop(cache_key, None)
        self._store_openclaw_cache(cache_key, analysis)
        return analysis, joined_existing

    async def _cached_openclaw_stock_analysis(self, cache_key: tuple[str, str]) -> tuple[dict[str, Any], bool]:
        cached = self._openclaw_cached(cache_key)
        if cached is not None:
            return cached, True

        task = self._openclaw_inflight.get(cache_key)
        joined_existing = task is not None
        if task is None:
            task = asyncio.create_task(self.runtime.analyse_stock(cache_key[0]))
            self._openclaw_inflight[cache_key] = task
        try:
            analysis = await asyncio.shield(task)
        finally:
            if task.done() and self._openclaw_inflight.get(cache_key) is task:
                self._openclaw_inflight.pop(cache_key, None)
        self._store_openclaw_cache(cache_key, analysis)
        return analysis, joined_existing

    async def _serve_frontend(self, scope: dict[str, Any], send: Any) -> bool:
        method = scope.get("method", "GET").upper()
        path = scope.get("path", "/")
        if method not in {"GET", "HEAD"} or path.startswith(("/api/", "/health/")):
            return False

        relative_path = "index.html" if path == "/" else path.lstrip("/")
        candidate = (self.static_dir / relative_path).resolve()
        try:
            candidate.relative_to(self.static_dir)
        except ValueError:
            return False
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.is_file():
            return False

        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json", "image/svg+xml"}:
            content_type += "; charset=utf-8"
        headers = [
            (b"content-type", content_type.encode()),
            (b"content-length", str(len(body)).encode()),
            (b"x-content-type-options", b"nosniff"),
        ]
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": b"" if method == "HEAD" else body})
        return True

    @staticmethod
    async def _respond(send: Any, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        await send({"type": "http.response.start", "status": code, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    async def _production_analysis(self, scope: dict[str, Any], receive: Any) -> tuple[int, dict[str, Any]]:
        if self.runtime.environment.get("MONATISE_ENVIRONMENT", "").strip().casefold() != "production":
            return 404, {"status": "not_found"}
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if len(body) > 4096:
                return 413, {"status": "request_too_large"}
            if not message.get("more_body", False):
                break
        headers = {key.decode().casefold(): value.decode() for key, value in scope.get("headers", ())}
        timestamp = headers.get("x-monatise-timestamp", "")
        signature = headers.get("x-monatise-signature", "")
        token = self.runtime.environment.get("MONATISE_OPENCLAW_TOKEN", "")
        try:
            fresh = abs(time() - int(timestamp)) <= 300
        except ValueError:
            fresh = False
        expected = hmac.new(token.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest() if token else ""
        if not token or not fresh or not hmac.compare_digest(signature, expected):
            return 401, {"status": "unauthorized"}
        if self.runtime.redis_coordination is None:
            return 503, {"status": "unavailable", "reason": "replay protection is not configured"}
        if not await self.runtime.redis_coordination.claim_nonce(signature):
            return 409, {"status": "duplicate_request"}
        try:
            request = json.loads(body or b"{}")
            if not isinstance(request, dict) or set(request) != {"symbol"}:
                return 400, {"status": "invalid_request", "reason": "only symbol is accepted"}
            return 200, await self.runtime.analyse(str(request["symbol"]), source="monatise.production")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return 400, {"status": "invalid_request", "reason": str(exc)}
        except Exception as exc:
            LOGGER.exception("production analysis failed", extra={"error_type": type(exc).__name__})
            return 503, {"status": "analysis_unavailable", "error_type": type(exc).__name__}

    async def _tradingview_webhook(self, scope: dict[str, Any], receive: Any) -> tuple[int, dict[str, Any]]:
        """Ingest one TradingView alert. Analysis input only: this never
        places an order or changes execution state -- it only normalizes,
        validates, and durably stores what TradingView sent."""
        expected_token = self.runtime.environment.get("MONATISE_TRADINGVIEW_WEBHOOK_TOKEN", "").strip()
        if not expected_token:
            return 503, {"status": "unavailable", "reason": "tradingview webhook token is not configured"}
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if len(body) > 8192:
                return 413, {"status": "request_too_large"}
            if not message.get("more_body", False):
                break
        try:
            parsed: dict | str = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError:
            parsed = body.decode("utf-8", errors="replace")
        supplied_token = ""
        if isinstance(parsed, dict):
            supplied_token = str(parsed.pop("token", parsed.pop("secret", "")))
        elif isinstance(parsed, str):
            parts = [part.strip() for part in parsed.replace("|", ",").split(",") if part.strip()]
            supplied_token = next(
                (part.split("=", 1)[1].strip() for part in parts if part.lower().startswith(("token=", "secret="))),
                "",
            )
            parsed = ", ".join(part for part in parts if not part.lower().startswith(("token=", "secret=")))
        if not secrets.compare_digest(supplied_token, expected_token):
            return 401, {"status": "unauthorized"}
        # A replay (identical bytes resent -- a TradingView retry, or a
        # captured-and-resent request) fingerprints identically and is
        # rejected by the storage layer's UNIQUE constraint.
        deduplication_window = int(time()) // TRADINGVIEW_FRESH_SECONDS
        canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":")) if isinstance(parsed, dict) else parsed
        fingerprint = hashlib.sha256(f"{deduplication_window}:{canonical}".encode()).hexdigest()
        try:
            alert = await self.runtime.record_tradingview_alert(parsed, fingerprint=fingerprint)
        except TradingViewAlertDuplicate:
            return 409, {"status": "duplicate_alert"}
        except ValueError as exc:
            return 422, {"status": "invalid_alert", "reason": str(exc)}
        except RuntimeError as exc:
            return 503, {"status": "unavailable", "reason": str(exc)}
        except Exception as exc:
            LOGGER.exception("tradingview alert storage failed", extra={"error_type": type(exc).__name__})
            return 503, {"status": "unavailable", "error_type": type(exc).__name__}
        return 200, {"status": "accepted", "symbol": alert["symbol"], "action": alert["action"], "execution_enabled": False}

    async def _tradingview_signals(self, scope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        query = parse_qs(scope.get("query_string", b"").decode())
        raw_symbol = str(query.get("symbol", [""])[0]).strip()
        symbol = normalize_alert_symbol(raw_symbol) if raw_symbol else None
        try:
            alerts = await self.runtime.recent_tradingview_alerts(symbol=symbol, limit=20)
        except Exception as exc:
            LOGGER.warning("tradingview signals fetch failed", extra={"error_type": type(exc).__name__})
            return 503, {"status": "unavailable"}
        return 200, {
            "configured": bool(self.runtime.environment.get("MONATISE_TRADINGVIEW_WEBHOOK_TOKEN", "").strip()),
            "alerts": alerts,
            "count": len(alerts),
            "source": "TradingView webhook alerts",
            "role": "tradingview_primary_signal",
            "snapshotPolicy": {
                "lockSeconds": TRADINGVIEW_SNAPSHOT_LOCK_SECONDS,
                "freshSeconds": TRADINGVIEW_FRESH_SECONDS,
                "fastCheckSeconds": TRADINGVIEW_FRESH_SECONDS,
            },
            "execution_enabled": False,
        }
app = ProductionASGI()
