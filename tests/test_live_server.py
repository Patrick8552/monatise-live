from __future__ import annotations

import json
import os
from io import BytesIO

from monatise.live.server import MonatiseHandler


class FakeHandler:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers
        self.status = 0
        self.wfile = BytesIO()

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, _key: str, _value: str) -> None:
        pass

    def end_headers(self) -> None:
        pass


def test_live_server_requires_control_token_for_status() -> None:
    old_token = os.environ.get("MONATISE_CONTROL_TOKEN")
    os.environ["MONATISE_CONTROL_TOKEN"] = "test-token"

    try:
        rejected = FakeHandler({})
        assert not MonatiseHandler._require_api_auth(rejected)  # type: ignore[arg-type]
        assert rejected.status == 401
        assert json.loads(rejected.wfile.getvalue()) == {"error": "control token required"}

        accepted = FakeHandler({"Authorization": "Bearer test-token"})
        assert MonatiseHandler._require_api_auth(accepted)  # type: ignore[arg-type]
        assert accepted.status == 0
    finally:
        if old_token is None:
            os.environ.pop("MONATISE_CONTROL_TOKEN", None)
        else:
            os.environ["MONATISE_CONTROL_TOKEN"] = old_token
