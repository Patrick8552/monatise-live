from __future__ import annotations

from datetime import UTC, datetime

from monatise.live.sessions import forex_session_break_guard, is_forex_symbol


def test_forex_session_break_guard_flags_one_hour_before_london_close() -> None:
    guard = forex_session_break_guard("EURUSD", datetime(2026, 6, 7, 15, 0, tzinfo=UTC))

    assert guard["active"]
    assert guard["session"] == "London"
    assert guard["transition"] == "close"
    assert guard["minutes"] == 60
    assert "EURUSD" in guard["affectedPairs"]


def test_forex_session_break_guard_ignores_crypto_symbols() -> None:
    guard = forex_session_break_guard("BTC", datetime(2026, 6, 7, 15, 0, tzinfo=UTC))

    assert not guard["active"]
    assert not is_forex_symbol("BTC")
