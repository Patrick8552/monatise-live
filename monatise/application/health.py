"""Dependency-free ASGI liveness and readiness endpoints."""

from __future__ import annotations

import json
from typing import Any


class HealthApplication:
    def __init__(self, application: Any) -> None:
        self._application = application

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await self._application.start()
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await self._application.shutdown()
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if scope.get("type") != "http":
            return
        path = scope.get("path", "")
        if path == "/health/live":
            status, payload = 200, {"status": "alive", "execution_enabled": False}
        elif path == "/health/ready":
            payload = self._application.orchestrator.health()
            status = 200 if payload["status"] == "healthy" else 503
        else:
            status, payload = 404, {"status": "not_found"}
        body = json.dumps(payload, separators=(",", ":")).encode()
        await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
