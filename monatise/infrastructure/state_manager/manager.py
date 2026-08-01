from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from inspect import isawaitable
from math import isfinite
from typing import Any, Callable

from monatise.infrastructure.state_manager.models import (
    StateConflictError,
    StateEntry,
    StateError,
    StateKey,
    StateSnapshot,
    StateStatus,
)


UpdateCallable = Callable[[Any], Any]


class StateManager:
    """Versioned in-memory state manager with atomic update semantics.

    Engines may store workflow and analytical state here, but the manager does
    not contain trading logic, execution adapters, or secret material.
    """

    def __init__(self) -> None:
        self._entries: dict[str, StateEntry] = {}
        self._global_lock = asyncio.Lock()
        self._sequence = 0

    async def set(
        self,
        state_key: StateKey,
        value: Any,
        *,
        ttl_seconds: float | None = None,
        expected_version: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StateEntry:
        state_key.validate()
        if ttl_seconds is not None and (
            not isfinite(ttl_seconds) or ttl_seconds <= 0
        ):
            raise ValueError("ttl_seconds must be finite and positive")

        async with self._global_lock:
            now = datetime.now(timezone.utc)
            current = self._materialize_expiry(state_key.canonical, now)

            if expected_version is not None:
                actual_version = current.version if current is not None else 0
                if actual_version != expected_version:
                    raise StateConflictError(
                        f"version conflict for {state_key.canonical}: "
                        f"expected {expected_version}, actual {actual_version}"
                    )

            version = (current.version if current is not None else 0) + 1
            created_at = current.created_at if current is not None else now
            expires_at = (
                now + timedelta(seconds=ttl_seconds)
                if ttl_seconds is not None
                else None
            )

            entry = StateEntry(
                state_key=state_key,
                value=deepcopy(value),
                version=version,
                status=StateStatus.ACTIVE,
                created_at=created_at,
                updated_at=now,
                expires_at=expires_at,
                metadata=deepcopy(metadata or {}),
            )
            self._entries[state_key.canonical] = entry
            self._sequence += 1
            return deepcopy(entry)

    async def get(
        self,
        state_key: StateKey,
        *,
        include_expired: bool = False,
        include_deleted: bool = False,
    ) -> StateEntry | None:
        state_key.validate()
        async with self._global_lock:
            current = self._materialize_expiry(
                state_key.canonical,
                datetime.now(timezone.utc),
            )
            if current is None:
                return None
            if (
                current.status is StateStatus.EXPIRED
                and not include_expired
            ):
                return None
            if (
                current.status is StateStatus.DELETED
                and not include_deleted
            ):
                return None
            return deepcopy(current)

    async def require(self, state_key: StateKey) -> StateEntry:
        entry = await self.get(state_key)
        if entry is None:
            raise StateError(
                f"required state is missing: {state_key.canonical}"
            )
        return entry

    async def update(
        self,
        state_key: StateKey,
        updater: UpdateCallable,
        *,
        expected_version: int | None = None,
        ttl_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StateEntry:
        state_key.validate()
        if not callable(updater):
            raise ValueError("updater must be callable")
        if ttl_seconds is not None and (
            not isfinite(ttl_seconds) or ttl_seconds <= 0
        ):
            raise ValueError("ttl_seconds must be finite and positive")

        async with self._global_lock:
            now = datetime.now(timezone.utc)
            current = self._materialize_expiry(state_key.canonical, now)

            if current is None or current.status is not StateStatus.ACTIVE:
                raise StateError(
                    f"cannot update missing state: {state_key.canonical}"
                )

            if (
                expected_version is not None
                and current.version != expected_version
            ):
                raise StateConflictError(
                    f"version conflict for {state_key.canonical}: "
                    f"expected {expected_version}, actual {current.version}"
                )

            try:
                new_value = updater(deepcopy(current.value))
                if isawaitable(new_value):
                    close = getattr(new_value, "close", None)
                    if callable(close):
                        close()
                    raise TypeError("state updater must return synchronously")
            except Exception as exc:
                raise StateError(
                    f"state updater failed for {state_key.canonical}: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc

            expires_at = (
                now + timedelta(seconds=ttl_seconds)
                if ttl_seconds is not None
                else current.expires_at
            )
            entry = StateEntry(
                state_key=state_key,
                value=deepcopy(new_value),
                version=current.version + 1,
                status=StateStatus.ACTIVE,
                created_at=current.created_at,
                updated_at=now,
                expires_at=expires_at,
                metadata=deepcopy(
                    metadata if metadata is not None else current.metadata
                ),
            )
            self._entries[state_key.canonical] = entry
            self._sequence += 1
            return deepcopy(entry)

    async def compare_and_set(
        self,
        state_key: StateKey,
        *,
        expected_version: int,
        value: Any,
        ttl_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StateEntry:
        return await self.set(
            state_key,
            value,
            ttl_seconds=ttl_seconds,
            expected_version=expected_version,
            metadata=metadata,
        )

    async def delete(
        self,
        state_key: StateKey,
        *,
        expected_version: int | None = None,
    ) -> StateEntry | None:
        state_key.validate()
        async with self._global_lock:
            current = self._materialize_expiry(
                state_key.canonical,
                datetime.now(timezone.utc),
            )
            if current is None:
                return None

            if (
                expected_version is not None
                and current.version != expected_version
            ):
                raise StateConflictError(
                    f"version conflict for {state_key.canonical}: "
                    f"expected {expected_version}, actual {current.version}"
                )

            now = datetime.now(timezone.utc)
            deleted = StateEntry(
                state_key=current.state_key,
                value=None,
                version=current.version + 1,
                status=StateStatus.DELETED,
                created_at=current.created_at,
                updated_at=now,
                expires_at=None,
                metadata=current.metadata,
            )
            self._entries[state_key.canonical] = deleted
            self._sequence += 1
            return deepcopy(deleted)

    async def list_namespace(
        self,
        namespace: str,
        *,
        include_expired: bool = False,
        include_deleted: bool = False,
    ) -> tuple[StateEntry, ...]:
        if not namespace.strip():
            raise ValueError("namespace is required")

        now = datetime.now(timezone.utc)
        results: list[StateEntry] = []

        async with self._global_lock:
            for canonical, entry in list(self._entries.items()):
                if entry.state_key.namespace != namespace:
                    continue

                updated = self._materialize_expiry(canonical, now)
                if updated is None:
                    continue

                if (
                    updated.status is StateStatus.EXPIRED
                    and not include_expired
                ):
                    continue
                if (
                    updated.status is StateStatus.DELETED
                    and not include_deleted
                ):
                    continue
                results.append(deepcopy(updated))

        return tuple(
            sorted(
                results,
                key=lambda item: item.state_key.key,
            )
        )

    async def snapshot(
        self,
        namespace: str | None = None,
        *,
        include_expired: bool = False,
        include_deleted: bool = False,
    ) -> StateSnapshot:
        now = datetime.now(timezone.utc)
        entries: list[StateEntry] = []

        async with self._global_lock:
            for canonical, entry in list(self._entries.items()):
                updated = self._materialize_expiry(canonical, now)
                if updated is None:
                    continue

                if (
                    namespace is not None
                    and updated.state_key.namespace != namespace
                ):
                    continue
                if (
                    updated.status is StateStatus.EXPIRED
                    and not include_expired
                ):
                    continue
                if (
                    updated.status is StateStatus.DELETED
                    and not include_deleted
                ):
                    continue
                entries.append(deepcopy(updated))

            sequence = self._sequence

        return StateSnapshot(
            namespace=namespace,
            entries=tuple(
                sorted(
                    entries,
                    key=lambda item: item.state_key.canonical,
                )
            ),
            created_at=now,
            sequence=sequence,
            metadata={
                "read_only_snapshot": True,
                "execution_enabled": False,
            },
        )

    async def restore(
        self,
        snapshot: StateSnapshot,
        *,
        replace_existing: bool = False,
    ) -> None:
        if not isinstance(snapshot, StateSnapshot):
            raise ValueError("snapshot must be a StateSnapshot")
        snapshot = deepcopy(snapshot)
        self._validate_snapshot(snapshot)

        async with self._global_lock:
            if replace_existing:
                if snapshot.namespace is None:
                    self._entries.clear()
                else:
                    self._entries = {
                        canonical: entry
                        for canonical, entry in self._entries.items()
                        if entry.state_key.namespace != snapshot.namespace
                    }

            for entry in snapshot.entries:
                canonical = entry.state_key.canonical
                current = self._entries.get(canonical)

                if (
                    current is not None
                    and not replace_existing
                    and current.version >= entry.version
                ):
                    continue

                self._entries[canonical] = deepcopy(entry)

            self._sequence = max(self._sequence, snapshot.sequence) + 1

    async def purge_expired(self) -> int:
        now = datetime.now(timezone.utc)
        removed = 0

        async with self._global_lock:
            for canonical, entry in list(self._entries.items()):
                updated = self._expire_if_needed(entry, now)
                if updated.status is StateStatus.EXPIRED:
                    del self._entries[canonical]
                    removed += 1
                else:
                    self._entries[canonical] = updated

            if removed:
                self._sequence += 1

        return removed

    def _materialize_expiry(
        self,
        canonical: str,
        now: datetime,
    ) -> StateEntry | None:
        current = self._entries.get(canonical)
        updated = self._expire_if_needed(current, now)
        if updated is not current and updated is not None:
            updated = StateEntry(
                state_key=updated.state_key,
                value=updated.value,
                version=updated.version + 1,
                status=updated.status,
                created_at=updated.created_at,
                updated_at=updated.updated_at,
                expires_at=updated.expires_at,
                metadata=updated.metadata,
            )
            self._entries[canonical] = updated
            self._sequence += 1
        return updated

    @staticmethod
    def _validate_snapshot(snapshot: StateSnapshot) -> None:
        if snapshot.sequence < 0:
            raise ValueError("snapshot sequence cannot be negative")
        seen: set[str] = set()
        for entry in snapshot.entries:
            if not isinstance(entry, StateEntry):
                raise ValueError("snapshot entries must be StateEntry values")
            entry.state_key.validate()
            canonical = entry.state_key.canonical
            if canonical in seen:
                raise ValueError(f"duplicate snapshot state key: {canonical}")
            seen.add(canonical)
            if entry.version < 1:
                raise ValueError("snapshot entry version must be positive")
            if not isinstance(entry.status, StateStatus):
                raise ValueError("snapshot entry status is invalid")
            if (
                snapshot.namespace is not None
                and entry.state_key.namespace != snapshot.namespace
            ):
                raise ValueError("snapshot entry is outside its namespace")

    @staticmethod
    def _expire_if_needed(
        entry: StateEntry | None,
        now: datetime,
    ) -> StateEntry | None:
        if entry is None:
            return None
        if entry.status is not StateStatus.ACTIVE:
            return entry
        if entry.expires_at is None or now < entry.expires_at:
            return entry

        return StateEntry(
            state_key=entry.state_key,
            value=entry.value,
            version=entry.version,
            status=StateStatus.EXPIRED,
            created_at=entry.created_at,
            updated_at=now,
            expires_at=entry.expires_at,
            metadata=entry.metadata,
        )

    @property
    def execution_enabled(self) -> bool:
        return False
