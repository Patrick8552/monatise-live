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
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping
from uuid import uuid4
from urllib.request import Request, urlopen

from monatise.application.composition import create_application, create_durable_infrastructure
from monatise.application.production_analysis import ACTIVE_GRID_SPACING_STRATEGY, build_directional_plan, build_moving_grid_plan, build_production_analysis_run, build_setup_validity, sanitized_result, strongest_confirmation_signal
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
from monatise.application.stock_analysis import build_stock_analysis
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
SCHEDULED_ANALYSIS_DEFAULT_SYMBOLS = ("BTC", "ETH", "SOL")
# Bump whenever the snapshot payload shape changes, so a later replay can
# tell which schema a given historical row was written under.
DECISION_SNAPSHOT_SCHEMA_VERSION = 1
DECISION_SNAPSHOT_WRITE_TIMEOUT_SECONDS = 5.0
DECISION_SNAPSHOT_RETENTION_DAYS = 30
# Alerts are only ever read within TRADINGVIEW_FRESH_SECONDS (5 minutes) of
# receipt, but kept longer than that so a short recent-history window
# survives for debugging/review before the retention sweep prunes them.
TRADINGVIEW_ALERT_RETENTION_DAYS = 3
STOCK_SCAN_SYMBOLS = ("AAPL", "TSLA", "NVDA", "QQQ", "SPY")
SCHEDULED_ANALYSIS_INTERVAL_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1_800,
    "1h": 3_600, "4h": 14_400, "6h": 21_600, "8h": 28_800,
    "12h": 43_200, "1d": 86_400, "1w": 604_800,
}


def _false(value: str | None) -> bool:
    return value is None or value.strip().casefold() in FALSE_VALUES


