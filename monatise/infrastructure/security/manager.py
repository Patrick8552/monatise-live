from __future__ import annotations

import hmac
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from json import dumps
from math import isfinite
from threading import RLock
from typing import Any

from monatise.infrastructure.security.models import (
    AccessDecision,
    ActorIdentity,
    Permission,
    ReplayProtectionError,
    SecurityError,
    SecurityEvent,
    SecurityPolicy,
    SecretReference,
    SignatureError,
    SignedRequest,
)


class SecurityManager:
    """Identity, authorization, request-integrity, and redaction service.

    Secret values remain outside this manager. Only references and verification
    keys used by the host application are accepted.
    """

    REDACTED = "***REDACTED***"

    def __init__(
        self,
        *,
        maximum_clock_skew_seconds: int = 300,
        sensitive_keys: tuple[str, ...] = (
            "api_key",
            "apikey",
            "secret",
            "token",
            "password",
            "private_key",
            "authorization",
        ),
    ) -> None:
        if (
            isinstance(maximum_clock_skew_seconds, bool)
            or not isinstance(maximum_clock_skew_seconds, int)
            or maximum_clock_skew_seconds < 1
        ):
            raise ValueError("maximum_clock_skew_seconds must be positive")
        if (
            not isinstance(sensitive_keys, tuple)
            or any(not isinstance(key, str) or not key.strip() for key in sensitive_keys)
        ):
            raise ValueError("sensitive_keys must contain non-empty strings")

        self._maximum_clock_skew = timedelta(
            seconds=maximum_clock_skew_seconds
        )
        self._sensitive_keys = {
            key.lower() for key in sensitive_keys
        }
        self._actors: dict[str, ActorIdentity] = {}
        self._policies: dict[tuple[str, str], SecurityPolicy] = {}
        self._verification_keys: dict[str, tuple[bytes, str]] = {}
        self._seen_nonces: dict[tuple[str, str], datetime] = {}
        self._events: list[SecurityEvent] = []
        self._lock = RLock()

    def register_actor(
        self,
        actor: ActorIdentity,
        *,
        replace: bool = False,
    ) -> None:
        actor.validate()
        with self._lock:
            if actor.actor_id in self._actors and not replace:
                raise SecurityError(
                    f"actor already registered: {actor.actor_id}"
                )
            self._actors[actor.actor_id] = deepcopy(actor)

    def register_policy(
        self,
        policy: SecurityPolicy,
        *,
        replace: bool = False,
    ) -> None:
        policy.validate()
        self._reject_execution_policy(policy.resource, policy.action)
        key = (policy.resource, policy.action)

        with self._lock:
            if key in self._policies and not replace:
                raise SecurityError(
                    f"security policy already registered: {key}"
                )
            self._policies[key] = deepcopy(policy)

    def authorize(
        self,
        actor_id: str,
        *,
        resource: str,
        action: str,
        correlation_id: str | None = None,
    ) -> AccessDecision:
        for value, name in (
            (actor_id, "actor_id"),
            (resource, "resource"),
            (action, "action"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        with self._lock:
            actor = self._actors.get(actor_id)
            policy = self._policies.get((resource, action))

        if actor is None:
            return self._record_decision(
                actor_id=actor_id,
                decision=AccessDecision.DENY,
                resource=resource,
                action=action,
                reason="actor is not registered",
                correlation_id=correlation_id,
            )

        if not actor.enabled:
            return self._record_decision(
                actor_id=actor_id,
                decision=AccessDecision.DENY,
                resource=resource,
                action=action,
                reason="actor is disabled",
                correlation_id=correlation_id,
            )

        if policy is None:
            return self._record_decision(
                actor_id=actor_id,
                decision=AccessDecision.DENY,
                resource=resource,
                action=action,
                reason="no matching security policy",
                correlation_id=correlation_id,
            )

        if (
            policy.allowed_actor_types
            and actor.actor_type not in policy.allowed_actor_types
        ):
            return self._record_decision(
                actor_id=actor_id,
                decision=AccessDecision.DENY,
                resource=resource,
                action=action,
                reason="actor type is not allowed",
                correlation_id=correlation_id,
            )

        actor_permissions = set(actor.permissions)
        required = set(policy.required_permissions)
        allowed = (
            required.issubset(actor_permissions)
            if policy.require_all
            else bool(required.intersection(actor_permissions))
        )

        return self._record_decision(
            actor_id=actor_id,
            decision=(
                AccessDecision.ALLOW
                if allowed
                else AccessDecision.DENY
            ),
            resource=resource,
            action=action,
            reason=(
                "required permissions satisfied"
                if allowed
                else "required permissions missing"
            ),
            correlation_id=correlation_id,
        )

    def register_verification_key(
        self,
        key_id: str,
        key: bytes,
        *,
        actor_id: str,
        replace: bool = False,
    ) -> None:
        if not isinstance(key_id, str) or not key_id.strip():
            raise ValueError("key_id is required")
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("verification key must contain at least 32 bytes")
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise ValueError("actor_id is required for verification keys")

        with self._lock:
            actor = self._actors.get(actor_id)
            if actor is None or not actor.enabled:
                raise SecurityError("verification key actor must be registered and enabled")
            if key_id in self._verification_keys and not replace:
                raise SecurityError(
                    f"verification key already registered: {key_id}"
                )
            self._verification_keys[key_id] = (bytes(key), actor_id)

    def verify_signed_request(
        self,
        request: SignedRequest,
        payload: dict[str, Any],
        *,
        observed_at: datetime | None = None,
    ) -> None:
        request.validate()
        now = observed_at or datetime.now(timezone.utc)
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("observed_at must be a timezone-aware datetime")
        now = now.astimezone(timezone.utc)

        timestamp = request.timestamp.astimezone(timezone.utc)

        if abs(now - timestamp) > self._maximum_clock_skew:
            raise SignatureError("signed request timestamp is outside allowed skew")

        with self._lock:
            self._purge_expired_nonces(now)
            nonce_key = (request.actor_id, request.nonce)
            if nonce_key in self._seen_nonces:
                raise ReplayProtectionError("request nonce has already been used")
            key_registration = self._verification_keys.get(request.key_id)
            actor = self._actors.get(request.actor_id)

        if actor is None or not actor.enabled:
            raise SignatureError("signed request actor is unknown or disabled")
        if key_registration is None:
            raise SignatureError("verification key is not registered")
        key, key_actor_id = key_registration
        if not hmac.compare_digest(key_actor_id, request.actor_id):
            raise SignatureError("verification key is not bound to request actor")

        payload_hash = self.hash_payload(payload)
        if not hmac.compare_digest(payload_hash, request.payload_hash):
            raise SignatureError("payload hash mismatch")

        message = self._signature_message(
            actor_id=request.actor_id,
            request_id=request.request_id,
            timestamp=timestamp,
            nonce=request.nonce,
            payload_hash=request.payload_hash,
            key_id=request.key_id,
        )
        expected = hmac.new(
            key,
            message.encode("utf-8"),
            sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, request.signature):
            raise SignatureError("request signature is invalid")

        with self._lock:
            self._purge_expired_nonces(now)
            current_actor = self._actors.get(request.actor_id)
            current_key = self._verification_keys.get(request.key_id)
            if current_actor is None or not current_actor.enabled:
                raise SignatureError("signed request actor is unknown or disabled")
            if current_key != key_registration:
                raise SignatureError("verification key changed during verification")
            if nonce_key in self._seen_nonces:
                raise ReplayProtectionError("request nonce has already been used")
            self._seen_nonces[nonce_key] = now + self._maximum_clock_skew

    def sign_request(
        self,
        *,
        actor_id: str,
        request_id: str,
        timestamp: datetime,
        nonce: str,
        payload: dict[str, Any],
        key_id: str,
        key: bytes,
    ) -> SignedRequest:
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("signing key must contain at least 32 bytes")
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            raise ValueError("timestamp must be a timezone-aware datetime")
        timestamp = timestamp.astimezone(timezone.utc)

        payload_hash = self.hash_payload(payload)
        message = self._signature_message(
            actor_id=actor_id,
            request_id=request_id,
            timestamp=timestamp,
            nonce=nonce,
            payload_hash=payload_hash,
            key_id=key_id,
        )
        signature = hmac.new(
            key,
            message.encode("utf-8"),
            sha256,
        ).hexdigest()

        request = SignedRequest(
            actor_id=actor_id,
            request_id=request_id,
            timestamp=timestamp,
            nonce=nonce,
            payload_hash=payload_hash,
            signature=signature,
            key_id=key_id,
        )
        request.validate()
        return request

    def validate_secret_reference(
        self,
        reference: SecretReference,
    ) -> SecretReference:
        reference.validate()
        safe = deepcopy(reference)
        if self.redact(safe.metadata) != safe.metadata:
            raise SecurityError("secret reference metadata cannot contain secret values")
        return safe

    def redact(self, value: Any) -> Any:
        return self._redact(value, set(), 0)

    def _redact(self, value: Any, active: set[int], depth: int) -> Any:
        if depth > 100:
            raise ValueError("redaction value exceeds maximum nesting depth")
        if isinstance(value, dict):
            identity = id(value)
            if identity in active:
                raise ValueError("redaction value cannot contain reference cycles")
            active.add(identity)
            try:
                return {
                key: (
                    self.REDACTED
                    if isinstance(key, str) and self._is_sensitive_key(key)
                    else self._redact(item, active, depth + 1)
                )
                for key, item in value.items()
                }
            finally:
                active.remove(identity)
        if isinstance(value, list):
            identity = id(value)
            if identity in active:
                raise ValueError("redaction value cannot contain reference cycles")
            active.add(identity)
            try:
                return [self._redact(item, active, depth + 1) for item in value]
            finally:
                active.remove(identity)
        if isinstance(value, tuple):
            identity = id(value)
            if identity in active:
                raise ValueError("redaction value cannot contain reference cycles")
            active.add(identity)
            try:
                return tuple(self._redact(item, active, depth + 1) for item in value)
            finally:
                active.remove(identity)
        return value

    def events(self) -> tuple[SecurityEvent, ...]:
        with self._lock:
            return tuple(deepcopy(self._events))

    def _record_decision(
        self,
        *,
        actor_id: str | None,
        decision: AccessDecision,
        resource: str,
        action: str,
        reason: str,
        correlation_id: str | None,
    ) -> AccessDecision:
        event = SecurityEvent(
            event_type="authorization.decision",
            actor_id=actor_id,
            decision=decision,
            resource=resource,
            action=action,
            reason=reason,
            created_at=datetime.now(timezone.utc),
            correlation_id=correlation_id,
        )
        with self._lock:
            self._events.append(event)
        return decision

    @staticmethod
    def hash_payload(payload: dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            raise ValueError("signed payload must be a dictionary")
        raw = dumps(
            SecurityManager._canonicalize(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _canonicalize(value: Any, active: set[int] | None = None, depth: int = 0) -> Any:
        if depth > 100:
            raise ValueError("signed payload exceeds maximum nesting depth")
        if value is None or isinstance(value, (bool, int, str)):
            return value
        if isinstance(value, float):
            if not isfinite(value):
                raise ValueError("signed payload cannot contain non-finite numbers")
            return value
        if isinstance(value, (list, dict)):
            seen = active if active is not None else set()
            identity = id(value)
            if identity in seen:
                raise ValueError("signed payload cannot contain reference cycles")
            seen.add(identity)
            try:
                if isinstance(value, dict):
                    if any(not isinstance(key, str) for key in value):
                        raise ValueError("signed payload keys must be strings")
                    return {key: SecurityManager._canonicalize(value[key], seen, depth + 1) for key in sorted(value)}
                return [SecurityManager._canonicalize(item, seen, depth + 1) for item in value]
            finally:
                seen.remove(identity)
        raise ValueError(f"unsupported signed payload type: {type(value).__name__}")

    def _is_sensitive_key(self, key: str) -> bool:
        normalized = "".join(char for char in key.casefold() if char.isalnum())
        sensitive = {
            "".join(char for char in item.casefold() if char.isalnum())
            for item in self._sensitive_keys
        }
        return normalized in sensitive or normalized.endswith(
            ("secret", "token", "password", "privatekey", "authorization")
        )

    def _purge_expired_nonces(self, now: datetime) -> None:
        self._seen_nonces = {
            nonce: expires_at
            for nonce, expires_at in self._seen_nonces.items()
            if expires_at >= now
        }

    @staticmethod
    def _reject_execution_policy(resource: str, action: str) -> None:
        resource_key = resource.casefold().replace("-", "_").replace(" ", "_")
        action_key = action.casefold().replace("-", "_").replace(" ", "_")
        forbidden_resources = {
            "order", "orders", "trade", "trades", "broker",
            "execution_adapter", "exchange_account", "withdrawal", "transfer",
        }
        forbidden_actions = {
            "place_order", "submit_order", "execute_trade", "trade",
            "withdraw", "transfer", "bypass_governance", "bypass_risk",
        }
        resource_parts = set(resource_key.split("_"))
        forbidden_resource_parts = {
            "order", "orders", "trade", "trades", "broker",
            "withdrawal", "withdrawals", "transfer", "transfers",
        }
        if (
            resource_key in forbidden_resources
            or resource_parts.intersection(forbidden_resource_parts)
            or action_key in forbidden_actions
            or action_key.startswith(("place_order", "submit_order", "execute_trade"))
        ):
            raise SecurityError("execution and governance-bypass policies are prohibited")

    @staticmethod
    def _signature_message(
        *,
        actor_id: str,
        request_id: str,
        timestamp: datetime,
        nonce: str,
        payload_hash: str,
        key_id: str,
    ) -> str:
        return dumps(
            [
                actor_id,
                request_id,
                timestamp.isoformat(),
                nonce,
                payload_hash,
                key_id,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @property
    def stores_secret_values(self) -> bool:
        return False

    @property
    def execution_authorization_available(self) -> bool:
        return False
