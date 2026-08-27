from __future__ import annotations

import math
from typing import Any


FLASHALPHA_FUTURES_SYMBOLS = ("ES", "NQ", "RTY", "YM", "MES", "MNQ")


def flashalpha_directional_bias(context: dict[str, Any]) -> str:
    price = _number(context.get("underlying_price"))
    flip = _number(context.get("gamma_flip"))
    if price is None or flip is None:
        return "neutral"
    tolerance = max(abs(price) * 0.0005, 1e-9)
    if price > flip + tolerance:
        return "bullish"
    if price < flip - tolerance:
        return "bearish"
    return "neutral"


def build_flashalpha_futures_analysis(context: dict[str, Any], *, minimum_reward_risk: float = 1.5) -> dict[str, Any]:
    symbol = str(context.get("symbol") or "UNKNOWN").removesuffix("=F")
    price = _number(context.get("underlying_price"))
    flip = _number(context.get("gamma_flip"))
    call_wall = _number(context.get("call_wall"))
    put_wall = _number(context.get("put_wall"))
    bias = flashalpha_directional_bias(context)
    result: dict[str, Any] = {
        "asset": symbol,
        "api_symbol": str(context.get("symbol") or symbol),
        "asset_class": "cme_futures",
        "decision": "NO_TRADE",
        "direction": "NONE",
        "score": 0,
        "score_threshold": 7,
        "setup_status": "insufficient_positioning",
        "current_price": price,
        "gamma_flip": flip,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "net_gex": context.get("net_gex"),
        "net_gex_label": context.get("net_gex_label"),
        "as_of": context.get("as_of"),
        "data_source": context.get("source") or "FlashAlpha",
        "execution": {"enabled": False, "orders_placed": 0},
    }
    if price is None or flip is None:
        return result

    if bias == "bullish" and call_wall is not None and call_wall > price and flip < price:
        risk, reward = price - flip, call_wall - price
        direction, decision, stop, target = "LONG", "BUY_WATCH", flip, call_wall
    elif bias == "bearish" and put_wall is not None and put_wall < price and flip > price:
        risk, reward = flip - price, price - put_wall
        direction, decision, stop, target = "SHORT", "SELL_WATCH", flip, put_wall
    else:
        result["setup_status"] = "no_directional_room"
        return result

    reward_risk = reward / risk if risk > 0 else 0.0
    score = 9 if reward_risk >= 3 else 8 if reward_risk >= 2 else 7 if reward_risk >= minimum_reward_risk else 5
    result.update({
        "direction": direction,
        "score": score if direction == "LONG" else -score,
        "reward_risk": round(reward_risk, 2),
        "entry": price,
        "stop_loss": stop,
        "target": target,
        "setup_status": "confirmed" if reward_risk >= minimum_reward_risk else "reward_risk_below_threshold",
    })
    if reward_risk >= minimum_reward_risk:
        result["decision"] = decision
    return result


def build_flashalpha_stock_analysis(context: dict[str, Any], *, minimum_reward_risk: float = 1.5) -> dict[str, Any]:
    """Build a FlashAlpha-led stock setup using the same positioning contract.

    FlashAlpha supplies the directional price/flip/wall geometry. Other stock
    providers may confirm or contradict it, but they do not replace these
    required primary fields.
    """
    result = build_flashalpha_futures_analysis(context, minimum_reward_risk=minimum_reward_risk)
    result.update({
        "asset_class": "stock",
        "direction_authority": "FlashAlpha options positioning and directional levels",
        "data_source": context.get("source") or "FlashAlpha",
    })
    return result


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None
