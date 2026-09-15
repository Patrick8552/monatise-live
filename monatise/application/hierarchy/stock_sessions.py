"""Regular-session expectations for Alpaca's existing UTC-aligned stock bars.

The calendar changes which bars are expected, never their prices, timestamps,
durations, or finalization buffer. A bar intersecting an early close still has
to reach its provider interval end: an aggregate may include extended trading.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from monatise.application.hierarchy.policy import INTERVAL_SECONDS

NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class StockSession:
    day: date
    opens: datetime
    closes: datetime


@dataclass(frozen=True)
class StockSessionCalendar:
    start: date
    end: date
    sessions: tuple[StockSession, ...]

    @classmethod
    def from_provider(cls, rows, *, start: date, end: date):
        if not isinstance(rows, list) or not rows or start > end:
            raise ValueError("stock_calendar_unavailable")
        sessions = []
        previous = None
        for row in rows:
            try:
                day = date.fromisoformat(row["date"])
                opens, closes = (
                    time.fromisoformat(row["open"]),
                    time.fromisoformat(row["close"]),
                )
                if (
                    not start <= day <= end
                    or previous is not None
                    and day <= previous
                    or opens.tzinfo is not None
                    or closes.tzinfo is not None
                    or opens.second
                    or closes.second
                    or opens.microsecond
                    or closes.microsecond
                    or day.weekday() >= 5
                    or not opens < closes
                ):
                    raise ValueError
                opening = datetime.combine(day, opens, NEW_YORK).astimezone(
                    timezone.utc
                )
                closing = datetime.combine(day, closes, NEW_YORK).astimezone(
                    timezone.utc
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("stock_calendar_invalid") from exc
            sessions.append(StockSession(day, opening, closing))
            previous = day
        return cls(start, end, tuple(sessions))

    def require_regular_session(self, now: datetime) -> StockSession:
        self._covered(now)
        session = next(
            (s for s in self.sessions if s.day == now.astimezone(NEW_YORK).date()), None
        )
        if session is None:
            raise ValueError("stock_exchange_closed")
        if not session.opens <= now < session.closes:
            raise ValueError("stock_regular_session_closed")
        return session

    def _covered(self, now: datetime) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("stock_calendar_timestamp_invalid")
        if not self.start <= now.astimezone(NEW_YORK).date() <= self.end:
            raise ValueError("stock_calendar_coverage_incomplete")

    def regular_bar(self, opened: datetime, timeframe: str) -> bool:
        self._covered(opened)
        seconds = INTERVAL_SECONDS[timeframe]
        if opened.timestamp() % seconds:
            raise ValueError(f"{timeframe}_candle_boundary_invalid")
        closed = opened + timedelta(seconds=seconds)
        return any(opened < s.closes and closed > s.opens for s in self.sessions)

    def expected_closed_open(
        self, timeframe: str, now: datetime, *, grace_seconds: int
    ) -> datetime:
        self._covered(now)
        seconds = INTERVAL_SECONDS[timeframe]
        eligible_open = (
            int((now - timedelta(seconds=grace_seconds)).timestamp() // seconds)
            * seconds
            - seconds
        )
        for session in reversed(self.sessions):
            first = int(session.opens.timestamp() // seconds) * seconds
            last = int((session.closes.timestamp() - 1) // seconds) * seconds
            candidate = min(last, eligible_open)
            if candidate >= first:
                return datetime.fromtimestamp(candidate, timezone.utc)
        raise ValueError(f"{timeframe}_expected_session_bar_unavailable")
