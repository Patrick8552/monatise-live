"""End-to-end smoke test for the standalone monatise-live runtime.

monatise/live/server.py is not run by the Render or Docker production
deployment (which runs monatise.application.production:app instead), but it
is still the packaged `monatise-live` CLI entrypoint and the runtime documented
as the standalone/self-hosted way to run Monatise. Nothing
else in CI exercises it end-to-end, so a regression here (a startup crash, an
execution-safety flag flipping on, a shutdown that leaks a thread or a
connection) would go unnoticed until someone tried to actually run it.
"""

from __future__ import annotations

import http.client
import json
import os
import signal
import socket
import subprocess
import time
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

REPO_ROOT = Path(__file__).resolve().parents[1]
STARTUP_TIMEOUT_SECONDS = 20.0
SHUTDOWN_TIMEOUT_SECONDS = 10.0

# Env vars that could carry a real credential in on a developer's machine or a
# misconfigured runner. The whole point of this test is proving the runtime
# starts fine -- in read-only paper mode -- without any of them.
CREDENTIAL_ENV_VARS = (
    "HYPERLIQUID_ACCOUNT_ADDRESS",
    "HYPERLIQUID_SECRET_KEY",
    "COINGLASS_API_KEY",
    "QUIVER_API_KEY",
    "BACKPACK_API_KEY",
    "BACKPACK_SECRET_KEY",
    "MONATISE_TRADINGVIEW_WEBHOOK_TOKEN",
    "MONATISE_CONTROL_TOKEN",
    "DATABASE_URL",
    "MONATISE_DATABASE_URL",
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _get_json(host: str, port: int, path: str, timeout: float = 5.0) -> dict:
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        body = response.read()
        if response.status != 200:
            raise AssertionError(f"{path} returned {response.status}: {body!r}")
        return json.loads(body)
    finally:
        conn.close()


def _wait_until_healthy(host: str, port: int, deadline: float) -> None:
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            payload = _get_json(host, port, "/api/health", timeout=1.0)
            if payload.get("ok") is True:
                return
        except (OSError, AssertionError, ValueError) as error:
            last_error = error
        time.sleep(0.2)
    raise TimeoutError(f"monatise-live never became healthy: {last_error}")


def _port_is_closed(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((host, port)) != 0


@pytest.fixture
def paper_mode_env(tmp_path: Path) -> dict[str, str]:
    port = _free_port()
    env = dict(os.environ)
    for var in CREDENTIAL_ENV_VARS:
        env.pop(var, None)
    env.update(
        {
            "MONATISE_MODE": "paper",
            "MONATISE_NETWORK": "testnet",
            "MONATISE_HOST": "127.0.0.1",
            "MONATISE_PORT": str(port),
            "MONATISE_AUTH_DB": str(tmp_path / "monatise-users.db"),
            "MONATISE_DATA_DIR": str(tmp_path),
            "MONATISE_ENABLE_GLOBAL_CREDENTIALS": "false",
            # A throwaway Fernet key generated fresh per test run -- not a
            # real secret, just satisfies the "no hardcoded fallback key"
            # startup guard so the process can boot at all.
            "MONATISE_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
            "PYTHONUNBUFFERED": "1",
        }
    )
    env["_SMOKE_TEST_PORT"] = str(port)
    return env


def test_packaged_cli_boots_read_only_and_shuts_down_cleanly(
    paper_mode_env: dict[str, str],
) -> None:
    port = int(paper_mode_env.pop("_SMOKE_TEST_PORT"))
    host = "127.0.0.1"

    process = subprocess.Popen(
        ["monatise-live"],
        cwd=REPO_ROOT,
        env=paper_mode_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_until_healthy(host, port, deadline=time.monotonic() + STARTUP_TIMEOUT_SECONDS)

        health = _get_json(host, port, "/api/health")
        assert health == {"ok": True}

        operator = _get_json(host, port, "/api/operator")
        assert operator["mode"] == "paper"
        assert operator["executionMode"] == "disabled"
        assert operator["riskCaps"]["allowLiveOrders"] is False
        assert operator["riskCaps"]["liveConfirmation"] is False
        assert operator["integrations"]["backpack"]["executionEnabled"] is False
        # No exchange/data-provider credentials were configured above --
        # confirm the process honestly reports that instead of the
        # deployment silently assuming a secret exists that it doesn't have.
        assert operator["integrations"]["coinglass"]["configured"] is False
        assert operator["integrations"]["quiver"]["configured"] is False
        assert operator["integrations"]["backpack"]["configured"] is False
        assert operator["integrations"]["tradingView"]["configured"] is False
    finally:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            output = process.stdout.read() if process.stdout else ""
            raise AssertionError(
                f"monatise-live did not shut down within {SHUTDOWN_TIMEOUT_SECONDS}s "
                f"of SIGTERM and had to be killed. Output:\n{output}"
            ) from None

    assert process.returncode == 0, (
        f"expected a clean exit (0) on SIGTERM, got {process.returncode}; "
        "a non-zero/negative code means the process was killed rather than "
        "shutting down gracefully"
    )
    assert _port_is_closed(host, port), "server port is still accepting connections after shutdown"


def test_legacy_server_refuses_to_start_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    from monatise.live import server

    monkeypatch.setenv("MONATISE_ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="legacy monatise.live.server is disabled in production"):
        server.main()
