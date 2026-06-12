from __future__ import annotations

from datetime import UTC, datetime

from monatise.live.sessions import (
    commodity_london_guard,
    economic_release_guard,
    forex_session_break_guard,
    is_forex_symbol,
    signal_window_guard,
)


def test_forex_session_break_guard_flags_one_hour_before_london_close() -> None:
    guard = forex_session_break_guard("EURUSD", datetime(2026, 6, 7, 15, 0, tzinfo=UTC))

    assert guard["active"]
    assert guard["session"] == "London"
    assert guard["transition"] == "close"
    assert guard["direction"] == "before"
    assert guard["minutes"] == 60
    assert "EURUSD" in guard["affectedPairs"]


def test_forex_session_break_guard_flags_one_hour_after_london_close() -> None:
    guard = forex_session_break_guard("EURUSD", datetime(2026, 6, 7, 17, 0, tzinfo=UTC))

    assert guard["active"]
    assert guard["session"] == "London"
    assert guard["transition"] == "close"
    assert guard["direction"] == "after"
    assert guard["minutes"] == 60


def test_forex_session_break_guard_ignores_crypto_symbols() -> None:
    guard = forex_session_break_guard("BTC", datetime(2026, 6, 7, 15, 0, tzinfo=UTC))

    assert not guard["active"]
    assert not is_forex_symbol("BTC")


def test_commodity_london_guard_blocks_gold_outside_london() -> None:
    guard = commodity_london_guard("GOLD", datetime(2026, 6, 7, 18, 0, tzinfo=UTC))

    assert guard["active"]
    assert guard["symbol"] == "GOLD"
    assert guard["session"] == "London"


def test_commodity_london_guard_allows_oil_during_london() -> None:
    guard = commodity_london_guard("CL", datetime(2026, 6, 7, 10, 0, tzinfo=UTC))

    assert not guard["active"]
    assert guard["symbol"] == "CL"


def test_signal_window_guard_allows_london_and_new_york_only() -> None:
    london_guard = signal_window_guard(datetime(2026, 7, 14, 10, 0, tzinfo=UTC))
    new_york_guard = signal_window_guard(datetime(2026, 7, 14, 17, 0, tzinfo=UTC))
    closed_guard = signal_window_guard(datetime(2026, 7, 14, 22, 0, tzinfo=UTC))

    assert not london_guard["active"]
    assert not new_york_guard["active"]
    assert closed_guard["active"]
    assert "London or New York" in closed_guard["message"]


def test_economic_release_guard_blocks_one_hour_before_and_after_cpi() -> None:
    before = economic_release_guard(datetime(2026, 7, 14, 12, 0, tzinfo=UTC))
    after = economic_release_guard(datetime(2026, 7, 14, 13, 0, tzinfo=UTC))
    clear = economic_release_guard(datetime(2026, 7, 14, 14, 0, tzinfo=UTC))

    assert before["active"]
    assert before["event"] == "CPI"
    assert after["active"]
    assert after["phase"] == "after"
    assert not clear["active"]


def test_economic_release_guard_blocks_ppi_window() -> None:
    guard = economic_release_guard(datetime(2026, 7, 15, 12, 30, tzinfo=UTC))

    assert guard["active"]
    assert guard["event"] == "PPI"
