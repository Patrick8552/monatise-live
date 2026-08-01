import asyncio
from datetime import datetime, timedelta, timezone

from monatise.infrastructure.audit_database import (
    AuditAction,
    AuditActor,
    AuditError,
    AuditQuery,
    AuditRecordType,
    InMemoryAuditRepository,
)


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def actor() -> AuditActor:
    return AuditActor(
        actor_id="system",
        actor_type="service",
        display_name="Monatise",
    )


def test_append_and_get() -> None:
    async def run() -> None:
        repository = InMemoryAuditRepository()

        record = await repository.append(
            record_type=AuditRecordType.DECISION,
            action=AuditAction.CREATED,
            actor=actor(),
            source="decision_engine",
            payload={"classification": "trend"},
            symbol="BTCUSDT",
            created_at=NOW,
        )

        loaded = await repository.get(record.record_id)
        assert loaded is not None
        assert loaded.payload["classification"] == "trend"
        assert loaded.sequence == 1

    asyncio.run(run())


def test_hash_chain_integrity() -> None:
    async def run() -> None:
        repository = InMemoryAuditRepository()

        first = await repository.append(
            record_type=AuditRecordType.ENGINE_RESULT,
            action=AuditAction.CREATED,
            actor=actor(),
            source="regime_engine",
            payload={"state": "trend_up"},
            created_at=NOW,
        )
        second = await repository.append(
            record_type=AuditRecordType.RISK_VALIDATION,
            action=AuditAction.APPROVED,
            actor=actor(),
            source="risk_validation_engine",
            payload={"risk_score": 0.8},
            created_at=NOW + timedelta(seconds=1),
        )

        assert second.previous_hash == first.integrity_hash
        assert await repository.verify_integrity() == ()

    asyncio.run(run())


def test_query_filters() -> None:
    async def run() -> None:
        repository = InMemoryAuditRepository()

        await repository.append(
            record_type=AuditRecordType.DECISION,
            action=AuditAction.CREATED,
            actor=actor(),
            source="decision_engine",
            payload={},
            symbol="BTCUSDT",
            correlation_id="corr-1",
            created_at=NOW,
        )
        await repository.append(
            record_type=AuditRecordType.GOVERNANCE,
            action=AuditAction.BLOCKED,
            actor=actor(),
            source="governance_engine",
            payload={},
            symbol="ETHUSDT",
            correlation_id="corr-2",
            created_at=NOW,
        )

        records = await repository.query(
            AuditQuery(
                record_types=(AuditRecordType.GOVERNANCE,),
                symbol="ETHUSDT",
            )
        )

        assert len(records) == 1
        assert records[0].source == "governance_engine"

    asyncio.run(run())


def test_duplicate_record_id_is_rejected() -> None:
    async def run() -> None:
        repository = InMemoryAuditRepository()

        await repository.append(
            record_id="fixed",
            record_type=AuditRecordType.SYSTEM,
            action=AuditAction.CREATED,
            actor=actor(),
            source="system",
            payload={},
            created_at=NOW,
        )

        try:
            await repository.append(
                record_id="fixed",
                record_type=AuditRecordType.SYSTEM,
                action=AuditAction.CREATED,
                actor=actor(),
                source="system",
                payload={},
                created_at=NOW,
            )
        except AuditError as exc:
            assert "already exists" in str(exc)
        else:
            raise AssertionError("expected duplicate id rejection")

    asyncio.run(run())


def test_snapshot_is_append_only() -> None:
    async def run() -> None:
        repository = InMemoryAuditRepository()

        await repository.append(
            record_type=AuditRecordType.CONFIGURATION,
            action=AuditAction.FROZEN,
            actor=actor(),
            source="configuration_manager",
            payload={"version": 1},
            configuration_version=1,
            created_at=NOW,
        )

        snapshot = await repository.snapshot()

        assert snapshot.metadata["append_only"] is True
        assert snapshot.metadata["hash_chain_enabled"] is True
        assert snapshot.sequence == 1
        assert snapshot.append_only is True
        assert snapshot.hash_chain_enabled is True
        assert snapshot.execution_enabled is False

    asyncio.run(run())


