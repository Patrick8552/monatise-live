#!/usr/bin/env python3
"""Fail-fast public smoke checks for Monatise paper staging."""

from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from monatise.application.registry import CANONICAL_ENGINE_ORDER


def get_json(base_url: str, path: str) -> tuple[int, dict]:
    try:
        with urlopen(base_url.rstrip("/") + path, timeout=20) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.load(exc)
    except (URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError(f"request failed for {path}: {type(exc).__name__}") from exc


def run(base_url: str) -> list[str]:
    failures: list[str] = []
    live_code, live = get_json(base_url, "/health/live")
    if live_code != 200 or live.get("status") != "alive":
        failures.append("liveness failed")
    ready_code, ready = get_json(base_url, "/health/ready")
    if ready_code != 200 or ready.get("status") != "ready":
        failures.append("readiness failed")
    dependencies = ready.get("dependencies", {})
    for dependency in ("postgresql", "redis", "migrations", "event_bus", "state_manager", "audit_repository", "audit_integrity", "scheduler", "pipeline_orchestrator", "governance", "coinglass"):
        if dependencies.get(dependency, {}).get("status") != "ok":
            failures.append(f"{dependency} is not ready")
    registry = dependencies.get("engine_registry", {})
    if registry.get("count") != 20 or tuple(registry.get("order", ())) != CANONICAL_ENGINE_ORDER:
        failures.append("canonical engine registry mismatch")
    if ready.get("mode") != "paper" or ready.get("execution_enabled") is not False:
        failures.append("paper-only execution invariant failed")
    notifications = dependencies.get("notifications", {})
    if notifications.get("telegram") not in {"configured_notification_only", "unavailable_optional"} or notifications.get("openclaw") not in {"configured_non_executable", "unavailable_optional"}:
        failures.append("notification execution invariant failed")
    if dependencies.get("governance", {}).get("kill_switch") is not True:
        failures.append("governance kill switch unavailable")
    macro = dependencies.get("macro_provider", {})
    if macro.get("status") not in {"ok", "degraded"}:
        failures.append("macro_provider is not ready")
    if macro.get("mode") == "degraded_unavailable_factors" and macro.get("blocks_on_missing_data") is not False:
        failures.append("degraded macro mode is not configured to continue safely")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    failures = run(args.base_url)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS: Monatise paper staging is live, ready, canonical, and execution-disabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
