"""Regular-session histories for stock pipeline tests (no fabricated gap bars)."""

from datetime import date, datetime, timedelta, timezone


def calendar_rows(start, end, *, holidays=(), early_closes=None):
    day, last = date.fromisoformat(start), date.fromisoformat(end)
    result = []
    while day <= last:
        if day.weekday() < 5 and day.isoformat() not in holidays:
            result.append(
                {
                    "date": day.isoformat(),
                    "open": "09:30",
                    "close": (early_closes or {}).get(day.isoformat(), "16:00"),
                }
            )
        day += timedelta(days=1)
    return result


def stock_rows(tf, now, *, count=60):
    # These fixtures are in September (EDT); provider aggregates stay UTC based.
    step = {"4h": 14400, "1h": 3600, "15m": 900, "5m": 300, "1m": 60}[tf]
    boundary = datetime.fromtimestamp(int(now.timestamp()) // step * step, timezone.utc)
    times = []
    candidate = boundary - timedelta(seconds=step)
    while len(times) < count:
        start = candidate.replace(hour=13, minute=30, second=0)
        close = start.replace(hour=20, minute=0)
        if (
            candidate.weekday() < 5
            and candidate < close
            and candidate + timedelta(seconds=step) > start
        ):
            times.append(candidate)
        candidate -= timedelta(seconds=step)
    return [
        {
            "t": t.isoformat(),
            "o": 100 + i * 0.4,
            "h": 101.2 + i * 0.4,
            "l": 99.2 + i * 0.4,
            "c": 100.6 + i * 0.4,
            "v": 1000 + i,
        }
        for i, t in enumerate(reversed(times), start=100 - count)
    ]
