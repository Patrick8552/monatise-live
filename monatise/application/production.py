"""Production-facing, analysis-only ASGI entrypoint for Monatise."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import mimetypes
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import secrets
from time import monotonic, time
from typing import Any
from urllib.parse import parse_qs

from monatise.adapters.quiver import QuiverAdapter, normalize_quiver_symbol
from monatise.adapters.alpaca import AlpacaMarketDataAdapter
from monatise.adapters.finnhub import FinnhubAdapter, FinnhubAdapterError
from monatise.application.stock_analysis import build_stock_analysis

from monatise.adapters.coinglass_production import CoinGlassProductionAdapter
from monatise.application.deployment import OrchestrationASGI, OrchestrationRuntime
from monatise.engines.market_data import MarketDataEngine, MarketDataRequest


LOGGER = logging.getLogger("monatise.production")


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

    def readiness(self) -> tuple[bool, dict[str, Any]]:
        # During a zero-downtime deploy the live instance owns the scheduler
        # lock until Render cuts traffic over.  The replacement is a healthy
        # contender and acquires leadership after the old instance shuts down;
        # requiring this process to be leader would deadlock every redeploy.
        return super().readiness()


class ProductionASGI(OrchestrationASGI):
    MARKET_SYMBOLS = {"BTC", "ETH", "SOL", "XRP", "DOGE", "BNB"}
    MARKET_INTERVALS = set(CoinGlassProductionAdapter.SUPPORTED_INTERVALS)
    INTERVAL_MAX_AGE_SECONDS = {
        "1m": 120, "3m": 360, "5m": 600, "15m": 1_800, "30m": 3_600,
        "1h": 7_200, "4h": 28_800, "6h": 43_200, "8h": 57_600,
        "12h": 86_400, "1d": 172_800, "1w": 1_209_600,
    }

    def __init__(self, runtime: OrchestrationRuntime | None = None, static_dir: Path | None = None) -> None:
        super().__init__(runtime or ProductionRuntime())
        self.static_dir = (static_dir or Path(__file__).resolve().parents[2] / "app").resolve()
        self._market_rate_windows: dict[str, tuple[int, int]] = {}
        self._openclaw_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
        self._openclaw_inflight: dict[tuple[str, str], asyncio.Task[dict[str, Any]]] = {}
        self._public_analysis_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        path = scope.get("path", "")
        if scope.get("type") == "http" and path == "/api/health":
            if scope.get("method", "GET").upper() not in {"GET", "HEAD"}:
                await self._respond(send, 405, {"status": "method_not_allowed"})
                return
            await self._respond(send, 200, {"ok": True, "status": "alive", "execution_enabled": False})
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
            LOGGER.warning("CoinGlass dashboard dataset unavailable", extra={"path": upstream_path, "error_type": type(exc).__name__})
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
        if symbol not in {"BTC", "ETH", "SOL", *stock_symbols} or interval not in self.MARKET_INTERVALS:
            return 400, {"status": "invalid_request", "reason": "unsupported symbol or interval"}
        cache_key = (symbol, interval)
        try:
            if symbol in stock_symbols:
                def stock_analysis() -> dict[str, Any]:
                    alpaca = AlpacaMarketDataAdapter.from_env()
                    try:
                        finnhub = FinnhubAdapter.from_env().context(symbol)
                    except FinnhubAdapterError:
                        finnhub = {"source": "Finnhub", "unavailable": True}
                    return build_stock_analysis(
                        QuiverAdapter.from_env().context(normalize_quiver_symbol(symbol)),
                        bars=alpaca.stock_bars(symbol),
                        snapshot=alpaca.stock_snapshot(symbol),
                        finnhub=finnhub,
                    )
                analysis = await asyncio.to_thread(stock_analysis)
                cache_hit = False
            else:
                analysis, cache_hit = await self._cached_openclaw_analysis(cache_key)
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

    async def _public_analysis_status(self, scope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        query = parse_qs(scope.get("query_string", b"").decode())
        symbol = str(query.get("symbol", ["BTC"])[0]).strip().upper()
        interval = str(query.get("interval", ["1h"])[0]).strip()
        if symbol not in {"BTC", "ETH", "SOL"} or interval not in self.MARKET_INTERVALS:
            return 400, {"status": "invalid_request", "reason": "unsupported symbol or interval"}
        cache_key = (symbol, interval)
        cached = self._public_analysis_cache.get(cache_key)
        now = monotonic()
        if cached is not None and now - cached[0] < 55:
            return 200, {"ok": True, "source": "monatise-live", "interval": interval, "analysis": cached[1], "cache_hit": True, "execution_enabled": False}
        try:
            analysis = await self.runtime.analyse(symbol, interval=interval, source="monatise.web", notify=False)
        except Exception as exc:
            LOGGER.exception("public analysis failed", extra={"error_type": type(exc).__name__})
            return 503, {"status": "analysis_unavailable", "error_type": type(exc).__name__}
        self._public_analysis_cache[cache_key] = (monotonic(), analysis)
        return 200, {"ok": True, "source": "monatise-live", "interval": interval, "analysis": analysis, "cache_hit": False, "execution_enabled": False}

    async def _cached_openclaw_analysis(self, cache_key: tuple[str, str]) -> tuple[dict[str, Any], bool]:
        raw_ttl = self.runtime.environment.get("MONATISE_OPENCLAW_CACHE_TTL_SECONDS", "300")
        try:
            ttl_seconds = min(max(float(raw_ttl), 0.0), 900.0)
        except ValueError:
            ttl_seconds = 300.0
        cached = self._openclaw_cache.get(cache_key)
        now = monotonic()
        if cached is not None and now - cached[0] < ttl_seconds:
            return cached[1], True

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
        self._openclaw_cache[cache_key] = (monotonic(), analysis)
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
        if self.runtime.redis_coordination and not await self.runtime.redis_coordination.claim_nonce(signature):
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


app = ProductionASGI()
