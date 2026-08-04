from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from monatise.application.persistence import DurableAuditRepository, DurableEventStore, DurableRecord, DurableStateManager, DurableTaskScheduler, PostgresDocumentStore
from monatise.infrastructure.audit_database import AuditAction, AuditActor, AuditRecordType
from monatise.infrastructure.audit_database import AuditQuery
from monatise.infrastructure.event_bus import DeliveryMode, DomainEvent, EventEnvelope, EventPriority
from monatise.infrastructure.state_manager import StateKey
from monatise.infrastructure.state_manager import StateConflictError, StateStatus
from monatise.infrastructure.task_scheduler import JobDefinition, ScheduleType


class MemoryDocumentStore:
    def __init__(self):
        self.documents = {}
        self.streams = {}

    async def put(self, namespace, key, value, **kwargs):
        old = self.documents.get((namespace, key))
        version = 1 if old is None else old.version + 1
        record = DurableRecord(namespace, key, value, version)
        self.documents[(namespace, key)] = record
        return record

    async def get(self, namespace, key): return self.documents.get((namespace, key))
    async def delete(self, namespace, key): self.documents.pop((namespace, key), None)
    async def append(self, stream, value): self.streams.setdefault(stream, []).append(value)
    async def read_stream(self, stream): return tuple(self.streams.get(stream, ()))


def test_durable_event_store_supports_idempotency_and_replay():
    async def scenario():
        backend = MemoryDocumentStore()
        store = DurableEventStore(backend)
        envelope = EventEnvelope.create(DomainEvent("analysis.started", {"value": 1}, "test", priority=EventPriority.HIGH), sequence=1, idempotency_key="one", delivery_mode=DeliveryMode.AT_LEAST_ONCE, max_attempts=3)
        assert await store.append(envelope)
        assert not await store.append(envelope)
        replay = await store.all()
        assert replay == (envelope,)
        replay[0].event.validate()
        assert await store.by_event_type("analysis.started") == replay
        replay[0].event.payload["value"] = 999
        assert (await store.all())[0].event.payload["value"] == 1
    asyncio.run(scenario())


def test_durable_state_manager_restores_into_a_new_process_cache():
    async def scenario():
        backend = MemoryDocumentStore()
        key = StateKey("pipeline", "run-1")
        first = DurableStateManager(backend)
        await first.set(key, {"status": "running"})
        await first.update(key, lambda value: {**value, "status": "complete"})
        second = DurableStateManager(backend)
        restored = await second.get(key)
        assert restored is not None
        assert restored.value == {"status": "complete"}
        assert restored.version == 2
        try:
            await second.set(key, {"status": "invalid"}, expected_version=1)
        except StateConflictError:
            pass
        else:
            raise AssertionError("expected state version conflict")
        await first.delete(key)
        third = DurableStateManager(backend)
        assert await third.get(key) is None
        tombstone = await third.get(key, include_deleted=True)
        assert tombstone is not None and tombstone.status is StateStatus.DELETED
    asyncio.run(scenario())


def test_durable_audit_repository_preserves_contract_and_streams_record():
    async def scenario():
        backend = MemoryDocumentStore()
        repository = DurableAuditRepository(backend)
        record = await repository.append(record_type=AuditRecordType.SYSTEM, action=AuditAction.CREATED, actor=AuditActor("test", "application"), source="test", payload={"safe": True}, created_at=datetime.now(timezone.utc))
        assert backend.streams["audit"][0]["record_id"] == record.record_id
        assert await repository.verify_integrity() == ()
        restored = DurableAuditRepository(backend)
        assert await restored.verify_integrity() == ()
        snapshot = await restored.snapshot()
        assert snapshot.records[0].record_id == record.record_id
        assert await restored.get(record.record_id) == record
        assert await restored.count() == 1
        assert await restored.query(AuditQuery(actor_id="test")) == (record,)
    asyncio.run(scenario())


def test_durable_audit_repository_restores_concurrent_rows_by_signed_sequence():
    async def scenario():
        backend = MemoryDocumentStore()
        repository = DurableAuditRepository(backend)
        first = await repository.append(
            record_type=AuditRecordType.SYSTEM,
            action=AuditAction.CREATED,
            actor=AuditActor("first", "application"),
            source="test",
            payload={"order": 1},
        )
        second = await repository.append(
            record_type=AuditRecordType.SYSTEM,
            action=AuditAction.CREATED,
            actor=AuditActor("second", "application"),
            source="test",
            payload={"order": 2},
        )
        backend.streams["audit"] = list(reversed(backend.streams["audit"]))

        restored = DurableAuditRepository(backend)

        assert await restored.verify_integrity() == ()
        snapshot = await restored.snapshot()
        assert [record.record_id for record in snapshot.records] == [first.record_id, second.record_id]

    asyncio.run(scenario())


