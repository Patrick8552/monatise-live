"""Production-facing, analysis-only ASGI entrypoint for Monatise."""

from __future__ import annotations

import hashlib
import hmac
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
from typing import Any
from urllib.parse import parse_qs

from dataclasses import asdict

from monatise.adapters.quiver import QuiverAdapter, normalize_quiver_symbol
from monatise.analysis.context import context_assets, grid_instruction, indicator_snapshot
from monatise.analysis.fibonacci import analyze_fibonacci
from monatise.analysis.fvg import analyze_fvg
from monatise.analysis.liquidity_clusters import estimate_liquidation_clusters
from monatise.analysis.tradingview import TRADINGVIEW_FRESH_SECONDS, TRADINGVIEW_SNAPSHOT_LOCK_SECONDS, normalize_alert_symbol
from monatise.adapters.memecoins import creator_leaderboard, discover_pumpfun, inspect_memecoin, resolve_creator

from monatise.adapters.coinglass_production import CoinGlassProductionAdapter
from monatise.application.deployment import OrchestrationASGI, OrchestrationRuntime, TelegramCommandTransition, TradingViewAlertDuplicate
from monatise.application.stock_analysis import refresh_setup_validity
from monatise.engines.market_data import MarketDataEngine, MarketDataRequest
from monatise.core.models import Candle


LOGGER = logging.getLogger("monatise.production")


class TelegramLeaseLost(RuntimeError):
    """Raised when a worker no longer owns a Telegram command lease."""


def telegram_webhook_secret(token: str) -> str:
    return hashlib.sha256(f"monatise-telegram-webhook:{token}".encode()).hexdigest()


