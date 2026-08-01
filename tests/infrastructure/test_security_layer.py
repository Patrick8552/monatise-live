from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

from monatise.infrastructure.security import (
    AccessDecision,
    ActorIdentity,
    Permission,
    ReplayProtectionError,
    SecurityError,
    SecurityManager,
    SecurityPolicy,
    SecretReference,
    SignatureError,
)


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
KEY = b"monatise-test-verification-key-32-bytes-minimum"


def register_service(manager: SecurityManager, actor_id: str) -> None:
    manager.register_actor(ActorIdentity(
        actor_id=actor_id,
        actor_type="service",
        roles=("infrastructure",),
        permissions=(Permission.RUN_ANALYSIS,),
    ))


def test_permission_based_authorization() -> None:
    manager = SecurityManager()
    manager.register_actor(
        ActorIdentity(
            actor_id="reporter",
            actor_type="service",
            roles=("reporting",),
            permissions=(Permission.READ_REPORTS,),
        )
    )
    manager.register_policy(
        SecurityPolicy(
            resource="reports",
            action="read",
            required_permissions=(Permission.READ_REPORTS,),
        )
    )

    assert manager.authorize(
        "reporter",
        resource="reports",
        action="read",
    ) is AccessDecision.ALLOW


def test_missing_permission_is_denied() -> None:
    manager = SecurityManager()
    manager.register_actor(
        ActorIdentity(
            actor_id="viewer",
            actor_type="user",
            roles=("viewer",),
            permissions=(Permission.READ_REPORTS,),
        )
    )
    manager.register_policy(
        SecurityPolicy(
            resource="configuration",
            action="write",
            required_permissions=(Permission.MANAGE_CONFIGURATION,),
        )
    )

    assert manager.authorize(
        "viewer",
        resource="configuration",
        action="write",
    ) is AccessDecision.DENY


def test_signed_request_verification() -> None:
    manager = SecurityManager()
    key = KEY
    register_service(manager, "scheduler")
    manager.register_verification_key("key-1", key, actor_id="scheduler")
    payload = {"symbol": "BTCUSDT", "operation": "refresh"}

    signed = manager.sign_request(
        actor_id="scheduler",
        request_id="req-1",
        timestamp=NOW,
        nonce="nonce-1",
        payload=payload,
        key_id="key-1",
        key=key,
    )

    manager.verify_signed_request(
        signed,
        payload,
        observed_at=NOW,
    )


def test_replay_is_rejected() -> None:
    manager = SecurityManager()
    key = KEY
    register_service(manager, "service")
    manager.register_verification_key("key-1", key, actor_id="service")
    payload = {"value": 1}

    signed = manager.sign_request(
        actor_id="service",
        request_id="req",
        timestamp=NOW,
        nonce="same-nonce",
        payload=payload,
        key_id="key-1",
        key=key,
    )

    manager.verify_signed_request(signed, payload, observed_at=NOW)

    try:
        manager.verify_signed_request(signed, payload, observed_at=NOW)
    except ReplayProtectionError:
        pass
    else:
        raise AssertionError("expected replay rejection")


def test_stale_signature_is_rejected() -> None:
    manager = SecurityManager(maximum_clock_skew_seconds=60)
    key = KEY
    register_service(manager, "service")
    manager.register_verification_key("key-1", key, actor_id="service")
    payload = {"value": 1}

    signed = manager.sign_request(
        actor_id="service",
        request_id="req",
        timestamp=NOW - timedelta(minutes=5),
        nonce="nonce",
        payload=payload,
        key_id="key-1",
        key=key,
    )

    try:
        manager.verify_signed_request(signed, payload, observed_at=NOW)
    except SignatureError as exc:
        assert "timestamp" in str(exc)
    else:
        raise AssertionError("expected stale signature rejection")


def test_sensitive_values_are_redacted() -> None:
    manager = SecurityManager()

    redacted = manager.redact(
        {
            "api_key": "abc",
            "nested": {
                "password": "secret",
                "safe": "value",
            },
        }
    )

    assert redacted["api_key"] == manager.REDACTED
    assert redacted["nested"]["password"] == manager.REDACTED
    assert redacted["nested"]["safe"] == "value"


def test_secret_reference_does_not_contain_secret_value() -> None:
    manager = SecurityManager()
    reference = manager.validate_secret_reference(
        SecretReference(
            provider="vault",
            key="coinglass/api",
            version="1",
        )
    )

    assert reference.key == "coinglass/api"
    assert manager.stores_secret_values is False


def test_security_layer_cannot_authorize_execution() -> None:
    manager = SecurityManager()

    assert manager.execution_authorization_available is False
    assert not hasattr(manager, "place_order")
    assert not hasattr(manager, "submit_trade")


def test_execution_and_bypass_policies_are_rejected() -> None:
    manager = SecurityManager()
    for resource, action in (
        ("orders", "create"),
        ("governance", "bypass_governance"),
        ("risk", "bypass_risk"),
    ):
        try:
            manager.register_policy(SecurityPolicy(
                resource=resource,
                action=action,
                required_permissions=(Permission.RUN_ANALYSIS,),
            ))
        except SecurityError as exc:
            assert "prohibited" in str(exc)
        else:
            raise AssertionError("expected prohibited policy rejection")


def test_verification_key_is_bound_to_actor() -> None:
    manager = SecurityManager()
    register_service(manager, "first")
    register_service(manager, "second")
    manager.register_verification_key("key", KEY, actor_id="first")
    signed = manager.sign_request(
        actor_id="second",
        request_id="request",
        timestamp=NOW,
        nonce="nonce",
        payload={},
        key_id="key",
        key=KEY,
    )
    try:
        manager.verify_signed_request(signed, {}, observed_at=NOW)
    except SignatureError as exc:
        assert "not bound" in str(exc)
    else:
        raise AssertionError("expected actor binding failure")


def test_concurrent_replay_allows_exactly_one_request() -> None:
    manager = SecurityManager()
    register_service(manager, "service")
    manager.register_verification_key("key", KEY, actor_id="service")
    signed = manager.sign_request(
        actor_id="service",
        request_id="request",
        timestamp=NOW,
        nonce="concurrent",
        payload={"value": 1},
        key_id="key",
        key=KEY,
    )

    def verify():
        try:
            manager.verify_signed_request(signed, {"value": 1}, observed_at=NOW)
            return "accepted"
        except ReplayProtectionError:
            return "replayed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(lambda _: verify(), range(2)))
    assert outcomes == ["accepted", "replayed"]


def test_redaction_catches_composite_secret_names() -> None:
    manager = SecurityManager()
    redacted = manager.redact({
        "client_secret": "one",
        "access_token": "two",
        "privateKey": "three",
    })
    assert set(redacted.values()) == {manager.REDACTED}


def test_secret_reference_metadata_rejects_embedded_secret() -> None:
    manager = SecurityManager()
    try:
        manager.validate_secret_reference(SecretReference(
            provider="vault",
            key="service/key",
            metadata={"access_token": "plaintext"},
        ))
    except SecurityError as exc:
        assert "cannot contain secret values" in str(exc)
    else:
        raise AssertionError("expected secret metadata rejection")
