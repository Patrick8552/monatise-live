"""Swappable durable persistence boundaries for PostgreSQL and Redis."""

from __future__ import annotations

import json
import asyncio
import inspect
import re
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from time import perf_counter
from typing import Any, Protocol

from monatise.infrastructure.event_bus import DeliveryMode, DomainEvent, EventEnvelope, EventPriority
from monatise.infrastructure.state_manager import StateEntry, StateKey, StateManager, StateSnapshot, StateStatus
from monatise.infrastructure.audit_database import AuditAction, AuditActor, AuditQuery, AuditRecordType, InMemoryAuditRepository
from monatise.infrastructure.task_scheduler import JobDefinition, RetryPolicy, ScheduleType, TaskScheduler


class AsyncPostgresConnection(Protocol):
    async def execute(self, query: str, *args: Any) -> Any: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...
    async def fetch(self, query: str, *args: Any) -> Any: ...


class AsyncRedisClient(Protocol):
    async def get(self, key: str) -> Any: ...
    async def set(self, key: str, value: str, **kwargs: Any) -> Any: ...
    async def delete(self, key: str) -> Any: ...
    async def rpush(self, key: str, *values: str) -> Any: ...
    async def lrange(self, key: str, start: int, stop: int) -> Any: ...
    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any: ...


class DocumentStore(Protocol):
    async def put(self, namespace: str, key: str, value: dict[str, Any], **kwargs: Any) -> "DurableRecord": ...
    async def get(self, namespace: str, key: str) -> "DurableRecord | None": ...
    async def list_namespace(self, namespace: str) -> tuple["DurableRecord", ...]: ...
    async def delete(self, namespace: str, key: str) -> None: ...
    async def append(self, stream: str, value: dict[str, Any]) -> None: ...
    async def read_stream(self, stream: str) -> tuple[dict[str, Any], ...]: ...


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"value is not durably serializable: {type(value).__name__}")


@dataclass(frozen=True)
class DurableRecord:
    namespace: str
    key: str
    value: dict[str, Any]
    version: int


