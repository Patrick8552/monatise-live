from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


FOREX_BREAK_GUARD_MINUTES = 60


@dataclass(frozen=True)
class ForexSession:
    name: str
    open_hour: int
    close_hour: int
    pairs: tuple[str, ...]


FOREX_SESSIONS = (
    ForexSession("Sydney", 21, 6, ("AUDUSD", "NZDUSD", "AUDJPY")),
    ForexSession("Tokyo", 0, 9, ("USDJPY", "AUDJPY", "EURJPY")),
    ForexSession("London", 7, 16, ("EURUSD", "GBPUSD", "EURGBP")),
    ForexSession("New York", 12, 21, ("EURUSD", "GBPUSD", "USDJPY")),
)

FOREX_SYMBOLS = frozenset(pair for session in FOREX_SESSIONS for pair in session.pairs)


def normalize_forex_symbol(symbol: str) -> str:
    return symbol.replace("-", "").replace("/", "").upper()


def is_forex_symbol(symbol: str) -> bool:
    return normalize_forex_symbol(symbol) in FOREX_SYMBOLS


def minutes_since_utc_midnight(moment: datetime | None = None) -> int:
    moment = moment or datetime.now(UTC)
    return moment.hour * 60 + moment.minute


def is_session_open(session: ForexSession, moment: datetime | None = None) -> bool:
    now = minutes_since_utc_midnight(moment)
    open_minute = session.open_hour * 60
    close_minute = session.close_hour * 60
    if open_minute < close_minute:
        return open_minute <= now < close_minute
    return now >= open_minute or now < close_minute


def minutes_until_session_change(session: ForexSession, moment: datetime | None = None) -> int:
    now = minutes_since_utc_midnight(moment)
    target_hour = session.close_hour if is_session_open(session, moment) else session.open_hour
    target = target_hour * 60
    return (target - now + 1440) % 1440


def forex_session_break_guard(
    symbol: str,
    moment: datetime | None = None,
    guard_minutes: int = FOREX_BREAK_GUARD_MINUTES,
) -> dict:
    pair = normalize_forex_symbol(symbol)
    if pair not in FOREX_SYMBOLS:
        return {"active": False, "symbol": pair}

    guarded = []
    for session in FOREX_SESSIONS:
        if pair not in session.pairs:
            continue
        minutes = minutes_until_session_change(session, moment)
        if minutes <= guard_minutes:
            opening = not is_session_open(session, moment)
            guarded.append(
                {
                    "session": session.name,
                    "transition": "open" if opening else "close",
                    "minutes": minutes,
                    "pairs": list(session.pairs),
                }
            )

    if not guarded:
        return {"active": False, "symbol": pair}

    primary = min(guarded, key=lambda item: int(item["minutes"]))
    return {
        "active": True,
        "symbol": pair,
        "guardMinutes": guard_minutes,
        "session": primary["session"],
        "transition": primary["transition"],
        "minutes": primary["minutes"],
        "affectedPairs": primary["pairs"],
        "message": (
            f"forex session-break guard: {pair} is {primary['minutes']}m from "
            f"{primary['session']} {primary['transition']}"
        ),
    }
