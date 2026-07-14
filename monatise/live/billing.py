from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from monatise.live.secrets import secret_value


STRIPE_CHECKOUT_SESSIONS_URL = "https://api.stripe.com/v1/checkout/sessions"
PRIVATE_PLAN = "private"
PRIVATE_PLAN_PAYMENT_ASSET = "USDC"


@dataclass(frozen=True)
class StripeBillingConfig:
    secret_key: str = ""
    private_price_id: str = ""
    webhook_secret: str = ""
    success_url: str = ""
    cancel_url: str = ""

    @classmethod
    def from_env(cls) -> "StripeBillingConfig":
        public_url = os.getenv("MONATISE_PUBLIC_URL", "").rstrip("/")
        default_success = f"{public_url}/?billing=success" if public_url else "/?billing=success"
        default_cancel = f"{public_url}/?billing=cancelled" if public_url else "/?billing=cancelled"
        return cls(
            secret_key=secret_value("STRIPE_SECRET_KEY", ""),
            private_price_id=os.getenv("STRIPE_PRIVATE_PRICE_ID", "").strip(),
            webhook_secret=secret_value("STRIPE_WEBHOOK_SECRET", ""),
            success_url=os.getenv("STRIPE_SUCCESS_URL", default_success).strip() or default_success,
            cancel_url=os.getenv("STRIPE_CANCEL_URL", default_cancel).strip() or default_cancel,
        )

    @property
    def checkout_configured(self) -> bool:
        return bool(self.secret_key and self.private_price_id)

    @property
    def webhook_configured(self) -> bool:
        return bool(self.webhook_secret)


class StripeBillingError(RuntimeError):
    pass


def create_private_checkout_session(
    config: StripeBillingConfig,
    *,
    user_id: int,
    email: str,
    opener=urlopen,
) -> dict:
    if not config.checkout_configured:
        raise StripeBillingError("USDC checkout is not configured")
    body = urlencode(
        {
            "mode": "subscription",
            "line_items[0][price]": config.private_price_id,
            "line_items[0][quantity]": "1",
            "client_reference_id": str(user_id),
            "customer_email": email,
            "success_url": config.success_url,
            "cancel_url": config.cancel_url,
            "metadata[monatise_user_id]": str(user_id),
            "metadata[payment_asset]": PRIVATE_PLAN_PAYMENT_ASSET,
            "subscription_data[metadata][monatise_user_id]": str(user_id),
            "subscription_data[metadata][payment_asset]": PRIVATE_PLAN_PAYMENT_ASSET,
        }
    ).encode("utf-8")
    request = Request(
        STRIPE_CHECKOUT_SESSIONS_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {config.secret_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with opener(request, timeout=15) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("url"):
        raise StripeBillingError("Stripe did not return a Checkout URL")
    return payload


def verify_stripe_signature(raw_body: bytes, signature_header: str, webhook_secret: str, tolerance_seconds: int = 300) -> bool:
    if not webhook_secret:
        return False
    parts = {}
    for item in signature_header.split(","):
        key, _, value = item.partition("=")
        if key and value:
            parts.setdefault(key, []).append(value)
    timestamps = parts.get("t", [])
    signatures = parts.get("v1", [])
    if not timestamps or not signatures:
        return False
    try:
        timestamp = int(timestamps[0])
    except ValueError:
        return False
    if abs(time.time() - timestamp) > tolerance_seconds:
        return False
    signed_payload = f"{timestamp}.".encode("utf-8") + raw_body
    expected = hmac.new(webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, signature) for signature in signatures)


def private_plan_user_id_from_event(event: dict) -> int | None:
    event_type = str(event.get("type") or "")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    obj = data.get("object") if isinstance(data.get("object"), dict) else {}
    if event_type == "checkout.session.completed":
        user_id = obj.get("client_reference_id") or obj.get("metadata", {}).get("monatise_user_id")
        if _stripe_session_paid_or_subscription(obj):
            return _parse_user_id(user_id)
    if event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        status = str(obj.get("status") or "").lower()
        if status in {"active", "trialing"}:
            return _parse_user_id(obj.get("metadata", {}).get("monatise_user_id"))
    return None


def _stripe_session_paid_or_subscription(session: dict) -> bool:
    return str(session.get("payment_status") or "").lower() in {"paid", "no_payment_required"}


def _parse_user_id(value) -> int | None:  # noqa: ANN001
    try:
        user_id = int(str(value or "").strip())
    except ValueError:
        return None
    return user_id if user_id > 0 else None