def _true(value: str | None) -> bool:
    return value is not None and value.strip().casefold() in {"1", "true", "yes", "on", "enabled"}


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
    raw_symbols = environment.get("MONATISE_SCHEDULED_ANALYSIS_SYMBOLS", ",".join(SCHEDULED_ANALYSIS_DEFAULT_SYMBOLS))
    symbols = tuple(dict.fromkeys(part.strip().upper() for part in raw_symbols.split(",") if part.strip()))
    unsupported = tuple(symbol for symbol in symbols if symbol not in SCHEDULED_ANALYSIS_DEFAULT_SYMBOLS)
    if not symbols:
        raise ValueError("scheduled analysis requires at least one symbol")
    if unsupported:
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

    def _send(self, chat_id: str, text: str) -> int:
        token = self._token_provider()
        if not token:
            raise RuntimeError("Telegram credential is unavailable")
        body = json.dumps({
            "chat_id": chat_id,
            "text": _bold_telegram_labels(text),
            "parse_mode": "HTML",
        }, separators=(",", ":")).encode()
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

    def __init__(self, client: Any, *, namespace: str) -> None:
        self.client = client
        self.namespace = namespace.strip(":")

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
    telegram: TelegramNotifier | None = None
    x_macro: XMacroAdapter | None = None
    dependencies: dict[str, dict[str, Any]] = field(default_factory=dict)
    hierarchy: ShadowHierarchyCoordinator | None = None
    hierarchy_service: ShadowHierarchyService | None = None
    _telegram_signal_states: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)

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
        publisher = self.telegram.hierarchy_shadow_notification if self.telegram is not None else None
        current_price_provider = getattr(self.coinglass, "latest_current_price", None)
        self.hierarchy_service = ShadowHierarchyService(self.hierarchy, HierarchyLayerEvaluator(configuration=configuration), repository, publisher=publisher, current_price_provider=current_price_provider)
        scheduler = self.application.infrastructure.scheduler
        job_ids: list[str] = []
        raw_symbols = self.environment.get("MONATISE_SCHEDULED_ANALYSIS_SYMBOLS", "BTC,ETH,SOL")
        symbols = tuple(dict.fromkeys(item.strip().upper() for item in raw_symbols.split(",") if item.strip()))
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

    async def _register_coin_discovery_monitor(self) -> tuple[str, ...]:
        if not _true(self.environment.get("MONATISE_COIN_DISCOVERY_ENABLED", "true")):
            self.dependencies["coin_discovery"] = {"status": "ok", "enabled": False}
            return ()
        if self.application is None or self.coinglass is None or self.telegram is None or self.redis is None:
            self.dependencies["coin_discovery"] = {"status": "error", "enabled": True}
            raise RuntimeError("Coin discovery monitoring dependencies are unavailable")
        namespace = self.environment.get("MONATISE_REDIS_NAMESPACE", "monatise:production-analysis")
        baseline_key = f"{namespace}:coinglass:supported-coins"
        threshold = max(1.0, float(self.environment.get("MONATISE_VOLATILITY_ALERT_PERCENT", "15")))
        interval_seconds = max(60, int(self.environment.get("MONATISE_COIN_DISCOVERY_INTERVAL_SECONDS", "300")))
        analysis_enabled = _true(self.environment.get("MONATISE_COIN_DISCOVERY_ANALYSIS_ENABLED", "true"))
        analysis_cap = max(0, int(self.environment.get("MONATISE_COIN_DISCOVERY_ANALYSIS_CAP", "5")))
        analysis_interval = self.environment.get("MONATISE_COIN_DISCOVERY_ANALYSIS_INTERVAL", "15m")
        analysis_cooldown_seconds = max(300, int(self.environment.get("MONATISE_COIN_DISCOVERY_ANALYSIS_COOLDOWN_SECONDS", "21600")))

        async def monitor() -> dict[str, Any]:
            started_at = datetime.now(timezone.utc)
            self.dependencies["coin_discovery"].update({"last_started_at": started_at.isoformat(), "last_error": None})
            try:
                coins, changes = await asyncio.gather(
                    asyncio.to_thread(self.coinglass.supported_futures_coins),
                    asyncio.to_thread(self.coinglass.futures_price_changes),
                )
                previous_raw = await self.redis.get(baseline_key)
                previous = set(json.loads(previous_raw)) if previous_raw else set()
                current = set(coins)
                new_coins = sorted(current - previous) if previous else []
                delivered = 0
                for symbol in new_coins:
                    message = "\n".join((
                        f"NEW COIN · {symbol}",
                        "CoinGlass has added this asset to its supported futures universe.",
                        "Status: discovery only — wait for liquidity, price history, and risk validation before considering a setup.",
                    ))
                    delivered += int(await self._deliver_coin_alert(f"new:{symbol}", message, ttl_seconds=604_800))
                await self.redis.set(baseline_key, json.dumps(sorted(current)), ex=2_592_000)
                movers = []
                for row in changes:
                    symbol = str(row.get("symbol") or row.get("coin") or "").strip().upper()
                    change = self._price_change_24h(row)
                    if symbol and change is not None and abs(change) >= threshold:
                        movers.append((symbol, change))
                selected_movers = sorted(movers, key=lambda item: abs(item[1]), reverse=True)[:10]
                for symbol, change in selected_movers:
                    direction = "up" if change > 0 else "down"
                    message = "\n".join((
                        f"VOLATILITY PICKUP · {symbol}",
                        f"24h move: {change:+.2f}% · threshold {threshold:.2f}%",
                        "Status: watchlist alert — CoinGlass structure, funding, OI, liquidation, and liquidity confirmation required.",
                    ))
                    delivered += int(await self._deliver_coin_alert(f"volatility:{symbol}:{direction}", message, ttl_seconds=86_400))

                analyzed = await self._analyze_volatile_movers(selected_movers, analysis_enabled, analysis_cap, analysis_interval, analysis_cooldown_seconds, namespace)
                result = {
                    "supported_coins": len(current), "new_coins": len(new_coins), "movers": len(selected_movers),
                    "delivered": delivered, "extended_universe_analyzed": analyzed,
                }
                self.dependencies["coin_discovery"].update({
                    "last_success_at": datetime.now(timezone.utc).isoformat(), "last_result": result, "last_error": None,
                })
                return result
            except Exception as exc:
                self.dependencies["coin_discovery"].update({
                    "last_failure_at": datetime.now(timezone.utc).isoformat(), "last_error": type(exc).__name__,
                })
                raise

        job_id = "coinglass-coin-discovery-telegram"
        await self.application.infrastructure.scheduler.register(JobDefinition(
            job_id=job_id,
            name="CoinGlass new coin and volatility Telegram scanner",
            task=monitor,
            schedule_type=ScheduleType.INTERVAL,
            interval=timedelta(seconds=interval_seconds),
            timeout_seconds=min(max(interval_seconds - 1, 30), 180),
            retry_policy=RetryPolicy(maximum_attempts=2, delay_seconds=5, maximum_delay_seconds=15),
            tags=("coinglass", "new-coins", "volatility", "telegram", "read-only"),
            metadata={"notification_only": True, "execution_enabled": False, "volatility_threshold_percent": threshold},
        ))
        self.dependencies["coin_discovery"] = {
            "status": "ok", "enabled": True, "job": job_id,
            "poll_interval_seconds": interval_seconds, "volatility_threshold_percent": threshold,
            "extended_universe_analysis_enabled": analysis_enabled,
            "extended_universe_analysis_cap": analysis_cap,
            "extended_universe_analysis_interval": analysis_interval,
            "extended_universe_analysis_cooldown_seconds": analysis_cooldown_seconds,
        }
        return (job_id,)

    async def _register_stock_scan_monitor(self) -> tuple[str, ...]:
        if not _true(self.environment.get("MONATISE_STOCK_SCAN_ENABLED", "true")):
            self.dependencies["stock_scan"] = {"status": "ok", "enabled": False}
            return ()
        if self.application is None or self.telegram is None or self.redis is None:
            self.dependencies["stock_scan"] = {"status": "error", "enabled": True}
            raise RuntimeError("Stock scan monitoring dependencies are unavailable")
        namespace = self.environment.get("MONATISE_REDIS_NAMESPACE", "monatise:production-analysis")
        interval_seconds = max(60, int(self.environment.get("MONATISE_STOCK_SCAN_INTERVAL_SECONDS", "1800")))
        cooldown_seconds = max(300, int(self.environment.get("MONATISE_STOCK_SCAN_COOLDOWN_SECONDS", "21600")))

        async def monitor() -> dict[str, Any]:
            started_at = datetime.now(timezone.utc)
            self.dependencies["stock_scan"].update({"last_started_at": started_at.isoformat(), "last_error": None})
            try:
                analyzed = await self._analyze_stocks(STOCK_SCAN_SYMBOLS, cooldown_seconds, namespace)
                result = {"symbols": len(STOCK_SCAN_SYMBOLS), "analyzed": analyzed}
                self.dependencies["stock_scan"].update({
                    "last_success_at": datetime.now(timezone.utc).isoformat(), "last_result": result, "last_error": None,
                })
                return result
            except Exception as exc:
                self.dependencies["stock_scan"].update({
                    "last_failure_at": datetime.now(timezone.utc).isoformat(), "last_error": type(exc).__name__,
                })
                raise

        job_id = "quiver-stock-scan-telegram"
        await self.application.infrastructure.scheduler.register(JobDefinition(
            job_id=job_id,
            name="Quiver stock scan Telegram notifier",
            task=monitor,
            schedule_type=ScheduleType.INTERVAL,
            interval=timedelta(seconds=interval_seconds),
            timeout_seconds=min(max(interval_seconds - 1, 30), 180),
            retry_policy=RetryPolicy(maximum_attempts=2, delay_seconds=5, maximum_delay_seconds=15),
            tags=("quiver", "stocks", "telegram", "read-only"),
            metadata={"notification_only": True, "execution_enabled": False},
        ))
        self.dependencies["stock_scan"] = {
            "status": "ok", "enabled": True, "job": job_id,
            "poll_interval_seconds": interval_seconds, "cooldown_seconds": cooldown_seconds,
        }
        return (job_id,)

    async def _analyze_stocks(self, symbols: tuple[str, ...], cooldown_seconds: int, namespace: str) -> int:
        """Cooldown-gated per symbol so each of the fixed Quiver stocks is
        re-analyzed and re-notified a few times a day, matching the crypto
        coin-discovery cadence -- notifies unconditionally on the outcome,
        NO_TRADE included, same as _analyze_volatile_movers."""
        claimed: list[str] = []
        for symbol in symbols:
            cooldown_key = f"{namespace}:stock-alert:analysis:{symbol}"
            if await self.redis.set(cooldown_key, "reserved", nx=True, ex=cooldown_seconds):
                claimed.append(symbol)
        if not claimed:
            return 0

        outcomes = await asyncio.gather(
            *(self.analyse_stock(symbol) for symbol in claimed),
            return_exceptions=True,
        )
        analyzed = 0
        for symbol, outcome in zip(claimed, outcomes):
            if isinstance(outcome, Exception):
                LOGGER.warning(
                    "Stock scan analysis failed",
                    extra={"symbol": symbol, "error_type": type(outcome).__name__},
                )
                await self.redis.delete(f"{namespace}:stock-alert:analysis:{symbol}")
                continue
            try:
                message = TelegramNotifier.format_stock_analysis(outcome)
                await self.telegram.stock_analysis_notification(message)
            except Exception as exc:
                LOGGER.warning(
                    "Stock analysis delivery failed",
                    extra={"symbol": symbol, "error_type": type(exc).__name__},
                )
                continue
            analyzed += 1
        return analyzed

    async def _analyze_volatile_movers(
        self,
        selected_movers: list[tuple[str, float]],
        analysis_enabled: bool,
        analysis_cap: int,
        analysis_interval: str,
        analysis_cooldown_seconds: int,
        namespace: str,
    ) -> int:
        """Run verified dynamic analysis (resolve_futures_asset + full engine chain)
        on the strongest movers and deliver the result, instead of leaving the
        watchlist alert as the only signal. Capped and cooldown-gated per symbol
        so a persistently volatile coin is re-analyzed a few times a day, not on
        every 5-minute scan and not only once."""
        if not (analysis_enabled and analysis_cap > 0 and selected_movers):
            return 0

        claimed: list[str] = []
        for symbol, _change in selected_movers[:analysis_cap]:
            cooldown_key = f"{namespace}:coin-alert:analysis:{symbol}"
            if await self.redis.set(cooldown_key, "reserved", nx=True, ex=analysis_cooldown_seconds):
                claimed.append(symbol)
        if not claimed:
            return 0

        outcomes = await asyncio.gather(
            *(
                self.analyse_dynamic_coinglass(symbol, interval=analysis_interval, source="monatise.coin_discovery")
                for symbol in claimed
            ),
            return_exceptions=True,
        )
        analyzed = 0
        for symbol, outcome in zip(claimed, outcomes):
            if isinstance(outcome, Exception):
                LOGGER.warning(
                    "Extended-universe volatility analysis failed",
                    extra={"symbol": symbol, "error_type": type(outcome).__name__},
                )
                await self.redis.delete(f"{namespace}:coin-alert:analysis:{symbol}")
                continue
            try:
                message = TelegramNotifier.format_dynamic_analysis(outcome)
                await self.telegram.dynamic_analysis_notification(message)
            except Exception as exc:
                LOGGER.warning(
                    "Dynamic analysis delivery failed",
                    extra={"symbol": symbol, "error_type": type(exc).__name__},
                )
                continue
            analyzed += 1
        return analyzed

    async def _deliver_coin_alert(self, identity: str, message: str, *, ttl_seconds: int) -> bool:
        key = f"{self.environment.get('MONATISE_REDIS_NAMESPACE', 'monatise:production-analysis')}:coin-alert:{identity}"
        if not await self.redis.set(key, "reserved", nx=True, ex=300):
            return False
        try:
            await self.telegram.coin_discovery_notification(message)
            await self.redis.set(key, "delivered", ex=ttl_seconds)
            return True
        except Exception:
            await self.redis.delete(key)
            raise

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
            self.postgres = await self.postgres_pool.getconn(timeout=10)
            await self.postgres.execute("SELECT 1")
            self.dependencies["postgresql"] = {"status": "ok", "latency_ms": round((perf_counter() - started) * 1000, 2)}
            startup_phase = "database_migrations"
            self.migrations = MigrationRunner(self.postgres, self.migration_directory)
            await self.migrations.run()
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
            if telegram_token and telegram_chat:
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
            await self._register_coin_discovery_monitor()
            await self._register_stock_scan_monitor()
            await self._register_decision_snapshot_retention()
            await self._register_tradingview_alert_retention()
            self.leadership = RedisSchedulerLeadership(
                self.redis, namespace=self.environment.get("MONATISE_REDIS_NAMESPACE", "monatise:production-analysis")
            )
            self.redis_coordination = RedisCoordinationStore(
                self.redis, namespace=self.environment.get("MONATISE_REDIS_NAMESPACE", "monatise:production-analysis")
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
                "telegram": "configured_notification_only" if self.environment.get("MONATISE_TELEGRAM_BOT_TOKEN") and self.environment.get("MONATISE_TELEGRAM_CHAT_ID") else "unavailable_optional",
                "openclaw": "configured_analysis_only" if self.environment.get("MONATISE_OPENCLAW_TOKEN") else "unavailable_optional",
                "x_macro": "configured_read_only" if self.x_macro is not None else "unavailable_optional",
                "coin_discovery": "configured_notification_only",
            }
            self.dependencies["audit_logging"] = {"status": "ok", "enabled": True}
            startup_phase = "audit_integrity"
            audit_errors = await infrastructure.audit.verify_integrity()
            self.dependencies["audit_integrity"] = {
                "status": "ok" if not audit_errors else "error",
                "verification": "verified" if not audit_errors else "failed",
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
        if self.postgres is not None:
            if self.postgres_pool is not None:
                await self.postgres_pool.putconn(self.postgres)
            else:
                await self.postgres.close()
        if self.postgres_pool is not None:
            await self.postgres_pool.close()

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
        result = await self.application.orchestrator.run(build_production_analysis_run(symbol, interval=interval, correlation_id=correlation_id, source=source))
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
        if self.postgres is not None:
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
        market_data_raw = result.context.outputs.get("market_data")
        outputs: dict[str, Any] = {}
        for name, value in result.context.outputs.items():
            serialized = _json_value(value)
            if name == "market_data" and isinstance(serialized, dict):
                # Candles are the bulk of this payload and are the one input
                # CoinGlass CAN answer historically later (unlike derivatives),
                # so a compact reference is enough to re-fetch the exact
                # window on replay instead of duplicating it every cycle.
                serialized["candles"] = _compact_candle_reference(getattr(value, "candles", ()) or ())
            outputs[name] = serialized

        # Recomputed fresh (build_moving_grid_plan is a pure function of
        # market_data) rather than read from a module constant, so this
        # reflects what spacing strategy actually resolved for this run --
        # including the case where it fails closed to None.
        grid_plan = None
        if market_data_raw is not None:
            try:
                grid_plan = build_moving_grid_plan(market_data_raw)
            except Exception:
                grid_plan = None
        grid_spacing_strategy = grid_plan.get("spacing_strategy") if grid_plan else ACTIVE_GRID_SPACING_STRATEGY

        decision_output = result.context.outputs.get("decision")
        classification = getattr(getattr(decision_output, "classification", None), "value", None)

        snapshot = {
            "schema_version": DECISION_SNAPSHOT_SCHEMA_VERSION,
            "run_id": result.run_id,
            "correlation_id": result.correlation_id,
            "symbol": result.symbol,
            "interval": interval,
            "source": source,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "grid_spacing_strategy": grid_spacing_strategy,
            "grid_plan": grid_plan,
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
        bars_task = asyncio.to_thread(alpaca.stock_bars, symbol)
        snapshot_task = asyncio.to_thread(alpaca.stock_snapshot, symbol)

        def finnhub_context() -> dict[str, Any]:
            try:
                return FinnhubAdapter.from_env().context(symbol)
            except FinnhubAdapterError:
                return {"source": "Finnhub", "unavailable": True}

        context, bars, snapshot, finnhub = await asyncio.gather(
            quiver_task, bars_task, snapshot_task, asyncio.to_thread(finnhub_context)
        )
        return build_stock_analysis(context, bars=bars, snapshot=snapshot, finnhub=finnhub)

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
