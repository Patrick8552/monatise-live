#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

SUPPORTED = {"AAPL", "TSLA", "NVDA", "QQQ", "SPY"}


def normalize(raw: str) -> str:
    symbol = raw.strip().upper().removeprefix("/STOCK ").removeprefix("/")
    if ":" in symbol:
        symbol = symbol.rsplit(":", 1)[-1]
    if symbol not in SUPPORTED:
        raise ValueError("Unsupported stock: expected AAPL, TSLA, NVDA, QQQ, or SPY")
    return symbol


def fetch(symbol: str) -> dict:
    tool = Path.home() / ".openclaw/workspace/tools/monatise-readonly-status"
    run = subprocess.run([str(tool), symbol, "1h"], capture_output=True, text=True, timeout=120, check=False)
    if run.returncode:
        raise RuntimeError("Monatise stock analysis unavailable")
    return json.loads(run.stdout)


def telegram(result: dict) -> str:
    decision = str(result.get("decision") or "NO_TRADE")
    lines = [
        "MONATISE STOCK ANALYSIS",
        f"Asset: {result.get('asset')}",
        f"Decision: {decision.replace('_', ' ')}",
        f"Quiver score: {int(result.get('score') or 0):+d}/10 | threshold: ±{int(result.get('score_threshold') or 3)}",
    ]
    reasons = list(result.get("reasons") or [])[:4]
    cautions = list(result.get("cautions") or [])[:3]
    if reasons:
        lines += ["Evidence:", *[f"• {item}" for item in reasons]]
    if cautions:
        lines += ["Cautions:", *[f"• {item}" for item in cautions]]
    if result.get("setup_status") == "confirmed":
        lines += [
            f"Entry: ${float(result['entry']):,.2f}",
            f"Stop: ${float(result['stop_loss']):,.2f}",
            f"Target: ${float(result['target']):,.2f}",
            f"Reward/risk: {float(result['reward_risk']):.2f}",
            f"Levels: {result.get('level_source', 'Alpaca market data')}",
        ]
    elif decision in {"BUY_WATCH", "SELL_WATCH"}:
        lines.append("Price confirmation pending; no entry or stop is active.")
    lines += ["Quiver alternative-data watch signal only.", "No trade was executed; confirm price structure, entry, invalidation, and risk before acting."]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol")
    parser.add_argument("--format", choices=("json", "telegram"), default="telegram")
    args = parser.parse_args()
    try:
        result = fetch(normalize(args.symbol))
    except ValueError as exc:
        parser.error(str(exc))
    print(telegram(result) if args.format == "telegram" else json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
