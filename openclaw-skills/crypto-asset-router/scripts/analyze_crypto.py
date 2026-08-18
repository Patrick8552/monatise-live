#!/usr/bin/env python3
"""Read-only OpenClaw formatter for the canonical Monatise production decision."""
from __future__ import annotations

import argparse
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path


SUPPORTED = {"BTC", "ETH", "SOL"}
FORBIDDEN = {"EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "GOLD", "XAU", "OIL", "CL", "SPX", "NDX"}


def valid_grid_plan(grid: object) -> bool:
    if not isinstance(grid, dict):
        return False
    center = grid.get("center")
    buys = grid.get("buy_levels")
    sells = grid.get("sell_levels")
    lower = grid.get("lower_invalidation")
    upper = grid.get("upper_invalidation")
    lower_boundary = grid.get("lower_boundary")
    upper_boundary = grid.get("upper_boundary")
    spacing = grid.get("spacing")
    levels_per_side = grid.get("levels_per_side")

    def valid_number(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0

    return (
        valid_number(center)
        and isinstance(buys, list)
        and isinstance(sells, list)
        and len(buys) >= 2
        and len(sells) >= 2
        and all(valid_number(value) for value in [*buys, *sells, lower, upper, lower_boundary, upper_boundary, spacing])
        and isinstance(levels_per_side, int)
        and not isinstance(levels_per_side, bool)
        and levels_per_side == len(buys) == len(sells)
        and len(set(buys)) == len(buys)
        and len(set(sells)) == len(sells)
        and all(buys[index] > buys[index + 1] for index in range(len(buys) - 1))
        and all(sells[index] < sells[index + 1] for index in range(len(sells) - 1))
        and max(buys) < center < min(sells)
        and lower < min(buys)
        and upper > max(sells)
        # lower_boundary/upper_boundary must be the actual outermost levels
        # (the formatter reads these keys unconditionally, so a
        # structurally-valid grid missing/mismatching them must fail
        # closed rather than crash the formatter).
        and lower_boundary == min(buys)
        and upper_boundary == max(sells)
    )


def normalize(raw: str) -> str:
    value = raw.strip().upper().removeprefix("/ANALYZE ").removeprefix("/")
    for suffix in ("-USDT", "/USDT", "USDT", "-PERP", "/USD", "USD"):
        if value.endswith(suffix):
            value = value[:-len(suffix)]
            break
    if value in FORBIDDEN or value not in SUPPORTED:
        raise ValueError("Unsupported asset: expected BTC, ETH, or SOL")
    return value


def fetch(asset: str, interval: str) -> dict:
    tool = Path.home() / ".openclaw/workspace/tools/monatise-readonly-status"
    run = subprocess.run([str(tool), asset, interval], capture_output=True, text=True, timeout=120, check=False)
    if run.returncode:
        raise RuntimeError("Monatise read-only service unavailable")
    return json.loads(run.stdout)


def analyze(asset: str, interval: str = "1h", payload: dict | None = None, current_time: datetime | None = None) -> dict:
    generated = current_time or datetime.now(timezone.utc)
    analysis = payload if payload is not None else fetch(asset, interval)
    classification = str(analysis.get("classification") or "no_trade").lower()
    direction = str(analysis.get("direction") or "none").lower()
    score = int(analysis.get("score") or 0)
    threshold = int(analysis.get("score_threshold") or 7)
    weekend = generated.weekday() >= 5

    if weekend:
        decision, reason = "NO_TRADE", "WEEKEND_NO_TRADE"
    elif classification == "trend" and direction == "long" and score >= threshold:
        decision, reason = "LONG", "SIGNED_SCORE_THRESHOLD_MET"
    elif classification == "trend" and direction == "short" and score <= -threshold:
        decision, reason = "SHORT", "SIGNED_SCORE_THRESHOLD_MET"
    elif classification in {"grid", "two_sided"}:
        decision, reason = "NO_TRADE", "DIRECTIONAL_ANALYSIS_REQUIRED"
    else:
        decision = "NO_TRADE"
        reason = "PRODUCTION_BLOCKED" if analysis.get("blockers") else "SCORE_BELOW_THRESHOLD"

    actionable = decision in {"LONG", "SHORT"}
    entry = analysis.get("entry") if actionable else None
    invalidation = analysis.get("invalidation") if actionable else None
    target = analysis.get("target") if actionable else None
    if actionable and not all(isinstance(value, (int, float)) and value > 0 for value in (entry, invalidation, target)):
        decision, reason, actionable = "NO_TRADE", "INVALID_RISK_LEVELS", False

    return {
        "asset": asset,
        "decision": decision,
        "classification": classification,
        "score": score,
        "score_threshold": threshold,
        "conviction_score": round(float(analysis.get("conviction") or 0) * 100),
        "entry": entry if actionable else None,
        "stop_loss": invalidation if actionable else None,
        "target": target if actionable else None,
        "reward_risk": analysis.get("reward_risk") if actionable else None,
        "risk_decision": analysis.get("risk_decision"),
        "risk_issues": list(analysis.get("risk_issues") or []),
        "status": analysis.get("status"),
        "blocked_by": analysis.get("blocked_by"),
        "expires_at": analysis.get("expires_at"),
        "reason_code": reason,
        "reasons": list(analysis.get("reasons") or []),
        "blockers": list(analysis.get("blockers") or []),
        "data_source": analysis.get("data_source") or "CoinGlass",
        "execution": {"enabled": False, "orders_placed": 0},
    }


def telegram(analysis: dict) -> str:
    score_text = f"{analysis['score']:+d}/10"
    lines = [
        "MONATISE CRYPTO ANALYSIS",
        f"Asset: {analysis['asset']}",
        f"Decision: {analysis['decision'].replace('_', ' ')}",
        f"Score: {score_text} | threshold: ±{analysis['score_threshold']}",
        f"Conviction: {analysis['conviction_score']}/100",
    ]
    if analysis["decision"] == "NO_TRADE":
        lines += ["Reason:", analysis["reason_code"].replace("_", " ").title()]
    else:
        lines += [
            f"Entry: ${analysis['entry']:,.2f}",
            f"Invalidation: ${analysis['stop_loss']:,.2f}",
            f"Target: ${analysis['target']:,.2f}",
        ]
        if analysis["reward_risk"] is not None:
            lines.append(f"Reward/risk: {float(analysis['reward_risk']):.2f}")
    if analysis["reasons"]:
        lines += ["Evidence:", *[f"• {reason}" for reason in analysis["reasons"][:3]]]
    if analysis["blockers"]:
        lines += ["Blocked by:", *[f"• {blocker}" for blocker in analysis["blockers"][:3]]]
    if analysis["expires_at"]:
        lines.append(f"Expires: {analysis['expires_at']}")
    return "\n".join(lines + ["Analysis only. No trade was executed."])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("asset")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--format", choices=("json", "telegram"), default="telegram")
    args = parser.parse_args()
    try:
        result = analyze(normalize(args.asset), args.interval)
    except ValueError as exc:
        parser.error(str(exc))
    print(telegram(result) if args.format == "telegram" else json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