def test_append_copies_payload_before_storage_and_hashing() -> None:
    async def run() -> None:
        repository = InMemoryAuditRepository()
        payload = {"nested": {"score": 1}}
        record = await repository.append(
            record_type=AuditRecordType.ENGINE_RESULT,
            action=AuditAction.CREATED,
            actor=actor(),
            source="regime_engine",
            payload=payload,
            created_at=NOW,
        )
        payload["nested"]["score"] = 999
        try:
            record.payload["nested"]["score"] = 500
        except TypeError:
            pass
        else:
            raise AssertionError("expected immutable audit record")

        stored = await repository.get(record.record_id)
        assert stored is not None
        assert stored.payload["nested"]["score"] == 1
        assert await repository.verify_integrity() == ()

    asyncio.run(run())


def test_snapshot_records_and_metadata_are_deeply_immutable() -> None:
    async def run() -> None:
        repository = InMemoryAuditRepository()
        await repository.append(
            record_type=AuditRecordType.SYSTEM,
            action=AuditAction.CREATED,
            actor=actor(),
            source="system",
            payload={"items": [1]},
            created_at=NOW,
        )
        snapshot = await repository.snapshot()

        try:
            snapshot.records[0].payload["items"] = (2,)
        except TypeError:
            pass
        else:
            raise AssertionError("expected immutable snapshot payload")
        try:
            snapshot.metadata["append_only"] = False
        except TypeError:
            pass
        else:
            raise AssertionError("expected immutable snapshot metadata")

    asyncio.run(run())


def test_query_validates_timezone_before_comparison() -> None:
    query = AuditQuery(
        created_from=datetime.now(),
        created_to=datetime.now(timezone.utc),
    )
    try:
        query.validate()
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("expected timezone validation failure")


def test_invalid_payload_does_not_consume_sequence() -> None:
    async def run() -> None:
        repository = InMemoryAuditRepository()
        try:
            await repository.append(
                record_type=AuditRecordType.SYSTEM,
                action=AuditAction.CREATED,
                actor=actor(),
                source="system",
                payload={"unstable": {1, 2}},
                created_at=NOW,
            )
        except ValueError as exc:
            assert "unsupported audit value type" in str(exc)
        else:
            raise AssertionError("expected canonicalization failure")

        record = await repository.append(
            record_type=AuditRecordType.SYSTEM,
            action=AuditAction.CREATED,
            actor=actor(),
            source="system",
            payload={},
            created_at=NOW,
        )
        assert record.sequence == 1

    asyncio.run(run())


def test_cyclic_payload_is_rejected_cleanly() -> None:
    async def run() -> None:
        repository = InMemoryAuditRepository()
        payload = {}
        payload["self"] = payload
        try:
            await repository.append(
                record_type=AuditRecordType.SYSTEM,
                action=AuditAction.CREATED,
                actor=actor(),
                source="system",
                payload=payload,
            )
        except ValueError as exc:
            assert "reference cycles" in str(exc)
        else:
            raise AssertionError("expected cyclic payload rejection")

    asyncio.run(run())


def test_audit_identifier_and_version_types_are_validated() -> None:
    async def run() -> None:
        repository = InMemoryAuditRepository()
        for kwargs in (
            {"source": 1},
            {"source": "system", "configuration_version": True},
        ):
            try:
                await repository.append(
                    record_type=AuditRecordType.SYSTEM,
                    action=AuditAction.CREATED,
                    actor=actor(),
                    payload={},
                    **kwargs,
                )
            except ValueError:
                pass
            else:
                raise AssertionError("expected audit type validation failure")

    asyncio.run(run())


def test_concurrent_appends_have_contiguous_hash_chain() -> None:
    async def run() -> None:
        repository = InMemoryAuditRepository()

        async def append(index: int):
            return await repository.append(
                record_id=f"record-{index}",
                record_type=AuditRecordType.SYSTEM,
                action=AuditAction.CREATED,
                actor=actor(),
                source="system",
                payload={"index": index},
                created_at=NOW,
            )

        records = await asyncio.gather(*(append(index) for index in range(100)))
        assert sorted(record.sequence for record in records) == list(range(1, 101))
        assert await repository.verify_integrity() == ()
        snapshot = await repository.snapshot()
        assert await repository.chain_head_hash() == snapshot.chain_head_hash

    asyncio.run(run())


def test_repository_has_no_mutation_or_execution_methods() -> None:
    repository = InMemoryAuditRepository()

    assert repository.append_only is True
    assert repository.execution_enabled is False
    assert not hasattr(repository, "update")
    assert not hasattr(repository, "delete")
    assert not hasattr(repository, "place_order")
