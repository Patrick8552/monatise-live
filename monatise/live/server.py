from __future__ import annotations

import json
import hmac
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from urllib.parse import urlparse

from monatise.live.config import RuntimeConfig
from monatise.live.secrets import secret_value
from monatise.live.service import JsonEncoder, TradingService


class MonatiseHandler(SimpleHTTPRequestHandler):
    service: TradingService
    app_dir: Path

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, directory=str(self.app_dir), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._json({"ok": True})
            return
        if parsed.path == "/api/status":
            if not self._require_api_auth():
                return
            self._json(self.service.snapshot())
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/start":
            if not self._require_api_auth():
                return
            self._json(self.service.start())
            return
        if parsed.path == "/api/stop":
            if not self._require_api_auth():
                return
            self._json(self.service.stop())
            return
        self.send_error(404, "not found")

    def _require_api_auth(self) -> bool:
        token = secret_value("MONATISE_CONTROL_TOKEN", "")
        if not token:
            return True

        authorization = self.headers.get("Authorization", "")
        supplied = ""
        if authorization.startswith("Bearer "):
            supplied = authorization.removeprefix("Bearer ").strip()
        supplied = supplied or self.headers.get("X-Monatise-Control-Token", "").strip()

        if hmac.compare_digest(supplied, token):
            return True

        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":"control token required"}')
        return False

    def _json(self, payload: dict) -> None:
        body = json.dumps(payload, cls=JsonEncoder).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    config = RuntimeConfig.from_env()
    service = TradingService(config)
    app_dir = Path(__file__).resolve().parents[2] / "app"

    class Handler(MonatiseHandler):
        pass

    Handler.service = service
    Handler.app_dir = app_dir

    port = int(os.getenv("MONATISE_PORT", os.getenv("PORT", "4174")))
    host = os.getenv("MONATISE_HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Monatise backend running at http://{host}:{port}", flush=True)
    print(f"mode={config.mode} network={config.network} live_ready={config.live_enabled}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