def test_durable_audit_repository_serializes_concurrent_durable_appends():
    class DelayedDocumentStore(MemoryDocumentStore):
        async def append(self, stream, value):
            if value["sequence"] == 1:
                await asyncio.sleep(0.01)
            await super().append(stream, value)

    async def scenario():
        backend = DelayedDocumentStore()
        repository = DurableAuditRepository(backend)

        await asyncio.gather(*(
            repository.append(
                record_type=AuditRecordType.SYSTEM,
                action=AuditAction.CREATED,
                actor=AuditActor(f"actor-{index}", "application"),
                source="test",
                payload={"index": index},
            )
            for index in range(2)
        ))

        assert [value["sequence"] for value in backend.streams["audit"]] == [1, 2]
        assert await DurableAuditRepository(backend).verify_integrity() == ()

    asyncio.run(scenario())


def test_durable_audit_repository_rejects_missing_sequence_during_restoration():
    async def scenario():
        backend = MemoryDocumentStore()
        repository = DurableAuditRepository(backend)
        await repository.append(
            record_type=AuditRecordType.SYSTEM,
            action=AuditAction.CREATED,
            actor=AuditActor("test", "application"),
            source="test",
            payload={"safe": True},
        )
        backend.streams["audit"][0]["sequence"] = 2

        with pytest.raises(RuntimeError, match="sequence is incomplete"):
            await DurableAuditRepository(backend).verify_integrity()

    asyncio.run(scenario())


def test_durable_audit_repository_restores_unique_longest_fork_without_deleting_evidence():
    async def scenario():
        base = MemoryDocumentStore()
        await DurableAuditRepository(base).append(
            record_type=AuditRecordType.SYSTEM,
            action=AuditAction.CREATED,
            actor=AuditActor("base", "application"),
            source="test",
            payload={"branch": "base"},
        )
        left = MemoryDocumentStore()
        right = MemoryDocumentStore()
        left.streams["audit"] = list(base.streams["audit"])
        right.streams["audit"] = list(base.streams["audit"])
        await DurableAuditRepository(left).append(
            record_type=AuditRecordType.SYSTEM, action=AuditAction.CREATED,
            actor=AuditActor("left", "application"), source="test", payload={"branch": "left"},
        )
        right_repository = DurableAuditRepository(right)
        right_second = await right_repository.append(
            record_type=AuditRecordType.SYSTEM, action=AuditAction.CREATED,
            actor=AuditActor("right", "application"), source="test", payload={"branch": "right"},
        )
        right_third = await right_repository.append(
            record_type=AuditRecordType.SYSTEM, action=AuditAction.CREATED,
            actor=AuditActor("right", "application"), source="test", payload={"branch": "right-continued"},
        )
        combined = MemoryDocumentStore()
        combined.streams["audit"] = left.streams["audit"] + right.streams["audit"][1:]

        restored = DurableAuditRepository(combined)
        assert await restored.verify_integrity() == ()
        snapshot = await restored.snapshot()
        assert [record.record_id for record in snapshot.records[1:]] == [right_second.record_id, right_third.record_id]
        assert len(combined.streams["audit"]) == 4

    asyncio.run(scenario())


def test_durable_scheduler_restores_definition_with_code_owned_task():
    async def scenario():
        backend = MemoryDocumentStore()
        scheduler = DurableTaskScheduler(backend)

        async def task(): return "ok"

        await scheduler.register(JobDefinition("analysis", "Analysis", task, ScheduleType.INTERVAL, interval=timedelta(minutes=5)))
        restored = DurableTaskScheduler(backend)
        assert await restored.restore({"analysis": task}) == ("analysis",)
        definitions = await restored.definitions()
        assert definitions[0].interval == timedelta(minutes=5)
        result = await restored.run_now("analysis")
        assert result.successful
        assert backend.streams["scheduler_history"][0]["output"] == "ok"
        await restored.cancel("analysis")
        restarted = DurableTaskScheduler(backend)
        assert await restarted.restore({"analysis": task}) == ("analysis",)
        assert (await restarted.state_of("analysis")).value == "cancelled"
        assert len(await restored.query_execution_history("analysis")) == 1
    asyncio.run(scenario())


def test_postgres_store_supports_installed_psycopg_parameter_style():
    class Cursor:
        def fetchone(self): return (1,)

    class PsycopgConnection:
        def __init__(self): self.calls = []
        def execute(self, query, params):
            self.calls.append((query, params))
            return Cursor()

    async def scenario():
        connection = PsycopgConnection()
        record = await PostgresDocumentStore(connection).put("state", "one", {"ok": True})
        assert record.version == 1
        query, params = connection.calls[0]
        assert "$1" not in query and query.count("%s") == 4
        assert params == ("state", "one", '{"ok":true}', None)
    asyncio.run(scenario())
