from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from json import dumps
from math import isfinite
from typing import Any
from uuid import uuid4

from monatise.infrastructure.audit_database.models import (
    AuditAction,
    AuditActor,
    AuditError,
    AuditQuery,
    AuditRecord,
    AuditRecordType,
    AuditSnapshot,
    IntegrityError,
    freeze_audit_value,
)


class InMemoryAuditRepository:
    """Append-only audit repository with hash-chain integrity.

    This in-memory implementation is for tests and local development.
    Production may replace it with PostgreSQL or another durable store.
    """

    def __init__(
        self,
        *,
        base_sequence: int = 0,
        base_hash: str | None = None,
    ) -> None:
        if base_sequence < 0:
            raise ValueError("base_sequence cannot be negative")
        if base_sequence == 0 and base_hash is not None:
            raise ValueError("base_hash requires a positive base_sequence")
        if base_sequence > 0 and not base_hash:
            raise ValueError("base_hash is required for a positive base_sequence")
        self._records: list[AuditRecord] = []
        self._record_ids: set[str] = set()
        self._base_sequence = base_sequence
        self._base_hash = base_hash
        self._sequence = base_sequence
        self._lock = asyncio.Lock()

    async def append(
        self,
        *,
        record_type: AuditRecordType,
        action: AuditAction,
        actor: AuditActor,
        source: str,
        payload: dict,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        symbol: str | None = None,
        configuration_version: int | None = None,
        metadata: dict | None = None,
        record_id: str | None = None,
        created_at: datetime | None = None,
    ) -> AuditRecord:
        if not isinstance(record_type, AuditRecordType):
            raise ValueError("record_type is invalid")
        if not isinstance(action, AuditAction):
            raise ValueError("action is invalid")
        if not isinstance(actor, AuditActor):
            raise ValueError("actor must be an AuditActor")
        actor = replace(
            deepcopy(actor),
            metadata=freeze_audit_value(deepcopy(actor.metadata)),
        )
        actor.validate()
        if not isinstance(source, str):
            raise ValueError("source must be a string")
        if not source.strip():
            raise ValueError("source is required")
        if source != source.strip():
            raise ValueError("source cannot have surrounding whitespace")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dictionary")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be a dictionary")
        if configuration_version is not None:
            if isinstance(configuration_version, bool) or not isinstance(
                configuration_version,
                int,
            ):
                raise ValueError("configuration_version must be an integer")
            if configuration_version < 0:
                raise ValueError("configuration_version cannot be negative")
        if record_id is not None and not isinstance(record_id, str):
            raise ValueError("record_id must be a string")
        if record_id is not None and not record_id.strip():
            raise ValueError("record_id cannot be empty")
        if record_id is not None and record_id != record_id.strip():
            raise ValueError("record_id cannot have surrounding whitespace")
        for value, name in (
            (correlation_id, "correlation_id"),
            (causation_id, "causation_id"),
            (symbol, "symbol"),
        ):
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError(f"{name} must be a string")
                if not value.strip():
                    raise ValueError(f"{name} cannot be empty")

        safe_payload = freeze_audit_value(deepcopy(payload))
        safe_metadata = freeze_audit_value(deepcopy(metadata or {}))
        timestamp = created_at or datetime.now(timezone.utc)
        if not isinstance(timestamp, datetime):
            raise ValueError("created_at must be a datetime")
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)

        # Validate canonical serialization before reserving a sequence number.
        self._canonicalize(safe_payload)
        self._canonicalize(safe_metadata)
        self._canonicalize(actor.metadata)

        async with self._lock:
            actual_record_id = record_id or str(uuid4())
            if actual_record_id in self._record_ids:
                raise AuditError(
                    f"audit record id already exists: {actual_record_id}"
                )

            next_sequence = self._sequence + 1
            previous_hash = (
                self._records[-1].integrity_hash
                if self._records
                else self._base_hash
            )
            integrity_hash = self._hash_record(
                record_id=actual_record_id,
                sequence=next_sequence,
                record_type=record_type,
                action=action,
                actor=actor,
                source=source,
                created_at=timestamp,
                payload=safe_payload,
                correlation_id=correlation_id,
                causation_id=causation_id,
                symbol=symbol,
                configuration_version=configuration_version,
                previous_hash=previous_hash,
                metadata=safe_metadata,
            )

            record = AuditRecord(
                record_id=actual_record_id,
                sequence=next_sequence,
                record_type=record_type,
                action=action,
                actor=actor,
                source=source,
                created_at=timestamp,
                payload=safe_payload,
                correlation_id=correlation_id,
                causation_id=causation_id,
                symbol=symbol,
                configuration_version=configuration_version,
                previous_hash=previous_hash,
                integrity_hash=integrity_hash,
                metadata=safe_metadata,
            )
            record.validate()
            self._records.append(record)
            self._record_ids.add(actual_record_id)
            self._sequence = next_sequence
            return deepcopy(record)

    async def get(self, record_id: str) -> AuditRecord | None:
        async with self._lock:
            for record in self._records:
                if record.record_id == record_id:
                    return deepcopy(record)
        return None

    async def query(
        self,
        query: AuditQuery,
    ) -> tuple[AuditRecord, ...]:
        query.validate()

        async with self._lock:
            results = [
                record
                for record in self._records
                if self._matches(record, query)
            ]

            if query.limit is not None:
                results = results[-query.limit:]

            return tuple(deepcopy(results))

    async def verify_integrity(self) -> tuple[str, ...]:
        errors: list[str] = []

        async with self._lock:
            previous_hash = self._base_hash
            seen_ids: set[str] = set()

            for expected_sequence, record in enumerate(
                self._records,
                start=self._base_sequence + 1,
            ):
                if record.record_id in seen_ids:
                    errors.append(
                        f"duplicate record id in chain: {record.record_id}"
                    )
                seen_ids.add(record.record_id)
                if record.sequence != expected_sequence:
                    errors.append(
                        f"sequence mismatch for {record.record_id}: "
                        f"expected {expected_sequence}, got {record.sequence}"
                    )

                if record.previous_hash != previous_hash:
                    errors.append(
                        f"previous-hash mismatch for {record.record_id}"
                    )

                try:
                    record.validate()
                    expected_hash = self._hash_record(
                        record_id=record.record_id,
                        sequence=record.sequence,
                        record_type=record.record_type,
                        action=record.action,
                        actor=record.actor,
                        source=record.source,
                        created_at=record.created_at,
                        payload=record.payload,
                        correlation_id=record.correlation_id,
                        causation_id=record.causation_id,
                        symbol=record.symbol,
                        configuration_version=record.configuration_version,
                        previous_hash=record.previous_hash,
                        metadata=record.metadata,
                    )
                except (TypeError, ValueError) as exc:
                    errors.append(
                        f"invalid record {record.record_id}: {exc}"
                    )
                    expected_hash = None

                if (
                    expected_hash is not None
                    and record.integrity_hash != expected_hash
                ):
                    errors.append(
                        f"integrity-hash mismatch for {record.record_id}"
                    )

                previous_hash = record.integrity_hash

            expected_repository_sequence = self._base_sequence + len(self._records)
            if self._sequence != expected_repository_sequence:
                errors.append(
                    f"repository sequence mismatch: expected "
                    f"{expected_repository_sequence}, got {self._sequence}"
                )

        return tuple(errors)

    async def require_integrity(self) -> None:
        errors = await self.verify_integrity()
        if errors:
            raise IntegrityError(
                "audit integrity validation failed: "
                + "; ".join(errors)
            )

    async def snapshot(self) -> AuditSnapshot:
        async with self._lock:
            return AuditSnapshot(
                records=tuple(deepcopy(self._records)),
                created_at=datetime.now(timezone.utc),
                chain_head_hash=(
                    self._records[-1].integrity_hash
                    if self._records
                    else None
                ),
                sequence=self._sequence,
                metadata=freeze_audit_value({
                    "append_only": True,
                    "hash_chain_enabled": True,
                    "execution_enabled": False,
                    "base_sequence": self._base_sequence,
                }),
            )

    async def count(self) -> int:
        async with self._lock:
            return self._sequence

    async def chain_head_hash(self) -> str | None:
        async with self._lock:
            return self._records[-1].integrity_hash if self._records else self._base_hash

    @staticmethod
    def _matches(
        record: AuditRecord,
        query: AuditQuery,
    ) -> bool:
        if query.record_types and record.record_type not in query.record_types:
            return False
        if query.actions and record.action not in query.actions:
            return False
        if query.actor_id and record.actor.actor_id != query.actor_id:
            return False
        if query.source and record.source != query.source:
            return False
        if query.symbol and record.symbol != query.symbol:
            return False
        if (
            query.correlation_id
            and record.correlation_id != query.correlation_id
        ):
            return False
        if (
            query.created_from is not None
            and record.created_at < query.created_from
        ):
            return False
        if (
            query.created_to is not None
            and record.created_at > query.created_to
        ):
            return False
        return True

    @staticmethod
    def _hash_record(**values) -> str:
        actor = values["actor"]
        raw = dumps(
            InMemoryAuditRepository._canonicalize({
                **{
                    key: value
                    for key, value in values.items()
                    if key != "actor"
                },
                "actor": {
                    "actor_id": actor.actor_id,
                    "actor_type": actor.actor_type,
                    "display_name": actor.display_name,
                    "metadata": actor.metadata,
                },
            }),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _canonicalize(value: Any) -> Any:
        if value is None:
            return ["null"]
        if isinstance(value, bool):
            return ["bool", value]
        if isinstance(value, int):
            return ["int", str(value)]
        if isinstance(value, float):
            if not isfinite(value):
                raise ValueError("audit data cannot contain non-finite numbers")
            return ["float", repr(value)]
        if isinstance(value, str):
            return ["str", value]
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise ValueError("audit datetimes must be timezone-aware")
            normalized = value.astimezone(timezone.utc)
            return ["datetime", normalized.isoformat(timespec="microseconds")]
        if isinstance(value, list):
            return ["list", [
                InMemoryAuditRepository._canonicalize(item)
                for item in value
            ]]
        if isinstance(value, tuple):
            return ["tuple", [
                InMemoryAuditRepository._canonicalize(item)
                for item in value
            ]]
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise ValueError("audit dictionary keys must be strings")
            return ["dict", [
                [key, InMemoryAuditRepository._canonicalize(value[key])]
                for key in sorted(value)
            ]]
        raise ValueError(
            f"unsupported audit value type: {type(value).__name__}"
        )

    @property
    def append_only(self) -> bool:
        return True

    @property
    def execution_enabled(self) -> bool:
        return False
