from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any


def build_forex_analysis(
    symbol: str,
    hourly_bars: list[dict[str, Any]],
    trigger_bars: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    observed = now or datetime.now(timezone.utc)
    result: dict[str, Any] = {
        "asset": symbol, "asset_class": "forex", "decision": "NO_TRADE",
        "direction": "NONE", "score": 0, "score_threshold": 7,
        "setup_status": "insufficient_market_data", "execution": {"enabled": False, "orders_placed": 0},
        "analysis_provider": "yahoo_finance", "analysis_instrument": symbol,
        "reasons": [],
    }
    hourly, trigger = _clean(hourly_bars), _clean(trigger_bars)
    if len(hourly) < 60 or len(trigger) < 60:
        return result
    latest_at = datetime.fromisoformat(str(trigger[-1]["t"]).replace("Z", "+00:00"))
    if observed - latest_at.astimezone(timezone.utc) > timedelta(hours=2):
        result["setup_status"] = "stale_market_data"
        result["reasons"] = ["latest 15-minute FX candle is stale"]
        return result

    hclose = [row["c"] for row in hourly]
    tclose = [row["c"] for row in trigger]
    ema20, ema50 = _ema(hclose, 20), _ema(hclose, 50)
    fast = _ema(tclose, 20)
    price = tclose[-1]
    atr = _atr(trigger, 14)
    upper = max(row["h"] for row in trigger[-21:-1])
    lower = min(row["l"] for row in trigger[-21:-1])
    rsi = _rsi(hclose, 14)
    long = ema20 > ema50 and price > fast
    short = ema20 < ema50 and price < fast
    direction = "LONG" if long else "SHORT" if short else "NONE"
    score = 0
    reasons: list[str] = []
    if direction == "LONG":
        score += 3; reasons.append("hourly EMA20 is above EMA50")
        if price > upper: score += 3; reasons.append("15-minute close confirmed a 20-bar breakout")
        if 52 <= rsi <= 72: score += 2; reasons.append(f"hourly RSI supports continuation ({rsi:.1f})")
        if tclose[-1] > tclose[-2]: score += 1; reasons.append("positive trigger momentum")
        entry, stop = price, min(min(row["l"] for row in trigger[-10:]), price - 1.5 * atr)
    elif direction == "SHORT":
        score += 3; reasons.append("hourly EMA20 is below EMA50")
        if price < lower: score += 3; reasons.append("15-minute close confirmed a 20-bar breakdown")
        if 28 <= rsi <= 48: score += 2; reasons.append(f"hourly RSI supports continuation ({rsi:.1f})")
        if tclose[-1] < tclose[-2]: score += 1; reasons.append("negative trigger momentum")
        entry, stop = price, max(max(row["h"] for row in trigger[-10:]), price + 1.5 * atr)
    else:
        result.update({
            "setup_status": "suppressed", "current_price": price,
            "reasons": ["hourly and 15-minute trends are not aligned"],
            "generated_at": observed.isoformat(),
            "market_observed_at": latest_at.astimezone(timezone.utc).isoformat(),
        })
        return result
    signed = min(score, 10) if direction == "LONG" else -min(score, 10)
    risk = abs(entry - stop)
    target = entry + 2 * risk if direction == "LONG" else entry - 2 * risk
    confirmed = abs(signed) >= 7 and ((direction == "LONG" and price > upper) or (direction == "SHORT" and price < lower))
    digits = 5 if price < 20 else 3
    result.update({
        "direction": direction, "score": signed, "current_price": round(price, digits),
        "entry": round(entry, digits), "stop_loss": round(stop, digits),
        "target": round(target, digits), "targets": [round(target, digits)], "reward_risk": 2.0,
        "timeframe": "1h regime / 15m trigger", "setup_status": "confirmed" if confirmed else "suppressed",
        "decision": ("BUY_WATCH" if direction == "LONG" else "SELL_WATCH") if confirmed else "NO_TRADE",
        "reasons": reasons, "generated_at": observed.isoformat(),
        "expires_at": (observed + timedelta(minutes=30)).isoformat(), "freshness": "fresh",
        "publication_valid": confirmed,
        "market_observed_at": latest_at.astimezone(timezone.utc).isoformat(),
    })
    return result


def _clean(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean = []
    for row in rows:
        try:
            values = {key: float(row[key]) for key in ("o", "h", "l", "c")}
        except (KeyError, TypeError, ValueError):
            continue
        if all(isfinite(value) and value > 0 for value in values.values()) and row.get("t"):
            clean.append({**values, "t": row["t"]})
    return clean


def _ema(values: list[float], period: int) -> float:
    value, alpha = values[0], 2 / (period + 1)
    for item in values[1:]: value = item * alpha + value * (1 - alpha)
    return value


def _rsi(values: list[float], period: int) -> float:
    changes = [values[index] - values[index - 1] for index in range(len(values) - period, len(values))]
    gains = sum(max(change, 0) for change in changes) / period
    losses = sum(max(-change, 0) for change in changes) / period
    return 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)


def _atr(rows: list[dict[str, Any]], period: int) -> float:
    values = []
    for index in range(len(rows) - period, len(rows)):
        values.append(max(rows[index]["h"] - rows[index]["l"], abs(rows[index]["h"] - rows[index - 1]["c"]), abs(rows[index]["l"] - rows[index - 1]["c"])))
    return sum(values) / len(values)
