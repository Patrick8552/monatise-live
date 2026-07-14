from __future__ import annotations

import hashlib
import hmac
import json
from contextlib import contextmanager
from urllib.parse import parse_qs

from monatise.live.billing import StripeBillingConfig, create_private_checkout_session, private_plan_user_id_from_event, verify_stripe_signature


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


def test_private_checkout_session_marks_usdc_only() -> None:
    captured = {}

    @contextmanager
    def fake_opener(request, timeout=15):  # noqa: ANN001, ARG001
        captured["body"] = request.data.decode("utf-8")

        class Response:
            def read(self) -> bytes:
                return json.dumps({"id": "cs_test", "url": "https://checkout.stripe.test/session"}).encode("utf-8")

        yield Response()

    session = create_private_checkout_session(
        StripeBillingConfig(
            secret_key="sk_test",
            private_price_id="price_usdc",
            success_url="https://app.test/success",
            cancel_url="https://app.test/cancel",
        ),
        user_id=42,
        email="client@example.com",
        opener=fake_opener,
    )
    fields = parse_qs(captured["body"])

    assert session["url"] == "https://checkout.stripe.test/session"
    assert fields["metadata[payment_asset]"] == ["USDC"]
    assert fields["subscription_data[metadata][payment_asset]"] == ["USDC"]
