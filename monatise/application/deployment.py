"""Paper-only deployment lifecycle for the orchestration application."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter, time
from typing import Any, Mapping
from uuid import uuid4
from urllib.request import Request, urlopen

from monatise.application.composition import create_application, create_durable_infrastructure
from monatise.application.staging_analysis import build_paper_analysis_run, sanitized_result
from monatise.application.registry import CANONICAL_ENGINE_ORDER
from monatise.application.persistence import PostgresDocumentStore
from monatise.application.workflows import TelegramNotifier
from monatise.application.hierarchy import HierarchyConfiguration, HierarchyLayerEvaluator, HierarchyRepository, Provenance, ShadowHierarchyCoordinator, ShadowHierarchyService
from monatise.adapters.coinglass_production import CoinGlassProductionAdapter
from monatise.infrastructure.audit_database import AuditAction, AuditActor, AuditRecordType
from monatise.infrastructure.task_scheduler import JobDefinition, RetryPolicy, ScheduleType
from monatise.engines.macro.rules import CRYPTO_MACRO_RULES


LOGGER = logging.getLogger("monatise.orchestration")
MIGRATION_LOCK_ID = 4_602_161_943_641_489_731
FALSE_VALUES = {"0", "false", "no", "off", "disabled", ""}
COINGLASS_PROVIDER_KEY = "coinglass.market_provider"
SCHEDULED_ANALYSIS_JOB_PREFIX = "scheduled-analysis"
SCHEDULED_ANALYSIS_DEFAULT_SYMBOLS = ("BTC", "ETH", "SOL")


def _false(value: str | None) -> bool:
    return value is None or value.strip().casefold() in FALSE_VALUES


def _true(value: str | None) -> bool:
    return value is not None and value.strip().casefold() in {"1", "true", "yes", "on", "enabled"}


def scheduled_analysis_configuration(environment: Mapping[str, str]) -> tuple[tuple[str, ...], int] | None:
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
    try:
        interval_seconds = int(environment.get("MONATISE_SCHEDULED_ANALYSIS_INTERVAL_SECONDS", "900"))
    except ValueError as exc:
        raise ValueError("scheduled analysis interval must be an integer") from exc
    if not 60 <= interval_seconds <= 86_400:
        raise ValueError("scheduled analysis interval must be between 60 and 86400 seconds")
    return symbols, interval_seconds


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
        body = json.dumps({"chat_id": chat_id, "text": text}, separators=(",", ":")).encode()
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
                    if row[0] != checksum:
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

    async def acquire(self) -> bool:
        self.is_leader = bool(await self.client.set(self.key, self.token, nx=True, ex=self.ttl_seconds))
        if self.is_leader:
            self._renewal = asyncio.create_task(self._renew(), name="monatise-scheduler-leadership")
        return self.is_leader

    async def acquire_or_wait(self, on_acquired: Any) -> bool:
        """Acquire immediately or keep contending until leadership is available."""
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
                    await on_acquired()
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
                    return
        except asyncio.CancelledError:
            raise

    async def release(self) -> None:
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


class _UnavailableMacroProvider:
    def context_snapshot(self, symbol: str) -> dict[str, Any]:
        raise RuntimeError("macro provider is not invoked during startup")

    def economic_events(self) -> list[Any]:
        return []


class _DegradedMacroProvider:
    """Explicitly unavailable staging factors; never fabricates macro values."""

    def context_snapshot(self, symbol: str) -> dict[str, None]:
        return {rule.factor: None for rule in CRYPTO_MACRO_RULES}

    def economic_events(self) -> list[Any]:
        return []


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
    telegram: TelegramNotifier | None = None
    dependencies: dict[str, dict[str, Any]] = field(default_factory=dict)
    hierarchy: ShadowHierarchyCoordinator | None = None
    hierarchy_service: ShadowHierarchyService | None = None

    async def _register_scheduled_analysis(self) -> tuple[str, ...]:
        configuration = scheduled_analysis_configuration(self.environment)
        if configuration is None:
            return ()
        if self.application is None:
            raise RuntimeError("orchestration runtime is unavailable")
        symbols, interval_seconds = configuration
        scheduler = self.application.infrastructure.scheduler
        job_ids: list[str] = []
        for symbol in symbols:
            job_id = f"{SCHEDULED_ANALYSIS_JOB_PREFIX}-{symbol.casefold()}"

            async def task(asset: str = symbol) -> dict[str, Any]:
                return await self.analyse(asset, source="monatise.scheduler")

            await scheduler.register(JobDefinition(
                job_id=job_id,
                name=f"Scheduled paper analysis for {symbol}",
                task=task,
                schedule_type=ScheduleType.INTERVAL,
                interval=timedelta(seconds=interval_seconds),
                timeout_seconds=min(float(interval_seconds), 300.0),
                retry_policy=RetryPolicy(maximum_attempts=2, delay_seconds=5.0, maximum_delay_seconds=30.0),
                tags=("scheduled", "crypto", "analysis", "paper-only"),
                metadata={"symbol": symbol, "execution_enabled": False, "notification_policy": "validated_signals_only"},
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
        self.hierarchy_service = ShadowHierarchyService(self.hierarchy, HierarchyLayerEvaluator(configuration=configuration), repository, publisher=publisher)
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
                interval=timedelta(seconds=60),
                timeout_seconds=55,
                retry_policy=RetryPolicy(maximum_attempts=2, delay_seconds=5, maximum_delay_seconds=15),
                tags=("hierarchy", "shadow", "analysis-only"),
                metadata={"symbol": symbol, "shadow": True, "telegram_publish_enabled": configuration.telegram_publish_enabled, "execution_enabled": False},
            ))
            job_ids.append(job_id)
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

    async def start(self) -> None:
        LOGGER.info("validating paper-only orchestration configuration")
        self.safety = PaperSafetyConfiguration.from_environment(self.environment)
        self.dependencies["configuration"] = {"status": "ok", "frozen": True}
        database_url = self.environment.get("MONATISE_DATABASE_URL") or self.environment.get("DATABASE_URL")
        redis_url = self.environment.get("MONATISE_REDIS_URL") or self.environment.get("REDIS_URL")
        if not database_url:
            raise RuntimeError("PostgreSQL configuration is unavailable")
        deployment_environment = self.environment.get("MONATISE_ENVIRONMENT", "production").strip().casefold()
        if not redis_url or (deployment_environment != "test" and ("localhost" in redis_url or "127.0.0.1" in redis_url)):
            raise RuntimeError("network-accessible Redis configuration is unavailable")
        try:
            from psycopg_pool import AsyncConnectionPool
            from redis.asyncio import Redis
            LOGGER.info("opening managed PostgreSQL pool")
            started = perf_counter()
            self.postgres_pool = AsyncConnectionPool(database_url, min_size=1, max_size=4, open=False, kwargs={"autocommit": True})
            await self.postgres_pool.open(wait=True, timeout=15)
            self.postgres = await self.postgres_pool.getconn(timeout=10)
            await self.postgres.execute("SELECT 1")
            self.dependencies["postgresql"] = {"status": "ok", "latency_ms": round((perf_counter() - started) * 1000, 2)}
            self.migrations = MigrationRunner(self.postgres, self.migration_directory)
            await self.migrations.run()
            self.dependencies["migrations"] = {"status": "ok", "version": self.migrations.version}
            started = perf_counter()
            LOGGER.info("opening managed Redis connection")
            self.redis = Redis.from_url(redis_url, decode_responses=True)
            if not await self.redis.ping():
                raise RuntimeError("Redis ping failed")
            self.dependencies["redis"] = {
                "status": "ok",
                "latency_ms": round((perf_counter() - started) * 1000, 2),
                "capabilities": ["scheduler_lock", "event_deduplication", "replay_nonce", "coinglass_cache", "ttl"],
            }
            store = PostgresDocumentStore(self.postgres)
            infrastructure = create_durable_infrastructure(store)
            self.coinglass = register_coinglass_provider(infrastructure.container, self.environment)
            degraded_macro_enabled = deployment_environment == "test" or (
                deployment_environment in {"staging", "production"}
                and not _false(self.environment.get("MONATISE_ALLOW_DEGRADED_MACRO"))
            )
            macro_provider = _DegradedMacroProvider() if degraded_macro_enabled else _UnavailableMacroProvider()
            self.application = create_application(
                market_data_providers={"coinglass": self.coinglass},
                macro_provider=macro_provider,
                derivatives_provider=self.coinglass,
                infrastructure=infrastructure,
            )
            telegram_token = self.environment.get("MONATISE_TELEGRAM_BOT_TOKEN", "")
            telegram_chat = self.environment.get("MONATISE_TELEGRAM_CHAT_ID", "")
            if telegram_token and telegram_chat:
                secrets = EnvironmentSecretBoundary(self.environment)
                self.telegram = TelegramNotifier(TelegramNotificationTransport(lambda: secrets.get("MONATISE_TELEGRAM_BOT_TOKEN")), telegram_chat)
            scheduled_jobs = await self._register_scheduled_analysis()
            await self._register_hierarchy_shadow(store)
            self.leadership = RedisSchedulerLeadership(
                self.redis, namespace=self.environment.get("MONATISE_REDIS_NAMESPACE", "monatise:paper-staging")
            )
            self.redis_coordination = RedisCoordinationStore(
                self.redis, namespace=self.environment.get("MONATISE_REDIS_NAMESPACE", "monatise:paper-staging")
            )
            leader = await self.leadership.acquire_or_wait(infrastructure.scheduler.start)
            await infrastructure.plugins.start_all()
            if leader:
                await infrastructure.scheduler.start()
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
                "status": "ok", "count": len(self.application.registry.ordered()), "order": list(CANONICAL_ENGINE_ORDER)
            }
            self.dependencies["governance"] = {"status": "ok", "kill_switch": True}
            self.dependencies["macro_provider"] = {
                "status": "degraded" if degraded_macro_enabled else "error",
                "mode": "degraded_unavailable_factors" if degraded_macro_enabled else "unavailable",
                "blocks_on_missing_data": not degraded_macro_enabled,
                "event_calendar": "empty",
            }
            configured = bool(self.environment.get("COINGLASS_API_KEY", "").strip())
            coinglass_required = deployment_environment != "test"
            self.dependencies["coinglass"] = {
                "status": "ok" if configured or not coinglass_required else "error",
                "configured": configured,
                "required": coinglass_required,
                "latest_request": "not_yet_requested",
            }
            self.dependencies["notifications"] = {
                "status": "ok",
                "telegram": "configured_notification_only" if self.environment.get("MONATISE_TELEGRAM_BOT_TOKEN") and self.environment.get("MONATISE_TELEGRAM_CHAT_ID") else "unavailable_optional",
                "openclaw": "configured_analysis_only" if self.environment.get("MONATISE_OPENCLAW_TOKEN") else "unavailable_optional",
            }
            self.dependencies["audit_logging"] = {"status": "ok", "enabled": True}
            audit_errors = await infrastructure.audit.verify_integrity()
            self.dependencies["audit_integrity"] = {
                "status": "ok" if not audit_errors else "error",
                "verification": "verified" if not audit_errors else "failed",
                "error_count": len(audit_errors),
            }
        except Exception as exc:
            self.dependencies["startup"] = {"status": "error", "reason": type(exc).__name__}
            await self.shutdown()
            raise

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
            self.dependencies.setdefault("coinglass", {})["latest_request"] = (
                "healthy" if health.healthy else ("failed" if health.consecutive_failures else "not_yet_requested")
            )
        registry_ok = bool(self.application and tuple(item.name for item in self.application.registry.ordered()) == CANONICAL_ENGINE_ORDER)
        mandatory = (
            "configuration", "postgresql", "migrations", "redis", "event_bus", "state_manager",
            "audit_repository", "audit_integrity", "audit_logging", "scheduler", "engine_registry", "pipeline_orchestrator", "governance", "notifications", "coinglass", "macro_provider", "hierarchy_shadow",
        )
        mandatory_ok = all(
            self.dependencies.get(key, {}).get("status") == "ok"
            or (key == "macro_provider" and self.dependencies.get(key, {}).get("status") == "degraded")
            for key in mandatory
        )
        ready = registry_ok and self.safety is not None and mandatory_ok
        return ready, {
            "status": "ready" if ready else "not_ready",
            "execution_enabled": False,
            "mode": "paper",
            "dependencies": self.dependencies,
        }

    async def analyse(self, symbol: str, correlation_id: str | None = None, scenario: str = "live", *, source: str = "monatise.staging") -> dict[str, Any]:
        if self.application is None:
            raise RuntimeError("orchestration runtime is unavailable")
        if self.dependencies.get("macro_provider", {}).get("status") == "degraded":
            await self.application.infrastructure.audit.append(
                record_type=AuditRecordType.CONFIGURATION,
                action=AuditAction.REVIEWED,
                actor=AuditActor("monatise-runtime", "application"),
                source="monatise.macro",
                payload={"event": "degraded_macro_used", "mode": "unavailable_factors", "confidence": 0},
                correlation_id=correlation_id,
                symbol=symbol.strip().upper(),
            )
        result = await self.application.orchestrator.run(build_paper_analysis_run(symbol, correlation_id=correlation_id, scenario=scenario, source=source))
        decision = result.context.outputs.get("decision")
        classification = getattr(getattr(decision, "classification", None), "value", None)
        validated_signal = (
            getattr(result.status, "value", result.status) == "completed"
            and classification in {"trend", "grid"}
            and all(stage in result.context.outputs for stage in ("risk_validation", "capital_allocation", "execution_policy", "governance_loss_control"))
        )
        if self.telegram is not None and validated_signal:
            try:
                await self.telegram.deliver(result)
            except Exception as exc:
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
        return sanitized_result(result, macro_mode=self.dependencies.get("macro_provider", {}).get("mode", "unknown"))

    async def verify_hierarchy_telegram(self) -> dict[str, Any]:
        """Send one controlled notification and persist positive/negative audit evidence."""
        if self.application is None or self.postgres is None or self.telegram is None:
            raise RuntimeError("notification verification dependencies are unavailable")
        ready, _ = self.readiness()
        scheduler_active = bool(self.leadership and self.leadership.is_leader)
        hierarchy = self.dependencies.get("hierarchy_shadow", {})
        if not ready or not scheduler_active or not hierarchy.get("telegram_publication_operational"):
            raise RuntimeError("notification verification preconditions are not satisfied")

        created_at = datetime.now(timezone.utc)
        test_id = uuid4().hex
        decision_id = f"test-decision-{test_id}"
        publication_id = f"test-publication-{test_id}"
        blocked_decision_id = f"test-blocked-{test_id}"
        chat_id = self.environment.get("MONATISE_TELEGRAM_CHAT_ID", "")
        destination = f"telegram:{hashlib.sha256(chat_id.encode()).hexdigest()[:12]}"
        strategy_version = str(hierarchy.get("strategy_version", "hierarchy-shadow-v1"))
        store = PostgresDocumentStore(self.postgres)

        decision = {
            "test_id": test_id, "decision_id": decision_id, "outcome": "VALID_SIGNAL",
            "strategy_version": strategy_version, "execution_enabled": False, "created_at": created_at.isoformat(),
        }
        await store.put("hierarchy_notification_test_decisions", decision_id, decision, expected_version=0)
        await self.application.infrastructure.audit.append(
            record_type=AuditRecordType.DECISION, action=AuditAction.APPROVED,
            actor=AuditActor("monatise-notification-verifier", "application"), source="monatise.hierarchy.notification_test",
            payload=decision, correlation_id=test_id,
        )
        LOGGER.warning("telegram publish requested publication_id=%s decision_id=%s destination=%s execution_enabled=false", publication_id, decision_id, destination)
        message = (
            "MONATISE TEST NOTIFICATION — SYSTEM TEST ONLY\n"
            f"Strategy: {strategy_version}\nService: ready\nScheduler: active\n"
            "Hierarchical Telegram: enabled\nExecution: disabled\n"
            f"Timestamp: {created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\nPublication: {publication_id}"
        )
        telegram_message_id = await self.telegram.hierarchy_shadow_notification(message)
        publication = {
            "test_id": test_id, "decision_id": decision_id, "publication_id": publication_id,
            "destination": destination, "status": "SENT", "telegram_message_id": telegram_message_id,
            "created_at": created_at.isoformat(), "strategy_version": strategy_version, "execution_enabled": False,
        }
        await store.put("hierarchy_notification_test_publications", publication_id, publication, expected_version=0)
        await self.application.infrastructure.audit.append(
            record_type=AuditRecordType.INTEGRATION, action=AuditAction.CREATED,
            actor=AuditActor("monatise-notification-verifier", "application"), source="monatise.telegram.notification_test",
            payload=publication, correlation_id=test_id, causation_id=decision_id,
        )
        LOGGER.warning("telegram publish succeeded publication_id=%s telegram_message_id=%s destination=%s execution_enabled=false", publication_id, telegram_message_id, destination)

        blocked = {
            "test_id": test_id, "decision_id": blocked_decision_id, "outcome": "BLOCKED",
            "reason": "controlled_negative_path", "strategy_version": strategy_version,
            "execution_enabled": False, "created_at": created_at.isoformat(), "publication_created": False,
        }
        await store.put("hierarchy_notification_test_decisions", blocked_decision_id, blocked, expected_version=0)
        await self.application.infrastructure.audit.append(
            record_type=AuditRecordType.DECISION, action=AuditAction.BLOCKED,
            actor=AuditActor("monatise-notification-verifier", "application"), source="monatise.hierarchy.notification_test",
            payload=blocked, correlation_id=test_id,
        )
        return {**publication, "blocked_decision_id": blocked_decision_id, "blocked_publication_created": False, "scheduler_active": True}


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
                        await send({"type": "lifespan.startup.failed", "message": type(exc).__name__})
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
        elif path == "/api/staging/analyse" and scope.get("method", "GET").upper() == "POST":
            code, payload = await self._analyse(scope, receive)
        else:
            code, payload = 404, {"status": "not_found"}
        body = json.dumps(payload, separators=(",", ":")).encode()
        await send({"type": "http.response.start", "status": code, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    async def _analyse(self, scope: dict[str, Any], receive: Any) -> tuple[int, dict[str, Any]]:
        environment = self.runtime.environment
        if environment.get("MONATISE_ENVIRONMENT", "").strip().casefold() != "staging":
            return 404, {"status": "not_found"}
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if len(body) > 16_384:
                return 413, {"status": "request_too_large"}
            if not message.get("more_body", False):
                break
        headers = {key.decode().casefold(): value.decode() for key, value in scope.get("headers", ())}
        token = environment.get("MONATISE_STAGING_API_TOKEN", "")
        timestamp = headers.get("x-monatise-timestamp", "")
        signature = headers.get("x-monatise-signature", "")
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
            if not isinstance(request, dict) or set(request) - {"symbol", "correlation_id", "scenario"}:
                return 400, {"status": "invalid_request", "reason": "only symbol, correlation_id, and scenario are accepted"}
            result = await self.runtime.analyse(str(request.get("symbol", "")), request.get("correlation_id"), str(request.get("scenario", "live")))
            return 200, result
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return 400, {"status": "invalid_request", "reason": str(exc)}
        except Exception as exc:
            LOGGER.exception("staging analysis failed", extra={"error_type": type(exc).__name__})
            return 503, {"status": "analysis_unavailable", "error_type": type(exc).__name__}


app = OrchestrationASGI()
