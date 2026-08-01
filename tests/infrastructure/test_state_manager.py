import asyncio

from monatise.infrastructure.state_manager import (
    StateConflictError,
    StateError,
    StateKey,
    StateManager,
    StateStatus,
)


def test_set_and_get() -> None:
    async def run() -> None:
        manager = StateManager()
        key = StateKey("engine", "BTCUSDT:regime")

        stored = await manager.set(key, {"state": "trend_up"})
        loaded = await manager.get(key)

        assert stored.version == 1
        assert loaded is not None
        assert loaded.value["state"] == "trend_up"

    asyncio.run(run())


def test_atomic_update_increments_version() -> None:
    async def run() -> None:
        manager = StateManager()
        key = StateKey("workflow", "analysis-count")
        await manager.set(key, 1)

        updated = await manager.update(
            key,
            lambda value: value + 1,
            expected_version=1,
        )

        assert updated.value == 2
        assert updated.version == 2

    asyncio.run(run())


def test_compare_and_set_rejects_stale_version() -> None:
    async def run() -> None:
        manager = StateManager()
        key = StateKey("decision", "BTCUSDT")
        await manager.set(key, {"classification": "trend"})

        try:
            await manager.compare_and_set(
                key,
                expected_version=0,
                value={"classification": "no_trade"},
            )
        except StateConflictError as exc:
            assert "version conflict" in str(exc)
        else:
            raise AssertionError("expected state conflict")

    asyncio.run(run())


def test_ttl_expiry() -> None:
    async def run() -> None:
        manager = StateManager()
        key = StateKey("cache", "short-lived")
        await manager.set(key, "value", ttl_seconds=0.001)
        await asyncio.sleep(0.01)

        assert await manager.get(key) is None
        expired = await manager.get(key, include_expired=True)
        assert expired is not None
        assert expired.status is StateStatus.EXPIRED

    asyncio.run(run())


def test_delete_marks_tombstone() -> None:
    async def run() -> None:
        manager = StateManager()
        key = StateKey("workflow", "job")
        await manager.set(key, {"status": "running"})

        deleted = await manager.delete(key, expected_version=1)

        assert deleted is not None
        assert deleted.status is StateStatus.DELETED
        assert deleted.version == 2
        assert await manager.get(key) is None
        assert (await manager.get(key, include_deleted=True)) is not None

    asyncio.run(run())


def test_namespace_listing() -> None:
    async def run() -> None:
        manager = StateManager()
        await manager.set(StateKey("engine", "macro"), 1)
        await manager.set(StateKey("engine", "regime"), 2)
        await manager.set(StateKey("workflow", "run"), 3)

        entries = await manager.list_namespace("engine")
        assert tuple(item.state_key.key for item in entries) == (
            "macro",
            "regime",
        )

    asyncio.run(run())


def test_snapshot_and_restore() -> None:
    async def run() -> None:
        source = StateManager()
        await source.set(StateKey("engine", "macro"), {"score": 0.7})
        snapshot = await source.snapshot()

        target = StateManager()
        await target.restore(snapshot)

        restored = await target.require(StateKey("engine", "macro"))
        assert restored.value["score"] == 0.7

    asyncio.run(run())


def test_namespace_replacement_preserves_other_namespaces() -> None:
    async def run() -> None:
        source = StateManager()
        await source.set(StateKey("engine", "macro"), "new")
        snapshot = await source.snapshot(namespace="engine")

        target = StateManager()
        await target.set(StateKey("engine", "old"), "remove")
        await target.set(StateKey("workflow", "keep"), "safe")
        await target.restore(snapshot, replace_existing=True)

        assert await target.get(StateKey("engine", "old")) is None
        assert (await target.require(StateKey("engine", "macro"))).value == "new"
        assert (await target.require(StateKey("workflow", "keep"))).value == "safe"

    asyncio.run(run())


def test_concurrent_atomic_updates_do_not_lose_writes() -> None:
    async def run() -> None:
        manager = StateManager()
        key = StateKey("workflow", "counter")
        await manager.set(key, 0)

        await asyncio.gather(*(
            manager.update(key, lambda value: value + 1)
            for _ in range(100)
        ))

        entry = await manager.require(key)
        assert entry.value == 100
        assert entry.version == 101

    asyncio.run(run())


def test_expiry_is_a_versioned_state_transition() -> None:
    async def run() -> None:
        manager = StateManager()
        key = StateKey("cache", "versioned-expiry")
        await manager.set(key, "value", ttl_seconds=0.001)
        await asyncio.sleep(0.01)

        expired = await manager.get(key, include_expired=True)
        assert expired is not None
        assert expired.status is StateStatus.EXPIRED
        assert expired.version == 2

        try:
            await manager.compare_and_set(
                key,
                expected_version=1,
                value="stale",
            )
        except StateConflictError:
            pass
        else:
            raise AssertionError("expected expiry version conflict")

    asyncio.run(run())


def test_require_missing_state_raises() -> None:
    async def run() -> None:
        manager = StateManager()

        try:
            await manager.require(StateKey("missing", "value"))
        except StateError as exc:
            assert "required state is missing" in str(exc)
        else:
            raise AssertionError("expected missing-state error")

    asyncio.run(run())


def test_canonical_key_components_are_unambiguous() -> None:
    async def run() -> None:
        manager = StateManager()
        try:
            await manager.set(StateKey("engine:btc", "regime"), "value")
        except ValueError as exc:
            assert "namespace cannot contain ':'" in str(exc)
        else:
            raise AssertionError("expected ambiguous-key rejection")

    asyncio.run(run())


def test_async_updater_result_is_rejected_without_mutation() -> None:
    async def run() -> None:
        manager = StateManager()
        key = StateKey("workflow", "safe-update")
        await manager.set(key, 1)

        async def invalid_updater(value):
            return value + 1

        try:
            await manager.update(key, invalid_updater)
        except StateError as exc:
            assert "must return synchronously" in str(exc)
        else:
            raise AssertionError("expected updater rejection")

        entry = await manager.require(key)
        assert entry.value == 1
        assert entry.version == 1

    asyncio.run(run())


def test_manager_is_non_executable() -> None:
    manager = StateManager()

    assert manager.execution_enabled is False
    assert not hasattr(manager, "place_order")
    assert not hasattr(manager, "submit_trade")
