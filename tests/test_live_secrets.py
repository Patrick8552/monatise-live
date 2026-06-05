from __future__ import annotations

import os
import tempfile
from pathlib import Path

from monatise.live import secrets


def test_secret_value_reads_direct_secret_file() -> None:
    with _isolated_secrets_dir() as tmp_path:
        os.environ.pop("MONATISE_CONTROL_TOKEN", None)
        (tmp_path / "MONATISE_CONTROL_TOKEN").write_text("control-token\n", encoding="utf-8")

        assert secrets.secret_value("MONATISE_CONTROL_TOKEN") == "control-token"


def test_secret_value_reads_key_value_secret_file() -> None:
    with _isolated_secrets_dir() as tmp_path:
        os.environ.pop("HYPERLIQUID_SECRET_KEY", None)
        (tmp_path / "render-secrets").write_text(
            "MONATISE_CONTROL_TOKEN=control-token\nHYPERLIQUID_SECRET_KEY='api-key'\n",
            encoding="utf-8",
        )

        assert secrets.secret_value("HYPERLIQUID_SECRET_KEY") == "api-key"


class _isolated_secrets_dir:
    def __enter__(self) -> Path:
        self._old_dir = secrets.SECRETS_DIR
        self._tmp = tempfile.TemporaryDirectory()
        path = Path(self._tmp.name)
        secrets.SECRETS_DIR = path
        return path

    def __exit__(self, *_args: object) -> None:
        secrets.SECRETS_DIR = self._old_dir
        self._tmp.cleanup()
