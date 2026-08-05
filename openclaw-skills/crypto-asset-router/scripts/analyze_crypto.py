#!/usr/bin/env python3
"""Read-only OpenClaw formatter for the canonical Monatise production decision."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


SUPPORTED = {"BTC", "ETH", "SOL"}
FORBIDDEN = {"EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "GOLD", "XAU", "OIL", "CL", "SPX", "NDX"}


def normalize(raw: str) -> str:
    value = raw.strip().upper().removeprefix("/ANALYZE ").removeprefix("/")
    for suffix in ("-USDT", "USDT", "-PERP", "/USD", "USD"):
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
    grid_score = int(analysis.get("grid_score") or 0)
    threshold = int(analysis.get("score_threshold") or 7)
    weekend = generated.weekday() >= 5

    if weekend:
        decision, reason = "NO_TRADE", "WEEKEND_NO_TRADE"
    elif classification == "trend" and direction == "long" and score >= threshold:
        decision, reason = "LONG", "SIGNED_SCORE_THRESHOLD_MET"
    elif classification == "trend" and direction == "short" and score <= -threshold:
        decision, reason = "SHORT", "SIGNED_SCORE_THRESHOLD_MET"
    elif classification == "grid" and grid_score >= threshold:
        decision, reason = "GRID", "GRID_SCORE_THRESHOLD_MET"
    else:
        decision, reason = "NO_TRADE", "SCORE_BELOW_THRESHOLD"

    actionable = decision in {"LONG", "SHORT", "GRID"}
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
        "grid_score": grid_score,
        "score_threshold": threshold,
        "conviction_score": round(float(analysis.get("conviction") or 0) * 100),
        "entry": entry if actionable else None,
        "stop_loss": invalidation if actionable else None,
        "target": target if actionable else None,
        "reward_risk": analysis.get("reward_risk") if actionable else None,
        "expires_at": analysis.get("expires_at"),
        "reason_code": reason,
        "reasons": list(analysis.get("reasons") or []),
        "data_source": analysis.get("data_source") or "CoinGlass",
        "execution": {"enabled": False, "orders_placed": 0},
    }


def telegram(analysis: dict) -> str:
    score = analysis["grid_score"] if analysis["decision"] == "GRID" else analysis["score"]
    score_text = f"{score:+d}/10" if analysis["decision"] != "GRID" else f"{score}/10"
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
