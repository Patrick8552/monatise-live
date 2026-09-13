"""Classify MT5 server evidence independently of CTrade's boolean return value."""

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


REJECTION_CODES = frozenset({
    10004, 10006, 10007, 10013, 10014, 10015, 10016, 10017, 10018,
    10019, 10020, 10021, 10022, 10024, 10026, 10027, 10029, 10030,
    10032, 10033, 10034, 10035, 10036, 10038, 10040, 10042, 10043,
    10044, 10045, 10046,
})


def _positive(value: Any) -> bool:
    try:
        number = Decimal(str(value))
        return number.is_finite() and number > 0
    except InvalidOperation:
        return False


def broker_result_status(operation: str, order_type: str, evidence: Mapping[str, Any]) -> str:
    try:
        code = int(str(evidence.get("broker_retcode") or ""))
    except ValueError:
        return "broker_uncertain"
    if code == 10009:  # TRADE_RETCODE_DONE
        if operation != "open" or (
            _positive(evidence.get("broker_ticket"))
            and (order_type != "market" or (
                _positive(evidence.get("fill_price")) and _positive(evidence.get("executed_volume"))
            ))
        ):
            return "reconciled"
    elif code == 10008:  # TRADE_RETCODE_PLACED, not proof of a market fill
        if operation == "open" and order_type in {"limit", "stop"} and _positive(evidence.get("broker_ticket")):
            return "reconciled"
    elif code == 10025 and operation in {"sl", "tp", "breakeven", "modify_targets"}:  # NO_CHANGES
        return "reconciled"
    elif code in REJECTION_CODES:
        return "rejected"
    # Partial fills, timeouts, connection errors and unknown codes require
    # reconciliation. Retrying them could create additional exposure.
    return "broker_uncertain"
