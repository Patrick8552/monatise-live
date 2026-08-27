from datetime import datetime, timezone

import pytest

from monatise.application.ftmo_registry import FTMO_REGISTRY
from monatise.application.market_session import classify_market_session, session_allows_execution


@pytest.mark.parametrize(
    "hour,expected",
    [
        (1, "ASIA"),
        (9, "LONDON"),
        (13, "LONDON_NEW_YORK_OVERLAP"),
        (18, "NEW_YORK"),
        (22, "OFF_SESSION"),
    ],
)
def test_weekday_session_classification_is_fresh_and_dst_aware(hour, expected):
    observed = datetime(2026, 8, 27, hour, 0, tzinfo=timezone.utc)
    context = classify_market_session(observed, instrument=FTMO_REGISTRY.resolve("XAU/USD"), trade_mode="4")
    assert context.market_session == expected
    assert context.analysis_timestamp_utc == observed.isoformat()
    assert context.session_checked_at == observed.isoformat()
    assert context.session_source
    assert context.market_open is True


def test_weekend_and_broker_break_fail_closed_even_if_clock_session_would_be_active():
    weekend = classify_market_session(
        datetime(2026, 8, 29, 13, 0, tzinfo=timezone.utc),
        instrument=FTMO_REGISTRY.resolve("XAU/USD"),
        trade_mode="0",
    )
    assert weekend.market_session == "MARKET_CLOSED"
    assert weekend.broker_break_proximity == "BROKER_BREAK_OR_CLOSED"
    assert session_allows_execution(weekend) is False

    broker_break = classify_market_session(
        datetime(2026, 8, 27, 13, 0, tzinfo=timezone.utc),
        instrument=FTMO_REGISTRY.resolve("XAU/USD"),
        trade_mode="0",
    )
    assert broker_break.session_status == "CLOSED"
    assert session_allows_execution(broker_break) is False
