from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from copy import deepcopy
from typing import Any


class StateStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    DELETED = "deleted"


class StateError(RuntimeError):
    pass


class StateConflictError(StateError):
    pass


@dataclass(frozen=True)
class StateKey:
    namespace: str
    key: str

    def validate(self) -> None:
        if not self.namespace.strip():
            raise ValueError("state namespace is required")
        if not self.key.strip():
            raise ValueError("state key is required")
        if self.namespace != self.namespace.strip():
            raise ValueError("state namespace cannot have surrounding whitespace")
        if self.key != self.key.strip():
            raise ValueError("state key cannot have surrounding whitespace")
        if ":" in self.namespace:
            raise ValueError("state namespace cannot contain ':'")

    @property
    def canonical(self) -> str:
        return f"{self.namespace}:{self.key}"


@dataclass(frozen=True)
class StateEntry:
    state_key: StateKey
    value: Any
    version: int
    status: StateStatus
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return self.status is StateStatus.ACTIVE


@dataclass(frozen=True)
class StateSnapshot:
    namespace: str | None
    entries: tuple[StateEntry, ...]
    created_at: datetime
    sequence: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def read_only_snapshot(self) -> bool:
        return True

    @property
    def execution_enabled(self) -> bool:
        return False

    def as_dict(self) -> dict[str, Any]:
        return {
            entry.state_key.canonical: deepcopy(entry.value)
            for entry in self.entries
            if entry.status is StateStatus.ACTIVE
        }
