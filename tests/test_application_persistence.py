from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from monatise.application.persistence import AmbiguousDurableAuditChainError, DurableAuditRepository, DurableEventStore, DurableRecord, DurableStateManager, DurableTaskScheduler, PostgresDocumentStore
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
    async def read_stream_tail(self, stream, limit): return tuple(self.streams.get(stream, ())[-limit:])


def test_durable_audit_startup_uses_bounded_tail_and_preserves_chain_head():
    async def scenario():
        class CountingStore(MemoryDocumentStore):
            def __init__(self):
                super().__init__()
                self.full_reads = 0
                self.tail_reads = []

            async def read_stream(self, stream):
                self.full_reads += 1
                return await super().read_stream(stream)

            async def read_stream_tail(self, stream, limit):
                self.tail_reads.append((stream, limit))
                return await super().read_stream_tail(stream, limit)

        backend = CountingStore()
        writer = DurableAuditRepository(backend)
        records = []
        for index in range(8):
            records.append(await writer.append(
                record_type=AuditRecordType.SYSTEM,
                action=AuditAction.CREATED,
                actor=AuditActor("test", "application"),
                source="test",
                payload={"index": index},
            ))

        backend.full_reads = 0
        backend.tail_reads.clear()
        restored = DurableAuditRepository(backend, startup_window=3)
        assert await restored.verify_integrity() == ()
        assert backend.full_reads == 0
        assert backend.tail_reads == [("audit", 3)]
        assert await restored.count() == 8
        snapshot = await restored.snapshot()
        assert [record.sequence for record in snapshot.records] == [6, 7, 8]
        assert snapshot.metadata["base_sequence"] == 5

        appended = await restored.append(
            record_type=AuditRecordType.SYSTEM,
            action=AuditAction.CREATED,
            actor=AuditActor("test", "application"),
            source="test",
            payload={"index": 8},
        )
        assert appended.sequence == 9
        assert appended.previous_hash == records[-1].integrity_hash
        assert await restored.count() == 9

        assert await restored.verify_full_integrity() == ()
        assert backend.full_reads == 1

    asyncio.run(scenario())


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


def test_durable_audit_repository_ignores_higher_orphan_and_restores_complete_chain():
    async def scenario():
        backend = MemoryDocumentStore()
        repository = DurableAuditRepository(backend)
        await repository.append(
            record_type=AuditRecordType.SYSTEM, action=AuditAction.CREATED,
            actor=AuditActor("base", "application"), source="test", payload={"step": 1},
        )
        await repository.append(
            record_type=AuditRecordType.SYSTEM, action=AuditAction.CREATED,
            actor=AuditActor("base", "application"), source="test", payload={"step": 2},
        )
        orphan = dict(backend.streams["audit"][-1])
        orphan["sequence"] = 4
        orphan["previous_hash"] = "missing-parent-hash"
        orphan["integrity_hash"] = "orphan-hash"
        backend.streams["audit"].append(orphan)

        restored = DurableAuditRepository(backend)

        assert await restored.verify_integrity() == ()
        snapshot = await restored.snapshot()
        assert [record.sequence for record in snapshot.records] == [1, 2]
        assert len(backend.streams["audit"]) == 3

    asyncio.run(scenario())


def _tied_audit_stream():
    """Two branches that both sign the same next sequence off a shared
    ancestor -- a genuine tie at the true maximum, unlike the "longest fork"
    fixture above where only one branch ever reaches the maximum."""
    base = MemoryDocumentStore()

    async def build():
        await DurableAuditRepository(base).append(
            record_type=AuditRecordType.SYSTEM, action=AuditAction.CREATED,
            actor=AuditActor("base", "application"), source="test", payload={"branch": "base"},
        )
        left = MemoryDocumentStore()
        right = MemoryDocumentStore()
        left.streams["audit"] = list(base.streams["audit"])
        right.streams["audit"] = list(base.streams["audit"])
        await DurableAuditRepository(left).append(
            record_type=AuditRecordType.SYSTEM, action=AuditAction.CREATED,
            actor=AuditActor("left", "application"), source="test", payload={"branch": "left"},
        )
        await DurableAuditRepository(right).append(
            record_type=AuditRecordType.SYSTEM, action=AuditAction.CREATED,
            actor=AuditActor("right", "application"), source="test", payload={"branch": "right"},
        )
        tied = list(base.streams["audit"]) + [left.streams["audit"][-1], right.streams["audit"][-1]]
        return tied, left, right

    return asyncio.run(build())


