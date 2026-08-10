"""Formatting helpers for user-facing Monatise timestamps."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


NIGERIA_TIME_ZONE = ZoneInfo("Africa/Lagos")


def format_nigeria_time(value: datetime) -> str:
    """Render an aware timestamp in West Africa Time."""
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(NIGERIA_TIME_ZONE).strftime("%Y-%m-%d %H:%M:%S WAT")


def nigeria_isoformat(value: datetime) -> str:
    """Render an aware timestamp as an ISO-8601 Nigeria-local value."""
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(NIGERIA_TIME_ZONE).isoformat()
