from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")
ECONOMIC_BLACKOUT_MINUTES = 60
ECONOMIC_RELEASES = (
    ("CPI", "Consumer Price Index", "2026-01-13T08:30:00"),
    ("PPI", "Producer Price Index", "2026-01-14T08:30:00"),
    ("PPI", "Producer Price Index", "2026-01-30T08:30:00"),
    ("CPI", "Consumer Price Index", "2026-02-13T08:30:00"),
    ("PPI", "Producer Price Index", "2026-02-27T08:30:00"),
    ("CPI", "Consumer Price Index", "2026-03-11T08:30:00"),
    ("PPI", "Producer Price Index", "2026-03-18T08:30:00"),
    ("CPI", "Consumer Price Index", "2026-04-10T08:30:00"),
    ("PPI", "Producer Price Index", "2026-04-14T08:30:00"),
    ("CPI", "Consumer Price Index", "2026-05-12T08:30:00"),
    ("PPI", "Producer Price Index", "2026-05-13T08:30:00"),
    ("CPI", "Consumer Price Index", "2026-06-10T08:30:00"),
    ("PPI", "Producer Price Index", "2026-06-11T08:30:00"),
    ("CPI", "Consumer Price Index", "2026-07-14T08:30:00"),
    ("PPI", "Producer Price Index", "2026-07-15T08:30:00"),
    ("CPI", "Consumer Price Index", "2026-08-12T08:30:00"),
    ("PPI", "Producer Price Index", "2026-08-13T08:30:00"),
    ("PPI", "Producer Price Index", "2026-09-10T08:30:00"),
    ("CPI", "Consumer Price Index", "2026-09-11T08:30:00"),
    ("CPI", "Consumer Price Index", "2026-10-14T08:30:00"),
    ("PPI", "Producer Price Index", "2026-10-15T08:30:00"),
    ("CPI", "Consumer Price Index", "2026-11-10T08:30:00"),
    ("PPI", "Producer Price Index", "2026-11-13T08:30:00"),
    ("CPI", "Consumer Price Index", "2026-12-10T08:30:00"),
    ("PPI", "Producer Price Index", "2026-12-15T08:30:00"),
)


def _minutes_since_utc_midnight(moment: datetime | None = None) -> int:
    moment = moment or datetime.now(UTC)
    return moment.hour * 60 + moment.minute


def _window_open(start_hour: int, end_hour: int, moment: datetime | None = None) -> bool:
    now = _minutes_since_utc_midnight(moment)
    start = start_hour * 60
    end = end_hour * 60
    return start <= now < end


def _minutes_until_hour(hour: int, moment: datetime | None = None) -> int:
    now = _minutes_since_utc_midnight(moment)
    return (hour * 60 - now + 1440) % 1440


def signal_window_guard(moment: datetime | None = None, window: str = "always") -> dict:
    return {"active": False, "window": "always"}


def economic_release_guard(
    moment: datetime | None = None,
    blackout_minutes: int = ECONOMIC_BLACKOUT_MINUTES,
) -> dict:
    now = moment or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    now = now.astimezone(UTC)
    blackout = timedelta(minutes=blackout_minutes)
    next_release: tuple[str, str, datetime] | None = None
    for code, name, local_iso in ECONOMIC_RELEASES:
        release = datetime.fromisoformat(local_iso).replace(tzinfo=EASTERN).astimezone(UTC)
        starts = release - blackout
        ends = release + blackout
        if starts <= now <= ends:
            if now < release:
                minutes = int((release - now).total_seconds() // 60)
                side = "before"
            else:
                minutes = int((ends - now).total_seconds() // 60)
                side = "after"
            return {
                "active": True,
                "event": code,
                "eventName": name,
                "releaseTime": release.isoformat().replace("+00:00", "Z"),
                "minutes": max(0, minutes),
                "message": f"{code} blackout: no signals from {blackout_minutes}m before until {blackout_minutes}m after the {name} release",
                "phase": side,
            }
        if release > now and (next_release is None or release < next_release[2]):
            next_release = (code, name, release)
    if next_release is None:
        return {"active": False}
    code, name, release = next_release
    return {
        "active": False,
        "event": code,
        "eventName": name,
        "releaseTime": release.isoformat().replace("+00:00", "Z"),
    }