def test_durable_audit_repository_deterministically_resolves_a_genuine_tie_after_exhausting_retries(monkeypatch):
    # A genuine tie (the losing writer's last append landed at the same
    # sequence the winner is still at, and the losing writer has since
    # exited) can never resolve by waiting -- neither branch will ever grow.
    # Startup must not fail forever in that case: after exhausting retries,
    # pick one branch deterministically and keep the other as forensic
    # evidence, exactly like an already-resolved fork.
    tied, left, right = _tied_audit_stream()
    expected_winner = left if left.streams["audit"][-1]["integrity_hash"] < right.streams["audit"][-1]["integrity_hash"] else right
    expected_branch = expected_winner.streams["audit"][-1]["payload"]["branch"]

    async def scenario():
        backend = MemoryDocumentStore()
        backend.streams["audit"] = tied
        sleeps = []
        real_sleep = asyncio.sleep
        monkeypatch.setattr(asyncio, "sleep", lambda seconds: sleeps.append(seconds) or real_sleep(0))

        assert await DurableAuditRepository(backend).verify_integrity() == ()

        # Retried up to the configured attempt count, not just once, and
        # actually paused between attempts rather than busy-looping --
        # still gives a transient tie every chance to resolve on its own
        # before falling back to the deterministic tiebreak.
        assert len(sleeps) == DurableAuditRepository._LOAD_RETRY_ATTEMPTS - 1
        assert all(delay == DurableAuditRepository._LOAD_RETRY_DELAY_SECONDS for delay in sleeps)

        # Exactly one of the two tied leaves was kept, not both, and the
        # stream itself is untouched -- the losing row stays as forensic
        # evidence rather than being deleted.
        snapshot = await DurableAuditRepository(backend).snapshot()
        assert [record.payload.get("branch") for record in snapshot.records] == ["base", expected_branch]
        assert len(backend.streams["audit"]) == 3

        # A second, independent instance restoring the same tied stream
        # converges on the same winner without any coordination.
        again_snapshot = await DurableAuditRepository(backend).snapshot()
        assert [record.payload.get("branch") for record in again_snapshot.records] == ["base", expected_branch]

    asyncio.run(scenario())


def test_durable_audit_repository_still_raises_ambiguous_before_the_final_retry_attempt():
    # force_resolve is only for the LAST attempt -- an earlier attempt must
    # still raise (not silently resolve early), so a transient tie keeps
    # getting a chance to extend naturally first.
    tied, _left, _right = _tied_audit_stream()
    with pytest.raises(AmbiguousDurableAuditChainError, match="ambiguous"):
        DurableAuditRepository._canonical_chain(tuple(tied))
    # But when forced (the final-attempt path), it resolves instead of raising.
    resolved = DurableAuditRepository._canonical_chain(tuple(tied), force_resolve=True)
    assert resolved[-1]["payload"]["branch"] in {"left", "right"}


def test_durable_audit_repository_recovers_once_a_transient_tie_is_extended(monkeypatch):
    tied, _left, right = _tied_audit_stream()

    async def scenario():
        class EventuallyResolvingStore(MemoryDocumentStore):
            def __init__(self):
                super().__init__()
                self.streams["audit"] = list(tied)
                self.reads = 0

            async def read_stream(self, stream):
                self.reads += 1
                if self.reads >= 3:
                    # The surviving process (the "right" branch) kept
                    # appending after the deploy overlap ended, extending
                    # its chain past the tie point -- exactly how a real
                    # rolling-deploy race resolves itself.
                    right_repository = DurableAuditRepository(right)
                    await right_repository.append(
                        record_type=AuditRecordType.SYSTEM, action=AuditAction.CREATED,
                        actor=AuditActor("right", "application"), source="test", payload={"branch": "right-continued"},
                    )
                    self.streams["audit"] = list(right.streams["audit"])
                return await super().read_stream(stream)

            async def read_stream_tail(self, stream, limit):
                values = await self.read_stream(stream)
                return values[-limit:]

        backend = EventuallyResolvingStore()
        real_sleep = asyncio.sleep
        monkeypatch.setattr(asyncio, "sleep", lambda seconds: real_sleep(0))

        # Does not raise -- the retry loop waits out the transient tie.
        assert await DurableAuditRepository(backend).verify_integrity() == ()
        assert backend.reads == 3

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


def test_durable_scheduler_skips_unchanged_definition_and_reuses_job_index():
    async def scenario():
        class CountingStore(MemoryDocumentStore):
            def __init__(self):
                super().__init__()
                self.puts = []
                self.gets = []

            async def put(self, namespace, key, value, **kwargs):
                self.puts.append((namespace, key))
                return await super().put(namespace, key, value, **kwargs)

            async def get(self, namespace, key):
                self.gets.append((namespace, key))
                return await super().get(namespace, key)

        backend = CountingStore()

        async def task(): return "ok"

        definition = JobDefinition("analysis", "Analysis", task, ScheduleType.INTERVAL, interval=timedelta(minutes=5))
        await DurableTaskScheduler(backend).register(definition)
        first_version = backend.documents[("scheduler", "analysis")].version
        backend.puts.clear()

        restarted = DurableTaskScheduler(backend)
        await restarted.register(definition)
        assert backend.puts == []
        assert backend.documents[("scheduler", "analysis")].version == first_version

        changed = JobDefinition("second", "Second", task, ScheduleType.INTERVAL, interval=timedelta(minutes=10))
        backend.gets.clear()
        await restarted.register(changed)
        assert backend.gets.count(("scheduler_indexes", "all")) == 0
        assert backend.puts == [("scheduler", "second"), ("scheduler_indexes", "all")]

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


def test_postgres_store_reads_only_the_requested_stream_tail():
    class AsyncpgConnection:
        def __init__(self):
            self.calls = []

        async def fetch(self, query, *args):
            self.calls.append((query, args))
            return [
                {"payload": {"sequence": 8}},
                {"payload": {"sequence": 9}},
            ]

    async def scenario():
        connection = AsyncpgConnection()
        values = await PostgresDocumentStore(connection).read_stream_tail("audit", 2)
        assert values == ({"sequence": 8}, {"sequence": 9})
        query, args = connection.calls[0]
        assert "ORDER BY sequence DESC LIMIT $2" in query
        assert query.endswith("ORDER BY sequence")
        assert args == ("audit", 2)

    asyncio.run(scenario())
