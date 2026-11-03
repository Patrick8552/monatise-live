"""Dated BTC 24/7 calendar with explicit maintenance and exceptional closures.

This is a reviewed calendar input, not a provider continuity or session-CVD
certificate. No calendar is implicitly attached to unrelated XCME products.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.databento.candles import ExchangeCalendar, WIDTHS
from monatise.research.institutional.models import digest, hash_required

CHICAGO = ZoneInfo('America/Chicago')
REFERENCE = 'https://www.cmegroup.com/markets/trade-24-7'
EFFECTIVE_NS = int(datetime(2026, 5, 29, 16, 2, tzinfo=CHICAGO).timestamp()) * 10**9


@dataclass(frozen=True)
class BitcoinScheduleReview:
    valid_from_ns: int
    valid_to_ns: int
    source_reference: str
    source_sha256: str
    additional_closures: tuple[tuple[int, int], ...] = ()

    def __post_init__(self):
        timestamp_ns(self.valid_from_ns); timestamp_ns(self.valid_to_ns)
        hash_required(self.source_sha256)
        if (not EFFECTIVE_NS <= self.valid_from_ns < self.valid_to_ns
                or self.valid_to_ns-self.valid_from_ns > 366*86400*10**9
                or not isinstance(self.source_reference, str) or not self.source_reference.strip()
                or not isinstance(self.additional_closures, tuple) or len(self.additional_closures) > 1000):
            raise ValueError('dated_bitcoin_schedule_review_required')
        for bounds in self.additional_closures:
            if not isinstance(bounds, tuple) or len(bounds) != 2:
                raise ValueError('explicit_bitcoin_exceptional_closures_required')
            start, end = bounds
            timestamp_ns(start); timestamp_ns(end)
            if not self.valid_from_ns <= start < end <= self.valid_to_ns or start % WIDTHS['1m'] or end % WIDTHS['1m']:
                raise ValueError('explicit_bitcoin_exceptional_closures_required')


def bitcoin_calendar(start_ns, end_ns, *, review):
    if (not isinstance(review, BitcoinScheduleReview)
            or type(start_ns) is not int or type(end_ns) is not int
            or not review.valid_from_ns <= start_ns < end_ns <= review.valid_to_ns
            or start_ns % WIDTHS['1m'] or end_ns % WIDTHS['1m']):
        raise ValueError('reviewed_bitcoin_calendar_window_required')
    first = datetime.fromtimestamp(start_ns / 10**9, CHICAGO).date()
    last = datetime.fromtimestamp(end_ns / 10**9, CHICAGO).date()
    closures = list(review.additional_closures)
    day = first
    while day <= last:
        if day.weekday() < 5:
            opening = datetime(day.year, day.month, day.day, 16, tzinfo=CHICAGO)
            closing = opening + timedelta(minutes=2)
        elif day.weekday() == 5:
            opening = datetime(day.year, day.month, day.day, 2, tzinfo=CHICAGO)
            closing = opening + timedelta(hours=2)
        else:
            day += timedelta(days=1)
            continue
        closures.append((int(opening.timestamp())*10**9, int(closing.timestamp())*10**9))
        day += timedelta(days=1)
    intervals = []
    cursor = start_ns
    for start, end in sorted(closures):
        start, end = max(start_ns, start), min(end_ns, end)
        if end <= start or end <= cursor:
            continue
        if start > cursor:
            intervals.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < end_ns:
        intervals.append((cursor, end_ns))
    if not intervals:
        raise ValueError('bitcoin_window_contains_only_reviewed_closures')
    return ExchangeCalendar('GLBX.MDP3', 'XCME', review.source_reference,
        digest(review), 'CME-BTC-reviewed-24x7-v1', start_ns, end_ns, tuple(intervals))