class PostgresDocumentStore:
    """Durable JSONB store used by state, scheduler, event, and audit adapters."""

    def __init__(self, connection: AsyncPostgresConnection, *, table: str = "monatise_application_documents", observer: Any | None = None) -> None:
        if not table.replace("_", "").isalnum():
            raise ValueError("invalid table name")
        self._connection, self._table = connection, table
        self._observer = observer

    async def put(self, namespace: str, key: str, value: dict[str, Any], *, expected_version: int | None = None) -> DurableRecord:
        payload = json.dumps(value, separators=(",", ":"), sort_keys=True)
        row = await self._fetchrow(
            f"INSERT INTO {self._table} (namespace, document_key, value, version) VALUES ($1,$2,$3::jsonb,1) "
            f"ON CONFLICT (namespace, document_key) DO UPDATE SET value=EXCLUDED.value, version={self._table}.version+1, updated_at=NOW() "
            f"WHERE {self._table}.version=COALESCE($4::bigint,{self._table}.version) RETURNING version",
            namespace, key, payload, expected_version,
        )
        if row is None:
            raise RuntimeError("durable state version conflict")
        version = row["version"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
        return DurableRecord(namespace, key, value, int(version))

    async def get(self, namespace: str, key: str) -> DurableRecord | None:
        row = await self._fetchrow(f"SELECT value, version FROM {self._table} WHERE namespace=$1 AND document_key=$2", namespace, key)
        if row is None:
            return None
        raw_value = row["value"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
        version = row["version"] if isinstance(row, dict) or hasattr(row, "keys") else row[1]
        value = raw_value if isinstance(raw_value, dict) else json.loads(raw_value)
        return DurableRecord(namespace, key, value, int(version))

    async def list_namespace(self, namespace: str) -> tuple[DurableRecord, ...]:
        rows = await self._fetch(
            f"SELECT document_key, value, version FROM {self._table} WHERE namespace=$1 ORDER BY document_key",
            namespace,
        )
        records = []
        for row in rows:
            key = row["document_key"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
            raw_value = row["value"] if isinstance(row, dict) or hasattr(row, "keys") else row[1]
            version = row["version"] if isinstance(row, dict) or hasattr(row, "keys") else row[2]
            value = raw_value if isinstance(raw_value, dict) else json.loads(raw_value)
            records.append(DurableRecord(namespace, key, value, int(version)))
        return tuple(records)

    async def delete(self, namespace: str, key: str) -> None:
        await self._execute(f"DELETE FROM {self._table} WHERE namespace=$1 AND document_key=$2", namespace, key)

    async def append(self, stream: str, value: dict[str, Any]) -> None:
        await self._execute("INSERT INTO monatise_application_streams (stream, payload) VALUES ($1,$2::jsonb)", stream, json.dumps(value, separators=(",", ":"), sort_keys=True))

    async def read_stream(self, stream: str) -> tuple[dict[str, Any], ...]:
        rows = await self._fetch("SELECT payload FROM monatise_application_streams WHERE stream=$1 ORDER BY sequence", stream)
        values = []
        for row in rows:
            payload = row["payload"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
            values.append(payload if isinstance(payload, dict) else json.loads(payload))
        return tuple(values)

    async def _execute(self, query: str, *args: Any) -> Any:
        started = perf_counter()
        try:
            if callable(getattr(self._connection, "fetchrow", None)):
                result = self._connection.execute(query, *args)
            else:
                result = self._connection.execute(self._driver_query(query), args)
            value = await result if inspect.isawaitable(result) else result
            self._observe("postgres.operation", {"operation": "execute", "success": True, "duration_ms": (perf_counter() - started) * 1000})
            return value
        except Exception:
            self._observe("postgres.operation", {"operation": "execute", "success": False, "duration_ms": (perf_counter() - started) * 1000})
            raise

    async def _fetchrow(self, query: str, *args: Any) -> Any:
        fetchrow = getattr(self._connection, "fetchrow", None)
        if callable(fetchrow):
            return await fetchrow(query, *args)
        cursor = await self._execute(query, *args)
        result = cursor.fetchone()
        return await result if inspect.isawaitable(result) else result

    async def _fetch(self, query: str, *args: Any) -> Any:
        fetch = getattr(self._connection, "fetch", None)
        if callable(fetch):
            return await fetch(query, *args)
        cursor = await self._execute(query, *args)
        result = cursor.fetchall()
        return await result if inspect.isawaitable(result) else result

    def _driver_query(self, query: str) -> str:
        if callable(getattr(self._connection, "fetchrow", None)):
            return query
        return re.sub(r"\$\d+", "%s", query)

    def _observe(self, event: str, fields: dict[str, Any]) -> None:
        try:
            if self._observer is not None:
                self._observer(event, fields)
        except Exception:
            return


class RedisDocumentStore:
    _PUT_SCRIPT = """
local current = redis.call('GET', KEYS[1])
local version = 1
if current then version = (cjson.decode(current).version or 0) + 1 end
local document = cjson.encode({version=version, value=cjson.decode(ARGV[1])})
if tonumber(ARGV[2]) > 0 then redis.call('SET', KEYS[1], document, 'EX', ARGV[2]) else redis.call('SET', KEYS[1], document) end
return version
"""
    def __init__(self, client: AsyncRedisClient, *, prefix: str = "monatise", observer: Any | None = None) -> None:
        self._client, self._prefix = client, prefix.strip(":")
        self._lock = asyncio.Lock()
        self._observer = observer

    def _key(self, namespace: str, key: str) -> str:
        return f"{self._prefix}:{namespace}:{key}"

    async def put(self, namespace: str, key: str, value: dict[str, Any], *, ttl_seconds: int | None = None) -> DurableRecord:
        document_key = self._key(namespace, key)
        evaluator = getattr(self._client, "eval", None)
        if callable(evaluator):
            version = await self._call("put", lambda: evaluator(self._PUT_SCRIPT, 1, document_key, json.dumps(value, separators=(",", ":"), sort_keys=True), int(ttl_seconds or 0)))
            return DurableRecord(namespace, key, value, int(version))
        async with self._lock:
            current = await self.get(namespace, key)
            version = 1 if current is None else current.version + 1
            await self._call("put", lambda: self._client.set(document_key, json.dumps({"version": version, "value": value}, separators=(",", ":"), sort_keys=True), **({"ex": ttl_seconds} if ttl_seconds else {})))
            return DurableRecord(namespace, key, value, version)

    async def get(self, namespace: str, key: str) -> DurableRecord | None:
        raw = await self._call("get", lambda: self._client.get(self._key(namespace, key)))
        if raw is None:
            return None
        document = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        return DurableRecord(namespace, key, document["value"], int(document["version"]))

    async def delete(self, namespace: str, key: str) -> None:
        await self._call("delete", lambda: self._client.delete(self._key(namespace, key)))

    async def append(self, stream: str, value: dict[str, Any]) -> None:
        await self._call("append", lambda: self._client.rpush(self._key("stream", stream), json.dumps(value, separators=(",", ":"), sort_keys=True)))

    async def read_stream(self, stream: str) -> tuple[dict[str, Any], ...]:
        rows = await self._call("read_stream", lambda: self._client.lrange(self._key("stream", stream), 0, -1))
        return tuple(json.loads(row.decode() if isinstance(row, bytes) else row) for row in rows)

    async def _call(self, operation: str, factory: Any) -> Any:
        started = perf_counter()
        try:
            result = await factory()
            self._observe("redis.operation", {"operation": operation, "success": True, "duration_ms": (perf_counter() - started) * 1000})
            return result
        except Exception:
            self._observe("redis.operation", {"operation": operation, "success": False, "duration_ms": (perf_counter() - started) * 1000})
            raise

    def _observe(self, event: str, fields: dict[str, Any]) -> None:
        try:
            if self._observer is not None:
                self._observer(event, fields)
        except Exception:
            return


class AmbiguousDurableAuditChainError(RuntimeError):
    """Two equally-valid endpoint chains were found while restoring the
    audit stream. Expected transiently during a zero-downtime rolling
    deploy, where the outgoing and incoming process briefly append to the
    same stream and may sign the same next sequence -- the losing branch's
    writer typically stops within seconds. Distinct from a genuinely
    incomplete or invalid chain, which will not resolve by waiting."""


class DurableAuditRepository:
    """AuditRepository-compatible append-through durable adapter."""

    _LOAD_RETRY_ATTEMPTS = 6
    _LOAD_RETRY_DELAY_SECONDS = 3.0

    def __init__(self, store: DocumentStore) -> None:
        self._store = store
        self._repository = InMemoryAuditRepository()
        self._loaded = False
        self._load_lock = asyncio.Lock()
        self._append_lock = asyncio.Lock()

    async def append(self, **kwargs: Any) -> Any:
        await self._ensure_loaded()
        # Keep the in-memory hash-chain order and durable stream insertion order
        # aligned even when independent engines append concurrently.
        async with self._append_lock:
            record = await self._repository.append(**kwargs)
            await self._store.append("audit", _json_value(record))
            return record

    async def query(self, query: AuditQuery) -> Any:
        await self._ensure_loaded()
        return await self._repository.query(query)

    async def get(self, record_id: str) -> Any:
        await self._ensure_loaded()
        return await self._repository.get(record_id)

    async def count(self) -> int:
        await self._ensure_loaded()
        return await self._repository.count()

    async def verify_integrity(self) -> tuple[str, ...]:
        await self._ensure_loaded()
        return await self._repository.verify_integrity()

    async def require_integrity(self) -> None:
        await self._ensure_loaded()
        await self._repository.require_integrity()

    async def snapshot(self) -> Any:
        await self._ensure_loaded()
        return await self._repository.snapshot()

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        async with self._load_lock:
            if self._loaded:
                return
            ordered_values: tuple[dict[str, Any], ...] = ()
            for attempt in range(1, self._LOAD_RETRY_ATTEMPTS + 1):
                values = await self._store.read_stream("audit")
                try:
                    # force_resolve only on the final attempt: give a
                    # transient rolling-deploy fork every earlier attempt to
                    # resolve itself as one side appends further (the
                    # common case), and only fall back to a deterministic
                    # tiebreak if it's still genuinely tied once retries are
                    # exhausted -- e.g. because the losing writer already
                    # exited and nothing will ever extend either branch
                    # further, which would otherwise fail startup forever.
                    ordered_values = self._canonical_chain(values, force_resolve=attempt == self._LOAD_RETRY_ATTEMPTS)
                    break
                except AmbiguousDurableAuditChainError:
                    await asyncio.sleep(self._LOAD_RETRY_DELAY_SECONDS)
            for value in ordered_values:
                actor = value["actor"]
                record = await self._repository.append(
                    record_type=AuditRecordType(value["record_type"]), action=AuditAction(value["action"]),
                    actor=AuditActor(actor["actor_id"], actor["actor_type"], actor.get("display_name"), actor.get("metadata", {})),
                    source=value["source"], payload=value["payload"], correlation_id=value.get("correlation_id"),
                    causation_id=value.get("causation_id"), symbol=value.get("symbol"), configuration_version=value.get("configuration_version"),
                    metadata=value.get("metadata", {}), record_id=value["record_id"], created_at=datetime.fromisoformat(value["created_at"]),
                )
                if (
                    record.sequence != int(value["sequence"])
                    or record.previous_hash != value.get("previous_hash")
                    or record.integrity_hash != value["integrity_hash"]
                ):
                    raise RuntimeError("durable audit integrity verification failed during restoration")
            self._loaded = True

    @staticmethod
    def _canonical_chain(values: tuple[dict[str, Any], ...], *, force_resolve: bool = False) -> tuple[dict[str, Any], ...]:
        """Restore the uniquely longest valid chain while retaining orphaned fork rows.

        Rolling deployments can briefly run two processes against the same append-only
        stream. Both may sign the same next sequence. Descendants identify the branch
        that remained active; the other rows stay untouched as forensic evidence.

        force_resolve=True: an equally-long fork is still possible (the losing
        writer's very last append happened to land at the same sequence the
        winner is still at). Normally that's left to resolve itself as one
        side gets a descendant on a later retry -- but if the losing writer
        has already exited, neither branch will ever grow, and refusing to
        pick one would fail startup indefinitely. When forced, every replica
        restoring this same fork computes the same by-integrity-hash
        ordering and picks the same lexicographically-smallest endpoint, so
        independent instances converge on the same canonical branch without
        needing to coordinate -- the losing branch's rows remain in the
        stream, untouched, as forensic evidence, exactly as for a resolved
        fork.
        """
        if not values:
            return ()
        try:
            by_hash = {value["integrity_hash"]: value for value in values}
            if len(by_hash) != len(values):
                raise RuntimeError("durable audit hash is duplicated during restoration")
            maximum = max(int(value["sequence"]) for value in values)
            endpoints = [value for value in values if int(value["sequence"]) == maximum]
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("durable audit sequence is invalid during restoration") from exc

        chains: list[tuple[dict[str, Any], ...]] = []
        for endpoint in endpoints:
            reverse_chain: list[dict[str, Any]] = []
            current: dict[str, Any] | None = endpoint
            expected = maximum
            seen: set[str] = set()
            while current is not None and expected > 0:
                integrity_hash = current["integrity_hash"]
                if integrity_hash in seen or int(current["sequence"]) != expected:
                    break
                seen.add(integrity_hash)
                reverse_chain.append(current)
                previous_hash = current.get("previous_hash")
                current = by_hash.get(previous_hash) if previous_hash is not None else None
                expected -= 1
            if expected == 0 and current is None:
                chains.append(tuple(reversed(reverse_chain)))

        if len(chains) != 1:
            if not chains:
                raise RuntimeError("durable audit sequence is incomplete during restoration")
            if not force_resolve:
                raise AmbiguousDurableAuditChainError("durable audit sequence is ambiguous during restoration")
            chains.sort(key=lambda chain: chain[-1]["integrity_hash"])
        return chains[0]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._repository, name)

    @property
    def append_only(self) -> bool:
        return True

    @property
    def execution_enabled(self) -> bool:
        return False


class DurableEventStore:
    """EventStore-compatible adapter with durable idempotency and replay."""

    def __init__(self, store: DocumentStore) -> None:
        self._store = store
        self._lock = asyncio.Lock()

    async def contains_idempotency_key(self, key: str) -> bool:
        return await self._store.get("event_idempotency", key) is not None

    async def append(self, envelope: EventEnvelope) -> bool:
        async with self._lock:
            if await self.contains_idempotency_key(envelope.idempotency_key):
                return False
            index = await self._event_ids()
            await self._store.put("events", envelope.event_id, _json_value(envelope))
            await self._store.put("event_idempotency", envelope.idempotency_key, {"event_id": envelope.event_id})
            await self._store.put("event_indexes", "all", {"event_ids": [*index, envelope.event_id]})
            return True

    async def all(self) -> tuple[EventEnvelope, ...]:
        events = []
        for event_id in await self._event_ids():
            record = await self._store.get("events", event_id)
            if record is not None:
                events.append(self._deserialize(record.value))
        return tuple(events)

    async def by_event_type(self, event_type: str) -> tuple[EventEnvelope, ...]:
        return tuple(item for item in await self.all() if item.event.event_type == event_type)

    async def _event_ids(self) -> list[str]:
        record = await self._store.get("event_indexes", "all")
        return list(record.value.get("event_ids", ())) if record else []

    @staticmethod
    def _deserialize(value: dict[str, Any]) -> EventEnvelope:
        value = deepcopy(value)
        event = value["event"]
        return EventEnvelope(
            event_id=value["event_id"],
            event=DomainEvent(
                event_type=event["event_type"], payload=event["payload"], source=event["source"],
                symbol=event.get("symbol"), correlation_id=event.get("correlation_id"), causation_id=event.get("causation_id"),
                priority=EventPriority(event.get("priority", "normal")), schema_version=event.get("schema_version", 1), metadata=event.get("metadata", {}),
            ),
            created_at=datetime.fromisoformat(value["created_at"]), sequence=int(value["sequence"]),
            idempotency_key=value["idempotency_key"], delivery_mode=DeliveryMode(value["delivery_mode"]),
            attempt=int(value.get("attempt", 1)), max_attempts=int(value.get("max_attempts", 3)),
        )


class DurableTaskScheduler:
    """TaskScheduler-compatible adapter that persists recoverable job metadata."""

    def __init__(self, store: DocumentStore, scheduler: TaskScheduler | None = None) -> None:
        self._store = store
        self._scheduler = scheduler or TaskScheduler()
        self._lock = asyncio.Lock()

    async def register(self, definition: Any) -> None:
        async with self._lock:
            await self._scheduler.register(definition)
            retry = definition.retry_policy
            await self.save_job_definition(definition.job_id, {
                "job_id": definition.job_id, "name": definition.name, "schedule_type": definition.schedule_type.value,
                "run_at": definition.run_at.isoformat() if definition.run_at else None,
                "interval_seconds": definition.interval.total_seconds() if definition.interval else None,
                "timeout_seconds": definition.timeout_seconds, "enabled": definition.enabled,
                "tags": list(definition.tags), "metadata": _json_value(definition.metadata),
                "retry": {"maximum_attempts": retry.maximum_attempts, "delay_seconds": retry.delay_seconds, "backoff_multiplier": retry.backoff_multiplier, "maximum_delay_seconds": retry.maximum_delay_seconds},
            })

    async def unregister(self, job_id: str) -> None:
        await self._scheduler.unregister(job_id)
        await self.delete_job_persistence(job_id)

    async def restore(self, task_factories: dict[str, Any]) -> tuple[str, ...]:
        """Restore definitions while requiring code-owned callable factories."""
        index = await self._store.get("scheduler_indexes", "all")
        restored = []
        for job_id in (index.value.get("job_ids", ()) if index else ()):
            record = await self._store.get("scheduler", job_id)
            if record is None:
                continue
            task = task_factories.get(job_id)
            if task is None:
                raise KeyError(f"scheduler task factory is missing: {job_id}")
            value = record.value
            retry = value["retry"]
            definition = JobDefinition(
                job_id=value["job_id"], name=value["name"], task=task, schedule_type=ScheduleType(value["schedule_type"]),
                run_at=datetime.fromisoformat(value["run_at"]) if value["run_at"] else None,
                interval=timedelta(seconds=value["interval_seconds"]) if value["interval_seconds"] else None,
                timeout_seconds=value["timeout_seconds"], retry_policy=RetryPolicy(**retry), enabled=value["enabled"],
                tags=tuple(value["tags"]), metadata=value["metadata"],
            )
            await self._scheduler.register(definition)
            persisted_state = await self._store.get("scheduler_state", job_id)
            state = persisted_state.value.get("state") if persisted_state else None
            if state == "paused":
                await self._scheduler.pause(job_id)
            elif state == "cancelled":
                await self._scheduler.cancel(job_id)
            restored.append(job_id)
        return tuple(restored)

    async def pause(self, job_id: str) -> None:
        await self._scheduler.pause(job_id)
        await self._persist_state(job_id)

    async def resume(self, job_id: str) -> None:
        await self._scheduler.resume(job_id)
        await self._persist_state(job_id)

    async def cancel(self, job_id: str) -> None:
        await self._scheduler.cancel(job_id)
        await self._persist_state(job_id)

    async def run_now(self, job_id: str) -> Any:
        result = await self._scheduler.run_now(job_id)
        await self._persist_state(job_id)
        await self.append_execution_history(_json_value(result))
        return result

    async def _persist_state(self, job_id: str) -> None:
        state = await self._scheduler.state_of(job_id)
        await self.save_job_state(job_id, {"state": state.value})

    async def save_job_definition(self, job_id: str, value: dict[str, Any]) -> None:
        await self._store.put("scheduler", job_id, value)
        index = await self._store.get("scheduler_indexes", "all")
        job_ids = list(index.value.get("job_ids", ())) if index else []
        if job_id not in job_ids:
            await self._store.put("scheduler_indexes", "all", {"job_ids": [*job_ids, job_id]})

    async def load_job_definitions(self) -> tuple[dict[str, Any], ...]:
        index = await self._store.get("scheduler_indexes", "all")
        values = []
        for job_id in (index.value.get("job_ids", ()) if index else ()):
            record = await self._store.get("scheduler", job_id)
            if record is not None:
                values.append(record.value)
        return tuple(values)

    async def save_job_state(self, job_id: str, value: dict[str, Any]) -> None:
        await self._store.put("scheduler_state", job_id, value)

    async def load_job_state(self, job_id: str) -> dict[str, Any] | None:
        record = await self._store.get("scheduler_state", job_id)
        return record.value if record else None

    async def append_execution_history(self, value: dict[str, Any]) -> None:
        await self._store.append("scheduler_history", value)

    async def query_execution_history(self, job_id: str | None = None) -> tuple[dict[str, Any], ...]:
        values = await self._store.read_stream("scheduler_history")
        return tuple(value for value in values if job_id is None or value.get("job_id") == job_id)

    async def delete_job_persistence(self, job_id: str) -> None:
        await self._store.delete("scheduler", job_id)
        await self._store.delete("scheduler_state", job_id)
        index = await self._store.get("scheduler_indexes", "all")
        if index:
            await self._store.put("scheduler_indexes", "all", {"job_ids": [item for item in index.value.get("job_ids", ()) if item != job_id]})

    def __getattr__(self, name: str) -> Any:
        return getattr(self._scheduler, name)


class DurableStateManager:
    """StateManager-compatible adapter with read-through restoration."""

    def __init__(self, store: DocumentStore, manager: StateManager | None = None) -> None:
        self._store = store
        self._manager = manager or StateManager()
        self._loaded = False
        self._load_lock = asyncio.Lock()

    async def set(self, state_key: StateKey, value: Any, **kwargs: Any) -> Any:
        await self._ensure_loaded()
        entry = await self._manager.set(state_key, value, **kwargs)
        await self._persist_snapshot()
        return entry

    async def get(self, state_key: StateKey, **kwargs: Any) -> Any:
        await self._ensure_loaded()
        return await self._manager.get(state_key, **kwargs)

    async def require(self, state_key: StateKey) -> Any:
        await self._ensure_loaded()
        return await self._manager.require(state_key)

    async def delete(self, state_key: StateKey, **kwargs: Any) -> Any:
        await self._ensure_loaded()
        result = await self._manager.delete(state_key, **kwargs)
        await self._persist_snapshot()
        return result

    async def update(self, state_key: StateKey, updater: Any, **kwargs: Any) -> Any:
        await self._ensure_loaded()
        entry = await self._manager.update(state_key, updater, **kwargs)
        await self._persist_snapshot()
        return entry

    async def compare_and_set(self, state_key: StateKey, expected_value: Any, new_value: Any, **kwargs: Any) -> Any:
        await self._ensure_loaded()
        entry = await self._manager.compare_and_set(state_key, expected_value, new_value, **kwargs)
        if entry is not None:
            await self._persist_snapshot()
        return entry

    async def list_namespace(self, namespace: str, **kwargs: Any) -> Any:
        await self._ensure_loaded()
        return await self._manager.list_namespace(namespace, **kwargs)

    async def snapshot(self, namespace: str | None = None, **kwargs: Any) -> StateSnapshot:
        await self._ensure_loaded()
        return await self._manager.snapshot(namespace, **kwargs)

    async def restore(self, snapshot: StateSnapshot, **kwargs: Any) -> None:
        await self._ensure_loaded()
        await self._manager.restore(snapshot, **kwargs)
        await self._persist_snapshot()

    async def purge_expired(self) -> int:
        await self._ensure_loaded()
        count = await self._manager.purge_expired()
        await self._persist_snapshot()
        return count

    async def _persist_snapshot(self) -> None:
        snapshot = await self._manager.snapshot(include_expired=True, include_deleted=True)
        await self._store.put("state_snapshots", "all", _json_value(snapshot))

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        async with self._load_lock:
            if self._loaded:
                return
            record = await self._store.get("state_snapshots", "all")
            if record is not None:
                value = record.value
                entries = tuple(StateEntry(
                    state_key=StateKey(item["state_key"]["namespace"], item["state_key"]["key"]),
                    value=item["value"], version=int(item["version"]), status=StateStatus(item["status"]),
                    created_at=datetime.fromisoformat(item["created_at"]), updated_at=datetime.fromisoformat(item["updated_at"]),
                    expires_at=datetime.fromisoformat(item["expires_at"]) if item.get("expires_at") else None,
                    metadata=item.get("metadata", {}),
                ) for item in value["entries"])
                snapshot = StateSnapshot(value.get("namespace"), entries, datetime.fromisoformat(value["created_at"]), int(value["sequence"]), value.get("metadata", {}))
                await self._manager.restore(snapshot)
            self._loaded = True

    def __getattr__(self, name: str) -> Any:
        return getattr(self._manager, name)

    @property
    def execution_enabled(self) -> bool:
        return False


# Compatibility aliases retained for callers of the initial orchestration build.
AuditStoreAdapter = DurableAuditRepository
EventStoreAdapter = DurableEventStore
SchedulerStoreAdapter = DurableTaskScheduler
StateStoreAdapter = DurableStateManager


class PostgresEventStore(DurableEventStore):
    def __init__(self, connection: AsyncPostgresConnection) -> None:
        super().__init__(PostgresDocumentStore(connection))


class PostgresAuditRepository(DurableAuditRepository):
    def __init__(self, connection: AsyncPostgresConnection) -> None:
        super().__init__(PostgresDocumentStore(connection))


class PostgresStateManager(DurableStateManager):
    def __init__(self, connection: AsyncPostgresConnection) -> None:
        super().__init__(PostgresDocumentStore(connection))


class PostgresTaskScheduler(DurableTaskScheduler):
    def __init__(self, connection: AsyncPostgresConnection) -> None:
        super().__init__(PostgresDocumentStore(connection))


class RedisEventStore(DurableEventStore):
    """Redis event replay/deduplication; not a replacement for durable audit."""
    def __init__(self, client: AsyncRedisClient, *, prefix: str = "monatise") -> None:
        super().__init__(RedisDocumentStore(client, prefix=prefix))


class RedisStateManager(DurableStateManager):
    """Redis state for transient workflows with explicit backend TTL support."""
    def __init__(self, client: AsyncRedisClient, *, prefix: str = "monatise") -> None:
        super().__init__(RedisDocumentStore(client, prefix=prefix))


class RedisTaskScheduler(DurableTaskScheduler):
    def __init__(self, client: AsyncRedisClient, *, prefix: str = "monatise") -> None:
        super().__init__(RedisDocumentStore(client, prefix=prefix))


async def connect_postgres_store(dsn: str, *, table: str = "monatise_application_documents") -> tuple[PostgresDocumentStore, Any]:
    """Open the installed psycopg async driver and return store plus owned connection."""
    if not isinstance(dsn, str) or not dsn.strip():
        raise ValueError("PostgreSQL DSN is required")
    import psycopg

    connection = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
    return PostgresDocumentStore(connection, table=table), connection


def connect_redis_store(url: str, *, prefix: str = "monatise") -> tuple[RedisDocumentStore, Any]:
    """Open the installed redis asyncio driver and return store plus owned client."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Redis URL is required")
    from redis.asyncio import Redis

    client = Redis.from_url(url, decode_responses=True)
    return RedisDocumentStore(client, prefix=prefix), client
