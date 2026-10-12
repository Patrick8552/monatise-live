"""Independently recompute reviewed minute expectations from native status clocks."""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from monatise.research.gc_fib.candles import MINUTE, timestamp_ns

CHICAGO = ZoneInfo("America/Chicago")


def instant(ns):
    return datetime.fromtimestamp(ns // 10**9, UTC)


def status_sessions(records, *, end_ns):
    """Retrospective exchange-event reconstruction, never historical local receipts.

    Receive-clock snapshots can repeat an older effective event. Multiple native
    transitions at one event timestamp use receive/source order. Indistinguishable
    conflicting clocks fail closed. Source hashes must be verified by the caller.
    """
    timestamp_ns(end_ns)
    states,clock_states = {},{}
    for record in sorted(records,key=lambda r:(int(r["ts_event"]),int(r["ts_recv"]),r.get("ordinal",0))):
        event,receive = int(record["ts_event"]),int(record["ts_recv"])
        timestamp_ns(event); timestamp_ns(receive)
        if event > receive: raise ValueError("status_clock_contradiction")
        value = record["is_trading"]
        if value is None or value in ("None","~"):
            if record.get("action") in ("<StatusAction.NONE: 0>","0",0):
                continue  # Unspecified field on a documented no-change record.
            raise ValueError("status_trading_unknown")
        if value not in ("True","False","Y","N",True,False): raise ValueError("status_trading_unknown")
        trading = value in ("True","Y",True)
        clock = (event,receive,record.get("ordinal"))
        if clock in clock_states and clock_states[clock] != trading:
            raise ValueError("conflicting_status_at_same_native_position")
        clock_states[clock] = trading
        states[event] = trading
    if not states: raise ValueError("initial_status_state_unavailable")
    sessions,start = [],None
    for event,trading in sorted(states.items()):
        if event >= end_ns: break
        if trading and start is None: start = event
        if not trading and start is not None:
            if event > start: sessions.append((start,event))
            start = None
    if start is not None and start < end_ns: sessions.append((start,end_ns))
    return tuple(sessions)


def complete_minute_sessions(sessions):
    return tuple(((a+MINUTE-1)//MINUTE*MINUTE,b//MINUTE*MINUTE)
                 for a,b in sessions if (a+MINUTE-1)//MINUTE*MINUTE < b//MINUTE*MINUTE)


def expectation(start, end, *, sessions, reviewed=True):
    """Partial sessions differ from full closure; neither creates a price bar."""
    if not start < end: raise ValueError("positive_interval_required")
    if not reviewed: return "UNREVIEWED"
    if any(a <= start < end <= b for a,b in sessions): return "FULLY_OPEN"
    if any(start < b and a < end for a,b in sessions): return "PARTIAL_SESSION"
    return "CLOSED"


def expected_opens(sessions, *, width_ns, start_ns, end_ns):
    if width_ns <= 0 or width_ns % MINUTE or not start_ns < end_ns:
        raise ValueError("bounded_aligned_expectation_required")
    result = []
    for a,b in sessions:
        lo,hi = max(a,start_ns),min(b,end_ns)
        if lo >= hi: continue
        first = (lo+width_ns-1)//width_ns*width_ns
        result.extend(t for t in range(first,hi,width_ns) if t+width_ns <= hi)
    return tuple(result)


def nominal_gc_state(ns):
    """Public GC regular-hours cross-check ONLY; native exceptions take priority.

    No holidays are invented. Holiday/early-close knowledge belongs to reviewed
    native sessions. This function never supplies qualification expectations.
    """
    wall = instant(ns).astimezone(CHICAGO)
    weekday,hour = wall.weekday(),wall.hour
    if weekday == 5 or (weekday == 6 and hour < 17) or (weekday == 4 and hour >= 16):
        return "CLOSED_WEEKEND"
    if weekday < 4 and hour == 16: return "MAINTENANCE"
    return "REGULAR_OPEN_SUBJECT_TO_HOLIDAY_AND_STATUS"


def session_presentations(sessions):
    return [dict(start_ns=a,end_ns=b,start_utc=instant(a).isoformat(),end_utc=instant(b).isoformat(),
                 start_chicago=instant(a).astimezone(CHICAGO).isoformat(),
                 end_chicago=instant(b).astimezone(CHICAGO).isoformat()) for a,b in sessions]
