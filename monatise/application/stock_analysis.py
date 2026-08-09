from __future__ import annotations

import math
from typing import Any


def build_stock_analysis(context: dict[str, Any], *, bars: list[dict[str, Any]] | None = None, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
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
    result = {
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
    result.update(build_directional_levels(decision, bars or [], snapshot or {}))
    return result


def build_directional_levels(decision: str, bars: list[dict[str, Any]], snapshot: dict[str, Any]) -> dict[str, Any]:
    clean = [row for row in bars if all(_positive_number(row.get(key)) for key in ("h", "l", "c"))]
    if decision not in {"BUY_WATCH", "SELL_WATCH"} or len(clean) < 22:
        return {"setup_status": "watch", "entry": None, "stop_loss": None, "target": None, "reward_risk": None}
    previous, latest = clean[-21:-1], clean[-1]
    ranges = []
    for index in range(max(1, len(clean) - 14), len(clean)):
        high, low, previous_close = float(clean[index]["h"]), float(clean[index]["l"]), float(clean[index - 1]["c"])
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    atr = sum(ranges) / len(ranges)
    quote = snapshot.get("latestQuote") if isinstance(snapshot.get("latestQuote"), dict) else {}
    bid, ask = quote.get("bp"), quote.get("ap")
    mark = (float(bid) + float(ask)) / 2 if _positive_number(bid) and _positive_number(ask) else float(latest["c"])
    if decision == "BUY_WATCH":
        trigger = max(float(row["h"]) for row in previous)
        confirmed = float(latest["c"]) > trigger
        entry = trigger
        structural_stop = min(float(row["l"]) for row in clean[-10:])
        stop = min(structural_stop, entry - atr * 1.25)
        risk = entry - stop
        target = entry + risk * 2
    else:
        trigger = min(float(row["l"]) for row in previous)
        confirmed = float(latest["c"]) < trigger
        entry = trigger
        structural_stop = max(float(row["h"]) for row in clean[-10:])
        stop = max(structural_stop, entry + atr * 1.25)
        risk = stop - entry
        target = entry - risk * 2
    if not confirmed or not all(math.isfinite(value) and value > 0 for value in (mark, entry, stop, target, risk)):
        return {"setup_status": "awaiting_price_confirmation", "current_price": round(mark, 4), "entry": None, "stop_loss": None, "target": None, "reward_risk": None, "atr": round(atr, 4)}
    return {"setup_status": "confirmed", "current_price": round(mark, 4), "entry": round(entry, 4), "stop_loss": round(stop, 4), "target": round(target, 4), "reward_risk": 2.0, "atr": round(atr, 4), "level_source": "Alpaca IEX hourly bars"}


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0
