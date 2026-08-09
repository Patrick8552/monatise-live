from __future__ import annotations

from typing import Any


def build_stock_analysis(context: dict[str, Any]) -> dict[str, Any]:
    """Convert Quiver alternative data into an analysis-only stock watch signal."""
    summary = context.get("summary") if isinstance(context.get("summary"), dict) else {}
    score = int(summary.get("score") or 0)
    available = bool(context.get("available"))
    if not available:
        decision, reason = "NO_TRADE", "QUIVER_DATA_UNAVAILABLE"
    elif score >= 3:
        decision, reason = "BUY_WATCH", "ALTERNATIVE_DATA_SUPPORTIVE"
    elif score <= -3:
        decision, reason = "SELL_WATCH", "ALTERNATIVE_DATA_CAUTIOUS"
    else:
        decision, reason = "NO_TRADE", "CONFLUENCE_BELOW_THRESHOLD"
    return {
        "asset": context.get("symbol"),
        "asset_class": "stock",
        "decision": decision,
        "score": score,
        "score_threshold": 3,
        "reason_code": reason,
        "reasons": list(summary.get("drivers") or [])[:4],
        "cautions": list(summary.get("cautions") or [])[:3],
        "activity": summary.get("activity") or {},
        "data_source": context.get("source") or "Quiver Quantitative",
        "execution": {"enabled": False, "orders_placed": 0},
    }