class ProductionRuntime(OrchestrationRuntime):
    async def start(self) -> None:
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
        configured = inbound_enabled and self.telegram is not None and bool(token and public_url.startswith("https://"))
        status = {"status": "ok", "enabled": configured, "execution_enabled": False}
        if not configured:
            status["registration"] = "not_configured"
            self.dependencies["telegram_inbound"] = status
            return
        secret_token = telegram_webhook_secret(token)
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
    MARKET_SYMBOLS = {"BTC", "ETH", "SOL", "XRP", "DOGE", "BNB"}
    MARKET_INTERVALS = set(CoinGlassProductionAdapter.SUPPORTED_INTERVALS)
    INTERVAL_MAX_AGE_SECONDS = {
        "1m": 120, "3m": 360, "5m": 600, "15m": 1_800, "30m": 3_600,
        "1h": 7_200, "4h": 28_800, "6h": 43_200, "8h": 57_600,
        "12h": 86_400, "1d": 172_800, "1w": 1_209_600,
    }
    STOCK_DIRECTORY = {
        "AAPL": "Apple", "AMD": "Advanced Micro Devices", "AMZN": "Amazon", "AVGO": "Broadcom",
        "COIN": "Coinbase", "GOOGL": "Alphabet", "JPM": "JPMorgan Chase", "META": "Meta Platforms",
        "MSFT": "Microsoft", "NFLX": "Netflix", "NVDA": "NVIDIA", "QQQ": "Invesco QQQ",
        "SPY": "SPDR S&P 500 ETF", "TSLA": "Tesla", "XOM": "Exxon Mobil",
    }
    STOCK_SCANNER_SYMBOLS = ("AAPL", "TSLA", "NVDA", "QQQ", "SPY")
    STOCK_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
    TELEGRAM_COMMAND_PATTERN = re.compile(r"^/(?:analyse|analyze)(?:@[A-Za-z0-9_]+)?(?:\s+(.+))?$", re.IGNORECASE)

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
            "/api/memecoins/discover",
            "/api/memecoins/token",
            "/api/memecoins/creators",
        }:
            if scope.get("method", "GET").upper() != "GET":
                await self._respond(send, 405, {"status": "method_not_allowed"})
                return
            if self._market_rate_limited(scope, maximum=30 if path.startswith("/api/memecoins/") else 120):
                await self._respond(send, 429, {"status": "rate_limited"})
                return
            handlers = {
                "/api/markets": self._market_summary,
                "/api/public/significant-universe": self._significant_universe,
                "/api/analysis/fibonacci": self._fibonacci_analysis,
                "/api/context/radar": self._context_radar,
                "/api/coinglass/context": self._coinglass_context,
                "/api/analysis/liquidity-clusters": self._liquidity_clusters,
                "/api/memecoins/discover": self._memecoins_discover,
                "/api/memecoins/token": self._memecoins_token,
                "/api/memecoins/creators": self._memecoins_creators,
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
        if not inbound_enabled or not token or not chat_id or self.runtime.telegram is None:
            return 503, {"status": "unavailable"}
        headers = {key.decode().casefold(): value.decode() for key, value in scope.get("headers", ())}
        supplied = headers.get("x-telegram-bot-api-secret-token", "")
        if not secrets.compare_digest(supplied, telegram_webhook_secret(token)):
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
        message = update.get("message")
        if not isinstance(message, dict) or str((message.get("chat") or {}).get("id", "")) != chat_id:
            return 200, {"status": "ignored"}
        update_id = update.get("update_id")
        if not isinstance(update_id, int):
            return 400, {"status": "invalid_update"}
        if self.runtime.redis_coordination is None:
            return 503, {"status": "unavailable"}
        text = str(message.get("text") or "").strip()
        queued = await self.runtime.redis_coordination.enqueue_telegram_command(update_id, {"update_id": update_id, "text": text}, ttl_seconds=86_400)
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
                except Exception as exc:
                    LOGGER.exception("application lifespan startup failed", extra={"error_type": type(exc).__name__})
                    await send({"type": "lifespan.startup.failed", "message": "startup_failed"})
                    return
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                if self._telegram_worker is not None:
                    self._telegram_worker.cancel()
                    with suppress(asyncio.CancelledError):
                        await self._telegram_worker
                    self._telegram_worker = None
                await self.runtime.shutdown()
                await send({"type": "lifespan.shutdown.complete"})
                return

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

    async def _process_telegram_command_once(self, *, timeout_seconds: int = 1) -> bool:
        coordination = self.runtime.redis_coordination
        payload = await coordination.dequeue_telegram_command(
            timeout_seconds=timeout_seconds, lease_seconds=self.TELEGRAM_LEASE_SECONDS,
        )
        if payload is None:
            return False
        heartbeat = asyncio.create_task(self._telegram_lease_heartbeat(coordination, payload), name="telegram-lease-heartbeat")
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
        finally:
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
    async def _send_owned_telegram_response(notifier: Any, response: str, ownership_check: Any | None) -> None:
        if ownership_check is not None and not await ownership_check():
            raise TelegramLeaseLost("Telegram command lease is no longer owned")
        await notifier.command_response(response)

    async def _handle_telegram_command(self, text: str, *, ownership_check: Any | None = None) -> None:
        notifier = self.runtime.telegram
        if notifier is None:
            return
        help_text = "Monatise remote analysis\nUse /analyze BTC or /analyze NVDA. Add crypto or stock when a symbol is ambiguous.\nAnalysis only; trade execution is disabled."
        if re.fullmatch(r"/(?:start|help)(?:@[A-Za-z0-9_]+)?", text, re.IGNORECASE):
            await self._send_owned_telegram_response(notifier, help_text, ownership_check)
            return
        match = self.TELEGRAM_COMMAND_PATTERN.fullmatch(text)
        raw_asset = (match.group(1) if match else "") or ""
        parts = raw_asset.strip().upper().split()
        symbol = parts[0].lstrip("$") if parts else ""
        asset_class = parts[1].casefold() if len(parts) == 2 else None
        if not match or not self.STOCK_SYMBOL_PATTERN.fullmatch(symbol) or len(parts) > 2 or asset_class not in {None, "crypto", "stock"}:
            await self._send_owned_telegram_response(notifier, help_text, ownership_check)
            return
        try:
            resolved_class, resolved_symbol = await self._telegram_asset_classification(symbol, asset_class)
            if resolved_class == "crypto":
                analysis = await asyncio.wait_for(
                    self.runtime.analyse(resolved_symbol, interval="15m", source="monatise.telegram.command", notify=False), timeout=90
                )
                response = self._format_telegram_crypto_analysis(analysis)
            elif resolved_class == "stock":
                analysis = await asyncio.wait_for(self.runtime.analyse_stock(resolved_symbol), timeout=90)
                response = self._format_telegram_stock_analysis(analysis)
            else:
                response = f"Monatise NO TRADE: {symbol}\nReason: asset class is ambiguous; use /analyze {symbol} crypto or /analyze {symbol} stock.\nExecution: disabled"
        except Exception as exc:
            LOGGER.warning("Telegram command analysis failed", extra={"symbol": symbol, "error_type": type(exc).__name__})
            response = f"Monatise NO TRADE: {symbol}\nReason: analysis is currently unavailable.\nExecution: disabled"
        await self._send_owned_telegram_response(notifier, response, ownership_check)

    async def _telegram_asset_classification(self, symbol: str, requested_class: str | None) -> tuple[str, str]:
        if requested_class is not None:
            return requested_class, symbol
        if symbol in self.STOCK_DIRECTORY:
            return "stock", symbol
        if symbol in self.MARKET_SYMBOLS or symbol in {"ADA", "AVAX", "LINK", "SUI"}:
            return "crypto", symbol
        provider = self.runtime.coinglass
        resolver = getattr(provider, "resolve_futures_asset", None)
        if resolver is None:
            return "unknown", symbol
        try:
            asset = await asyncio.to_thread(resolver, symbol)
        except Exception as exc:
            LOGGER.info("Telegram symbol was not resolved as crypto", extra={"symbol": symbol, "error_type": type(exc).__name__})
            return "unknown", symbol
        return "crypto", str(getattr(asset, "base_asset", symbol)).upper()

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
        matches = [
            {"symbol": symbol, "name": name, "asset_class": "stock", "tradable": False}
            for symbol, name in self.STOCK_DIRECTORY.items()
            if not term or term in symbol or term.casefold() in name.casefold()
        ][:10]
        return 200, {"status": "ready", "query": term, "results": matches, "execution_enabled": False}

    async def _stock_analysis(self, symbol: str) -> tuple[int, dict[str, Any]]:
        if not self.STOCK_SYMBOL_PATTERN.fullmatch(symbol):
            return 400, {"status": "invalid_request", "reason": "unsupported stock symbol"}
        try:
            analysis, cache_hit = await asyncio.wait_for(self._cached_openclaw_stock_analysis((symbol, "1h")), timeout=30)
            analysis = refresh_setup_validity(analysis)
        except (TypeError, ValueError) as exc:
            return 400, {"status": "invalid_request", "reason": str(exc)}
        except Exception as exc:
            LOGGER.warning("stock analysis unavailable", extra={"symbol": symbol, "error_type": type(exc).__name__})
            return 503, {"status": "analysis_unavailable", "symbol": symbol, "error_type": type(exc).__name__}
        return 200, {
            "status": "ready", "symbol": symbol, "company_name": self.STOCK_DIRECTORY.get(symbol, symbol),
            "analysis": analysis, "cache_hit": cache_hit, "execution_enabled": False,
        }

    async def _stocks_scanner(self) -> tuple[int, dict[str, Any]]:
        async def analyze(symbol: str) -> dict[str, Any]:
            code, payload = await self._stock_analysis(symbol)
            if code != 200:
                return {"asset": symbol, "company_name": self.STOCK_DIRECTORY.get(symbol, symbol), "decision": "NO_TRADE", "setup_state": "NO_TRADE", "reason_code": payload.get("status", "ANALYSIS_UNAVAILABLE").upper()}
            return {"company_name": payload["company_name"], **payload["analysis"]}

        results = await asyncio.gather(*(analyze(symbol) for symbol in self.STOCK_SCANNER_SYMBOLS))
        return 200, {
            "status": "ready", "generated_at": datetime.now(timezone.utc).isoformat(), "refresh_seconds": 120,
            "results": results, "providers": ["Alpaca", "FlashAlpha", "Quiver Quantitative", "Finnhub"],
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
            "groups": {"crypto": [item["symbol"] for item in assets], "stocks": ["AAPL", "TSLA", "NVDA", "QQQ", "SPY"]},
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
        raw = await self.runtime.redis.get(f"{namespace}:coinglass:ranked-universe")
        try:
            candidates = json.loads(raw) if raw else []
        except (TypeError, ValueError):
            candidates = []
        if not isinstance(candidates, list):
            candidates = []
        scan_completed = bool(getattr(self.runtime, "dependencies", {}).get("coin_discovery", {}).get("last_success_at"))
        return 200, {"status": "ready" if candidates or scan_completed else "warming", "candidates": candidates[:20], "source": "CoinGlass significant futures universe", "execution_enabled": False}

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

    async def _memecoins_discover(self, scope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        query = parse_qs(scope.get("query_string", b"").decode())
        try:
            limit = max(4, min(24, int(query.get("limit", ["12"])[0])))
        except ValueError:
            return 400, {"status": "invalid_request", "reason": "limit must be an integer"}
        try:
            payload = await asyncio.to_thread(discover_pumpfun, limit)
        except (RuntimeError, ValueError) as exc:
            LOGGER.warning("memecoin discovery unavailable: %s (%s: %s)", limit, type(exc).__name__, exc.__cause__ or exc)
            return 502, {"status": "unavailable", "reason": str(exc), "error": str(exc)}
        return 200, payload

    async def _memecoins_token(self, scope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        query = parse_qs(scope.get("query_string", b"").decode())
        address = str(query.get("address", [""])[0]).strip()
        rpc_url = self.runtime.environment.get("MONATISE_SOLANA_RPC_URL", "").strip() or "https://api.mainnet-beta.solana.com"
        try:
            payload = await asyncio.to_thread(inspect_memecoin, address, rpc_url)
        except ValueError as exc:
            return 400, {"status": "invalid_request", "reason": str(exc), "error": str(exc)}
        except RuntimeError as exc:
            LOGGER.warning("memecoin inspection unavailable: %s (%s: %s)", address, type(exc).__name__, exc.__cause__ or exc)
            return 502, {"status": "unavailable", "reason": str(exc), "error": str(exc)}
        return 200, payload

    async def _memecoins_creators(self, scope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        query = parse_qs(scope.get("query_string", b"").decode())
        try:
            limit = max(10, min(20, int(query.get("limit", ["15"])[0])))
        except ValueError:
            return 400, {"status": "invalid_request", "reason": "limit must be an integer"}
        rpc_url = self.runtime.environment.get("MONATISE_SOLANA_RPC_URL", "").strip() or "https://api.mainnet-beta.solana.com"
        try:
            discovery = await asyncio.to_thread(discover_pumpfun, 30)
        except (RuntimeError, ValueError) as exc:
            LOGGER.warning("memecoin creator scan unavailable: (%s: %s)", type(exc).__name__, exc.__cause__ or exc)
            return 502, {"status": "unavailable", "reason": str(exc), "error": str(exc)}
        tokens = discovery.get("tokens") or []

        # resolve_creator reads the pump.fun bonding-curve account directly
        # (one getAccountInfo call per token), so every discovered token can
        # be attempted -- still capped concurrently to stay a good citizen
        # of the free public Solana RPC.
        semaphore = asyncio.Semaphore(8)

        async def resolve(token: dict[str, Any]) -> tuple[str, str | None]:
            address = str(token.get("address") or "")
            async with semaphore:
                try:
                    creator = await asyncio.to_thread(resolve_creator, address, rpc_url)
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("creator resolution failed: %s (%s: %s)", address, type(exc).__name__, exc)
                    creator = None
            return address, creator

        resolved = await asyncio.gather(*(resolve(token) for token in tokens))
        creators_by_address = dict(resolved)
        leaderboard = creator_leaderboard(tokens, creators_by_address, limit=limit)
        return 200, leaderboard

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
