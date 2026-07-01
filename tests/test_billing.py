from __future__ import annotations

import hashlib
import hmac
import json

from monatise.live.billing import private_plan_user_id_from_event, verify_stripe_signature


def test_stripe_signature_verifies_signed_payload(monkeypatch) -> None:
    monkeypatch.setattr("monatise.live.billing.time.time", lambda: 1_000)
    body = json.dumps({"id": "evt_123"}).encode("utf-8")
    secret = "whsec_test"
    timestamp = 1_000
    signature = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode("utf-8") + body, hashlib.sha256).hexdigest()

    assert verify_stripe_signature(body, f"t={timestamp},v1={signature}", secret)
    assert not verify_stripe_signature(body, f"t={timestamp},v1=bad", secret)


def test_private_plan_user_id_from_checkout_event() -> None:
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "mode": "subscription",
                "client_reference_id": "42",
                "payment_status": "paid",
            }
        },
    }

    assert private_plan_user_id_from_event(event) == 42


def test_private_plan_user_id_rejects_unpaid_checkout_event() -> None:
    event = {
        "type": "checkout.session.completed",
        "data": {"object": {"mode": "subscription", "client_reference_id": "42", "payment_status": "unpaid"}},
    }

    assert private_plan_user_id_from_event(event) is None


def test_private_plan_user_id_from_active_subscription_event() -> None:
    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {"status": "active", "metadata": {"monatise_user_id": "42"}}},
    }

    assert private_plan_user_id_from_event(event) == 42
