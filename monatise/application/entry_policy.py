"""Fixed strategy levels and truthful quote-based entry decisions."""
from decimal import Decimal


def entry_order_type(*, side: str, planned: Decimal, executable: Decimal,
                     low: Decimal, high: Decimal, pending_only: bool = False) -> str:
    if side not in {"buy", "sell"} or not all(v.is_finite() and v > 0 for v in (planned, executable, low, high)):
        raise ValueError("entry policy requires a valid side and positive finite prices")
    if not low <= planned <= high:
        raise ValueError("planned entry is outside the approved zone")
    if low <= executable <= high and not pending_only:
        return "market"
    if planned == executable:
        raise ValueError("waiting for sufficient distance to place the approved pending entry")
    return "limit" if (planned < executable) == (side == "buy") else "stop"


PENDING_LEASE_SECONDS = 20
# Broker fallback expiry is separate from the short local eligibility lease.
PENDING_ORDER_LIFETIME_SECONDS = 30 * 60
PENDING_ENTRY_VERSION = 2
