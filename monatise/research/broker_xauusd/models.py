"""Broker identity and bounded manual acquisition contracts, not connections."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from monatise.application.gold_sessions import GoldSessionCalendar, utc
from monatise.application.hierarchy.policy import INTERVAL_SECONDS, SHARED_TIMEFRAME_POLICY

TIMEFRAMES = SHARED_TIMEFRAME_POLICY.timeframes
KINDS = {"ENGINEERING_SYNTHETIC", "POINT_IN_TIME_OBSERVATION", "RETROSPECTIVE_HISTORICAL_DOWNLOAD", "UNKNOWN_OR_UNVERIFIED"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def instant(value):
    return utc(value.isoformat() if isinstance(value, datetime) else value)


@dataclass(frozen=True)
class BrokerIdentity:
    broker: str
    account_id: str
    server: str
    broker_symbol: str
    symbol: str = "XAU/USD"

    def __post_init__(self):
        if any(not isinstance(v, str) or not v.strip() or len(v) > 128 for v in asdict(self).values()):
            raise ValueError("complete bounded broker identity required")
        # This is an explicit broker-symbol mapping, never GC or a continuous future.
        if self.symbol != "XAU/USD" or not re.fullmatch(r"XAU/?USD(?:m|[._][A-Za-z0-9_.-]+)?", self.broker_symbol):
            raise ValueError("broker XAUUSD mapping required; GC is not broker spot")

    @property
    def namespace(self):
        return "BROKER:XAUUSD:" + digest(asdict(self))

    def validate_calendar(self, calendar):
        calendar.require_identity(self.account_id, self.server, self.symbol)


def expected_opens(calendar: GoldSessionCalendar, timeframe: str, start, end, *, cutoff=None):
    """Reviewed broker-clock grid; never interpolate closures or partial bars."""
    start, end = instant(start), instant(end)
    if timeframe not in TIMEFRAMES or not calendar.start <= start < end <= calendar.end:
        raise ValueError("requested window outside reviewed calendar")
    if end - start > timedelta(days=7):
        raise ValueError("bounded window exceeds seven days")
    seconds = INTERVAL_SECONDS[timeframe]
    result = set()
    for era in calendar.offsets:
        # GoldSessionCalendar owns the interpretation of these reviewed eras.
        era_start, era_end, offset = era
        lo, hi = max(start, era_start), min(end, era_end)
        if lo >= hi:
            continue
        wall = int(lo.timestamp()) + offset
        opened = datetime.fromtimestamp(((wall + seconds - 1) // seconds) * seconds - offset, timezone.utc)
        while opened < hi:
            if opened >= lo and calendar.regular_bar(opened, timeframe):
                if cutoff is None or opened + timedelta(seconds=seconds + 10) <= instant(cutoff):
                    result.add(opened)
            opened += timedelta(seconds=seconds)
    return tuple(sorted(result))


def historical_plan(identity, calendar, *, start, end, page_bars=240):
    """Pure request plan for a separately authorized terminal/export operator.

    Does not call CopyRates, load MetaTrader5, authenticate, or poll a broker.
    Windows are half-open UTC; adapters must retain original broker clocks.
    """
    identity.validate_calendar(calendar)
    if isinstance(page_bars, bool) or not isinstance(page_bars, int) or not 1 <= page_bars <= 240:
        raise ValueError("page limit must be 1..240")
    pages = []
    for tf in TIMEFRAMES:
        opens = expected_opens(calendar, tf, start, end)
        for index in range(0, len(opens), page_bars):
            selected = opens[index:index + page_bars]
            pages.append({"timeframe": tf, "start": selected[0].isoformat(),
                          "end": (selected[-1] + timedelta(seconds=INTERVAL_SECONDS[tf])).isoformat(),
                          "expected_bars": len(selected)})
    return {"schema": "broker-xauusd-manual-acquisition-plan-v1", "identity": asdict(identity),
            "calendar_fingerprint": calendar.fingerprint, "pages": pages,
            "requires_separate_connection_authorization": True, "execution_enabled": False}
