from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class FrozenDict(dict):
    """Deep-copy-safe immutable dictionary used by audit records."""

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("audit data is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable

    def __deepcopy__(self, memo: dict[int, Any]) -> "FrozenDict":
        return self


def freeze_audit_value(
    value: Any,
    *,
    _active: set[int] | None = None,
    _depth: int = 0,
) -> Any:
    if _depth > 100:
        raise ValueError("audit data exceeds maximum nesting depth")
    active = _active if _active is not None else set()
    if isinstance(value, (dict, list, tuple)):
        identity = id(value)
        if identity in active:
            raise ValueError("audit data cannot contain reference cycles")
        active.add(identity)
        try:
            if isinstance(value, dict):
                return FrozenDict({
                    key: freeze_audit_value(
                        item,
                        _active=active,
                        _depth=_depth + 1,
                    )
                    for key, item in value.items()
                })
            return tuple(
                freeze_audit_value(
                    item,
                    _active=active,
                    _depth=_depth + 1,
                )
                for item in value
            )
        finally:
            active.remove(identity)
    return value


class AuditRecordType(StrEnum):
    ENGINE_RESULT = "engine_result"
    DECISION = "decision"
    RISK_VALIDATION = "risk_validation"
    CAPITAL_ALLOCATION = "capital_allocation"
    EXECUTION_POLICY = "execution_policy"
    GOVERNANCE = "governance"
    CONFIGURATION = "configuration"
    INTEGRATION = "integration"
    SECURITY = "security"
    SYSTEM = "system"


class AuditAction(StrEnum):
    CREATED = "created"
    REVIEWED = "reviewed"
    BLOCKED = "blocked"
    APPROVED = "approved"
    REDUCED = "reduced"
    FAILED = "failed"
    FROZEN = "frozen"
    RESTORED = "restored"


class AuditError(RuntimeError):
    pass


class IntegrityError(AuditError):
    pass


@dataclass(frozen=True)
class AuditActor:
    actor_id: str
    actor_type: str
    display_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not isinstance(self.actor_id, str):
            raise ValueError("actor_id must be a string")
        if not isinstance(self.actor_type, str):
            raise ValueError("actor_type must be a string")
        if not self.actor_id.strip():
            raise ValueError("actor_id is required")
        if not self.actor_type.strip():
            raise ValueError("actor_type is required")
        if self.actor_id != self.actor_id.strip():
            raise ValueError("actor_id cannot have surrounding whitespace")
        if self.actor_type != self.actor_type.strip():
            raise ValueError("actor_type cannot have surrounding whitespace")
        if not isinstance(self.metadata, dict):
            raise ValueError("actor metadata must be a dictionary")


@dataclass(frozen=True)
class AuditRecord:
    record_id: str
    sequence: int
    record_type: AuditRecordType
    action: AuditAction
    actor: AuditActor
    source: str
    created_at: datetime
    payload: dict[str, Any]
    correlation_id: str | None
    causation_id: str | None
    symbol: str | None
    configuration_version: int | None
    previous_hash: str | None
    integrity_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not isinstance(self.record_id, str):
            raise ValueError("record_id must be a string")
        if not self.record_id.strip():
            raise ValueError("record_id is required")
        if self.sequence < 1:
            raise ValueError("sequence must be positive")
        if not self.source.strip():
            raise ValueError("source is required")
        if self.source != self.source.strip():
            raise ValueError("source cannot have surrounding whitespace")
        if not isinstance(self.record_type, AuditRecordType):
            raise ValueError("record_type is invalid")
        if not isinstance(self.action, AuditAction):
            raise ValueError("action is invalid")
        if not isinstance(self.created_at, datetime):
            raise ValueError("created_at must be a datetime")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if not isinstance(self.payload, dict):
            raise ValueError("payload must be a dictionary")
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be a dictionary")
        if not self.integrity_hash.strip():
            raise ValueError("integrity_hash is required")
        self.actor.validate()


@dataclass(frozen=True)
class AuditQuery:
    record_types: tuple[AuditRecordType, ...] = ()
    actions: tuple[AuditAction, ...] = ()
    actor_id: str | None = None
    source: str | None = None
    symbol: str | None = None
    correlation_id: str | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    limit: int | None = None

    def validate(self) -> None:
        if self.limit is not None and self.limit < 1:
            raise ValueError("limit must be positive")
        for value, name in (
            (self.created_from, "created_from"),
            (self.created_to, "created_to"),
        ):
            if value is not None:
                if not isinstance(value, datetime):
                    raise ValueError(f"{name} must be a datetime")
                if value.tzinfo is None:
                    raise ValueError(f"{name} must be timezone-aware")
        if (
            self.created_from is not None
            and self.created_to is not None
            and self.created_from > self.created_to
        ):
            raise ValueError("created_from must be <= created_to")
        if any(not isinstance(item, AuditRecordType) for item in self.record_types):
            raise ValueError("record_types contains an invalid value")
        if any(not isinstance(item, AuditAction) for item in self.actions):
            raise ValueError("actions contains an invalid value")


@dataclass(frozen=True)
class AuditSnapshot:
    records: tuple[AuditRecord, ...]
    created_at: datetime
    chain_head_hash: str | None
    sequence: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def append_only(self) -> bool:
        return True

    @property
    def hash_chain_enabled(self) -> bool:
        return True

    @property
    def execution_enabled(self) -> bool:
        return False
