"""Paper-only deployment lifecycle for the orchestration application."""

from __future__ import annotations

import asyncio
import hashlib
import html
import inspect
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from time import perf_counter, time
from typing import Any, Mapping
from uuid import uuid4
from urllib.request import Request, urlopen

from monatise.application.composition import create_application, create_durable_infrastructure
from monatise.application.production_analysis import SUPPORTED_PRODUCTION_SYMBOLS, build_directional_plan, build_production_analysis_run, build_setup_validity, sanitized_result, strongest_confirmation_signal
from monatise.application.dynamic_analysis import finalize_dynamic_analysis
from monatise.application.persistence import PostgresDocumentStore, _json_value
from monatise.application.workflows import TelegramNotifier
from monatise.application.registry import PRODUCTION_ENGINE_ORDER
from monatise.application.time_display import format_nigeria_time
from monatise.application.hierarchy import HierarchyConfiguration, HierarchyLayerEvaluator, HierarchyRepository, Provenance, ShadowHierarchyCoordinator, ShadowHierarchyService
from monatise.adapters.coinglass_production import CoinGlassProductionAdapter
from monatise.adapters.backpack import BackpackAdapter, BackpackCredentials
from monatise.adapters.alpaca import AlpacaMarketDataAdapter
from monatise.adapters.quiver import QuiverAdapter, normalize_quiver_symbol
from monatise.adapters.finnhub import FinnhubAdapter, FinnhubAdapterError
from monatise.adapters.flashalpha import FlashAlphaAdapter, FlashAlphaAdapterError
from monatise.application.stock_analysis import build_stock_analysis
from monatise.application.flashalpha_analysis import build_flashalpha_futures_analysis
from monatise.application.stock_universe import StockCandidate, StockUniverseConfiguration, build_technical_stock_setup, rank_stock_universe
from monatise.application.universe_discovery import rank_significant_futures_universe
from monatise.application.ftmo_registry import FTMOAssetClass, FTMOInstrumentRegistry, FTMO_REGISTRY
from monatise.application.ftmo_scanner import publication_allowed
from monatise.application.ftmo_execution import FTMOExecutionConfiguration
from monatise.application.ftmo_master import FTMOMasterConfiguration, FTMOMasterControlService, FTMOMasterRepository, FTMOMasterError, format_proposal
from monatise.analysis.tradingview import TRADINGVIEW_ALERT_LIMIT, TRADINGVIEW_FRESH_SECONDS, enrich_tradingview_alert, normalize_tradingview_alert
from monatise.adapters.x_macro import XMacroAdapter, XMacroPost
from monatise.live.config import RuntimeConfig
from monatise.infrastructure.audit_database import AuditAction, AuditActor, AuditRecordType
from monatise.infrastructure.task_scheduler import JobDefinition, RetryPolicy, ScheduleType


LOGGER = logging.getLogger("monatise.orchestration")
MIGRATION_LOCK_ID = 4_602_161_943_641_489_731
FALSE_VALUES = {"0", "false", "no", "off", "disabled", ""}
COINGLASS_PROVIDER_KEY = "coinglass.market_provider"
SCHEDULED_ANALYSIS_JOB_PREFIX = "scheduled-analysis"
SCHEDULED_ANALYSIS_DEFAULT_SYMBOLS = ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC")
SCHEDULED_ANALYSIS_SUPPORTED_SYMBOLS = frozenset(
    item.underlying_symbol for item in FTMO_REGISTRY.for_asset_class(FTMOAssetClass.CRYPTO)
)
DIRECTIONAL_ANALYSIS_SYMBOLS_KEY = "MONATISE_DIRECTIONAL_ANALYSIS_SYMBOLS"
# Bump whenever the snapshot payload shape changes, so a later replay can
# tell which schema a given historical row was written under.


class TelegramCommandTransition(str, Enum):
    REQUEUED = "requeued"
    DEAD_LETTERED = "dead_lettered"
    OWNERSHIP_LOST = "ownership_lost"
    INVARIANT_VIOLATION = "invariant_violation"


DECISION_SNAPSHOT_SCHEMA_VERSION = 1
DECISION_SNAPSHOT_WRITE_TIMEOUT_SECONDS = 5.0
DECISION_SNAPSHOT_RETENTION_DAYS = 30
# Alerts are only ever read within TRADINGVIEW_FRESH_SECONDS (5 minutes) of
# receipt, but kept longer than that so a short recent-history window
# survives for debugging/review before the retention sweep prunes them.
TRADINGVIEW_ALERT_RETENTION_DAYS = 3
SCHEDULED_ANALYSIS_INTERVAL_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1_800,
    "1h": 3_600, "4h": 14_400, "6h": 21_600, "8h": 28_800,
    "12h": 43_200, "1d": 86_400, "1w": 604_800,
}
SETUP_MATERIAL_CHANGE_BPS = 50.0


@dataclass(frozen=True)
class _PooledPostgresResult:
    rowcount: int | None
    rows: tuple[Any, ...] = ()

    async def fetchone(self) -> Any | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> tuple[Any, ...]:
        return self.rows


class _PooledPostgresConnection:
    """Small psycopg-compatible facade that borrows a healthy connection per call."""

    def __init__(self, pool: Any, *, timeout_seconds: float = 10.0) -> None:
        self.pool = pool
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _query(query: str) -> str:
        return re.sub(r"\$\d+", "%s", query)

    @staticmethod
    def _parameters(args: tuple[Any, ...]) -> tuple[Any, ...]:
        if len(args) == 1 and isinstance(args[0], (tuple, list)):
            return tuple(args[0])
        return args

    async def execute(self, query: str, *args: Any) -> _PooledPostgresResult:
        parameters = self._parameters(args)
        async with self.pool.connection(timeout=self.timeout_seconds) as connection:
            cursor = await connection.execute(self._query(query), parameters)
            rows: tuple[Any, ...] = ()
            if getattr(cursor, "description", None) is not None:
                rows = tuple(await cursor.fetchall())
            return _PooledPostgresResult(getattr(cursor, "rowcount", None), rows)

    async def fetchrow(self, query: str, *args: Any) -> Any | None:
        return await (await self.execute(query, *args)).fetchone()

    async def fetch(self, query: str, *args: Any) -> tuple[Any, ...]:
        return await (await self.execute(query, *args)).fetchall()


def _interleave_stock_candidates(longs: list[StockCandidate], shorts: list[StockCandidate]) -> tuple[StockCandidate, ...]:
    balanced: list[StockCandidate] = []
    for index in range(max(len(longs), len(shorts))):
        if index < len(longs):
            balanced.append(longs[index])
        if index < len(shorts):
            balanced.append(shorts[index])
    return tuple(balanced)


def _setup_alert_state(analysis: Mapping[str, Any]) -> dict[str, Any]:
    targets = analysis.get("targets")
    if not isinstance(targets, (list, tuple)):
        targets = [analysis.get("target")]
    return {
        "direction": str(analysis.get("direction") or "").upper(),
        "score": int(analysis.get("score") or 0),
        "entry": analysis.get("entry"),
        "stop": analysis.get("stop_loss"),
        "targets": list(targets),
    }


def _setup_materially_changed(previous_raw: Any, current: Mapping[str, Any], *, threshold_bps: float = SETUP_MATERIAL_CHANGE_BPS) -> bool:
    try:
        if isinstance(previous_raw, bytes):
            previous_raw = previous_raw.decode("utf-8")
        previous = json.loads(previous_raw) if isinstance(previous_raw, str) else previous_raw
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return True
    if not isinstance(previous, Mapping):
        return True
    if str(previous.get("direction") or "").upper() != str(current.get("direction") or "").upper():
        return True
    if abs(int(previous.get("score") or 0) - int(current.get("score") or 0)) >= 2:
        return True

    previous_levels = [previous.get("entry"), previous.get("stop"), *(previous.get("targets") or [])]
    current_levels = [current.get("entry"), current.get("stop"), *(current.get("targets") or [])]
    if len(previous_levels) != len(current_levels):
        return True
    for old, new in zip(previous_levels, current_levels):
        try:
            old_value, new_value = float(old), float(new)
        except (TypeError, ValueError):
            if old != new:
                return True
            continue
        baseline = abs(old_value)
        if baseline == 0:
            if new_value != old_value:
                return True
        elif abs(new_value - old_value) / baseline * 10_000 >= threshold_bps:
            return True
    return False


def _false(value: str | None) -> bool:
    return value is None or value.strip().casefold() in FALSE_VALUES


def _true(value: str | None) -> bool:
    return value is not None and value.strip().casefold() in {"1", "true", "yes", "on", "enabled"}


def telegram_transport_enabled(environment: Mapping[str, str]) -> bool:
    return _true(environment.get("MONATISE_TELEGRAM_NOTIFICATIONS_ENABLED")) or _true(environment.get("MONATISE_TELEGRAM_INBOUND_ENABLED"))


def _compact_candle_reference(candles: Any) -> dict[str, Any]:
    """Window bounds + latest bar, not the full array.

    The candle history is reproducible later from a historical candle query
    (unlike derivatives, which CoinGlass only exposes as "recent window
    ending now") -- so a decision snapshot only needs enough to know which
    window to re-fetch, plus the newest bar for a quick look without one.
    """
    candles = tuple(candles)
    if not candles:
        return {"count": 0}
    latest = candles[-1]
    return {
        "count": len(candles),
        "first_timestamp": candles[0].timestamp,
        "last_timestamp": latest.timestamp,
        "latest": {
            "timestamp": latest.timestamp, "open": latest.open, "high": latest.high,
            "low": latest.low, "close": latest.close, "volume": latest.volume,
        },
    }


def scheduled_analysis_configuration(environment: Mapping[str, str]) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    """Return the production analysis schedule without granting execution capability."""
    if not _true(environment.get("MONATISE_SCHEDULED_ANALYSIS_ENABLED")):
        return None
    raw_symbols = environment.get(DIRECTIONAL_ANALYSIS_SYMBOLS_KEY)
    if raw_symbols is None:
        legacy_symbols = environment.get("MONATISE_SCHEDULED_ANALYSIS_SYMBOLS")
        legacy_btc_only = tuple(part.strip().upper() for part in (legacy_symbols or "").split(",") if part.strip()) == ("BTC",)
        if environment.get("MONATISE_ENVIRONMENT", "").strip().casefold() == "production" and legacy_btc_only:
            raw_symbols = ",".join(SCHEDULED_ANALYSIS_DEFAULT_SYMBOLS)
        else:
            raw_symbols = legacy_symbols or ",".join(SCHEDULED_ANALYSIS_DEFAULT_SYMBOLS)
    symbols = tuple(dict.fromkeys(part.strip().upper() for part in raw_symbols.split(",") if part.strip()))
    unsupported = tuple(symbol for symbol in symbols if symbol not in SCHEDULED_ANALYSIS_SUPPORTED_SYMBOLS)
    if not symbols:
        raise ValueError("scheduled analysis requires at least one symbol")
    if unsupported:
        if environment.get("MONATISE_ENVIRONMENT", "").strip().casefold() == "production" and environment.get(DIRECTIONAL_ANALYSIS_SYMBOLS_KEY) is not None:
            symbols = tuple(symbol for symbol in symbols if symbol in SCHEDULED_ANALYSIS_SUPPORTED_SYMBOLS)
            LOGGER.warning("ignored non-FTMO scheduled analysis symbols: %s", ",".join(unsupported))
            if not symbols:
                raise ValueError("scheduled analysis has no FTMO-supported symbols")
        else:
            raise ValueError("unsupported scheduled analysis symbols: " + ", ".join(unsupported))
    raw_intervals = environment.get("MONATISE_SCHEDULED_ANALYSIS_TIMEFRAMES", "15m")
    intervals = tuple(dict.fromkeys(part.strip() for part in raw_intervals.split(",") if part.strip()))
    unsupported_intervals = tuple(interval for interval in intervals if interval not in SCHEDULED_ANALYSIS_INTERVAL_SECONDS)
    if not intervals:
        raise ValueError("scheduled analysis requires at least one timeframe")
    if unsupported_intervals:
        raise ValueError("unsupported scheduled analysis timeframes: " + ", ".join(unsupported_intervals))
    return symbols, intervals


class EnvironmentSecretBoundary:
    """Minimal secret access boundary; values are never represented or logged."""

    def __init__(self, environment: Mapping[str, str]) -> None:
        self._environment = environment

    def get(self, key: str) -> str:
        return self._environment.get(key, "")


def register_coinglass_provider(container: Any, environment: Mapping[str, str], **adapter_options: Any) -> CoinGlassProductionAdapter:
    secrets = EnvironmentSecretBoundary(environment)
    container.register_instance(
        COINGLASS_PROVIDER_KEY,
        CoinGlassProductionAdapter(lambda: secrets.get("COINGLASS_API_KEY"), **adapter_options),
        metadata={"capability": "read_only_market_intelligence", "execution_enabled": False},
    )
    return container.resolve(COINGLASS_PROVIDER_KEY)


