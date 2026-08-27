"""Fresh, deterministic market-session classification for analysis and execution.

The clock classification is descriptive. The live MT5 symbol trade mode is the
authoritative execution-hours check whenever it is available.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from monatise.application.ftmo_registry import FTMOInstrument


SESSION_SOURCE = "canonical_market_session_v1+ftmo_mt5_trade_mode"


@dataclass(frozen=True)
class MarketSessionContext:
    analysis_timestamp_utc: str
    market_session: str
    session_status: str
    session_source: str
    session_checked_at: str
    market_open: bool
    london_active: bool
    new_york_active: bool
    london_new_york_overlap: bool
    broker_break_proximity: str
    instrument_schedule: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _aware_utc(value: datetime | None = None) -> datetime:
    observed = value or datetime.now(timezone.utc)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("session timestamp must be timezone-aware")
    return observed.astimezone(timezone.utc)


def _within(local: datetime, start: time, end: time) -> bool:
    return start <= local.time().replace(tzinfo=None) < end


def classify_market_session(
    observed_at: datetime | None = None,
    *,
    instrument: FTMOInstrument | None = None,
    trade_mode: str | int | None = None,
) -> MarketSessionContext:
    """Classify a fresh session without consulting prior analyses or proposals."""
    observed = _aware_utc(observed_at)
    weekday_open = observed.weekday() < 5
    london = observed.astimezone(ZoneInfo("Europe/London"))
    new_york = observed.astimezone(ZoneInfo("America/New_York"))
    tokyo = observed.astimezone(ZoneInfo("Asia/Tokyo"))
    london_active = weekday_open and _within(london, time(8), time(17))
    new_york_active = weekday_open and _within(new_york, time(8), time(17))
    asia_active = weekday_open and _within(tokyo, time(9), time(18))
    overlap = london_active and new_york_active

    normalized_trade_mode = str(trade_mode if trade_mode is not None else "").strip().casefold()
    broker_open = normalized_trade_mode in {"full", "4", "symbol_trade_mode_full"}
    broker_mode_known = bool(normalized_trade_mode)
    market_open = broker_open if broker_mode_known else weekday_open

    if not market_open:
        market_session = "MARKET_CLOSED" if not weekday_open else "OFF_SESSION"
        session_status = "CLOSED"
    elif overlap:
        market_session, session_status = "LONDON_NEW_YORK_OVERLAP", "OPEN"
    elif london_active:
        market_session, session_status = "LONDON", "OPEN"
    elif new_york_active:
        market_session, session_status = "NEW_YORK", "OPEN"
    elif asia_active:
        market_session, session_status = "ASIA", "OPEN"
    else:
        market_session, session_status = "OFF_SESSION", "OPEN_LOW_LIQUIDITY"

    broker_break = "SAFE" if broker_open else "BROKER_BREAK_OR_CLOSED" if broker_mode_known else "UNKNOWN"
    schedule = instrument.market_hours if instrument is not None else "instrument schedule unavailable; MT5 trade mode authoritative"
    timestamp = observed.isoformat()
    return MarketSessionContext(
        analysis_timestamp_utc=timestamp,
        market_session=market_session,
        session_status=session_status,
        session_source=SESSION_SOURCE,
        session_checked_at=timestamp,
        market_open=market_open,
        london_active=london_active,
        new_york_active=new_york_active,
        london_new_york_overlap=overlap,
        broker_break_proximity=broker_break,
        instrument_schedule=schedule,
    )


def session_allows_execution(context: MarketSessionContext) -> bool:
    return context.market_open and context.session_status in {"OPEN", "OPEN_LOW_LIQUIDITY"}
