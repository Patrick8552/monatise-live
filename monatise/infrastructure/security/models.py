from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class Permission(StrEnum):
    READ_MARKET_DATA = "read_market_data"
    RUN_ANALYSIS = "run_analysis"
    READ_REPORTS = "read_reports"
    PUBLISH_NOTIFICATIONS = "publish_notifications"
    READ_AUDIT = "read_audit"
    WRITE_AUDIT = "write_audit"
    MANAGE_CONFIGURATION = "manage_configuration"
    MANAGE_PLUGINS = "manage_plugins"
    MANAGE_SCHEDULER = "manage_scheduler"
    MANAGE_FEATURE_FLAGS = "manage_feature_flags"


class AccessDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class SecurityError(RuntimeError):
    pass


class SignatureError(SecurityError):
    pass


class ReplayProtectionError(SecurityError):
    pass


@dataclass(frozen=True)
class ActorIdentity:
    actor_id: str
    actor_type: str
    roles: tuple[str, ...]
    permissions: tuple[Permission, ...]
    enabled: bool = True
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
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be boolean")
        if any(not isinstance(item, Permission) for item in self.permissions):
            raise ValueError("permissions contains an invalid value")
        if len(self.permissions) != len(set(self.permissions)):
            raise ValueError("permissions cannot contain duplicates")
        if any(not isinstance(role, str) or not role.strip() for role in self.roles):
            raise ValueError("roles must contain non-empty strings")
        if not isinstance(self.metadata, dict):
            raise ValueError("actor metadata must be a dictionary")


@dataclass(frozen=True)
class SecurityPolicy:
    resource: str
    action: str
    required_permissions: tuple[Permission, ...]
    require_all: bool = True
    allowed_actor_types: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not isinstance(self.resource, str) or not isinstance(self.action, str):
            raise ValueError("resource and action must be strings")
        if not self.resource.strip():
            raise ValueError("resource is required")
        if not self.action.strip():
            raise ValueError("action is required")
        if not self.required_permissions:
            raise ValueError("required_permissions cannot be empty")
        if any(not isinstance(item, Permission) for item in self.required_permissions):
            raise ValueError("required_permissions contains an invalid value")
        if len(self.required_permissions) != len(set(self.required_permissions)):
            raise ValueError("required_permissions cannot contain duplicates")
        if not isinstance(self.require_all, bool):
            raise ValueError("require_all must be boolean")
        if any(
            not isinstance(item, str) or not item.strip()
            for item in self.allowed_actor_types
        ):
            raise ValueError("allowed_actor_types must contain non-empty strings")
        if not isinstance(self.metadata, dict):
            raise ValueError("policy metadata must be a dictionary")


@dataclass(frozen=True)
class SecretReference:
    provider: str
    key: str
    version: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not isinstance(self.provider, str) or not isinstance(self.key, str):
            raise ValueError("secret provider and key must be strings")
        if not self.provider.strip():
            raise ValueError("secret provider is required")
        if not self.key.strip():
            raise ValueError("secret key is required")
        if self.version is not None and (
            not isinstance(self.version, str) or not self.version.strip()
        ):
            raise ValueError("secret version must be a non-empty string")
        if not isinstance(self.metadata, dict):
            raise ValueError("secret reference metadata must be a dictionary")


@dataclass(frozen=True)
class SignedRequest:
    actor_id: str
    request_id: str
    timestamp: datetime
    nonce: str
    payload_hash: str
    signature: str
    key_id: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        for name, value in {
            "actor_id": self.actor_id,
            "request_id": self.request_id,
            "nonce": self.nonce,
            "payload_hash": self.payload_hash,
            "signature": self.signature,
            "key_id": self.key_id,
        }.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
        if not isinstance(self.timestamp, datetime):
            raise ValueError("timestamp must be a datetime")
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        for value, name in (
            (self.payload_hash, "payload_hash"),
            (self.signature, "signature"),
        ):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
        if not isinstance(self.metadata, dict):
            raise ValueError("signed request metadata must be a dictionary")


@dataclass(frozen=True)
class SecurityEvent:
    event_type: str
    actor_id: str | None
    decision: AccessDecision
    resource: str
    action: str
    reason: str
    created_at: datetime
    correlation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
