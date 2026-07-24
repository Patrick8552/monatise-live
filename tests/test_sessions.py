from __future__ import annotations

from datetime import UTC, datetime

from monatise.live.sessions import (
    economic_release_guard,
    signal_window_guard,
)


def test_signal_window_guard_defaults_to_always_on() -> None:
    guard = signal_window_guard(datetime(2026, 7, 14, 22, 0, tzinfo=UTC))

    assert not guard["active"]
    assert guard["window"] == "always"


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
