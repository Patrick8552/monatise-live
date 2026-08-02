#!/usr/bin/env python3
"""Fail-fast smoke checks for canonical production analysis-only Monatise."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from monatise.application.registry import CANONICAL_ENGINE_ORDER


def request_json(base_url: str, path: str, *, body: bytes | None = None, token: str = "") -> tuple[int, dict]:
    headers: dict[str, str] = {}
    if body is not None:
        timestamp = str(int(time.time()))
        headers = {
            "content-type": "application/json",
            "x-monatise-timestamp": timestamp,
            "x-monatise-signature": hmac.new(token.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest(),
        }
    request = Request(base_url.rstrip("/") + path, data=body, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.load(exc)
    except (URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError(f"request failed for {path}: {type(exc).__name__}") from exc


def run(base_url: str, token: str) -> list[str]:
    failures: list[str] = []
    live_code, live = request_json(base_url, "/health/live")
    if live_code != 200 or live.get("status") != "alive": failures.append("liveness failed")
    ready_code, ready = request_json(base_url, "/health/ready")
    dependencies = ready.get("dependencies", {})
    if ready_code != 200 or ready.get("status") != "ready": failures.append("readiness failed")
    registry = dependencies.get("engine_registry", {})
    if registry.get("count") != 20 or tuple(registry.get("order", ())) != CANONICAL_ENGINE_ORDER: failures.append("canonical engine registry mismatch")
    if ready.get("mode") != "paper" or ready.get("execution_enabled") is not False: failures.append("execution invariant failed")
    if dependencies.get("scheduler", {}).get("leader") is not True: failures.append("scheduler leader unavailable")
    if dependencies.get("governance", {}).get("kill_switch") is not True: failures.append("kill switch unavailable")
    if dependencies.get("audit_logging", {}).get("enabled") is not True: failures.append("audit logging unavailable")
    if dependencies.get("coinglass", {}).get("status") != "ok": failures.append("CoinGlass unavailable")
    if dependencies.get("macro_provider", {}).get("status") not in {"ok", "degraded"}: failures.append("Macro unavailable")
    if request_json(base_url, "/api/staging/analyse", body=b"{}", token=token)[0] not in {403, 404}: failures.append("staging route exposed")
    rejected = json.dumps({"symbol": "BTC", "leverage": 2}, separators=(",", ":")).encode()
    if request_json(base_url, "/api/analysis", body=rejected, token=token)[0] != 400: failures.append("execution-shaped input was not rejected")
    analysis = json.dumps({"symbol": "BTC"}, separators=(",", ":")).encode()
    code, result = request_json(base_url, "/api/analysis", body=analysis, token=token)
    if code != 200 or result.get("execution_enabled") is not False or not result.get("audit_reference") or not result.get("state_reference"):
        failures.append("paper analysis failed")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    token = os.environ.get("MONATISE_OPENCLAW_TOKEN", "")
    if not token:
        print("FAIL: MONATISE_OPENCLAW_TOKEN is required")
        return 1
    failures = run(args.base_url, token)
    for failure in failures: print(f"FAIL: {failure}")
    if failures: return 1
    print("PASS: Monatise production analysis is canonical, durable, and execution-disabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
