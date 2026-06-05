from __future__ import annotations

import os
from pathlib import Path


SECRETS_DIR = Path("/etc/secrets")


def secret_value(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value:
        return value.strip()

    direct = _read_secret_file(SECRETS_DIR / name)
    if direct:
        return direct

    for path in _secret_files():
        parsed = _read_key_value_file(path, name)
        if parsed:
            return parsed

    return default


def _secret_files() -> list[Path]:
    if not SECRETS_DIR.exists():
        return []
    return [path for path in SECRETS_DIR.iterdir() if path.is_file()]


def _read_secret_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _read_key_value_file(path: Path, name: str) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""
