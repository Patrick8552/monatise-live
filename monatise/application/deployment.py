"""Paper-only deployment lifecycle for the orchestration application."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping
from uuid import uuid4

from monatise.application.composition import create_application, create_durable_infrastructure
from monatise.application.registry import CANONICAL_ENGINE_ORDER
from monatise.application.persistence import PostgresDocumentStore


LOGGER = logging.getLogger("monatise.orchestration")
MIGRATION_LOCK_ID = 4_602_161_943_641_489_731
FALSE_VALUES = {"0", "false", "no", "off", "disabled", ""}


def _false(value: str | None) -> bool:
    return value is None or value.strip().casefold() in FALSE_VALUES


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

    async def acquire(self) -> bool:
        self.is_leader = bool(await self.client.set(self.key, self.token, nx=True, ex=self.ttl_seconds))
        if self.is_leader:
            self._renewal = asyncio.create_task(self._renew(), name="monatise-scheduler-leadership")
        return self.is_leader

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
        if self._renewal:
            self._renewal.cancel()
            await asyncio.gather(self._renewal, return_exceptions=True)
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


class _UnavailableMarketProvider:
    def latest_price(self, symbol: str) -> float:
        raise RuntimeError("market provider is not invoked during startup")

    def candles(self, symbol: str, limit: int, interval: str = "1m") -> list[Any]:
        raise RuntimeError("market provider is not invoked during startup")


class _UnavailableMacroProvider:
    def context_snapshot(self, symbol: str) -> dict[str, Any]:
        raise RuntimeError("macro provider is not invoked during startup")

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
    dependencies: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def start(self) -> None:
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
            self.application = create_application(
                market_data_providers={"deployment": _UnavailableMarketProvider()},
                macro_provider=_UnavailableMacroProvider(),
                infrastructure=infrastructure,
            )
            self.leadership = RedisSchedulerLeadership(
                self.redis, namespace=self.environment.get("MONATISE_REDIS_NAMESPACE", "monatise:paper-staging")
            )
            self.redis_coordination = RedisCoordinationStore(
                self.redis, namespace=self.environment.get("MONATISE_REDIS_NAMESPACE", "monatise:paper-staging")
            )
            leader = await self.leadership.acquire()
            await infrastructure.plugins.start_all()
            if leader:
                await infrastructure.scheduler.start()
            await infrastructure.observability.run_health_checks()
            for name in ("event_bus", "state_manager", "audit_repository", "scheduler", "pipeline_orchestrator"):
                self.dependencies[name] = {"status": "ok"}
            self.dependencies["scheduler"]["leader"] = leader
            self.dependencies["engine_registry"] = {
                "status": "ok", "count": len(self.application.registry.ordered()), "order": list(CANONICAL_ENGINE_ORDER)
            }
            self.dependencies["governance"] = {"status": "ok", "kill_switch": True}
            self.dependencies["notifications"] = {"status": "ok", "telegram": "notification_only", "openclaw": "non_executable"}
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
        registry_ok = bool(self.application and tuple(item.name for item in self.application.registry.ordered()) == CANONICAL_ENGINE_ORDER)
        mandatory = (
            "configuration", "postgresql", "migrations", "redis", "event_bus", "state_manager",
            "audit_repository", "scheduler", "engine_registry", "pipeline_orchestrator", "governance", "notifications",
        )
        ready = registry_ok and self.safety is not None and all(self.dependencies.get(key, {}).get("status") == "ok" for key in mandatory)
        return ready, {
            "status": "ready" if ready else "not_ready",
            "execution_enabled": False,
            "mode": "paper",
            "dependencies": self.dependencies,
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
        else:
            code, payload = 404, {"status": "not_found"}
        body = json.dumps(payload, separators=(",", ":")).encode()
        await send({"type": "http.response.start", "status": code, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


app = OrchestrationASGI()