class TelegramNotificationTransport:
    """Telegram notification transport with no trading methods or capability."""

    def __init__(self, token_provider: Any) -> None:
        self._token_provider = token_provider

    async def send_message(self, chat_id: str, text: str) -> int:
        return await asyncio.to_thread(self._send, chat_id, text)

    async def send_trade_proposal(self, chat_id: str, text: str, proposal_id: str) -> int:
        if not re.fullmatch(r"[a-f0-9]{12}", proposal_id):
            raise ValueError("invalid FTMO proposal identity")
        reply_markup = {
            "inline_keyboard": [[
                {"text": "APPROVE TRADE", "callback_data": f"ftmo:approve:{proposal_id}"},
                {"text": "REJECT TRADE", "callback_data": f"ftmo:reject:{proposal_id}"},
            ]]
        }
        return await asyncio.to_thread(self._send, chat_id, text, reply_markup)

    async def answer_callback_query(self, callback_query_id: str, text: str) -> bool:
        return await asyncio.to_thread(self._answer_callback_query, callback_query_id, text)

    async def set_webhook(self, url: str, secret_token: str) -> bool:
        return await asyncio.to_thread(self._set_webhook, url, secret_token)

    def _send(self, chat_id: str, text: str, reply_markup: Mapping[str, Any] | None = None) -> int:
        token = self._token_provider()
        if not token:
            raise RuntimeError("Telegram credential is unavailable")
        # Telegram limits messages to 4096 UTF-16 code units after entity
        # parsing.  1800 Unicode code points is safe even when every character
        # is represented by a surrogate pair.
        if len(text) > 1800:
            text = text[:1797].rstrip() + "..."
        payload = {
            "chat_id": chat_id,
            "text": _bold_telegram_labels(text),
            "parse_mode": "HTML",
        }
        if reply_markup is not None:
            payload["reply_markup"] = dict(reply_markup)
        body = json.dumps(payload, separators=(",", ":")).encode()
        request = Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body, headers={"content-type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=15) as response:  # noqa: S310
                if response.status >= 300:
                    raise RuntimeError("Telegram delivery was rejected")
                payload = json.loads(response.read().decode())
                message_id = payload.get("result", {}).get("message_id") if payload.get("ok") is True else None
                if not isinstance(message_id, int):
                    raise RuntimeError("Telegram response did not include a message ID")
                return message_id
        except Exception as exc:
            raise RuntimeError("Telegram notification delivery failed") from exc

    def _answer_callback_query(self, callback_query_id: str, text: str) -> bool:
        token = self._token_provider()
        if not token or not callback_query_id:
            raise RuntimeError("Telegram callback acknowledgement is unavailable")
        body = json.dumps({
            "callback_query_id": callback_query_id,
            "text": str(text)[:160],
            "show_alert": False,
        }, separators=(",", ":")).encode()
        request = Request(f"https://api.telegram.org/bot{token}/answerCallbackQuery", data=body, headers={"content-type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=15) as response:  # noqa: S310
                payload = json.loads(response.read().decode())
                return bool(response.status < 300 and payload.get("ok") is True)
        except Exception as exc:
            raise RuntimeError("Telegram callback acknowledgement failed") from exc

    def _set_webhook(self, url: str, secret_token: str) -> bool:
        token = self._token_provider()
        if not token:
            raise RuntimeError("Telegram credential is unavailable")
        body = json.dumps({
            "url": url,
            "secret_token": secret_token,
            "allowed_updates": ["message", "callback_query"],
            "drop_pending_updates": False,
        }, separators=(",", ":")).encode()
        request = Request(f"https://api.telegram.org/bot{token}/setWebhook", data=body, headers={"content-type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=15) as response:  # noqa: S310
                payload = json.loads(response.read().decode())
                return response.status < 300 and payload.get("ok") is True
        except Exception as exc:
            raise RuntimeError("Telegram webhook registration failed") from exc


_TELEGRAM_LABEL = re.compile(r"(^|\|\s*)([^|:\n]+):(?=\s)", re.MULTILINE)


def _bold_telegram_labels(text: str) -> str:
    """Escape Telegram HTML and bold colon labels without altering values."""
    escaped = html.escape(text, quote=False)
    return _TELEGRAM_LABEL.sub(lambda match: f"{match.group(1)}<b>{match.group(2)}</b>:", escaped)


@dataclass(frozen=True)
class PaperSafetyConfiguration:
    mode: str = "paper"
    execution_enabled: bool = False
    autonomous_execution: bool = False
    execution_adapter_enabled: bool = False
    openclaw_execution_allowed: bool = False
    telegram_execution_allowed: bool = False
    governance_kill_switch_enabled: bool = True
    audit_logging_enabled: bool = True

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> "PaperSafetyConfiguration":
        values = os.environ if environment is None else environment
        mode = values.get("MONATISE_MODE", "paper").strip().casefold()
        network = values.get("MONATISE_NETWORK", "paper").strip().casefold()
        violations: list[str] = []
        if mode != "paper":
            violations.append("MONATISE_MODE must be paper")
        if network in {"mainnet", "live"}:
            violations.append("MONATISE_NETWORK cannot be mainnet or live")
        for key in (
            "MONATISE_EXECUTION_ENABLED",
            "MONATISE_AUTONOMOUS_EXECUTION",
            "MONATISE_EXECUTION_ADAPTER_ENABLED",
            "MONATISE_OPENCLAW_EXECUTION_ALLOWED",
            "MONATISE_TELEGRAM_EXECUTION_ALLOWED",
            "MONATISE_ALLOW_LIVE_ORDERS",
        ):
            if not _false(values.get(key)):
                violations.append(f"{key} must be false")
        if values.get("MONATISE_GOVERNANCE_KILL_SWITCH_ENABLED", "true").strip().casefold() not in {"1", "true", "yes", "on"}:
            violations.append("MONATISE_GOVERNANCE_KILL_SWITCH_ENABLED must be true")
        if values.get("MONATISE_AUDIT_LOGGING_ENABLED", "true").strip().casefold() not in {"1", "true", "yes", "on"}:
            violations.append("MONATISE_AUDIT_LOGGING_ENABLED must be true")
        if violations:
            raise ValueError("unsafe orchestration configuration: " + "; ".join(violations))
        return cls()


class MigrationRunner:
    def __init__(self, connection: Any, migration_directory: Path) -> None:
        self.connection = connection
        self.migration_directory = migration_directory
        self.current = False
        self.version: str | None = None

    async def run(self) -> None:
        started = perf_counter()
        await self.connection.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))
        try:
            await self.connection.execute(
                "CREATE TABLE IF NOT EXISTS monatise_schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            )
            for path in sorted(self.migration_directory.glob("*.sql")):
                version = path.stem
                sql = path.read_text(encoding="utf-8")
                checksum = hashlib.sha256(sql.encode()).hexdigest()
                row = await (await self.connection.execute(
                    "SELECT checksum FROM monatise_schema_migrations WHERE version=%s", (version,)
                )).fetchone()
                if row:
                    stored_checksum = row[0].decode() if isinstance(row[0], bytes) else row[0]
                    if stored_checksum != checksum:
                        raise RuntimeError(f"migration checksum mismatch: {version}")
                    self.version = version
                    continue
                await self.connection.execute(sql)
                await self.connection.execute(
                    "INSERT INTO monatise_schema_migrations(version, checksum) VALUES (%s,%s)", (version, checksum)
                )
                self.version = version
                LOGGER.info("applied migration %s", version)
            self.current = True
            LOGGER.info("migrations current at %s in %.1fms", self.version or "none", (perf_counter() - started) * 1000)
        finally:
            await self.connection.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))


class RedisSchedulerLeadership:
    RELEASE_SCRIPT = "if redis.call('GET',KEYS[1]) == ARGV[1] then return redis.call('DEL',KEYS[1]) else return 0 end"
    RENEW_SCRIPT = "if redis.call('GET',KEYS[1]) == ARGV[1] then return redis.call('EXPIRE',KEYS[1],ARGV[2]) else return 0 end"

    def __init__(self, client: Any, *, namespace: str, ttl_seconds: int = 30) -> None:
        self.client = client
        self.key = f"{namespace}:scheduler:leader"
        self.token = uuid4().hex
        self.ttl_seconds = ttl_seconds
        self.is_leader = False
        self._renewal: asyncio.Task[None] | None = None
        self._contender: asyncio.Task[None] | None = None
        self._on_acquired: Any | None = None
        self._on_lost: Any | None = None
        self._released = False

    async def acquire(self) -> bool:
        self.is_leader = bool(await self.client.set(self.key, self.token, nx=True, ex=self.ttl_seconds))
        if self.is_leader:
            self._renewal = asyncio.create_task(self._renew(), name="monatise-scheduler-leadership")
        return self.is_leader

    async def acquire_or_wait(self, on_acquired: Any, on_lost: Any | None = None) -> bool:
        """Acquire immediately or keep contending until leadership is available."""
        self._on_acquired = on_acquired
        self._on_lost = on_lost
        self._released = False
        if await self.acquire():
            return True
        self._contender = asyncio.create_task(
            self._contend(on_acquired), name="monatise-scheduler-contender"
        )
        return False

    async def _contend(self, on_acquired: Any) -> None:
        try:
            while not self.is_leader:
                await asyncio.sleep(self.ttl_seconds / 3)
                if await self.acquire():
                    callback_result = on_acquired()
                    if inspect.isawaitable(callback_result):
                        await callback_result
                    return
        except asyncio.CancelledError:
            raise

    async def _renew(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.ttl_seconds / 3)
                renewed = await self.client.eval(self.RENEW_SCRIPT, 1, self.key, self.token, self.ttl_seconds)
                if not renewed:
                    self.is_leader = False
                    if self._on_lost is not None:
                        callback_result = self._on_lost()
                        if inspect.isawaitable(callback_result):
                            await callback_result
                    if not self._released and self._on_acquired is not None:
                        self._contender = asyncio.create_task(
                            self._contend(self._on_acquired),
                            name="monatise-scheduler-contender",
                        )
                    return
        except asyncio.CancelledError:
            raise

    async def release(self) -> None:
        self._released = True
        if self._contender:
            self._contender.cancel()
            await asyncio.gather(self._contender, return_exceptions=True)
            self._contender = None
        if self._renewal:
            self._renewal.cancel()
            await asyncio.gather(self._renewal, return_exceptions=True)
            self._renewal = None
        if self.is_leader:
            await self.client.eval(self.RELEASE_SCRIPT, 1, self.key, self.token)
        self.is_leader = False


class RedisCoordinationStore:
    """Namespaced ephemeral coordination for cache, deduplication, and nonces."""

    NOTIFICATION_CAS_SCRIPT = """
local current = redis.call('GET', KEYS[1])
local current_version = 0
if current then
  local decoded = cjson.decode(current)
  current_version = tonumber(decoded.version or 0)
end
if current_version ~= tonumber(ARGV[1]) then
  return nil
end
local incoming = cjson.decode(ARGV[2])
incoming.version = current_version + 1
local encoded = cjson.encode(incoming)
redis.call('SET', KEYS[1], encoded)
return encoded
"""

    def __init__(self, client: Any, *, namespace: str, telegram_dlq_max_length: int = 1000) -> None:
        self.client = client
        self.namespace = namespace.strip(":")
        self.telegram_dlq_max_length = min(max(int(telegram_dlq_max_length), 1), 100_000)

    def key(self, purpose: str, value: str) -> str:
        return f"{self.namespace}:{purpose}:{value}"

    async def cache_get(self, dataset: str) -> Any | None:
        value = await self.client.get(self.key("coinglass-cache", dataset))
        return json.loads(value) if value is not None else None

    async def cache_put(self, dataset: str, value: Any, *, ttl_seconds: int = 30) -> None:
        await self.client.set(self.key("coinglass-cache", dataset), json.dumps(value, separators=(",", ":")), ex=ttl_seconds)

    async def claim_event(self, event_id: str, *, ttl_seconds: int = 3600) -> bool:
        return bool(await self.client.set(self.key("event-dedup", event_id), "1", nx=True, ex=ttl_seconds))

    async def claim_nonce(self, nonce: str, *, ttl_seconds: int = 300) -> bool:
        return bool(await self.client.set(self.key("replay-nonce", nonce), "1", nx=True, ex=ttl_seconds))

    async def enqueue_telegram_command(self, update_id: int, payload: dict[str, Any], *, ttl_seconds: int = 86_400) -> bool:
        """Atomically deduplicate and durably enqueue a Telegram command."""
        script = """
local pending_type = redis.call('TYPE', KEYS[2]).ok
if pending_type ~= 'none' and pending_type ~= 'list' then return -2 end
local dedup_type = redis.call('TYPE', KEYS[1]).ok
local dedup_valid = false
local dedup_corrupt = false
if dedup_type == 'string' then
  dedup_valid = redis.call('GET', KEYS[1]) == '1' and redis.call('TTL', KEYS[1]) > 0
  dedup_corrupt = not dedup_valid
elseif dedup_type ~= 'none' then
  dedup_corrupt = true
end
if dedup_valid then return 0 end
local redis_time = redis.call('TIME')
local now = tonumber(redis_time[1]) + tonumber(redis_time[2]) / 1000000
local queued_payload = cjson.decode(ARGV[2])
queued_payload['queued_at'] = now
redis.call('LPUSH', KEYS[2], cjson.encode(queued_payload))
-- Deduplication is secondary metadata. If this write fails, retain the
-- accepted command so a provider retry can at worst produce at-least-once
-- delivery instead of suppressing a command that was never queued.
local dedup_write = redis.pcall('SET', KEYS[1], '1', 'EX', ARGV[1])
if dedup_corrupt or (type(dedup_write) == 'table' and dedup_write['err']) then
  local flagged = redis.pcall('INCR', KEYS[3])
  if type(flagged) == 'table' and flagged['err'] then redis.pcall('SET', KEYS[3], '1') end
end
return 1
"""
        outcome = int(await self.client.eval(
            script,
            3,
            self.key("telegram-update", str(update_id)),
            self.key("telegram-command", "pending"),
            self.key("telegram-command", "counter-corruption-count"),
            ttl_seconds,
            json.dumps(payload, separators=(",", ":")),
        ))
        if outcome == -2:
            raise RuntimeError("Telegram pending queue key-type invariant violation")
        return outcome == 1

    async def dequeue_telegram_command(self, *, timeout_seconds: int = 1, lease_seconds: int = 120) -> dict[str, Any] | None:
        deadline = time() + max(0, timeout_seconds)
        token = str(uuid4())
        script = """
local function key_is(key, expected)
  local kind = redis.call('TYPE', key).ok
  return kind == 'none' or kind == expected
end
local function safe_increment(key, amount)
  local result = redis.pcall('INCRBY', key, amount)
  if type(result) == 'table' and result['err'] then
    redis.pcall('SET', key, tostring(amount))
    local flagged = redis.pcall('INCR', KEYS[7])
    if type(flagged) == 'table' and flagged['err'] then redis.pcall('SET', KEYS[7], '1') end
  end
end
if not key_is(KEYS[1], 'list') or not key_is(KEYS[2], 'hash') or not key_is(KEYS[3], 'zset') or not key_is(KEYS[4], 'list') or not key_is(KEYS[5], 'string') then
  safe_increment(KEYS[6], 1)
  return cjson.encode({queue_status='invariant_violation'})
end
local value = redis.call('LINDEX', KEYS[1], -1)
if not value then return nil end
local redis_time = redis.call('TIME')
local now = tonumber(redis_time[1]) + tonumber(redis_time[2]) / 1000000
local ok, payload = pcall(cjson.decode, value)
local attempts = ok and type(payload) == 'table' and payload['attempts'] or nil
local valid = ok and type(payload) == 'table'
  and type(payload['update_id']) == 'number' and payload['update_id'] >= 0 and payload['update_id'] % 1 == 0
  and type(payload['text']) == 'string' and type(payload['queued_at']) == 'number'
  and (attempts == nil or (type(attempts) == 'number' and attempts >= 0 and attempts % 1 == 0))
if not valid then
  redis.call('LPUSH', KEYS[4], cjson.encode({reason='MALFORMED_PENDING_ENVELOPE', quarantined_at=now}))
  local overflow = redis.call('LLEN', KEYS[4]) - tonumber(ARGV[3])
  if overflow > 0 then
    redis.call('LTRIM', KEYS[4], 0, tonumber(ARGV[3]) - 1)
    safe_increment(KEYS[5], overflow)
  end
  redis.call('RPOP', KEYS[1])
  return cjson.encode({queue_status='malformed'})
end
local envelope = cjson.encode({payload=payload, token=ARGV[1], leased_at=now})
redis.call('HSET', KEYS[2], ARGV[1], envelope)
redis.call('ZADD', KEYS[3], now + tonumber(ARGV[2]), ARGV[1])
redis.call('RPOP', KEYS[1])
return envelope
"""
        while True:
            value = await self.client.eval(
                script,
                7,
                self.key("telegram-command", "pending"),
                self.key("telegram-command", "processing-v2"),
                self.key("telegram-command", "leases-v2"),
                self.key("telegram-command", "dead-letter"),
                self.key("telegram-command", "dlq-overflow-count"),
                self.key("telegram-command", "invariant-violation-count"),
                self.key("telegram-command", "counter-corruption-count"),
                token,
                lease_seconds,
                self.telegram_dlq_max_length,
            )
            if value is not None:
                envelope = json.loads(value)
                if envelope.get("queue_status") == "malformed":
                    continue
                if envelope.get("queue_status") == "invariant_violation":
                    raise RuntimeError("Telegram queue key-type invariant violation")
                payload = dict(envelope["payload"])
                payload["__monatise_lease_token"] = envelope["token"]
                return payload
            if time() >= deadline:
                return None
            await asyncio.sleep(min(0.1, max(0, deadline - time())))

    async def renew_telegram_command(self, payload: dict[str, Any], *, lease_seconds: int = 120) -> bool:
        token = str(payload.get("__monatise_lease_token") or "")
        if not token:
            return False
        script = """
local envelope = redis.call('HGET', KEYS[1], ARGV[1])
if not envelope then return 0 end
local decoded = cjson.decode(envelope)
if decoded['token'] ~= ARGV[1] then return 0 end
local redis_time = redis.call('TIME')
local now = tonumber(redis_time[1]) + tonumber(redis_time[2]) / 1000000
decoded['leased_at'] = now
redis.call('HSET', KEYS[1], ARGV[1], cjson.encode(decoded))
redis.call('ZADD', KEYS[2], now + tonumber(ARGV[2]), ARGV[1])
return 1
"""
        return bool(await self.client.eval(
            script, 2, self.key("telegram-command", "processing-v2"),
            self.key("telegram-command", "leases-v2"), token, lease_seconds,
        ))

    async def finish_telegram_command(self, payload: dict[str, Any]) -> bool:
        token = str(payload.get("__monatise_lease_token") or "")
        if not token:
            return False
        script = """
local function key_is(key, expected)
  local kind = redis.call('TYPE', key).ok
  return kind == 'none' or kind == expected
end
local function safe_increment(key, amount)
  local result = redis.pcall('INCRBY', key, amount)
  if type(result) == 'table' and result['err'] then
    redis.pcall('SET', key, tostring(amount))
    local flagged = redis.pcall('INCR', KEYS[5])
    if type(flagged) == 'table' and flagged['err'] then redis.pcall('SET', KEYS[5], '1') end
  end
end
if not key_is(KEYS[1], 'hash') or not key_is(KEYS[2], 'zset') then
  safe_increment(KEYS[4], 1)
  return -2
end
if redis.call('HEXISTS', KEYS[1], ARGV[1]) == 0 then return 0 end
local success_type = redis.call('TYPE', KEYS[3]).ok
local success_corrupt = success_type ~= 'none' and (success_type ~= 'string' or tonumber(redis.call('GET', KEYS[3])) == nil)
redis.call('HDEL', KEYS[1], ARGV[1])
redis.call('ZREM', KEYS[2], ARGV[1])
local redis_time = redis.call('TIME')
local now = tonumber(redis_time[1]) + tonumber(redis_time[2]) / 1000000
local telemetry_write = redis.pcall('SET', KEYS[3], tostring(now))
if success_corrupt or (type(telemetry_write) == 'table' and telemetry_write['err']) then
  safe_increment(KEYS[5], 1)
end
return 1
"""
        outcome = int(await self.client.eval(
            script, 5, self.key("telegram-command", "processing-v2"),
            self.key("telegram-command", "leases-v2"), self.key("telegram-command", "last-success-at"),
            self.key("telegram-command", "invariant-violation-count"),
            self.key("telegram-command", "counter-corruption-count"), token,
        ))
        return outcome == 1

    async def retry_telegram_command(self, payload: dict[str, Any], *, max_attempts: int = 3) -> TelegramCommandTransition:
        token = str(payload.get("__monatise_lease_token") or "")
        if not token:
            return TelegramCommandTransition.OWNERSHIP_LOST
        pending_payload = {key: value for key, value in payload.items() if key != "__monatise_lease_token"}
        pending_payload["attempts"] = int(pending_payload.get("attempts", 0)) + 1
        encoded = json.dumps(pending_payload, separators=(",", ":"))
        script = """
local function key_is(key, expected)
  local kind = redis.call('TYPE', key).ok
  return kind == 'none' or kind == expected
end
local function safe_increment(key, amount)
  local result = redis.pcall('INCRBY', key, amount)
  if type(result) == 'table' and result['err'] then
    redis.pcall('SET', key, tostring(amount))
    local flagged = redis.pcall('INCR', KEYS[7])
    if type(flagged) == 'table' and flagged['err'] then redis.pcall('SET', KEYS[7], '1') end
  end
end
if not key_is(KEYS[1], 'hash') or not key_is(KEYS[2], 'zset') or not key_is(KEYS[3], 'list') then
  safe_increment(KEYS[6], 1)
  return -2
end
if redis.call('HEXISTS', KEYS[1], ARGV[1]) == 0 then return 0 end
redis.call('LPUSH', KEYS[3], ARGV[2])
if ARGV[3] == '1' then
  local overflow = redis.call('LLEN', KEYS[3]) - tonumber(ARGV[4])
  if overflow > 0 then
    redis.call('LTRIM', KEYS[3], 0, tonumber(ARGV[4]) - 1)
    safe_increment(KEYS[5], overflow)
  end
end
redis.call('HDEL', KEYS[1], ARGV[1])
redis.call('ZREM', KEYS[2], ARGV[1])
safe_increment(KEYS[4], 1)
return 1
"""
        requeued = pending_payload["attempts"] < max_attempts
        destination = self.key("telegram-command", "pending" if requeued else "dead-letter")
        outcome = int(await self.client.eval(
            script, 7, self.key("telegram-command", "processing-v2"), self.key("telegram-command", "leases-v2"),
            destination, self.key("telegram-command", "retry-count"), self.key("telegram-command", "dlq-overflow-count"),
            self.key("telegram-command", "invariant-violation-count"),
            self.key("telegram-command", "counter-corruption-count"),
            token, encoded, "0" if requeued else "1", self.telegram_dlq_max_length,
        ))
        if outcome == -2:
            return TelegramCommandTransition.INVARIANT_VIOLATION
        if outcome == 0:
            return TelegramCommandTransition.OWNERSHIP_LOST
        return TelegramCommandTransition.REQUEUED if pending_payload["attempts"] < max_attempts else TelegramCommandTransition.DEAD_LETTERED

    async def release_telegram_command(self, payload: dict[str, Any]) -> TelegramCommandTransition:
        """Release an owned command during graceful shutdown without consuming an attempt."""
        token = str(payload.get("__monatise_lease_token") or "")
        if not token:
            return TelegramCommandTransition.OWNERSHIP_LOST
        pending_payload = {key: value for key, value in payload.items() if key != "__monatise_lease_token"}
        encoded = json.dumps(pending_payload, separators=(",", ":"))
        script = """
local function key_is(key, expected)
  local kind = redis.call('TYPE', key).ok
  return kind == 'none' or kind == expected
end
local function safe_increment(key, amount)
  local result = redis.pcall('INCRBY', key, amount)
  if type(result) == 'table' and result['err'] then
    redis.pcall('SET', key, tostring(amount))
    local flagged = redis.pcall('INCR', KEYS[5])
    if type(flagged) == 'table' and flagged['err'] then redis.pcall('SET', KEYS[5], '1') end
  end
end
if not key_is(KEYS[1], 'hash') or not key_is(KEYS[2], 'zset') or not key_is(KEYS[3], 'list') then
  safe_increment(KEYS[4], 1)
  return -2
end
if redis.call('HEXISTS', KEYS[1], ARGV[1]) == 0 then return 0 end
redis.call('LPUSH', KEYS[3], ARGV[2])
redis.call('HDEL', KEYS[1], ARGV[1])
redis.call('ZREM', KEYS[2], ARGV[1])
return 1
"""
        outcome = int(await self.client.eval(
            script, 5, self.key("telegram-command", "processing-v2"), self.key("telegram-command", "leases-v2"),
            self.key("telegram-command", "pending"), self.key("telegram-command", "invariant-violation-count"),
            self.key("telegram-command", "counter-corruption-count"), token, encoded,
        ))
        if outcome == -2:
            return TelegramCommandTransition.INVARIANT_VIOLATION
        return TelegramCommandTransition.REQUEUED if outcome == 1 else TelegramCommandTransition.OWNERSHIP_LOST

    async def recover_telegram_commands(self, *, batch_size: int = 100) -> int:
        processing = self.key("telegram-command", "processing-v2")
        leases = self.key("telegram-command", "leases-v2")
        pending = self.key("telegram-command", "pending")
        script = """
local function key_is(key, expected)
  local kind = redis.call('TYPE', key).ok
  return kind == 'none' or kind == expected
end
local function safe_increment(key, amount)
  local result = redis.pcall('INCRBY', key, amount)
  if type(result) == 'table' and result['err'] then
    redis.pcall('SET', key, tostring(amount))
    local flagged = redis.pcall('INCR', KEYS[7])
    if type(flagged) == 'table' and flagged['err'] then redis.pcall('SET', KEYS[7], '1') end
  end
end
if not key_is(KEYS[1], 'hash') or not key_is(KEYS[2], 'zset') or not key_is(KEYS[3], 'list') or not key_is(KEYS[4], 'list') or not key_is(KEYS[5], 'string') then
  safe_increment(KEYS[6], 1)
  return {-2, 0, 0}
end
local redis_time = redis.call('TIME')
local now = tonumber(redis_time[1]) + tonumber(redis_time[2]) / 1000000
local tokens = redis.call('ZRANGEBYSCORE', KEYS[2], '-inf', now, 'LIMIT', 0, tonumber(ARGV[1]))
local recovered = 0
local quarantined = 0
for _, token in ipairs(tokens) do
  local value = redis.call('HGET', KEYS[1], token)
  if value then
    local ok, envelope = pcall(cjson.decode, value)
    local payload = ok and type(envelope) == 'table' and envelope['payload'] or nil
    local attempts = type(payload) == 'table' and payload['attempts'] or nil
    local valid = type(payload) == 'table'
      and type(payload['update_id']) == 'number' and payload['update_id'] >= 0 and payload['update_id'] % 1 == 0
      and type(payload['text']) == 'string' and type(payload['queued_at']) == 'number'
      and (attempts == nil or (type(attempts) == 'number' and attempts >= 0 and attempts % 1 == 0))
    if valid then
      redis.call('LPUSH', KEYS[3], cjson.encode(envelope['payload']))
      redis.call('HDEL', KEYS[1], token)
      recovered = recovered + 1
    else
      redis.call('LPUSH', KEYS[4], cjson.encode({reason='malformed_lease_envelope', lease_token=token, quarantined_at=now}))
      local overflow = redis.call('LLEN', KEYS[4]) - tonumber(ARGV[2])
      if overflow > 0 then
        redis.call('LTRIM', KEYS[4], 0, tonumber(ARGV[2]) - 1)
        safe_increment(KEYS[5], overflow)
      end
      redis.call('HDEL', KEYS[1], token)
      quarantined = quarantined + 1
    end
  end
  redis.call('ZREM', KEYS[2], token)
end
return {recovered, quarantined, #tokens}
"""
        bounded_batch = min(max(int(batch_size), 1), 1000)
        recovered_total = 0
        while True:
            recovered, _quarantined, examined = await self.client.eval(
                script, 7, processing, leases, pending, self.key("telegram-command", "dead-letter"),
                self.key("telegram-command", "dlq-overflow-count"), self.key("telegram-command", "invariant-violation-count"),
                self.key("telegram-command", "counter-corruption-count"),
                bounded_batch, self.telegram_dlq_max_length,
            )
            if int(recovered) == -2:
                raise RuntimeError("Telegram recovery key-type invariant violation")
            recovered_total += int(recovered)
            if int(examined) < bounded_batch:
                return recovered_total
            await asyncio.sleep(0)

    async def telegram_queue_metrics(self) -> dict[str, Any]:
        """Return sanitized operational telemetry for health and operator views."""
        def counter(value: Any) -> tuple[int, bool]:
            if value is None:
                return 0, False
            if isinstance(value, Exception):
                return 0, True
            try:
                rendered = value.decode("utf-8") if isinstance(value, bytes) else str(value)
                return int(rendered), False
            except (UnicodeDecodeError, TypeError, ValueError):
                return 0, True

        started = perf_counter()
        try:
            pending = self.key("telegram-command", "pending")
            processing = self.key("telegram-command", "processing-v2")
            async with self.client.pipeline(transaction=False) as pipeline:
                pipeline.ping()
                pipeline.llen(pending)
                pipeline.hlen(processing)
                pipeline.llen(self.key("telegram-command", "dead-letter"))
                pipeline.get(self.key("telegram-command", "retry-count"))
                pipeline.get(self.key("telegram-command", "last-success-at"))
                pipeline.lindex(pending, -1)
                pipeline.time()
                pipeline.get(self.key("telegram-command", "dlq-overflow-count"))
                pipeline.get(self.key("telegram-command", "invariant-violation-count"))
                pipeline.get(self.key("telegram-command", "counter-corruption-count"))
                results = await pipeline.execute(raise_on_error=False)
            ping, pending_depth, active_leases, dead_letters, retries_raw, last_success, oldest, redis_time, dlq_overflows_raw, invariant_violations_raw, counter_corruptions_raw = results
            retries, retries_corrupt = counter(retries_raw)
            dlq_overflows, dlq_overflows_corrupt = counter(dlq_overflows_raw)
            invariant_violations, invariant_violations_corrupt = counter(invariant_violations_raw)
            counter_corruptions, counter_marker_corrupt = counter(counter_corruptions_raw)
            corrupt_counter_keys = [name for name, corrupt in (
                ("retry_count", retries_corrupt),
                ("dlq_overflow_count", dlq_overflows_corrupt),
                ("invariant_violation_count", invariant_violations_corrupt),
                ("counter_corruption_count", counter_marker_corrupt),
            ) if corrupt]
            corrupt_counters = len(corrupt_counter_keys)
            operational_errors = [value for value in (ping, pending_depth, active_leases, dead_letters, last_success, oldest, redis_time) if isinstance(value, Exception)]
            if operational_errors:
                return {
                    "redis": "degraded", "redis_latency_ms": round((perf_counter() - started) * 1000, 2),
                    "error_type": type(operational_errors[0]).__name__, "pending_depth": None,
                    "active_lease_count": None, "retry_count": retries, "dead_letter_count": None,
                    "dlq_overflow_count": dlq_overflows, "invariant_violation_count": invariant_violations,
                    "counter_corruption_count": counter_corruptions + corrupt_counters,
                    "counter_corruption_keys": corrupt_counter_keys, "queue_status": "degraded",
                    "last_success_at": None, "oldest_queued_age_seconds": None,
                }
            oldest_payload = json.loads(oldest) if oldest else {}
            queued_at = float(oldest_payload.get("queued_at", 0) or 0)
            redis_now = float(redis_time[0]) + float(redis_time[1]) / 1_000_000
            return {
                "redis": "connected" if ping else "degraded",
                "redis_latency_ms": round((perf_counter() - started) * 1000, 2),
                "pending_depth": int(pending_depth),
                "active_lease_count": int(active_leases),
                "retry_count": retries,
                "dead_letter_count": int(dead_letters),
                "dlq_overflow_count": dlq_overflows,
                "invariant_violation_count": invariant_violations,
                "counter_corruption_count": counter_corruptions + corrupt_counters,
                "counter_corruption_keys": corrupt_counter_keys,
                "queue_status": "degraded" if dlq_overflows or invariant_violations or counter_corruptions or corrupt_counters else "ok",
                "last_success_at": datetime.fromtimestamp(float(last_success), timezone.utc).isoformat() if last_success else None,
                "oldest_queued_age_seconds": round(max(0, redis_now - queued_at), 1) if queued_at else None,
            }
        except Exception as exc:
            try:
                dlq_overflows_raw, invariant_violations_raw, counter_corruptions_raw = await self.client.mget(
                    self.key("telegram-command", "dlq-overflow-count"),
                    self.key("telegram-command", "invariant-violation-count"),
                    self.key("telegram-command", "counter-corruption-count"),
                )
            except Exception:
                dlq_overflows_raw, invariant_violations_raw, counter_corruptions_raw = None, None, None
            dlq_overflows, dlq_corrupt = counter(dlq_overflows_raw)
            invariant_violations, invariant_corrupt = counter(invariant_violations_raw)
            counter_corruptions, marker_corrupt = counter(counter_corruptions_raw)
            return {
                "redis": "degraded", "redis_latency_ms": round((perf_counter() - started) * 1000, 2),
                "error_type": type(exc).__name__, "pending_depth": None, "active_lease_count": None,
                "retry_count": None, "dead_letter_count": None, "last_success_at": None,
                "dlq_overflow_count": dlq_overflows, "invariant_violation_count": invariant_violations,
                "counter_corruption_count": counter_corruptions + sum((dlq_corrupt, invariant_corrupt, marker_corrupt)),
                "counter_corruption_keys": [],
                "queue_status": "degraded",
                "oldest_queued_age_seconds": None,
            }

    async def notification_state_get(self, channel: str) -> dict[str, Any] | None:
        value = await self.client.get(self.key("notification-state", channel))
        return json.loads(value) if value is not None else None

    async def notification_state_compare_and_put(self, channel: str, expected_version: int, value: dict[str, Any]) -> dict[str, Any] | None:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
        result = await self.client.eval(
            self.NOTIFICATION_CAS_SCRIPT,
            1,
            self.key("notification-state", channel),
            expected_version,
            encoded,
        )
        return json.loads(result) if result is not None else None


class TradingViewAlertDuplicate(RuntimeError):
    """Raised when a webhook delivery exactly matches an already-stored alert."""


@dataclass
class OrchestrationRuntime:
    environment: Mapping[str, str] = field(default_factory=lambda: os.environ)
    migration_directory: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2] / "deploy" / "migrations")
    safety: PaperSafetyConfiguration | None = None
    postgres: Any | None = None
    postgres_pool: Any | None = None
    redis: Any | None = None
    application: Any | None = None
    leadership: RedisSchedulerLeadership | None = None
    redis_coordination: RedisCoordinationStore | None = None
    migrations: MigrationRunner | None = None
    coinglass: CoinGlassProductionAdapter | None = None
    backpack: BackpackAdapter | None = None
    alpaca: AlpacaMarketDataAdapter | None = None
    quiver: QuiverAdapter | None = None
    finnhub: FinnhubAdapter | None = None
    flashalpha: FlashAlphaAdapter | None = None
    telegram: TelegramNotifier | None = None
    x_macro: XMacroAdapter | None = None
    dependencies: dict[str, dict[str, Any]] = field(default_factory=dict)
    hierarchy: ShadowHierarchyCoordinator | None = None
    hierarchy_service: ShadowHierarchyService | None = None
    _telegram_signal_states: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    ftmo_registry: FTMOInstrumentRegistry = field(default_factory=lambda: FTMO_REGISTRY)
    ftmo_execution_configuration: FTMOExecutionConfiguration | None = None
    ftmo_master_configuration: FTMOMasterConfiguration | None = None
    ftmo_master: FTMOMasterControlService | None = None
    document_store: PostgresDocumentStore | None = None

    def market_data_providers(self) -> dict[str, Any]:
        if self.coinglass is None:
            raise RuntimeError("CoinGlass market provider is unavailable")
        providers: dict[str, Any] = {"coinglass": self.coinglass}
        if self.backpack is not None:
            providers["backpack_public"] = self.backpack
        return providers

    async def _register_scheduled_analysis(self) -> tuple[str, ...]:
        configuration = scheduled_analysis_configuration(self.environment)
        if configuration is None:
            return ()
        if self.application is None:
            raise RuntimeError("orchestration runtime is unavailable")
        symbols, intervals = configuration
        scheduler = self.application.infrastructure.scheduler
        job_ids: list[str] = []
        for symbol in symbols:
            for analysis_interval in intervals:
                job_id = f"{SCHEDULED_ANALYSIS_JOB_PREFIX}-{symbol.casefold()}-{analysis_interval}"

                async def task(asset: str = symbol, interval: str = analysis_interval) -> dict[str, Any]:
                    return await self.analyse(asset, interval=interval, source="monatise.scheduler", notification_policy="qualified_changes")

                cadence_seconds = SCHEDULED_ANALYSIS_INTERVAL_SECONDS[analysis_interval]
                await scheduler.register(JobDefinition(
                    job_id=job_id,
                    name=f"Scheduled {analysis_interval} paper analysis for {symbol}",
                    task=task,
                    schedule_type=ScheduleType.INTERVAL,
                    interval=timedelta(seconds=cadence_seconds),
                    timeout_seconds=min(max(float(cadence_seconds), 60.0), 300.0),
                    retry_policy=RetryPolicy(maximum_attempts=2, delay_seconds=5.0, maximum_delay_seconds=30.0),
                    tags=("scheduled", "crypto", "analysis", analysis_interval, "paper-only"),
                    metadata={"symbol": symbol, "analysis_interval": analysis_interval, "execution_enabled": False, "notification_policy": "qualified_changes", "align_to_interval_boundary": True, "alignment_delay_seconds": 10},
                ))
                job_ids.append(job_id)
        return tuple(job_ids)

    async def _register_hierarchy_shadow(self, store: PostgresDocumentStore) -> tuple[str, ...]:
        configuration = HierarchyConfiguration.from_environment(self.environment)
        if not configuration.enabled:
            self.dependencies["hierarchy_shadow"] = {"status": "ok", "enabled": False, "execution_enabled": False}
            return ()
        if self.application is None or self.coinglass is None:
            raise RuntimeError("hierarchical shadow dependencies are unavailable")
        repository = HierarchyRepository(store)
        self.hierarchy = ShadowHierarchyCoordinator(
            self.coinglass,
            repository,
            configuration=configuration,
            provenance=Provenance("coinglass", "binance", "dynamic-crypto-usdt", "v4", "hierarchy-candle-v1"),
        )
        async def publisher(message: str) -> Any:
            if self.telegram is None:
                raise RuntimeError("Telegram publisher is unavailable")
            result = await self.telegram.hierarchy_shadow_notification(message)
            await self._publish_ftmo_signal_from_message(message, source="monatise.crypto.hierarchy")
            return result
        publisher = publisher if self.telegram is not None else None
        current_price_provider = getattr(self.coinglass, "latest_current_price", None)
        self.hierarchy_service = ShadowHierarchyService(self.hierarchy, HierarchyLayerEvaluator(configuration=configuration), repository, publisher=publisher, current_price_provider=current_price_provider)
        scheduler = self.application.infrastructure.scheduler
        job_ids: list[str] = []
        scheduled = scheduled_analysis_configuration({**self.environment, "MONATISE_SCHEDULED_ANALYSIS_ENABLED": "true"})
        symbols = scheduled[0] if scheduled is not None else SCHEDULED_ANALYSIS_DEFAULT_SYMBOLS
        for symbol in symbols:
            job_id = f"hierarchy-shadow-{symbol.casefold()}"

            async def shadow_tick(asset: str = symbol) -> dict[str, Any]:
                return await self.hierarchy_service.tick(
                    asset,
                    macro_degraded=self.dependencies.get("macro_provider", {}).get("status") == "degraded",
                )

            await scheduler.register(JobDefinition(
                job_id=job_id,
                name=f"Hierarchical shadow evidence for {symbol}",
                task=shadow_tick,
                schedule_type=ScheduleType.INTERVAL,
                interval=timedelta(seconds=configuration.scheduler_interval_seconds),
                timeout_seconds=min(configuration.scheduler_interval_seconds - 1, 300),
                retry_policy=RetryPolicy(maximum_attempts=2, delay_seconds=5, maximum_delay_seconds=15),
                tags=("hierarchy", "shadow", "analysis-only"),
                metadata={"symbol": symbol, "shadow": True, "telegram_publish_enabled": configuration.telegram_publish_enabled, "execution_enabled": False, "confluence_timeframes": ("15m", "5m")},
            ))
            job_ids.append(job_id)
        if configuration.telegram_publish_enabled:
            reconciliation_job_id = "hierarchy-publication-reconciliation"

            async def reconcile_publications() -> dict[str, Any]:
                flagged = await repository.flag_stale_publications(occurred_at=datetime.now(timezone.utc))
                if flagged:
                    LOGGER.warning("hierarchical Telegram publications require operator reconciliation: %s", ",".join(flagged))
                return {"reconciliation_required": list(flagged), "automatic_resend": False}

            await scheduler.register(JobDefinition(
                job_id=reconciliation_job_id,
                name="Flag stale hierarchical Telegram publications",
                task=reconcile_publications,
                schedule_type=ScheduleType.INTERVAL,
                interval=timedelta(seconds=60),
                timeout_seconds=30,
                retry_policy=RetryPolicy(maximum_attempts=2, delay_seconds=5, maximum_delay_seconds=15),
                tags=("hierarchy", "telegram", "reconciliation"),
                metadata={"operator_resolution_required": True, "automatic_resend": False, "execution_enabled": False},
            ))
            job_ids.append(reconciliation_job_id)
        self.dependencies["hierarchy_shadow"] = {
            "status": "error" if configuration.telegram_publish_enabled and publisher is None else "ok",
            "enabled": True, "jobs": list(job_ids),
            "strategy_version": configuration.strategy_version,
            "telegram_publish_enabled": configuration.telegram_publish_enabled,
            "telegram_publisher_configured": publisher is not None,
            "telegram_publication_operational": configuration.telegram_publish_enabled and publisher is not None,
            "execution_enabled": False,
        }
        return tuple(job_ids)

    async def _register_ftmo_master_retention(self) -> str | None:
        if self.application is None or self.ftmo_master is None:
            return None
        job_id = "ftmo-master-control-retention"

        async def task() -> dict[str, int]:
            return await self.ftmo_master.repository.retention_sweep()

        await self.application.infrastructure.scheduler.register(JobDefinition(
            job_id=job_id,
            name="FTMO master control retention",
            task=task,
            schedule_type=ScheduleType.INTERVAL,
            interval=timedelta(hours=1),
            timeout_seconds=120.0,
            retry_policy=RetryPolicy(maximum_attempts=2, delay_seconds=10.0, maximum_delay_seconds=60.0),
            tags=("maintenance", "retention", "ftmo-master"),
            metadata={"nonce_retention_hours": 1, "control_record_retention_days": 90},
        ))
        return job_id

    async def _register_x_macro_monitor(self) -> tuple[str, ...]:
        if not _true(self.environment.get("MONATISE_X_MONITOR_ENABLED")):
            self.dependencies["x_macro"] = {"status": "ok", "enabled": False, "read_only": True}
            return ()
        if self.application is None or self.x_macro is None or self.telegram is None or self.redis is None:
            self.dependencies["x_macro"] = {"status": "error", "enabled": True, "read_only": True}
            raise RuntimeError("X macro monitoring dependencies are unavailable")
        accounts = tuple(dict.fromkeys(
            item.strip().lstrip("@") for item in self.environment.get("MONATISE_X_WATCH_ACCOUNTS", "").split(",") if item.strip()
        ))
        account_query = " OR ".join(f"from:{account}" for account in accounts)
        topic_query = '(bitcoin OR BTC OR "Federal Reserve" OR inflation OR CPI OR "bitcoin ETF") -is:retweet'
        query = f"({account_query}) ({topic_query})" if account_query else topic_query
        interval_seconds = max(60, int(self.environment.get("MONATISE_X_POLL_INTERVAL_SECONDS", "300")))

        async def monitor() -> dict[str, Any]:
            posts = await self.x_macro.recent(query)
            delivered = 0
            for post in reversed(posts):
                dedupe_key = f"{self.environment.get('MONATISE_REDIS_NAMESPACE', 'monatise:production-analysis')}:x-post:{post.post_id}"
                if not await self.redis.set(dedupe_key, "1", nx=True, ex=604_800):
                    continue
                await self.telegram.x_macro_notification(self._format_x_macro_post(post))
                delivered += 1
            return {"fetched": len(posts), "delivered": delivered, "execution_enabled": False}

        job_id = "x-macro-telegram-monitor"
        await self.application.infrastructure.scheduler.register(JobDefinition(
            job_id=job_id,
            name="Read-only X macro and Bitcoin whale monitor",
            task=monitor,
            schedule_type=ScheduleType.INTERVAL,
            interval=timedelta(seconds=interval_seconds),
            timeout_seconds=min(max(interval_seconds - 1, 30), 120),
            retry_policy=RetryPolicy(maximum_attempts=2, delay_seconds=5, maximum_delay_seconds=15),
            tags=("x", "macro", "bitcoin", "telegram", "read-only"),
            metadata={"read_only": True, "telegram_publish_enabled": True, "execution_enabled": False},
        ))
        self.dependencies["x_macro"] = {
            "status": "ok", "enabled": True, "read_only": True, "job": job_id,
            "watch_accounts": len(accounts), "poll_interval_seconds": interval_seconds,
        }
        return (job_id,)

    async def _register_ftmo_crypto_scanner(self) -> tuple[str, ...]:
        """Scan only crypto CFDs present in the canonical FTMO registry."""
        if not _true(self.environment.get("MONATISE_FTMO_CRYPTO_SCAN_ENABLED", "true")):
            self.dependencies["ftmo_crypto_scan"] = {"status": "ok", "enabled": False}
            return ()
        if self.application is None or self.coinglass is None or self.telegram is None or self.redis is None:
            self.dependencies["ftmo_crypto_scan"] = {"status": "error", "enabled": True}
            raise RuntimeError("FTMO crypto scanner dependencies are unavailable")
        registry = getattr(self, "ftmo_registry", FTMO_REGISTRY)
        ftmo_instruments = registry.for_asset_class(FTMOAssetClass.CRYPTO)
        by_underlying = {item.underlying_symbol: item for item in ftmo_instruments}
        namespace = self.environment.get("MONATISE_REDIS_NAMESPACE", "monatise:production-analysis")
        interval_seconds = max(60, int(self.environment.get("MONATISE_FTMO_CRYPTO_SCAN_INTERVAL_SECONDS", "300")))
        analysis_cap = max(1, min(20, int(self.environment.get("MONATISE_FTMO_CRYPTO_DEEP_ANALYSIS_LIMIT", "10"))))
        candidate_limit = max(1, min(30, int(self.environment.get("MONATISE_FTMO_CRYPTO_CANDIDATE_LIMIT", "20"))))
        minimum_volume = max(0.0, float(self.environment.get("MONATISE_FTMO_CRYPTO_MIN_VOLUME_USD", "5000000")))
        minimum_open_interest = max(0.0, float(self.environment.get("MONATISE_FTMO_CRYPTO_MIN_OPEN_INTEREST_USD", "1000000")))
        ranked_key = f"{namespace}:ftmo:crypto:ranked:v1"

        async def monitor() -> dict[str, Any]:
            started_at = datetime.now(timezone.utc)
            self.dependencies["ftmo_crypto_scan"].update({"last_started_at": started_at.isoformat(), "last_error": None})
            try:
                coins, markets, exchange_pairs = await asyncio.gather(
                    asyncio.to_thread(self.coinglass.supported_futures_coins),
                    asyncio.to_thread(self.coinglass.futures_coins_markets),
                    asyncio.to_thread(self.coinglass.supported_exchange_pairs),
                )
                current = set(coins)
                verified = {
                    base for exchange, _instrument, base, quote in exchange_pairs
                    if exchange.casefold() in {"binance", "okx", "bybit"} and quote.upper() in {"USDT", "USDC", "USD"}
                }
                market_priority = {
                    (quote, exchange): quote_rank * 10 + exchange_rank
                    for quote_rank, quote in enumerate(("USDT", "USDC", "USD"))
                    for exchange_rank, exchange in enumerate(("binance", "okx", "bybit"))
                }
                verified_markets: dict[str, tuple[str, str, str]] = {}
                verified_ranks: dict[str, int] = {}
                for exchange, instrument, base, quote in exchange_pairs:
                    rank = market_priority.get((quote.upper(), exchange.casefold()))
                    if rank is None or (base in verified_ranks and verified_ranks[base] <= rank):
                        continue
                    verified_ranks[base] = rank
                    verified_markets[base] = (exchange, instrument, quote)
                # CoinGlass supplies evidence only; the FTMO registry owns the
                # tradable universe. Unsupported movers can never enter here.
                eligible = set(by_underlying) & current & verified
                ranked = rank_significant_futures_universe(eligible, markets, minimum_volume_usd=minimum_volume, minimum_open_interest_usd=minimum_open_interest, limit=candidate_limit, verified_markets=verified_markets)
                serialized_candidates = [
                    {**item.to_dict(), "ftmo_symbol": by_underlying[item.symbol].ftmo_symbol, "asset_class": FTMOAssetClass.CRYPTO.value}
                    for item in ranked
                ]
                await self.redis.set(ranked_key, json.dumps(serialized_candidates), ex=max(interval_seconds * 3, 900))
                analyzed = 0
                analysis_failures: list[dict[str, str]] = []
                hierarchy_results: list[dict[str, Any]] = []
                if self.hierarchy_service is not None:
                    async def analyze_candidate(candidate: Any) -> dict[str, Any]:
                        instrument = by_underlying[candidate.symbol]
                        derivatives = await asyncio.to_thread(self.coinglass.derivatives_snapshot, candidate.symbol, "15m")
                        return await self.hierarchy_service.tick(candidate.symbol, market_context={
                            "discovery": {**candidate.to_dict(), "ftmo_symbol": instrument.ftmo_symbol}, "derivatives": derivatives,
                            "ftmo_instrument": instrument.to_dict(),
                            "verified_market": f"{candidate.instrument} on {candidate.exchange} ({candidate.quote_asset}-quoted perpetual)",
                        })

                    semaphore = asyncio.Semaphore(4)
                    async def bounded_analysis(candidate: Any) -> dict[str, Any]:
                        async with semaphore:
                            return await analyze_candidate(candidate)
                    outcomes = await asyncio.gather(*(bounded_analysis(item) for item in ranked[:analysis_cap]), return_exceptions=True)
                    for candidate, outcome in zip(ranked[:analysis_cap], outcomes):
                        if isinstance(outcome, Exception):
                            LOGGER.warning("Significant-universe hierarchy analysis failed", extra={"symbol": candidate.symbol, "error_type": type(outcome).__name__})
                            analysis_failures.append({"symbol": candidate.symbol, "error_type": type(outcome).__name__})
                            continue
                        analyzed += 1
                        hierarchy_results.append(outcome)
                result = {
                    "registry_version": ftmo_instruments[0].registry_version if ftmo_instruments else None,
                    "ftmo_universe_size": len(ftmo_instruments), "provider_supported": len(eligible), "ranked_candidates": len(ranked),
                    "deep_analysis_attempted": min(len(ranked), analysis_cap), "deep_analysis_completed": analyzed,
                    "deep_analysis_failures": analysis_failures,
                    "telegram_published": sum(bool(item.get("telegram_published")) for item in hierarchy_results),
                    "candidates": serialized_candidates, "execution_enabled": False,
                }
                self.dependencies["ftmo_crypto_scan"].update({
                    "last_success_at": datetime.now(timezone.utc).isoformat(), "last_result": result, "last_error": None,
                })
                return result
            except Exception as exc:
                self.dependencies["ftmo_crypto_scan"].update({
                    "last_failure_at": datetime.now(timezone.utc).isoformat(), "last_error": type(exc).__name__,
                })
                raise

        job_id = "ftmo-crypto-scanner-telegram"
        await self.application.infrastructure.scheduler.register(JobDefinition(
            job_id=job_id,
            name="Monatise FTMO crypto scanner",
            task=monitor,
            schedule_type=ScheduleType.INTERVAL,
            interval=timedelta(seconds=interval_seconds),
            timeout_seconds=min(max(interval_seconds - 1, 30), 180),
            retry_policy=RetryPolicy(maximum_attempts=2, delay_seconds=5, maximum_delay_seconds=15),
            tags=("ftmo", "crypto", "registry", "coinglass-intelligence", "telegram", "read-only"),
            metadata={"notification_only": True, "execution_enabled": False, "directional_only": True, "universe_owner": "ftmo_registry"},
        ))
        self.dependencies["ftmo_crypto_scan"] = {
            "status": "ok", "enabled": True, "job": job_id,
            "poll_interval_seconds": interval_seconds,
            "universe_size": len(ftmo_instruments),
            "deep_analysis_limit": analysis_cap,
            "candidate_limit": candidate_limit,
            "minimum_volume_usd": minimum_volume,
            "minimum_open_interest_usd": minimum_open_interest,
        }
        return (job_id,)

    async def _register_ftmo_stock_scanner(self) -> tuple[str, ...]:
        if not _true(self.environment.get("MONATISE_FTMO_STOCK_SCAN_ENABLED", "true")):
            self.dependencies["ftmo_stock_scan"] = {
                "status": "ok", "enabled": False, "scheduled": False, "running": False,
            }
            return ()
        if self.application is None or self.telegram is None or self.redis is None:
            self.dependencies["ftmo_stock_scan"] = {
                "status": "error", "enabled": True, "scheduled": False, "running": False,
            }
            raise RuntimeError("FTMO stock scanner dependencies are unavailable")
        namespace = self.environment.get("MONATISE_REDIS_NAMESPACE", "monatise:production-analysis")
        interval_seconds = max(300, int(self.environment.get("MONATISE_STOCK_SCAN_INTERVAL_SECONDS", "1800")))
        cooldown_seconds = max(300, int(self.environment.get("MONATISE_STOCK_SCAN_COOLDOWN_SECONDS", "21600")))
        configuration = StockUniverseConfiguration(
            minimum_price=max(0.01, float(self.environment.get("MONATISE_STOCK_MIN_PRICE", "5"))),
            maximum_spread_bps=max(1.0, float(self.environment.get("MONATISE_STOCK_MAX_SPREAD_BPS", "80"))),
            minimum_daily_dollar_volume=max(0.0, float(self.environment.get("MONATISE_STOCK_MIN_DOLLAR_VOLUME", "5000000"))),
            maximum_universe_size=max(0, int(self.environment.get("MONATISE_STOCK_UNIVERSE_MAX", "0"))),
            include_leveraged=_true(self.environment.get("MONATISE_STOCK_INCLUDE_LEVERAGED", "false")),
            shortlist_per_side=max(1, int(self.environment.get("MONATISE_STOCK_SHORTLIST_PER_SIDE", "5"))),
            minimum_score=max(1, int(self.environment.get("MONATISE_STOCK_MINIMUM_SCORE", "7"))),
            minimum_reward_risk=max(1.0, float(self.environment.get("MONATISE_STOCK_MINIMUM_REWARD_RISK", "1.5"))),
        )

        async def monitor() -> dict[str, Any]:
            started_at = datetime.now(timezone.utc)
            cycle_started = perf_counter()
            self.dependencies["ftmo_stock_scan"].update({
                "running": True,
                "last_cycle_status": "running",
                "last_started_at": started_at.isoformat(),
                "last_error": None,
                "candidate_count": 0,
                "analysis_completed_count": 0,
                "qualified_count": 0,
                "suppressed_count": 0,
                "published_count": 0,
            })
            LOGGER.info(
                "stock_scan_started",
                extra={"job_id": "ftmo-stock-scanner-telegram", "interval_seconds": interval_seconds},
            )
            try:
                result = await self._run_stock_universe_scan(configuration, cooldown_seconds, namespace)
                completed_at = datetime.now(timezone.utc)
                duration_ms = round((perf_counter() - cycle_started) * 1000, 2)
                counters = {
                    "candidate_count": int(result.get("candidate_count", result.get("deep_analysis_attempted", 0))),
                    "analysis_completed_count": int(result.get("analysis_completed_count", result.get("deep_analysis_completed", 0))),
                    "qualified_count": int(result.get("qualified_count", result.get("qualified_setups", 0))),
                    "suppressed_count": int(result.get("suppressed_count", 0)),
                    "published_count": int(result.get("proposal_published_count", result.get("telegram_published", 0))),
                }
                self.dependencies["ftmo_stock_scan"].update({
                    "last_success_at": completed_at.isoformat(),
                    "last_succeeded_at": completed_at.isoformat(),
                    "next_expected_at": (completed_at + timedelta(seconds=interval_seconds)).isoformat(),
                    "last_cycle_duration_ms": duration_ms,
                    "last_cycle_status": "succeeded",
                    "running": False,
                    "last_result": result,
                    "last_error": None,
                    **counters,
                })
                LOGGER.info(
                    "stock_scan_completed",
                    extra={"job_id": "ftmo-stock-scanner-telegram", "duration_ms": duration_ms, **counters},
                )
                return result
            except Exception as exc:
                failed_at = datetime.now(timezone.utc)
                duration_ms = round((perf_counter() - cycle_started) * 1000, 2)
                error_type = type(exc).__name__
                self.dependencies["ftmo_stock_scan"].update({
                    "last_failure_at": failed_at.isoformat(),
                    "last_failed_at": failed_at.isoformat(),
                    "last_cycle_duration_ms": duration_ms,
                    "last_cycle_status": "failed",
                    "running": False,
                    "last_error": error_type,
                })
                LOGGER.warning(
                    "stock_scan_failed",
                    extra={
                        "job_id": "ftmo-stock-scanner-telegram",
                        "duration_ms": duration_ms,
                        "error_type": error_type,
                    },
                )
                raise

        job_id = "ftmo-stock-scanner-telegram"
        await self.application.infrastructure.scheduler.register(JobDefinition(
            job_id=job_id,
            name="Monatise FTMO stock scanner",
            task=monitor,
            schedule_type=ScheduleType.INTERVAL,
            interval=timedelta(seconds=interval_seconds),
            timeout_seconds=min(max(interval_seconds - 1, 30), 180),
            retry_policy=RetryPolicy(maximum_attempts=2, delay_seconds=5, maximum_delay_seconds=15),
            tags=("monatise", "ftmo", "stocks", "registry", "telegram", "read-only"),
            metadata={"notification_only": True, "execution_enabled": False, "qualified_setups_only": True, "two_stage": True, "universe_owner": "ftmo_registry"},
        ))
        registry = getattr(self, "ftmo_registry", FTMO_REGISTRY)
        self.dependencies["ftmo_stock_scan"] = {
            "status": "ok", "enabled": True, "scheduled": True, "running": False,
            "last_cycle_status": "never_run", "job": job_id,
            "universe_size": len(registry.for_asset_class(FTMOAssetClass.STOCK)),
            "poll_interval_seconds": interval_seconds, "cooldown_seconds": cooldown_seconds,
            "last_started_at": None, "last_success_at": None, "last_succeeded_at": None,
            "last_failure_at": None, "last_failed_at": None, "last_error": None,
            "last_cycle_duration_ms": None,
            "candidate_count": 0, "analysis_completed_count": 0, "qualified_count": 0,
            "suppressed_count": 0, "published_count": 0,
            "maximum_universe_size": configuration.maximum_universe_size,
            "shortlist_per_side": configuration.shortlist_per_side,
            "minimum_score": configuration.minimum_score,
            "minimum_reward_risk": configuration.minimum_reward_risk,
            "enrichment_caps_per_cycle": {
                "quiver": max(0, int(self.environment.get("MONATISE_STOCK_QUIVER_CAP_PER_CYCLE", "6"))),
                "flashalpha": max(0, int(self.environment.get("MONATISE_STOCK_FLASHALPHA_CAP_PER_CYCLE", "4"))),
                "finnhub": max(0, int(self.environment.get("MONATISE_STOCK_FINNHUB_CAP_PER_CYCLE", "6"))),
            },
        }
        return (job_id,)

    async def _run_stock_universe_scan(self, configuration: StockUniverseConfiguration, cooldown_seconds: int, namespace: str) -> dict[str, Any]:
        alpaca = getattr(self, "alpaca", None) or AlpacaMarketDataAdapter.from_env()
        self.alpaca = alpaca
        registry = getattr(self, "ftmo_registry", FTMO_REGISTRY)
        instruments = registry.for_asset_class(FTMOAssetClass.STOCK)
        exclusions: dict[str, int] = {}
        assets = [{
            "symbol": item.provider_symbol or item.underlying_symbol,
            "ftmo_symbol": item.ftmo_symbol,
            "underlying_symbol": item.underlying_symbol,
            "name": item.display_name.removesuffix(", Spot CFD"),
            "status": "active", "tradable": True, "exchange": item.exchange,
            "ftmo_registry_verified": True, "market_data_provider": item.market_data_provider,
        } for item in instruments]
        if configuration.maximum_universe_size > 0:
            assets = assets[:configuration.maximum_universe_size]
        universe_source = "ftmo_registry"

        alpaca_assets = [row for row in assets if row.get("market_data_provider") == "alpaca"]
        provider_unavailable = len(assets) - len(alpaca_assets)
        if provider_unavailable:
            exclusions["provider_unavailable_fail_closed"] = provider_unavailable
        snapshot_batches = [tuple(str(row["symbol"]).upper() for row in alpaca_assets[index:index + 200]) for index in range(0, len(alpaca_assets), 200)]
        semaphore = asyncio.Semaphore(4)
        snapshot_failures = 0

        async def fetch_batch(batch: tuple[str, ...]) -> dict[str, dict[str, Any]]:
            nonlocal snapshot_failures
            async with semaphore:
                try:
                    return await asyncio.to_thread(alpaca.stock_snapshots, batch)
                except Exception:
                    snapshot_failures += 1
                    return {}

        batch_results = await asyncio.gather(*(fetch_batch(batch) for batch in snapshot_batches))
        snapshots = {symbol: snapshot for batch in batch_results for symbol, snapshot in batch.items()}
        longs, shorts, snapshot_exclusions = rank_stock_universe(assets, snapshots, configuration)
        for reason, count in snapshot_exclusions.items(): exclusions[reason] = exclusions.get(reason, 0) + count
        shortlisted = _interleave_stock_candidates(
            longs[:configuration.shortlist_per_side],
            shorts[:configuration.shortlist_per_side],
        )
        outcomes = await asyncio.gather(*(self._analyze_market_stock(candidate, configuration, index) for index, candidate in enumerate(shortlisted)), return_exceptions=True)
        analyzed = qualified = published = proposal_published = suppressed = 0
        scan_results: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        suppressions: dict[str, int] = {}
        provider_degraded = {"quiver": 0, "flashalpha": 0, "finnhub": 0}
        for candidate, outcome in zip(shortlisted, outcomes):
            if isinstance(outcome, Exception):
                failures.append({"symbol": candidate.symbol, "error_type": type(outcome).__name__})
                continue
            analyzed += 1
            outcome.setdefault("ftmo_symbol", candidate.ftmo_symbol or candidate.symbol)
            outcome.setdefault("underlying_symbol", candidate.underlying_symbol or candidate.symbol)
            outcome.setdefault("exchange", candidate.exchange)
            scan_results.append(outcome)
            additional = outcome.get("additional_context") or {}
            if not (additional.get("quiver") or {}).get("available"): provider_degraded["quiver"] += 1
            if (additional.get("flashalpha") or {}).get("unavailable"): provider_degraded["flashalpha"] += 1
            if (additional.get("finnhub") or {}).get("unavailable"): provider_degraded["finnhub"] += 1
            if outcome.get("setup_status") != "confirmed":
                suppressed += 1
                for reason in outcome.get("suppression_reasons") or ["not_qualified"]:
                    suppressions[reason] = suppressions.get(reason, 0) + 1
                continue
            qualified += 1
            alert_state = _setup_alert_state(outcome)
            dedupe_key = f"{namespace}:stock-setup-alert:{candidate.symbol}"
            previous_state = await self.redis.get(dedupe_key)
            if previous_state and not _setup_materially_changed(previous_state, alert_state):
                suppressed += 1
                suppressions["duplicate_unchanged"] = suppressions.get("duplicate_unchanged", 0) + 1
                continue
            await self.redis.set(dedupe_key, json.dumps(alert_state, separators=(",", ":"), sort_keys=True), ex=cooldown_seconds)
            try:
                notifier = getattr(self.telegram, "ftmo_stock_notification", self.telegram.stock_analysis_notification)
                message = TelegramNotifier.format_market_stock_setup(outcome)
                await notifier(message)
                proposal_published += int(await self._publish_ftmo_signal_proposal(outcome, source="monatise.stock.scanner"))
                published += 1
            except Exception as exc:
                if previous_state:
                    await self.redis.set(dedupe_key, previous_state, ex=cooldown_seconds)
                else:
                    await self.redis.delete(dedupe_key)
                failures.append({"symbol": candidate.symbol, "error_type": type(exc).__name__})
        return {
            "universe_source": universe_source, "registry_version": instruments[0].registry_version if instruments else None,
            "universe_size": len(assets), "snapshots_received": len(snapshots),
            "snapshot_batch_failures": snapshot_failures, "excluded": exclusions,
            "stage_a_long_ranked": len(longs), "stage_a_short_ranked": len(shorts),
            "shortlisted_long": min(len(longs), configuration.shortlist_per_side),
            "shortlisted_short": min(len(shorts), configuration.shortlist_per_side),
            "deep_analysis_attempted": len(shortlisted), "deep_analysis_completed": analyzed,
            "qualified_setups": qualified, "telegram_published": published,
            "candidate_count": len(shortlisted), "analysis_completed_count": analyzed,
            "qualified_count": qualified, "suppressed_count": suppressed,
            "proposal_published_count": proposal_published,
            "suppressions": suppressions, "failures": failures, "provider_degraded": provider_degraded,
            "results": scan_results, "execution_enabled": False,
        }

    async def _analyze_market_stock(self, candidate: StockCandidate, configuration: StockUniverseConfiguration, enrichment_index: int) -> dict[str, Any]:
        alpaca = getattr(self, "alpaca", None) or AlpacaMarketDataAdapter.from_env()
        self.alpaca = alpaca
        quiver = getattr(self, "quiver", None) or QuiverAdapter.from_env()
        flashalpha = getattr(self, "flashalpha", None) or FlashAlphaAdapter.from_env()
        finnhub = getattr(self, "finnhub", None) or FinnhubAdapter.from_env()
        self.quiver, self.flashalpha, self.finnhub = quiver, flashalpha, finnhub
        hourly_task = asyncio.to_thread(alpaca.stock_bars, candidate.symbol, "1Hour", 220)
        daily_task = asyncio.to_thread(alpaca.stock_bars, candidate.symbol, "1Day", 120)

        async def optional_context(factory: Any, fallback: dict[str, Any]) -> dict[str, Any]:
            try:
                return await asyncio.wait_for(asyncio.to_thread(factory), timeout=15)
            except Exception:
                return fallback

        quiver_task = optional_context(
            lambda: quiver.context(candidate.symbol),
            {"source": "Quiver Quantitative", "available": False, "summary": {"score": 0, "cautions": ["provider unavailable"]}},
        ) if enrichment_index < max(0, int(self.environment.get("MONATISE_STOCK_QUIVER_CAP_PER_CYCLE", "6"))) else asyncio.sleep(0, result={"source": "Quiver Quantitative", "available": False, "summary": {"score": 0, "cautions": ["cycle quota reserved"]}})
        flashalpha_task = optional_context(
            lambda: flashalpha.context(candidate.symbol),
            {"source": "FlashAlpha", "unavailable": True},
        ) if enrichment_index < max(0, int(self.environment.get("MONATISE_STOCK_FLASHALPHA_CAP_PER_CYCLE", "4"))) else asyncio.sleep(0, result={"source": "FlashAlpha", "unavailable": True, "reason": "cycle quota reserved"})
        finnhub_task = optional_context(
            lambda: finnhub.context(candidate.symbol),
            {"source": "Finnhub", "unavailable": True},
        ) if enrichment_index < max(0, int(self.environment.get("MONATISE_STOCK_FINNHUB_CAP_PER_CYCLE", "6"))) else asyncio.sleep(0, result={"source": "Finnhub", "unavailable": True, "reason": "cycle quota reserved"})
        hourly, daily, quiver, flashalpha, finnhub = await asyncio.gather(hourly_task, daily_task, quiver_task, flashalpha_task, finnhub_task)
        return build_technical_stock_setup(candidate, hourly, daily, configuration=configuration, quiver=quiver, flashalpha=flashalpha, finnhub=finnhub)

    async def _register_ftmo_futures_scanner(self) -> tuple[str, ...]:
        api_key_configured = bool(self.environment.get("FLASHALPHA_API_KEY", "").strip())
        if not _true(self.environment.get("MONATISE_FTMO_FUTURES_SCAN_ENABLED", "true")):
            self.dependencies["ftmo_futures_scan"] = {"status": "ok", "enabled": False}
            return ()
        if self.application is None or self.telegram is None or self.redis is None:
            self.dependencies["ftmo_futures_scan"] = {"status": "error", "enabled": True}
            raise RuntimeError("FTMO futures scanner dependencies are unavailable")
        registry = getattr(self, "ftmo_registry", FTMO_REGISTRY)
        instruments = registry.for_asset_class(FTMOAssetClass.FUTURES_LINKED)
        interval_seconds = max(300, int(self.environment.get("MONATISE_FTMO_FUTURES_SCAN_INTERVAL_SECONDS", "900")))
        cooldown_seconds = max(300, int(self.environment.get("MONATISE_FTMO_FUTURES_SCAN_COOLDOWN_SECONDS", "3600")))
        namespace = self.environment.get("MONATISE_REDIS_NAMESPACE", "monatise:production-analysis")

        async def monitor() -> dict[str, Any]:
            started_at = datetime.now(timezone.utc)
            self.dependencies["ftmo_futures_scan"].update({"last_started_at": started_at.isoformat(), "last_error": None})
            try:
                result = await self._analyze_ftmo_futures(instruments, cooldown_seconds, namespace)
                self.dependencies["ftmo_futures_scan"].update({
                    "last_success_at": datetime.now(timezone.utc).isoformat(), "last_result": result, "last_error": None,
                })
                return result
            except Exception as exc:
                self.dependencies["ftmo_futures_scan"].update({
                    "last_failure_at": datetime.now(timezone.utc).isoformat(), "last_error": type(exc).__name__,
                })
                raise

        job_id = "ftmo-futures-scanner-telegram"
        await self.application.infrastructure.scheduler.register(JobDefinition(
            job_id=job_id,
            name="Monatise FTMO futures-linked market scanner",
            task=monitor,
            schedule_type=ScheduleType.INTERVAL,
            interval=timedelta(seconds=interval_seconds),
            timeout_seconds=min(max(interval_seconds - 1, 60), 240),
            retry_policy=RetryPolicy(maximum_attempts=2, delay_seconds=5, maximum_delay_seconds=15),
            tags=("ftmo", "futures-linked-cfd", "registry", "telegram", "read-only"),
            metadata={"notification_only": True, "execution_enabled": False, "qualified_setups_only": True, "universe_owner": "ftmo_registry"},
        ))
        self.dependencies["ftmo_futures_scan"] = {
            "status": "ok" if api_key_configured else "degraded", "enabled": True, "configured": api_key_configured, "job": job_id,
            "universe_size": len(instruments), "futures_roots": sorted({item.futures_symbol for item in instruments}),
            "poll_interval_seconds": interval_seconds, "cooldown_seconds": cooldown_seconds,
        }
        return (job_id,)

    async def _analyze_ftmo_futures(self, instruments: tuple[Any, ...], cooldown_seconds: int, namespace: str) -> dict[str, Any]:
        adapter = getattr(self, "flashalpha", None) or FlashAlphaAdapter.from_env()
        self.flashalpha = adapter
        unique_roots = tuple(dict.fromkeys(item.futures_symbol for item in instruments if item.futures_symbol))
        queue: asyncio.Queue[str] = asyncio.Queue()
        for root in unique_roots:
            queue.put_nowait(root)
        contexts: dict[str, dict[str, Any]] = {}
        failures: list[dict[str, str]] = []

        async def worker() -> None:
            while True:
                try:
                    root = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    contexts[root] = await asyncio.to_thread(adapter.context, f"{root}=F")
                except Exception as exc:
                    failures.append({"symbol": root, "error_type": type(exc).__name__})
                finally:
                    queue.task_done()

        workers = tuple(asyncio.create_task(worker()) for _ in range(min(4, len(unique_roots))))
        if workers:
            await asyncio.gather(*workers)
        candidates: list[tuple[Any, dict[str, Any]]] = []
        for instrument in instruments:
            context = contexts.get(instrument.futures_symbol)
            if context is None:
                continue
            analysis = build_flashalpha_futures_analysis(context)
            analysis.update({
                "ftmo_symbol": instrument.ftmo_symbol,
                "underlying_market": instrument.underlying_market,
                "futures_symbol": instrument.futures_symbol,
                "micro_futures_symbol": instrument.micro_futures_symbol,
                "asset_class": FTMOAssetClass.FUTURES_LINKED.value,
            })
            candidates.append((instrument, analysis))
        candidates.sort(key=lambda item: (-abs(int(item[1].get("score") or 0)), item[0].ftmo_symbol))
        deep_limit = max(1, min(20, int(self.environment.get("MONATISE_FTMO_FUTURES_DEEP_ANALYSIS_LIMIT", "10"))))
        published = suppressed = 0
        for instrument, analysis in candidates[:deep_limit]:
            if not publication_allowed(analysis):
                suppressed += 1
                continue
            alert_state = _setup_alert_state(analysis)
            cooldown_key = f"{namespace}:ftmo:futures-alert:{instrument.ftmo_symbol}"
            previous_state = await self.redis.get(cooldown_key)
            if previous_state and not _setup_materially_changed(previous_state, alert_state):
                suppressed += 1
                continue
            await self.redis.set(cooldown_key, json.dumps(alert_state, separators=(",", ":"), sort_keys=True), ex=cooldown_seconds)
            try:
                notifier = getattr(self.telegram, "ftmo_futures_notification", self.telegram.stock_analysis_notification)
                message = TelegramNotifier.format_ftmo_futures_setup(analysis)
                await notifier(message)
                await self._publish_ftmo_signal_proposal(analysis, source="monatise.futures.scanner")
                published += 1
            except Exception as exc:
                failures.append({"symbol": instrument.ftmo_symbol, "error_type": type(exc).__name__})
                if previous_state:
                    await self.redis.set(cooldown_key, previous_state, ex=cooldown_seconds)
                else:
                    await self.redis.delete(cooldown_key)
        return {
            "universe_size": len(instruments), "provider_roots": len(unique_roots), "provider_contexts": len(contexts),
            "ranked_candidates": len(candidates), "deep_analysis_attempted": min(len(candidates), deep_limit),
            "telegram_published": published, "suppressed": suppressed, "failures": failures, "execution_enabled": False,
        }

    async def _publish_ftmo_signal_proposal(self, analysis: Mapping[str, Any], *, source: str) -> bool:
        """Publish a second, FTMO-native preview when the bridge can price it."""
        if self.ftmo_master is None or self.telegram is None:
            return False
        direction = str(analysis.get("direction") or "")
        symbol = str(analysis.get("ftmo_symbol") or analysis.get("asset") or "")
        entry, stop, target = analysis.get("entry"), analysis.get("stop_loss"), analysis.get("target")
        if not symbol or direction.casefold() not in {"long", "short", "buy", "sell"} or any(value is None for value in (entry, stop, target)):
            return False
        signal_id = str(
            analysis.get("publication_id") or analysis.get("setup_id") or analysis.get("valid_until")
            or hashlib.sha256(json.dumps({
                "symbol": symbol, "direction": direction, "entry": entry, "stop": stop, "target": target, "source": source,
            }, sort_keys=True, default=str).encode()).hexdigest()
        )
        asset_class = str(analysis.get("asset_class") or "").casefold()
        provider = "coinglass" if asset_class == FTMOAssetClass.CRYPTO.value or "crypto" in source.casefold() else str(analysis.get("analysis_provider") or source)
        provider_instrument = str(
            analysis.get("analysis_instrument") or analysis.get("coinglass_instrument")
            or (f"{analysis.get('asset')}USDT" if provider == "coinglass" and analysis.get("asset") else symbol)
        )
        analysis_state = str(analysis.get("analysis_state") or ("LONG" if direction.casefold() in {"long", "buy"} else "SHORT"))
        confirmation_status = str(analysis.get("setup_status") or analysis.get("entry_confirmation_status") or analysis.get("confirmation_status") or "")

        def timestamp(value: Any) -> datetime | None:
            if isinstance(value, datetime):
                return value
            if isinstance(value, str) and value.strip():
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    return None
            return None

        evidence = {key: analysis.get(key) for key in (
            "market_regime", "liquidity", "liquidity_sweep", "market_structure", "supply_demand",
            "fibonacci", "order_flow", "trigger", "open_interest", "funding_rate", "liquidations",
            "cvd", "long_short_ratio", "provider_observed_at",
        ) if analysis.get(key) is not None}
        try:
            proposal = await self.ftmo_master.create_signal_proposal(
                signal_id=signal_id, symbol=symbol, direction=direction,
                analysis_entry=entry, analysis_stop=stop, analysis_target=target, source=source,
                analysis_state=analysis_state, confirmation_status=confirmation_status,
                analysis_id=str(analysis.get("analysis_id") or analysis.get("run_id") or signal_id),
                analysis_provider=provider,
                analysis_instrument=provider_instrument,
                analysis_exchange=str(analysis.get("analysis_exchange") or analysis.get("exchange") or ""),
                analysis_observed_at=timestamp(analysis.get("analysis_observed_at") or analysis.get("observed_at")),
                signal_expires_at=timestamp(analysis.get("valid_until") or analysis.get("expires_at")),
                entry_zone_low=analysis.get("entry_zone_low"), entry_zone_high=analysis.get("entry_zone_high"),
                order_type=str(analysis.get("order_type") or "market"),
                strategy=str(analysis.get("strategy") or analysis.get("setup_type") or "Monatise confirmed setup"),
                timeframe=str(analysis.get("timeframe") or analysis.get("interval") or "unknown"),
                conviction=analysis.get("conviction") or analysis.get("score"),
                evidence_bundle=evidence,
                supersedes_signal_id=str(analysis.get("supersedes_signal_id") or "") or None,
            )
            publish = getattr(self.telegram, "trade_proposal", None)
            if publish is None:
                await self.telegram.command_response(format_proposal(proposal))
            else:
                await publish(format_proposal(proposal), proposal["proposal_id"])
            return True
        except FTMOMasterError as exc:
            LOGGER.info("FTMO-native scanner proposal withheld", extra={"symbol": symbol, "reason": str(exc)})
            return False

    async def _publish_ftmo_signal_from_message(self, message: str, *, source: str) -> bool:
        fields = {}
        for label in ("FTMO Symbol", "Direction"):
            match = re.search(rf"^{re.escape(label)}:\s*([^|\n]+)", message, re.MULTILINE)
            if match:
                fields[label] = match.group(1).strip()
        levels = re.search(r"^Entry\s+([0-9.eE+-]+)\s*\|\s*Stop\s+([0-9.eE+-]+)\s*\|\s*Target\s+([0-9.eE+-]+)", message, re.MULTILINE)
        publication = re.search(r"Publication\s+([A-Za-z0-9_-]+)", message)
        if not levels or "FTMO Symbol" not in fields or "Direction" not in fields:
            return False
        return await self._publish_ftmo_signal_proposal({
            "publication_id": publication.group(1) if publication else None,
            "ftmo_symbol": fields["FTMO Symbol"],
            "direction": fields["Direction"].split()[0],
            "analysis_state": fields["Direction"].split()[0].upper(),
            "confirmation_status": "confirmed",
            "entry": levels.group(1), "stop_loss": levels.group(2), "target": levels.group(3),
        }, source=source)

    @staticmethod
    def _price_change_24h(row: Mapping[str, Any]) -> float | None:
        for key in ("price_change_percent_24h", "price_change_24h", "change_24h", "price_change_percent"):
            try:
                if row.get(key) is not None:
                    return float(row[key])
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _format_x_macro_post(post: XMacroPost) -> str:
        category = "BTC WHALE-SALE WATCH" if post.category == "btc_whale_sale" else "MACRO WATCH"
        text = post.text if len(post.text) <= 500 else post.text[:497] + "..."
        return "\n".join((
            f"{category} · {post.severity.upper()}",
            text,
            f"Observed: {format_nigeria_time(post.created_at)}",
            f"Source: {post.url}",
            "Status: context only — CoinGlass/price confirmation required before any SELL signal",
        ))

    async def start(self) -> None:
        startup_phase = "configuration"
        LOGGER.info("validating paper-only orchestration configuration")
        self.safety = PaperSafetyConfiguration.from_environment(self.environment)
        self.dependencies["configuration"] = {"status": "ok", "frozen": True}
        startup_phase = "ftmo_execution_configuration"
        self.ftmo_execution_configuration = FTMOExecutionConfiguration.from_environment(self.environment)
        self.ftmo_master_configuration = FTMOMasterConfiguration.from_environment(self.environment)
        self.dependencies["ftmo_execution"] = {
            "status": "ok",
            "platform": self.ftmo_execution_configuration.platform.value if self.ftmo_execution_configuration.platform else None,
            "account_identity_configured": self.ftmo_execution_configuration.connected_identity_configured,
            "account_environment": self.ftmo_execution_configuration.account_environment.value,
            "mode": self.ftmo_execution_configuration.mode.value,
            "execution_enabled": self.ftmo_execution_configuration.order_submission_allowed,
            "price_authority": "ftmo_platform_required",
            "master_control": self.ftmo_master_configuration.public_status(),
        }
        database_url = self.environment.get("MONATISE_DATABASE_URL") or self.environment.get("DATABASE_URL")
        redis_url = self.environment.get("MONATISE_REDIS_URL") or self.environment.get("REDIS_URL")
        deployment_environment = self.environment.get("MONATISE_ENVIRONMENT", "production").strip().casefold()
        try:
            startup_phase = "postgresql_configuration"
            if not database_url:
                raise RuntimeError("PostgreSQL configuration is unavailable")
            startup_phase = "redis_configuration"
            if not redis_url or (deployment_environment != "test" and ("localhost" in redis_url or "127.0.0.1" in redis_url)):
                raise RuntimeError("network-accessible Redis configuration is unavailable")
        except Exception as exc:
            self._record_startup_failure(startup_phase, exc)
            raise
        try:
            from psycopg_pool import AsyncConnectionPool
            from redis.asyncio import Redis
            startup_phase = "postgresql_connection"
            LOGGER.info("opening managed PostgreSQL pool")
            started = perf_counter()
            self.postgres_pool = AsyncConnectionPool(database_url, min_size=1, max_size=4, open=False, kwargs={"autocommit": True})
            await self.postgres_pool.open(wait=True, timeout=15)
            async with self.postgres_pool.connection(timeout=10) as migration_connection:
                await migration_connection.execute("SELECT 1")
                self.dependencies["postgresql"] = {"status": "ok", "latency_ms": round((perf_counter() - started) * 1000, 2)}
                startup_phase = "database_migrations"
                self.migrations = MigrationRunner(migration_connection, self.migration_directory)
                await self.migrations.run()
            # Never pin one database connection for the service lifetime. A
            # checked-out connection can go stale after network/DB idle limits
            # and also serializes every concurrent hierarchy job. Borrowing
            # from the managed pool per operation lets psycopg replace broken
            # connections and gives parallel scanner work independent leases.
            self.postgres = _PooledPostgresConnection(self.postgres_pool)
            self.dependencies["migrations"] = {"status": "ok", "version": self.migrations.version}
            started = perf_counter()
            startup_phase = "redis_connection"
            LOGGER.info("opening managed Redis connection")
            self.redis = Redis.from_url(redis_url, decode_responses=True)
            if not await self.redis.ping():
                raise RuntimeError("Redis ping failed")
            self.dependencies["redis"] = {
                "status": "ok",
                "latency_ms": round((perf_counter() - started) * 1000, 2),
                "capabilities": ["scheduler_lock", "event_deduplication", "replay_nonce", "coinglass_cache", "ttl"],
            }
            startup_phase = "application_composition"
            store = PostgresDocumentStore(self.postgres)
            self.document_store = store
            self.ftmo_master = FTMOMasterControlService(
                self.ftmo_master_configuration,
                FTMOMasterRepository(store),
            )
            infrastructure = create_durable_infrastructure(store)
            self.coinglass = register_coinglass_provider(
                infrastructure.container,
                self.environment,
                timeout_seconds=max(2.0, float(self.environment.get("MONATISE_COINGLASS_TIMEOUT_SECONDS", "8"))),
                maximum_attempts=max(1, int(self.environment.get("MONATISE_COINGLASS_MAXIMUM_ATTEMPTS", "1"))),
                cache_ttl_seconds=max(30.0, float(self.environment.get("MONATISE_COINGLASS_CACHE_TTL_SECONDS", "300"))),
            )
            # Public Backpack endpoints provide an independent candle/price
            # fallback. Empty credentials make this adapter incapable of
            # authenticated account access, while its execution methods remain
            # hard-disabled by implementation.
            self.backpack = BackpackAdapter(
                RuntimeConfig(mode="paper", network="testnet", execution_mode="disabled"),
                credentials=BackpackCredentials(api_key="", secret_key=""),
            )
            self.application = create_application(
                market_data_providers=self.market_data_providers(),
                derivatives_provider=self.coinglass,
                infrastructure=infrastructure,
                engine_order=PRODUCTION_ENGINE_ORDER,
            )
            telegram_token = self.environment.get("MONATISE_TELEGRAM_BOT_TOKEN", "")
            telegram_chat = self.environment.get("MONATISE_TELEGRAM_CHAT_ID", "")
            telegram_notifications_enabled = _true(self.environment.get("MONATISE_TELEGRAM_NOTIFICATIONS_ENABLED", "false"))
            if not telegram_notifications_enabled:
                self.environment = {
                    **self.environment,
                    "MONATISE_HIERARCHICAL_TELEGRAM_PUBLISH_ENABLED": "false",
                    "MONATISE_X_MONITOR_ENABLED": "false",
                    "MONATISE_FTMO_CRYPTO_SCAN_ENABLED": "false",
                    "MONATISE_FTMO_STOCK_SCAN_ENABLED": "false",
                    "MONATISE_FTMO_FUTURES_SCAN_ENABLED": "false",
                }
            if telegram_transport_enabled(self.environment) and telegram_token and telegram_chat:
                secrets = EnvironmentSecretBoundary(self.environment)
                self.telegram = TelegramNotifier(TelegramNotificationTransport(lambda: secrets.get("MONATISE_TELEGRAM_BOT_TOKEN")), telegram_chat)
            x_token = self.environment.get("MONATISE_X_BEARER_TOKEN", "")
            if x_token:
                secrets = EnvironmentSecretBoundary(self.environment)
                self.x_macro = XMacroAdapter(lambda: secrets.get("MONATISE_X_BEARER_TOKEN"))
            startup_phase = "scheduler_registration"
            scheduled_jobs = await self._register_scheduled_analysis()
            await self._register_hierarchy_shadow(store)
            await self._register_x_macro_monitor()
            await self._register_ftmo_crypto_scanner()
            await self._register_ftmo_stock_scanner()
            await self._register_ftmo_futures_scanner()
            await self._register_decision_snapshot_retention()
            await self._register_tradingview_alert_retention()
            await self._register_ftmo_master_retention()
            self.leadership = RedisSchedulerLeadership(
                self.redis, namespace=self.environment.get("MONATISE_REDIS_NAMESPACE", "monatise:production-analysis")
            )
            self.redis_coordination = RedisCoordinationStore(
                self.redis,
                namespace=self.environment.get("MONATISE_REDIS_NAMESPACE", "monatise:production-analysis"),
                telegram_dlq_max_length=int(self.environment.get("MONATISE_TELEGRAM_DLQ_MAX_LENGTH", "1000")),
            )
            startup_phase = "scheduler_leadership"
            leader = await self.leadership.acquire_or_wait(
                infrastructure.scheduler.start,
                infrastructure.scheduler.stop,
            )
            startup_phase = "plugin_startup"
            await infrastructure.plugins.start_all()
            if leader:
                await infrastructure.scheduler.start()
            startup_phase = "health_checks"
            await infrastructure.observability.run_health_checks()
            for name in ("event_bus", "state_manager", "audit_repository", "scheduler", "pipeline_orchestrator"):
                self.dependencies[name] = {"status": "ok"}
            self.dependencies["scheduler"]["leader"] = leader
            self.dependencies["scheduler"]["scheduled_analysis"] = {
                "enabled": bool(scheduled_jobs),
                "jobs": list(scheduled_jobs),
                "execution_enabled": False,
            }
            self.dependencies["engine_registry"] = {
                "status": "ok",
                "count": len(self.application.registry.ordered()),
                "order": [item.name for item in self.application.registry.ordered()],
            }
            self.dependencies["governance"] = {"status": "ok", "kill_switch": True}
            configured = bool(self.environment.get("COINGLASS_API_KEY", "").strip())
            coinglass_required = deployment_environment != "test"
            self.dependencies["coinglass"] = {
                "status": "ok" if configured or not coinglass_required else "error",
                "configured": configured,
                "required": coinglass_required,
                "latest_request": "not_yet_requested",
            }
            self.dependencies["market_data"] = {
                "status": "ok",
                "providers": list(self.market_data_providers()),
                "fallback_enabled": self.backpack is not None,
                "execution_enabled": False,
            }
            self.dependencies["notifications"] = {
                "status": "ok",
                "telegram": "disabled" if not telegram_notifications_enabled else ("configured_notification_only" if self.telegram is not None else "unavailable_optional"),
                "openclaw": "configured_analysis_only" if self.environment.get("MONATISE_OPENCLAW_TOKEN") else "unavailable_optional",
                "x_macro": "configured_read_only" if self.x_macro is not None else "unavailable_optional",
                "ftmo_scanners": "configured_notification_only",
            }
            self.dependencies["audit_logging"] = {"status": "ok", "enabled": True}
            startup_phase = "audit_integrity"
            audit_errors = await infrastructure.audit.verify_integrity()
            self.dependencies["audit_integrity"] = {
                "status": "ok" if not audit_errors else "error",
                "verification": "verified_recent_window" if not audit_errors else "failed",
                "startup_window": getattr(infrastructure.audit, "startup_window", None),
                "error_count": len(audit_errors),
            }
        except Exception as exc:
            self._record_startup_failure(startup_phase, exc)
            try:
                await self.shutdown()
            except Exception:
                LOGGER.exception("orchestration startup cleanup failed", extra={"startup_phase": startup_phase})
            raise

    def _record_startup_failure(self, phase: str, exc: Exception) -> None:
        self.dependencies["startup"] = {
            "status": "error",
            "phase": phase,
            "error_type": type(exc).__name__,
        }
        LOGGER.exception(
            "orchestration startup failed during %s",
            phase,
            extra={"startup_phase": phase, "error_type": type(exc).__name__},
        )

    async def shutdown(self) -> None:
        if self.application is not None:
            if self.leadership and self.leadership.is_leader:
                await self.application.infrastructure.scheduler.stop()
            await self.application.infrastructure.plugins.stop_all()
            await self.application.infrastructure.observability.export()
        if self.leadership:
            await self.leadership.release()
        if self.redis is not None:
            await self.redis.aclose()
        if self.postgres_pool is not None:
            await self.postgres_pool.close()
        elif self.postgres is not None:
            await self.postgres.close()

    def readiness(self) -> tuple[bool, dict[str, Any]]:
        if self.leadership is not None and "scheduler" in self.dependencies:
            self.dependencies["scheduler"]["leader"] = self.leadership.is_leader
        if self.coinglass is not None:
            health = self.coinglass.health()
            coinglass_dependency = self.dependencies.setdefault("coinglass", {})
            unavailable = health.consecutive_failures >= 3
            coinglass_dependency["latest_request"] = (
                "healthy" if health.healthy else ("failed" if unavailable else ("degraded" if health.consecutive_failures else "not_yet_requested"))
            )
            coinglass_dependency["status"] = "error" if unavailable else "ok"
            coinglass_dependency["consecutive_failures"] = health.consecutive_failures
            market_dependency = self.dependencies.setdefault("market_data", {})
            fallback_available = self.backpack is not None
            market_dependency.update({
                "status": "ok" if fallback_available or not unavailable else "error",
                "providers": list(self.market_data_providers()),
                "fallback_enabled": fallback_available,
                "execution_enabled": False,
            })
        registry_ok = bool(self.application and tuple(item.name for item in self.application.registry.ordered()) == PRODUCTION_ENGINE_ORDER)
        mandatory = (
            "configuration", "postgresql", "migrations", "redis", "event_bus", "state_manager",
            "audit_repository", "audit_integrity", "audit_logging", "scheduler", "engine_registry", "pipeline_orchestrator", "governance", "notifications", "coinglass", "market_data", "hierarchy_shadow",
        )
        mandatory_ok = all(self.dependencies.get(key, {}).get("status") == "ok" for key in mandatory)
        ready = registry_ok and self.safety is not None and mandatory_ok
        return ready, {
            "status": "ready" if ready else "not_ready",
            "execution_enabled": False,
            "mode": "paper",
            "dependencies": self.dependencies,
        }

    async def analyse(self, symbol: str, correlation_id: str | None = None, *, interval: str = "1h", source: str = "monatise.production", notify: bool = True, notification_policy: str = "every_analysis") -> dict[str, Any]:
        if self.application is None:
            raise RuntimeError("orchestration runtime is unavailable")
        normalized = symbol.strip().upper()
        verified_dynamic = normalized not in SUPPORTED_PRODUCTION_SYMBOLS
        if verified_dynamic:
            if self.coinglass is None:
                raise RuntimeError("verified CoinGlass symbol resolution is unavailable")
            asset = await asyncio.to_thread(self.coinglass.resolve_futures_asset, normalized)
            normalized = asset.base_asset
        result = await self.application.orchestrator.run(build_production_analysis_run(normalized, interval=interval, correlation_id=correlation_id, source=source, verified_dynamic=verified_dynamic))
        should_notify = notify and self.telegram is not None
        notification_state = None
        if should_notify and notification_policy == "qualified_changes":
            notification_state = await self._telegram_notification_candidate(result, interval)
            should_notify = notification_state is not None and await self._reserve_telegram_notification(result.symbol, interval, notification_state)
            if notification_state is not None:
                LOGGER.info(
                    "Telegram notification transition selected",
                    extra={
                        "symbol": result.symbol,
                        "interval": interval,
                        "run_id": result.run_id,
                        "source": source,
                        "classification": notification_state.get("classification"),
                        "confirmation_status": notification_state.get("confirmation_status"),
                        "cancellation_reason": notification_state.get("cancellation_reason"),
                        "reserved": should_notify,
                    },
                )
        if should_notify:
            try:
                cancellation_reason = (notification_state or {}).get("cancellation_reason")
                if (notification_state or {}).get("replaces_confirmed_grid"):
                    message_id = await self.telegram.deliver_grid_replacement(result)
                elif (notification_state or {}).get("expires_directional_setup"):
                    message_id = await self.telegram.deliver_setup_expiry(result, notification_state["expired_at"])
                elif cancellation_reason:
                    message_id = await self.telegram.deliver_grid_cancellation(result, cancellation_reason)
                else:
                    message_id = await self.telegram.deliver(result)
                if notification_state is not None:
                    await self._finish_telegram_notification(result.symbol, interval, notification_state, "delivered", message_id=message_id)
            except Exception as exc:
                if notification_state is not None:
                    await self._finish_telegram_notification(result.symbol, interval, notification_state, "failed", error_type=type(exc).__name__)
                await self.application.infrastructure.audit.append(
                    record_type=AuditRecordType.SYSTEM,
                    action=AuditAction.FAILED,
                    actor=AuditActor("monatise-notifier", "application"),
                    source="monatise.telegram",
                    payload={"event": "notification_delivery_failed", "error_type": type(exc).__name__, "run_id": result.run_id},
                    correlation_id=result.correlation_id,
                    symbol=result.symbol,
                )
                LOGGER.warning("Telegram notification delivery failed", extra={"error_type": type(exc).__name__, "run_id": result.run_id})
        # Browser refreshes are read-only and can be frequent. Scheduled
        # production runs already capture the durable replay snapshot; making
        # the dashboard wait for the same large insert adds latency without
        # changing the analysis result.
        if self.postgres is not None and source != "monatise.web":
            try:
                # After notification delivery, bounded by a timeout: this is
                # pure telemetry for a future backtest and must never delay
                # (not just never crash) time-sensitive signal delivery.
                await asyncio.wait_for(
                    self._record_decision_snapshot(result, interval=interval, source=source),
                    timeout=DECISION_SNAPSHOT_WRITE_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                LOGGER.warning("decision snapshot recording failed", extra={"error_type": type(exc).__name__, "run_id": result.run_id})
        return sanitized_result(result)

    async def _record_decision_snapshot(self, result: Any, *, interval: str, source: str) -> None:
        """Persist everything the decision engine saw and decided this cycle.

        Point-in-time historical store for a future full-pipeline walk-forward
        replay: CoinGlass's derivatives endpoints (funding/OI/CVD/liquidations/
        order book) only expose a recent window ending now, not an "as of
        timestamp T in the past" query -- so today's live inputs are the only
        chance to capture what order_flow and the rest of the pipeline actually
        saw at this moment. Every stage's output is included, not just the
        final decision, since a future replay needs the intermediate evidence
        too, not just the conclusion. Written to its own table (see
        deploy/migrations/002_decision_snapshots.sql), not the audit-critical
        monatise_application_streams, so it can be pruned on a retention
        schedule without touching that table's immutability guarantee.
        """
        outputs: dict[str, Any] = {}
        for name, value in result.context.outputs.items():
            serialized = _json_value(value)
            if name == "decision" and isinstance(serialized, dict) and str(serialized.get("classification", "")).casefold() in {"grid", "two_sided"}:
                serialized["classification"] = "no_trade"
                serialized["direction"] = "none"
                metadata = serialized.get("metadata")
                if isinstance(metadata, dict):
                    metadata.pop("grid_signal_score", None)
                    metadata.pop("grid_plan", None)
            if name == "market_data" and isinstance(serialized, dict):
                # Candles are the bulk of this payload and are the one input
                # CoinGlass CAN answer historically later (unlike derivatives),
                # so a compact reference is enough to re-fetch the exact
                # window on replay instead of duplicating it every cycle.
                serialized["candles"] = _compact_candle_reference(getattr(value, "candles", ()) or ())
            outputs[name] = serialized

        decision_output = result.context.outputs.get("decision")
        classification = getattr(getattr(decision_output, "classification", None), "value", None)
        if classification in {"grid", "two_sided"}:
            classification = "no_trade"

        snapshot = {
            "schema_version": DECISION_SNAPSHOT_SCHEMA_VERSION,
            "run_id": result.run_id,
            "correlation_id": result.correlation_id,
            "symbol": result.symbol,
            "interval": interval,
            "source": source,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "code_version": self.environment.get("RENDER_GIT_COMMIT") or self.environment.get("MONATISE_GIT_COMMIT", ""),
            "status": result.status.value,
            "blocked_by": result.blocked_by,
            "outputs": outputs,
        }
        await self.postgres.execute(
            "INSERT INTO monatise_decision_snapshots (symbol, interval, classification, schema_version, payload) VALUES (%s,%s,%s,%s,%s::jsonb)",
            (result.symbol, interval, classification, DECISION_SNAPSHOT_SCHEMA_VERSION, json.dumps(snapshot, separators=(",", ":"), sort_keys=True)),
        )

    async def _register_decision_snapshot_retention(self) -> str | None:
        if self.application is None or self.postgres is None:
            return None
        job_id = "decision-snapshot-retention"

        async def task() -> dict[str, Any]:
            result = await self.postgres.execute(
                "DELETE FROM monatise_decision_snapshots WHERE created_at < NOW() - make_interval(days => %s)",
                (DECISION_SNAPSHOT_RETENTION_DAYS,),
            )
            deleted = getattr(result, "rowcount", None)
            LOGGER.info("decision snapshot retention swept", extra={"deleted": deleted, "retention_days": DECISION_SNAPSHOT_RETENTION_DAYS})
            return {"deleted": deleted}

        await self.application.infrastructure.scheduler.register(JobDefinition(
            job_id=job_id,
            name="Decision snapshot retention",
            task=task,
            schedule_type=ScheduleType.INTERVAL,
            interval=timedelta(hours=24),
            timeout_seconds=120.0,
            retry_policy=RetryPolicy(maximum_attempts=2, delay_seconds=30.0, maximum_delay_seconds=120.0),
            tags=("maintenance", "retention", "decision-snapshots"),
            metadata={"retention_days": DECISION_SNAPSHOT_RETENTION_DAYS},
        ))
        return job_id

    async def record_tradingview_alert(self, raw_payload: dict | str, *, fingerprint: str) -> dict[str, Any]:
        """Normalize, validate, and durably store one TradingView webhook alert.

        Read-only, analysis-input storage -- this never places an order or
        mutates execution state; nothing here can leave paper/analysis-only
        mode. Raises ValueError for a malformed/unsupported alert (caller
        maps that to 422) and TradingViewAlertDuplicate for an exact-repeat
        delivery (caller maps that to 409) -- both fail closed rather than
        storing bad or duplicate data.
        """
        if self.postgres is None:
            raise RuntimeError("tradingview alert storage is not configured")
        alert = normalize_tradingview_alert(raw_payload)
        cursor = await self.postgres.execute(
            "INSERT INTO monatise_tradingview_alerts (fingerprint, symbol, payload) VALUES (%s,%s,%s::jsonb) "
            "ON CONFLICT (fingerprint) DO NOTHING",
            (fingerprint, alert["symbol"], json.dumps(alert, separators=(",", ":"), sort_keys=True)),
        )
        if getattr(cursor, "rowcount", 0) == 0:
            raise TradingViewAlertDuplicate(fingerprint)
        if self.application is not None:
            try:
                await self.application.infrastructure.audit.append(
                    record_type=AuditRecordType.INTEGRATION,
                    action=AuditAction.CREATED,
                    actor=AuditActor("tradingview-webhook", "external_system"),
                    source="monatise.tradingview",
                    payload={"event": "tradingview_alert_received", "symbol": alert["symbol"], "action": alert["action"], "fingerprint": fingerprint},
                    symbol=alert["symbol"],
                )
            except Exception as exc:
                # The alert is already durable at this point. Do not tell the
                # sender delivery failed and provoke a retry that can only be
                # rejected as a duplicate.
                LOGGER.exception("tradingview receipt audit append failed", extra={"error_type": type(exc).__name__})
        return alert

    async def recent_tradingview_alerts(self, *, symbol: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Read-only fetch of alerts still inside the TRADINGVIEW_FRESH_SECONDS
        window -- an alert older than that has explicitly expired and is
        excluded here rather than left for the caller to filter out."""
        if self.postgres is None:
            return []
        query = "SELECT payload FROM monatise_tradingview_alerts WHERE received_at > NOW() - make_interval(secs => %s)"
        params: list[Any] = [TRADINGVIEW_FRESH_SECONDS]
        if symbol:
            query += " AND symbol = %s"
            params.append(symbol)
        query += " ORDER BY received_at DESC LIMIT %s"
        params.append(max(1, min(TRADINGVIEW_ALERT_LIMIT, limit)))
        cursor = await self.postgres.execute(query, tuple(params))
        rows = await cursor.fetchall()
        alerts = []
        for row in rows:
            raw = row[0]
            payload = raw if isinstance(raw, dict) else json.loads(raw)
            alerts.append(enrich_tradingview_alert(payload))
        return alerts

    async def _register_tradingview_alert_retention(self) -> str | None:
        if self.application is None or self.postgres is None:
            return None
        job_id = "tradingview-alert-retention"

        async def task() -> dict[str, Any]:
            result = await self.postgres.execute(
                "DELETE FROM monatise_tradingview_alerts WHERE received_at < NOW() - make_interval(days => %s)",
                (TRADINGVIEW_ALERT_RETENTION_DAYS,),
            )
            deleted = getattr(result, "rowcount", None)
            LOGGER.info("tradingview alert retention swept", extra={"deleted": deleted, "retention_days": TRADINGVIEW_ALERT_RETENTION_DAYS})
            return {"deleted": deleted}

        await self.application.infrastructure.scheduler.register(JobDefinition(
            job_id=job_id,
            name="TradingView alert retention",
            task=task,
            schedule_type=ScheduleType.INTERVAL,
            interval=timedelta(hours=24),
            timeout_seconds=120.0,
            retry_policy=RetryPolicy(maximum_attempts=2, delay_seconds=30.0, maximum_delay_seconds=120.0),
            tags=("maintenance", "retention", "tradingview-alerts"),
            metadata={"retention_days": TRADINGVIEW_ALERT_RETENTION_DAYS},
        ))
        return job_id

    async def analyse_dynamic_coinglass(self, symbol: str, *, interval: str = "1h", source: str = "monatise.openclaw.dynamic") -> dict[str, Any]:
        """Resolve and analyze one CoinGlass futures asset without notifications or execution."""
        if self.application is None or self.coinglass is None:
            raise RuntimeError("dynamic CoinGlass analysis is unavailable")
        asset = await asyncio.to_thread(self.coinglass.resolve_futures_asset, symbol)
        result = await self.application.orchestrator.run(
            build_production_analysis_run(asset.base_asset, interval=interval, source=source, verified_dynamic=True)
        )
        return finalize_dynamic_analysis(sanitized_result(result), result, asset)

    async def analyse_stock(self, symbol: str) -> dict[str, Any]:
        """Fetch and build one Quiver-backed stock analysis without notifications
        or execution -- shared by the on-demand OpenClaw endpoint and the
        autonomous stock scan job, so there is one source of this logic."""
        alpaca = AlpacaMarketDataAdapter.from_env()
        normalized = normalize_quiver_symbol(symbol)
        quiver_task = asyncio.to_thread(QuiverAdapter.from_env().context, normalized)
        bars_task = asyncio.to_thread(alpaca.stock_bars, symbol, "1Hour")
        trigger_bars_task = asyncio.to_thread(alpaca.stock_bars, symbol, "15Min")
        snapshot_task = asyncio.to_thread(alpaca.stock_snapshot, symbol)

        def finnhub_context() -> dict[str, Any]:
            try:
                return FinnhubAdapter.from_env().context(symbol)
            except FinnhubAdapterError:
                return {"source": "Finnhub", "unavailable": True}

        def flashalpha_context() -> dict[str, Any]:
            try:
                return FlashAlphaAdapter.from_env().context(normalized)
            except FlashAlphaAdapterError:
                return {"source": "FlashAlpha", "unavailable": True}

        context, bars, trigger_bars, snapshot, finnhub, flashalpha = await asyncio.gather(
            quiver_task, bars_task, trigger_bars_task, snapshot_task, asyncio.to_thread(finnhub_context), asyncio.to_thread(flashalpha_context)
        )
        validity_minutes = max(15, int(self.environment.get("MONATISE_STOCK_15M_VALIDITY_MINUTES", "60")))
        return build_stock_analysis(context, bars=bars, trigger_bars=trigger_bars, snapshot=snapshot, finnhub=finnhub, flashalpha=flashalpha, validity_minutes=validity_minutes)

    async def _telegram_notification_candidate(self, result: Any, interval: str) -> dict[str, Any] | None:
        outputs = result.context.outputs
        key = (result.symbol, interval)
        previous = await self._telegram_notification_state(key)
        if (previous or {}).get("classification") == "grid":
            # Retire legacy grid state silently. Grid/two-sided analysis is no
            # longer a valid notification or cancellation outcome.
            previous = {"version": int((previous or {}).get("version", 0) or 0)}
        expired_grid = self._expired_grid_candidate(previous)
        if expired_grid is not None:
            return expired_grid
        expired_directional = self._expired_directional_candidate(previous)
        if expired_directional is not None:
            return expired_directional
        previous_confirmed_grid = (
            (previous or {}).get("classification") == "grid"
            and (previous or {}).get("confirmation_status") == "confirmed"
            and (previous or {}).get("delivery_status") in {None, "delivered"}
        )
        decision = outputs.get("decision")
        if decision is None:
            return self._grid_cancellation_candidate(previous, previous_confirmed_grid, "analysis no longer produced a decision")
        metadata = getattr(decision, "metadata", {}) or {}
        classification = getattr(getattr(decision, "classification", None), "value", "no_trade")
        direction = getattr(getattr(decision, "direction", None), "value", "none")
        if classification == "grid" or direction == "two_sided":
            return None
        threshold = int(metadata.get("minimum_signal_score", 7) or 7)
        signed_score = int(metadata.get("signed_signal_score", 0) or 0)
        score = abs(signed_score)
        direction_is_qualified = (
            (direction == "long" and signed_score >= threshold)
            or (direction == "short" and signed_score <= -threshold)
        )
        # A confirmed grid must survive ordinary score noise. A single NO_TRADE
        # recalculation or a one-point score dip is not structural invalidation.
        # Directional replacements are handled below, while terminal price-action
        # states remain immediate cancellation events.
        cancellation_threshold = max(0, threshold - 2)
        if previous_confirmed_grid and classification == "no_trade":
            return None
        if score < threshold or not direction_is_qualified:
            if previous_confirmed_grid and classification == "grid" and score > cancellation_threshold:
                return None
            if classification == "no_trade":
                reason = "analysis changed to NO_TRADE"
            elif score < threshold:
                reason = f"signal score {score}/10 fell below the {threshold}/10 threshold"
            else:
                reason = "signal direction no longer qualifies"
            return self._grid_cancellation_candidate(previous, previous_confirmed_grid, reason)
        if result.status.value != "completed":
            return self._grid_cancellation_candidate(previous, previous_confirmed_grid, f"analysis status changed to {result.status.value}")
        market = outputs.get("market_data")
        price_action = outputs.get("price_action")
        confirmation_status = getattr(getattr(price_action, "status", None), "value", "pending")
        terminal_grid_statuses = {"conflict", "expired", "invalidated"}
        if classification == "grid":
            if confirmation_status == "pending":
                return None
            if confirmation_status in terminal_grid_statuses:
                if previous_confirmed_grid:
                    return self._grid_cancellation_candidate(
                        previous,
                        previous_confirmed_grid,
                        f"price-action confirmation became {confirmation_status}",
                    )
                return None
            if confirmation_status not in {"confirmed", *terminal_grid_statuses}:
                return None
        elif previous_confirmed_grid:
            replacement = self._directional_material(classification, direction, score, market, price_action)
            fingerprint = hashlib.sha256(json.dumps(replacement, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            return self._with_setup_validity({
                "fingerprint": fingerprint,
                "confirmation_status": "replaced",
                "classification": classification,
                "replaces_confirmed_grid": True,
                "expected_version": int((previous or {}).get("version", 0) or 0),
            }, result, market, interval)
        material = {
            "classification": classification,
            "direction": direction,
            "confirmation_status": confirmation_status,
            "confirmation_pattern": getattr(price_action, "strongest_confirming_pattern", None),
        }
        if classification == "grid" and confirmation_status == "confirmed":
            material["confirmation_signal"] = self._grid_confirmation_signal_id(market, price_action)
        elif classification != "grid":
            material.update(self._directional_material(classification, direction, score, market, price_action))
        fingerprint = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if (previous or {}).get("fingerprint") == fingerprint:
            return None
        candidate = {
            "fingerprint": fingerprint,
            "confirmation_status": confirmation_status,
            "classification": classification,
            "expected_version": int((previous or {}).get("version", 0) or 0),
        }
        return self._with_setup_validity(candidate, result, market, interval)

    @staticmethod
    def _expired_grid_candidate(previous: dict[str, Any] | None) -> dict[str, Any] | None:
        if (
            not previous
            or previous.get("classification") != "grid"
            or previous.get("confirmation_status") != "confirmed"
            or previous.get("delivery_status") != "delivered"
            or not previous.get("expires_at")
        ):
            return None
        try:
            expires_at = datetime.fromisoformat(str(previous["expires_at"]).replace("Z", "+00:00"))
        except ValueError:
            return None
        if expires_at.tzinfo is None or datetime.now(timezone.utc) < expires_at.astimezone(timezone.utc):
            return None
        return OrchestrationRuntime._grid_cancellation_candidate(
            previous,
            True,
            f"grid setup expired at {format_nigeria_time(expires_at)}",
        )

    @staticmethod
    def _expired_directional_candidate(previous: dict[str, Any] | None) -> dict[str, Any] | None:
        if (
            not previous
            or previous.get("classification") in {None, "grid"}
            or previous.get("delivery_status") != "delivered"
            or not previous.get("expires_at")
        ):
            return None
        try:
            expires_at = datetime.fromisoformat(str(previous["expires_at"]).replace("Z", "+00:00"))
        except ValueError:
            return None
        if expires_at.tzinfo is None or datetime.now(timezone.utc) < expires_at.astimezone(timezone.utc):
            return None
        fingerprint = hashlib.sha256(f"directional:expired:{previous.get('fingerprint')}:{expires_at.isoformat()}".encode()).hexdigest()
        return {
            "fingerprint": fingerprint,
            "confirmation_status": "expired",
            "classification": previous["classification"],
            "expires_directional_setup": True,
            "expired_at": format_nigeria_time(expires_at),
            "expected_version": int(previous.get("version", 0) or 0),
        }

    @staticmethod
    def _with_setup_validity(candidate: dict[str, Any], result: Any, market: Any, interval: str) -> dict[str, Any]:
        run = getattr(getattr(result, "context", None), "run", None)
        generated_at = getattr(result, "finished_at", None) or getattr(run, "requested_at", None) or datetime.now(timezone.utc)
        price_action = getattr(getattr(result, "context", None), "outputs", {}).get("price_action")
        confirmation_signal = strongest_confirmation_signal(price_action)
        confirmation_age = int(getattr(confirmation_signal, "age_candles", 0) or 0)
        validity = build_setup_validity(
            getattr(market, "interval", interval),
            generated_at,
            age_candles=confirmation_age if candidate.get("classification") == "grid" else 0,
        )
        if validity is not None:
            candidate.update({
                "generated_at": validity["generated_at"].isoformat(),
                "expires_at": validity["expires_at"].isoformat(),
                "validity_candles": validity["validity_candles"],
                "remaining_validity_candles": validity["remaining_candles"],
            })
        return candidate

    @staticmethod
    def _grid_cancellation_candidate(previous: dict[str, Any] | None, previous_confirmed_grid: bool, reason: str) -> dict[str, Any] | None:
        if not previous_confirmed_grid:
            return None
        fingerprint = hashlib.sha256(f"grid:cancelled:{reason}".encode()).hexdigest()
        return {
            "fingerprint": fingerprint,
            "confirmation_status": "cancelled",
            "classification": "grid",
            "cancellation_reason": reason,
            "expected_version": int((previous or {}).get("version", 0) or 0),
        }

    @staticmethod
    def _directional_material(classification: str, direction: str, score: int, market: Any, price_action: Any) -> dict[str, Any]:
        price = getattr(market, "price", None)
        plan = build_directional_plan(price, direction) or {}
        return {
            "classification": classification,
            "direction": direction,
            "score": score,
            "entry": round(float(plan.get("entry", price) or 0), 6),
            "invalidation": round(float(plan.get("invalidation", 0) or 0), 6),
            "target": round(float(plan.get("target", 0) or 0), 6),
            "confirmation_pattern": getattr(price_action, "strongest_confirming_pattern", None),
        }

    async def _telegram_notification_state(self, key: tuple[str, str]) -> dict[str, Any] | None:
        channel = f"{key[0].casefold()}:{key[1]}"
        if self.redis_coordination is not None:
            try:
                durable_state = await self.redis_coordination.notification_state_get(channel)
                if durable_state is not None:
                    self._telegram_signal_states[key] = durable_state
                    return durable_state
            except Exception as exc:
                LOGGER.warning("Telegram notification state read failed; using process state", extra={"error_type": type(exc).__name__, "channel": channel})
        return self._telegram_signal_states.get(key)

    async def _reserve_telegram_notification(self, symbol: str, interval: str, state: dict[str, Any]) -> bool:
        key = (symbol, interval)
        channel = f"{symbol.casefold()}:{interval}"
        expected_version = int(state.get("expected_version", 0) or 0)
        reserved_state = {key: value for key, value in state.items() if key != "expected_version"}
        reserved_state["delivery_status"] = "pending"
        if self.redis_coordination is not None:
            try:
                stored = await self.redis_coordination.notification_state_compare_and_put(channel, expected_version, reserved_state)
                if stored is None:
                    return False
                self._telegram_signal_states[key] = stored
                state["reservation_version"] = stored["version"]
                return True
            except Exception as exc:
                LOGGER.warning("Telegram notification reservation failed", extra={"error_type": type(exc).__name__, "channel": channel})
                return False
        reserved_state["version"] = expected_version + 1
        self._telegram_signal_states[key] = reserved_state
        state["reservation_version"] = reserved_state["version"]
        return True

    async def _finish_telegram_notification(self, symbol: str, interval: str, state: dict[str, Any], delivery_status: str, *, message_id: Any = None, error_type: str | None = None) -> None:
        key = (symbol, interval)
        channel = f"{symbol.casefold()}:{interval}"
        reservation_version = int(state.get("reservation_version", 0) or 0)
        finished_state = {key: value for key, value in state.items() if key not in {"expected_version", "reservation_version"}}
        finished_state.update({"delivery_status": delivery_status, "telegram_message_id": message_id if isinstance(message_id, int) else None})
        if error_type is not None:
            finished_state["error_type"] = error_type
        if self.redis_coordination is not None:
            try:
                stored = await self.redis_coordination.notification_state_compare_and_put(channel, reservation_version, finished_state)
                if stored is not None:
                    self._telegram_signal_states[key] = stored
                return
            except Exception as exc:
                LOGGER.warning("Telegram notification completion persistence failed", extra={"error_type": type(exc).__name__, "channel": channel})
                return
        finished_state["version"] = reservation_version + 1
        self._telegram_signal_states[key] = finished_state

    @staticmethod
    def _grid_confirmation_signal_id(market: Any, price_action: Any) -> dict[str, Any]:
        strongest_pattern = getattr(price_action, "strongest_confirming_pattern", None)
        signal = strongest_confirmation_signal(price_action)
        detected_at = None
        index = getattr(signal, "detected_at_index", -1)
        candles = tuple(getattr(market, "candles", ()) or ())
        if isinstance(index, int) and 0 <= index < len(candles):
            detected_at = getattr(candles[index], "timestamp", None)
        return {
            "pattern": strongest_pattern,
            "family": getattr(getattr(signal, "family", None), "value", None),
            "direction": getattr(getattr(signal, "direction", None), "value", None),
            "detected_at": detected_at,
        }

class OrchestrationASGI:
    def __init__(self, runtime: OrchestrationRuntime | None = None) -> None:
        self.runtime = runtime or OrchestrationRuntime()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    try:
                        await self.runtime.start()
                    except Exception as exc:
                        LOGGER.exception("application lifespan startup failed", extra={"error_type": type(exc).__name__})
                        await send({"type": "lifespan.startup.failed", "message": "startup_failed"})
                        return
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await self.runtime.shutdown()
                    await send({"type": "lifespan.shutdown.complete"})
                    return
            return
        if scope.get("type") != "http":
            return
        path = scope.get("path", "")
        if path == "/health/live":
            code, payload = 200, {"status": "alive"}
        elif path == "/health/ready":
            ready, payload = self.runtime.readiness()
            code = 200 if ready else 503
        else:
            code, payload = 404, {"status": "not_found"}
        body = json.dumps(payload, separators=(",", ":")).encode()
        await send({"type": "http.response.start", "status": code, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

app = OrchestrationASGI()
