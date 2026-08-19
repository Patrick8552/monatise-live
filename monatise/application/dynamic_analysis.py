"""Quality gates and response shaping for verified, on-demand futures analysis."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any

from monatise.adapters.coinglass_production import CoinGlassFuturesAsset


MINIMUM_CANDLES = 120
MINIMUM_VOLUME_USD = 100_000.0
MAX_PRICE_DISAGREEMENT = 0.08


def finalize_dynamic_analysis(
    analysis: dict[str, Any],
    result: Any,
    asset: CoinGlassFuturesAsset,
) -> dict[str, Any]:
    market = result.context.outputs.get("market_data")
    candles = tuple(getattr(market, "candles", ()) or ())
    quality = getattr(market, "quality", None)
    derivatives = dict(getattr(market, "derivatives", {}) or {})
    warnings = list(getattr(quality, "issues", ()) or ())
    failures: list[str] = []
    price = _positive(getattr(market, "price", None))
    latest_close = _positive(getattr(candles[-1], "close", None)) if candles else None
    if len(candles) < MINIMUM_CANDLES:
        failures.append(f"insufficient candle history: {len(candles)}/{MINIMUM_CANDLES}")
    if quality is None or getattr(getattr(quality, "status", None), "value", "no_data") != "ready":
        failures.append("market data is not fresh and ready")
    if price is None:
        failures.append("current price is unavailable or invalid")
    if price and latest_close and abs(price - latest_close) / latest_close > MAX_PRICE_DISAGREEMENT:
        failures.append("current price disagrees materially with the latest candle")
    recent_volume = sum(max(0.0, float(getattr(candle, "volume", 0.0) or 0.0)) for candle in candles[-24:])
    if recent_volume > 0 and recent_volume < MINIMUM_VOLUME_USD:
        failures.append("exposed recent volume is below the dynamic-asset liquidity gate")
    for key, value in derivatives.items():
        if value is None:
            warnings.append(f"optional derivatives dataset unavailable: {key}")
        elif not isinstance(value, (int, float)) or not isfinite(float(value)):
            failures.append(f"malformed derivatives dataset: {key}")
    imbalance = derivatives.get("order_book_imbalance")
    if isinstance(imbalance, (int, float)) and not isinstance(imbalance, bool) and abs(float(imbalance)) > 1:
        failures.append("malformed order-book imbalance")
    classification = str(analysis.get("classification") or "no_trade")
    direction = str(analysis.get("direction") or "none")
    if classification == "grid":
        failures.append("grid and two-sided analysis is disabled")
    if classification == "trend" and not _derivatives_confirm(direction, derivatives):
        failures.append("CoinGlass order flow (net CVD) does not confirm this setup")
    plan = _planned_setup(analysis, candles, price) if not failures else None
    if not failures and classification == "trend" and plan is None:
        failures.append("no structurally valid entry zone could be planned")
    if failures:
        analysis.update({
            "classification": "no_trade", "direction": "none", "entry": None,
            "entry_zone": None, "entry_trigger": None, "invalidation": None,
            "target": None, "targets": [], "reward_risk": None, "grid_plan": None,
        })
    else:
        analysis["grid_plan"] = None
        analysis.update(plan or {})
        analysis["entry_trigger"] = "confirmed by net CoinGlass order flow (CVD); price must still reach the planned zone"
        analysis["entry"] = None
    analysis["expires_at"] = analysis.get("expires_at") or _expiry(analysis.get("interval"))
    analysis.update({
        "provenance": asset.to_dict(),
        "evidence": {
            "candle_count": len(candles),
            "latest_candle_at": getattr(quality, "latest_candle_at", None).isoformat() if getattr(quality, "latest_candle_at", None) else None,
            "current_price": price,
            "recent_volume": recent_volume if recent_volume > 0 else None,
            "derivatives": {key: {"status": "available" if value is not None else "unavailable", "value": value} for key, value in derivatives.items()},
        },
        "data_quality": {"passed": not failures, "failures": failures, "warnings": sorted(set(warnings))},
        "volatility_assessment": "continuation requires order flow to keep confirming; otherwise treat the pickup as exhaustion/pump risk",
        "source_timestamps": {
            "analysis_generated_at": datetime.now(timezone.utc).isoformat(),
            "supported_coins_observed_at": asset.supported_coins_observed_at,
            "market_observed_at": asset.market_observed_at,
        },
        "position_size": None,
        "leverage": None,
        "execution_enabled": False,
    })
    return analysis


def _derivatives_confirm(direction: str, derivatives: dict[str, Any]) -> bool:
    """CoinGlass-only entry confirmation: does net order flow (CVD) back this setup?

    Replaces price-action pattern confirmation for dynamic (non-core) assets --
    a long/short setup needs net buying/selling pressure over the fetched
    window; a grid setup needs the absence of a one-sided flow that would
    break the range, judged against total traded volume in that window.
    """
    cvd_delta = derivatives.get("cvd_delta")
    if cvd_delta is None:
        return False
    if direction == "long":
        return cvd_delta > 0
    if direction == "short":
        return cvd_delta < 0
    if direction == "two_sided":
        volume = derivatives.get("derivatives_volume")
        return bool(volume) and volume > 0 and abs(cvd_delta) <= 0.5 * volume
    return False


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) and number > 0 else None


def _valid_grid_plan(grid: dict[str, Any], price: float | None = None) -> bool:
    center = grid.get("center")
    buys = grid.get("buy_levels")
    sells = grid.get("sell_levels")
    lower = grid.get("lower_invalidation")
    upper = grid.get("upper_invalidation")
    if not (
        _positive(center) is not None
        and isinstance(buys, list) and isinstance(sells, list)
        and len(buys) >= 2 and len(sells) >= 2
        and all(_positive(v) is not None for v in [*buys, *sells, lower, upper])
    ):
        return False
    buys_f, sells_f = [float(v) for v in buys], [float(v) for v in sells]
    if not (
        len(set(buys_f)) == len(buys_f) and len(set(sells_f)) == len(sells_f)
        and all(buys_f[i] > buys_f[i + 1] for i in range(len(buys_f) - 1))
        and all(sells_f[i] < sells_f[i + 1] for i in range(len(sells_f) - 1))
        and max(buys_f) < float(center) < min(sells_f)
        and float(lower) < min(buys_f) and float(upper) > max(sells_f)
    ):
        return False
    if price is not None:
        # Price must still sit inside the innermost band. A grid built from a
        # rolling range can lag a fast move and hand back levels the price has
        # already blown through on one side -- that's a breakout, not a range,
        # and has no meaningful room left before invalidation on that side.
        nearest_buy, nearest_sell = max(buys_f), min(sells_f)
        if not (nearest_buy < price < nearest_sell):
            return False
    return True


def _planned_setup(analysis: dict[str, Any], candles: tuple[Any, ...], price: float | None = None) -> dict[str, Any] | None:
    grid = analysis.get("grid_plan") or {}
    levels = list(grid.get("buy_levels") or []) + list(grid.get("sell_levels") or [])
    grid_plan: dict[str, Any] | None = None
    if levels:
        if not _valid_grid_plan(grid, price):
            return None
        spacing = _positive(grid.get("spacing"))
        if spacing is None:
            return None
        center = float(grid.get("center") or levels[0])
        level = min((float(item) for item in levels), key=lambda item: abs(item - center))
        zone = {"low": round(level - spacing * 0.15, 8), "high": round(level + spacing * 0.15, 8)}
        targets = [round(center, 8)]
        invalidation = round(min(float(item) for item in levels) - spacing, 8)
        grid_plan = grid
    else:
        recent = candles[-20:]
        if len(recent) < 10:
            return None
        low = min(float(item.low) for item in recent)
        high = max(float(item.high) for item in recent)
        span = high - low
        if span <= 0:
            return None
        direction = analysis.get("direction")
        if direction == "long":
            zone = {"low": round(high - span * .62, 8), "high": round(high - span * .38, 8)}
            invalidation, targets = round(low - span * .05, 8), [round(high, 8)]
        elif direction == "short":
            zone = {"low": round(low + span * .38, 8), "high": round(low + span * .62, 8)}
            invalidation, targets = round(high + span * .05, 8), [round(low, 8)]
        else:
            return None
    midpoint = (zone["low"] + zone["high"]) / 2
    risk = abs(midpoint - invalidation)
    reward = abs(targets[0] - midpoint)
    if risk <= 0 or reward <= 0:
        return None
    plan = {"entry_zone": zone, "invalidation": invalidation, "target": targets[0], "targets": targets, "reward_risk": round(reward / risk, 2)}
    if grid_plan is not None:
        plan["grid_plan"] = grid_plan
    return plan


def _expiry(interval: Any) -> str:
    text = str(interval or "1h")
    units = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
    try:
        seconds = int(text[:-1]) * units[text[-1]] * 4
    except (KeyError, TypeError, ValueError):
        seconds = 4 * 3600
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
