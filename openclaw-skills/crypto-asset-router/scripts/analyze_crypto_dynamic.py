#!/usr/bin/env python3
"""Read-only OpenClaw formatter for Monatise's verified dynamic CoinGlass
analysis -- any crypto ticker beyond the core BTC/ETH/SOL set, resolved and
verified against real CoinGlass instruments rather than assumed.

Follows docs/OPENCLAW_DYNAMIC_ANALYSIS.md's four responsibilities:
  Router:    normalize the ticker, reject forex/malformed input.
  Validator: require execution_enabled=false, verified provenance, source
             timestamps, a known classification, and -- for an actionable
             setup -- zone/trigger/invalidation/targets/reward-risk/expiry.
             Anything missing fails closed to NO_TRADE.
  Formatter: show unavailable evidence, warnings, and expiry; never turn a
             null/failed field into an inferred neutral/zero/entry value.
  Errors:    preserve 400 detail, distinguish 401/429/503, never retry
             400/401, bounded backoff for 429/503.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path


CORE = {"BTC", "ETH", "SOL"}
FORBIDDEN = {"EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "GOLD", "XAU", "OIL", "CL", "SPX", "NDX", "USD"}
RETRYABLE_STATUSES = {429, 503}
REQUIRED_ACTIONABLE_FIELDS = ("entry_zone", "entry_trigger", "invalidation", "targets", "reward_risk", "expires_at")


def normalize(raw: str) -> str:
    value = raw.strip().upper().removeprefix("/ANALYZE ").removeprefix("/")
    for suffix in ("-USDT", "/USDT", "USDT", "-PERP", "/USD", "USD"):
        if value.endswith(suffix) and len(value) > len(suffix):
            value = value[: -len(suffix)]
            break
    if not value or not value.isalnum() or value in FORBIDDEN:
        raise ValueError("Unsupported asset: expected a crypto ticker, got forex/commodity/index or malformed input")
    if value in CORE:
        raise ValueError(f"{value} is a core asset; use analyze_crypto.py instead")
    return value


def fetch(asset: str, interval: str, *, attempts: int = 3) -> dict:
    tool = Path.home() / ".openclaw/workspace/tools/monatise-readonly-dynamic-analyze"
    status: int | None = None
    reason = "Monatise read-only service unavailable"
    for attempt in range(1, attempts + 1):
        run = subprocess.run([str(tool), asset, interval], capture_output=True, text=True, timeout=130, check=False)
        try:
            payload = json.loads(run.stdout)
        except (ValueError, TypeError):
            payload = {}
        if run.returncode == 0 and isinstance(payload, dict) and "http_status" not in payload:
            return payload
        status = payload.get("http_status") if isinstance(payload, dict) else None
        reason = str(payload.get("reason") or reason) if isinstance(payload, dict) else reason
        if status not in RETRYABLE_STATUSES or attempt == attempts:
            break
        time.sleep(min(4.0, 0.5 * 2 ** (attempt - 1)))
    if status == 400:
        raise ValueError(f"Monatise rejected the request: {reason}")
    if status == 401:
        raise PermissionError("Monatise production authorization was rejected")
    raise RuntimeError(f"Monatise read-only service unavailable (HTTP {status}): {reason}")


def _is_positive_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _valid_entry_zone(zone: object) -> bool:
    return (
        isinstance(zone, dict)
        and _is_positive_number(zone.get("low"))
        and _is_positive_number(zone.get("high"))
        and zone["low"] < zone["high"]
    )


def analyze(asset: str, interval: str = "1h", payload: dict | None = None) -> dict:
    analysis = payload if payload is not None else fetch(asset, interval)

    classification = str(analysis.get("classification") or "no_trade").lower()
    direction = str(analysis.get("direction") or "none").lower()
    provenance = analysis.get("provenance") if isinstance(analysis.get("provenance"), dict) else {}
    quality = analysis.get("data_quality") if isinstance(analysis.get("data_quality"), dict) else {}

    # Validator: execution_enabled, read-only capability, verified provenance,
    # source timestamps, and a known classification are non-negotiable —
    # missing any of these fails the whole result closed, not just the trade.
    invalid_reasons: list[str] = []
    if analysis.get("execution_enabled") is not False:
        invalid_reasons.append("execution_enabled was not explicitly false")
    if not provenance.get("instrument") or not provenance.get("exchange"):
        invalid_reasons.append("provenance is missing a verified instrument/exchange")
    if not provenance.get("supported_coins_observed_at") or not provenance.get("market_observed_at"):
        invalid_reasons.append("provenance is missing source timestamps")
    if classification not in {"grid", "trend", "no_trade"}:
        invalid_reasons.append("classification is not a recognized value")
        classification = "no_trade"

    actionable = classification in {"grid", "trend"} and not invalid_reasons and quality.get("passed") is True

    if actionable:
        missing = []
        if not _valid_entry_zone(analysis.get("entry_zone")):
            missing.append("entry_zone")
        if not str(analysis.get("entry_trigger") or "").strip():
            missing.append("entry_trigger")
        if not _is_positive_number(analysis.get("invalidation")):
            missing.append("invalidation")
        targets = analysis.get("targets")
        if not (isinstance(targets, list) and targets and all(_is_positive_number(item) for item in targets)):
            missing.append("targets")
        if not _is_positive_number(analysis.get("reward_risk")):
            missing.append("reward_risk")
        if not str(analysis.get("expires_at") or "").strip():
            missing.append("expires_at")
        if missing:
            actionable = False
            invalid_reasons.append("actionable setup is missing " + ", ".join(missing))

    if not actionable:
        classification = "no_trade"
        direction = "none"

    result = {
        "asset": asset,
        "interval": analysis.get("interval", interval),
        "classification": classification,
        "direction": direction if actionable else "none",
        "actionable": actionable,
        "entry_zone": analysis.get("entry_zone") if actionable else None,
        "entry_trigger": analysis.get("entry_trigger") if actionable else None,
        "invalidation": analysis.get("invalidation") if actionable else None,
        "targets": list(analysis.get("targets") or []) if actionable else [],
        "reward_risk": analysis.get("reward_risk") if actionable else None,
        "score": analysis.get("score"),
        "grid_score": analysis.get("grid_score"),
        "score_threshold": analysis.get("score_threshold", 7),
        "provenance": provenance,
        "evidence": analysis.get("evidence") if isinstance(analysis.get("evidence"), dict) else {},
        "data_quality": {
            "passed": bool(quality.get("passed")) and not invalid_reasons,
            "failures": list(quality.get("failures") or []) + invalid_reasons,
            "warnings": list(quality.get("warnings") or []),
        },
        "volatility_assessment": analysis.get("volatility_assessment"),
        "expires_at": analysis.get("expires_at") if actionable else None,
        "run_id": analysis.get("run_id"),
        "execution": {"enabled": False, "orders_placed": 0},
    }
    return result


def telegram(result: dict) -> str:
    lines = [
        "MONATISE DYNAMIC CRYPTO ANALYSIS",
        f"Asset: {result['asset']}",
        f"Timeframe: {result['interval']}",
    ]
    provenance = result.get("provenance") or {}
    instrument, exchange = provenance.get("instrument"), provenance.get("exchange")
    if instrument and exchange:
        lines.append(f"Resolved market: {instrument} on {exchange}")
    else:
        lines.append("Resolved market: unavailable")

    if not result["actionable"]:
        lines.append(f"Decision: NO_TRADE ({result['classification'].upper()})")
        failures = result["data_quality"]["failures"][:3]
        if failures:
            lines += ["Why:", *[f"• {item}" for item in failures]]
    else:
        lines.append(f"Decision: {result['classification'].upper()} ({result['direction'].upper()})")
        zone = result["entry_zone"]
        lines.append(f"Entry zone: {zone['low']:,.8g} — {zone['high']:,.8g} (trigger required, not an automatic entry)")
        lines.append(f"Trigger: {result['entry_trigger']}")
        lines.append(f"Invalidation: {result['invalidation']:,.8g}")
        lines.append("Targets: " + " | ".join(f"{item:,.8g}" for item in result["targets"]))
        lines.append(f"Reward:risk: {result['reward_risk']:.2f}")

    display_score = result.get("grid_score") if result["classification"] == "grid" else result.get("score")
    if display_score is not None:
        lines.append(f"Score: {display_score}/10 | threshold: ±{result['score_threshold']}")

    warnings = result["data_quality"]["warnings"][:3]
    if warnings:
        lines += ["Evidence unavailable:", *[f"• {item}" for item in warnings]]

    if result.get("volatility_assessment"):
        lines.append(f"Note: {result['volatility_assessment']}")

    if result["actionable"] and result.get("expires_at"):
        lines.append(f"Expires: {result['expires_at']}")

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
