"""Production-facing, analysis-only ASGI entrypoint for Monatise."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import mimetypes
from pathlib import Path
from time import time
from typing import Any

from monatise.application.deployment import OrchestrationASGI, OrchestrationRuntime


LOGGER = logging.getLogger("monatise.production")


class ProductionRuntime(OrchestrationRuntime):
    async def start(self) -> None:
        LOGGER.info("validating production safety configuration")
        if self.environment.get("MONATISE_ENVIRONMENT", "").strip().casefold() != "production":
            raise ValueError("MONATISE_ENVIRONMENT must be production")
        if self.environment.get("MONATISE_ALLOW_DEGRADED_MACRO", "").strip().casefold() not in {"1", "true", "yes", "on"}:
            raise ValueError("production macro provider is unavailable and degraded mode was not explicitly enabled")
        required = {
            "MONATISE_MODE": "paper",
            "MONATISE_NETWORK": "paper",
            "MONATISE_EXECUTION_ENABLED": "false",
            "MONATISE_AUTONOMOUS_EXECUTION": "false",
            "MONATISE_EXECUTION_ADAPTER_ENABLED": "false",
            "MONATISE_ALLOW_LIVE_ORDERS": "false",
            "MONATISE_OPENCLAW_EXECUTION_ALLOWED": "false",
            "MONATISE_TELEGRAM_EXECUTION_ALLOWED": "false",
            "MONATISE_GOVERNANCE_KILL_SWITCH_ENABLED": "true",
            "MONATISE_AUDIT_LOGGING_ENABLED": "true",
        }
        invalid = [key for key, value in required.items() if self.environment.get(key, "").strip().casefold() != value]
        if invalid:
            raise ValueError("production safety configuration is missing or invalid: " + ", ".join(invalid))
        LOGGER.info("production safety configuration validated")
        await super().start()

    def readiness(self) -> tuple[bool, dict[str, Any]]:
        # During a zero-downtime deploy the live instance owns the scheduler
        # lock until Render cuts traffic over.  The replacement is a healthy
        # contender and acquires leadership after the old instance shuts down;
        # requiring this process to be leader would deadlock every redeploy.
        return super().readiness()


class ProductionASGI(OrchestrationASGI):
    def __init__(self, runtime: OrchestrationRuntime | None = None, static_dir: Path | None = None) -> None:
        super().__init__(runtime or ProductionRuntime())
        self.static_dir = (static_dir or Path(__file__).resolve().parents[2] / "app").resolve()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and scope.get("path") == "/api/analysis":
            if scope.get("method", "GET").upper() != "POST":
                await self._respond(send, 405, {"status": "method_not_allowed"})
                return
            code, payload = await self._production_analysis(scope, receive)
            await self._respond(send, code, payload)
            return
        if scope.get("type") == "http" and await self._serve_frontend(scope, send):
            return
        await super().__call__(scope, receive, send)

    async def _serve_frontend(self, scope: dict[str, Any], send: Any) -> bool:
        method = scope.get("method", "GET").upper()
        path = scope.get("path", "/")
        if method not in {"GET", "HEAD"} or path.startswith(("/api/", "/health/")):
            return False

        relative_path = "index.html" if path == "/" else path.lstrip("/")
        candidate = (self.static_dir / relative_path).resolve()
        try:
            candidate.relative_to(self.static_dir)
        except ValueError:
            return False
        if not candidate.is_file():
            return False

        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json", "image/svg+xml"}:
            content_type += "; charset=utf-8"
        headers = [
            (b"content-type", content_type.encode()),
            (b"content-length", str(len(body)).encode()),
            (b"x-content-type-options", b"nosniff"),
        ]
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": b"" if method == "HEAD" else body})
        return True

    @staticmethod
    async def _respond(send: Any, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        await send({"type": "http.response.start", "status": code, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    async def _production_analysis(self, scope: dict[str, Any], receive: Any) -> tuple[int, dict[str, Any]]:
        if self.runtime.environment.get("MONATISE_ENVIRONMENT", "").strip().casefold() != "production":
            return 404, {"status": "not_found"}
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if len(body) > 4096:
                return 413, {"status": "request_too_large"}
            if not message.get("more_body", False):
                break
        headers = {key.decode().casefold(): value.decode() for key, value in scope.get("headers", ())}
        timestamp = headers.get("x-monatise-timestamp", "")
        signature = headers.get("x-monatise-signature", "")
        token = self.runtime.environment.get("MONATISE_OPENCLAW_TOKEN", "")
        try:
            fresh = abs(time() - int(timestamp)) <= 300
        except ValueError:
            fresh = False
        expected = hmac.new(token.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest() if token else ""
        if not token or not fresh or not hmac.compare_digest(signature, expected):
            return 401, {"status": "unauthorized"}
        if self.runtime.redis_coordination and not await self.runtime.redis_coordination.claim_nonce(signature):
            return 409, {"status": "duplicate_request"}
        try:
            request = json.loads(body or b"{}")
            if not isinstance(request, dict) or set(request) != {"symbol"}:
                return 400, {"status": "invalid_request", "reason": "only symbol is accepted"}
            return 200, await self.runtime.analyse(str(request["symbol"]), source="monatise.production")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return 400, {"status": "invalid_request", "reason": str(exc)}
        except Exception as exc:
            LOGGER.exception("production analysis failed", extra={"error_type": type(exc).__name__})
            return 503, {"status": "analysis_unavailable", "error_type": type(exc).__name__}


app = ProductionASGI()
