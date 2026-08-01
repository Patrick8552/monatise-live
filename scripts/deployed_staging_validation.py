#!/usr/bin/env python3
"""Run signed, execution-disabled scenarios against deployed paper staging."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def post_scenario(base_url: str, token: str, scenario: str) -> tuple[int, dict]:
    body = json.dumps({"symbol": "BTC", "scenario": scenario}, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(token.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    request = Request(
        base_url.rstrip("/") + "/api/staging/analyse",
        data=body,
        headers={"content-type": "application/json", "x-monatise-timestamp": timestamp, "x-monatise-signature": signature},
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.load(exc)
    except (URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError(f"staging scenario request failed: {type(exc).__name__}") from exc


def run(base_url: str, token: str) -> list[str]:
    failures: list[str] = []
    for scenario in ("live", "no_trade", "governance_block"):
        code, result = post_scenario(base_url, token, scenario)
        if code != 200:
            failures.append(f"{scenario}: HTTP {code}")
            continue
        if result.get("execution_enabled") is not False:
            failures.append(f"{scenario}: execution invariant failed")
        if scenario == "live" and result.get("classification") not in {"trend", "grid", "no_trade"}:
            failures.append("live: invalid classification")
        if scenario == "no_trade" and (result.get("classification") != "no_trade" or result.get("risk_validation_invoked")):
            failures.append("no_trade: downstream risk gate was not skipped")
        if scenario == "governance_block" and result.get("blocked_by") != "governance_loss_control":
            failures.append("governance_block: governance did not block")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", default=os.environ.get("MONATISE_STAGING_API_TOKEN", ""))
    args = parser.parse_args()
    if not args.token:
        print("FAIL: MONATISE_STAGING_API_TOKEN is required", file=sys.stderr)
        return 2
    failures = run(args.base_url, args.token)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS: live, NO_TRADE, and governance-blocked paper scenarios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
