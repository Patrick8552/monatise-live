from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

from monatise.core.models import Candle
from monatise.engines.price_action.models import (
    PriceActionAssessment,
    PriceActionConfirmationStatus,
    PriceActionDirection,
)

SCRIPT = Path(__file__).parents[1] / "scripts/backtest_grid_spacing.py"
SPEC = importlib.util.spec_from_file_location("backtest_grid_spacing", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE  # dataclasses need the module registered before exec
SPEC.loader.exec_module(MODULE)


def _confirmed(direction: PriceActionDirection) -> PriceActionAssessment:
    return PriceActionAssessment(symbol="BTC", status=PriceActionConfirmationStatus.CONFIRMED, signals=(), reasons=())


def _flat_candles(level: float, count: int, *, wick: float = 5.0) -> list[Candle]:
    return [Candle(str(i), level, level + wick, level - wick, level, 10) for i in range(count)]


def _always_confirmed():
    return patch.object(MODULE.PriceActionEngine, "assess", lambda self, request: _confirmed(request.expected_direction))


def test_touch_confirm_and_target_hit_records_a_win():
    # Flat warmup centers the fixed_v1 grid at 63000 with $500 spacing, so
    # the nearest level is a tie broken toward buy_levels[0] = 62500 (BULLISH).
    candles = _flat_candles(63_000, MODULE.WARMUP_CANDLES + 1)
    # A dip through the entry zone (62425-62575) confirms the setup on this
    # candle...
    candles.append(Candle("touch", 62500, 62550, 62450, 62480, 10))
    # ...but the trade only enters at the NEXT candle's open (63400, not the
    # zone price) -- this candle's own high (63600) then clears the target
    # (nearest sell level, 63500).
    candles.append(Candle("entry_and_rally", 63400, 63600, 63400, 63550, 10))

    with _always_confirmed():
        stats = MODULE.run_backtest(candles, strategies=("fixed_v1",))

    result = stats["fixed_v1"]
    assert result.confirmed == 1
    assert result.wins == 1
    assert result.losses == 0
    assert result.trade_pnl_usd == [100.0]  # |target 63500 - entry 63400|
    assert result.trade_r_multiple == [100.0 / 2400.0]  # risk = |entry 63400 - invalidation 61000|


def test_touch_confirm_and_invalidation_hit_records_a_loss():
    candles = _flat_candles(63_000, MODULE.WARMUP_CANDLES + 1)
    candles.append(Candle("touch", 62500, 62550, 62450, 62480, 10))
    # Entry at the next candle's open (62000), which then breaks down
    # through the lower invalidation (61000).
    candles.append(Candle("entry_and_breakdown", 62000, 62100, 60900, 60950, 10))

    with _always_confirmed():
        stats = MODULE.run_backtest(candles, strategies=("fixed_v1",))

    result = stats["fixed_v1"]
    assert result.confirmed == 1
    assert result.wins == 0
    assert result.losses == 1
    assert result.trade_pnl_usd == [-1000.0]  # -|entry 62000 - invalidation 61000|
    assert result.trade_r_multiple == [-1.0]


def test_confirmation_candles_own_range_does_not_resolve_the_trade():
    # The confirming candle's range spans both the eventual target and
    # invalidation -- if the old (pre-fix) code evaluated the confirmation
    # candle itself, this would look like an immediate ambiguous/resolved
    # outcome. It must not: entry only happens at the NEXT candle's open.
    candles = _flat_candles(63_000, MODULE.WARMUP_CANDLES + 1)
    candles.append(Candle("touch_and_wide", 62500, 64000, 60000, 62500, 10))
    # Next candle is flat at the open price -- no resolution yet.
    candles.append(Candle("flat_entry", 62500, 62520, 62480, 62500, 10))

    with _always_confirmed():
        stats = MODULE.run_backtest(candles, strategies=("fixed_v1",))

    result = stats["fixed_v1"]
    assert result.confirmed == 1
    assert result.wins == 0
    assert result.losses == 0
    assert result.ambiguous == 0
    # Trade is still open at the end of the (short) dataset.
    assert result.open_at_window_end == 1


def test_target_and_invalidation_hit_in_the_same_candle_is_ambiguous():
    candles = _flat_candles(63_000, MODULE.WARMUP_CANDLES + 1)
    candles.append(Candle("touch", 62500, 62550, 62450, 62480, 10))
    # Entry candle's range spans BOTH the target (63500) and invalidation
    # (61000) -- no way to know which was hit first intrabar.
    candles.append(Candle("entry_and_whipsaw", 62000, 64000, 60000, 62000, 10))

    with _always_confirmed():
        stats = MODULE.run_backtest(candles, strategies=("fixed_v1",))

    result = stats["fixed_v1"]
    assert result.confirmed == 1
    assert result.ambiguous == 1
    assert result.wins == 0
    assert result.losses == 0
    assert result.trade_pnl_usd == []  # ambiguous trades don't contribute a known pnl


def test_confirmation_on_the_last_candle_has_no_entry_and_is_tracked_separately():
    # Confirmation happens on the very last candle in the dataset -- there's
    # no next candle to actually enter on.
    candles = _flat_candles(63_000, MODULE.WARMUP_CANDLES + 1)
    candles.append(Candle("touch_at_the_end", 62500, 62550, 62450, 62480, 10))

    with _always_confirmed():
        stats = MODULE.run_backtest(candles, strategies=("fixed_v1",))

    result = stats["fixed_v1"]
    assert result.confirmed == 1
    assert result.confirmed_at_window_end == 1
    assert result.wins == 0
    assert result.losses == 0
    assert result.open_at_window_end == 0


def test_pending_setup_still_waiting_at_window_end_is_tracked_not_dropped():
    # A decision is generated on the last candle, leaving its setup pending
    # (not yet expired, never touched) when the data runs out.
    candles = _flat_candles(63_000, MODULE.WARMUP_CANDLES + 1)

    stats = MODULE.run_backtest(candles, strategies=("fixed_v1",))

    result = stats["fixed_v1"]
    assert result.decisions_generated == 1
    assert result.pending_at_window_end == 1
    assert result.expired_no_touch == 0


def test_active_trade_still_open_at_window_end_is_censored_not_dropped():
    candles = _flat_candles(63_000, MODULE.WARMUP_CANDLES + 1)
    candles.append(Candle("touch", 62500, 62550, 62450, 62480, 10))
    # Entry candle, then a couple more flat candles that never reach target
    # or invalidation before the dataset ends.
    candles.append(Candle("entry", 62500, 62520, 62480, 62500, 10))
    candles.append(Candle("still_open", 62500, 62520, 62480, 62500, 10))

    with _always_confirmed():
        stats = MODULE.run_backtest(candles, strategies=("fixed_v1",))

    result = stats["fixed_v1"]
    assert result.confirmed == 1
    assert result.wins == 0
    assert result.losses == 0
    assert result.open_at_window_end == 1
    assert len(result.censored_unrealized_pnl_usd) == 1
    # confirmed reconciles exactly to one terminal bucket per confirmed setup.
    assert result.confirmed == (
        result.wins + result.losses + result.ambiguous
        + result.unresolved + result.open_at_window_end + result.confirmed_at_window_end
    )


def test_setup_expires_unconfirmed_when_price_never_reaches_a_level():
    # Flat throughout, including after the decision candle -- price never
    # leaves the zone around center, so it never touches the level at
    # spacing=500 away, and the setup should expire after SETUP_VALIDITY_CANDLES.
    candles = _flat_candles(63_000, MODULE.WARMUP_CANDLES + 10, wick=2)

    stats = MODULE.run_backtest(candles, strategies=("fixed_v1",))

    result = stats["fixed_v1"]
    assert result.decisions_generated >= 1
    assert result.confirmed == 0
    assert result.expired_no_touch >= 1
    assert result.level_touched == 0


def test_strategy_stats_summary_computes_rates_and_drawdown():
    stats = MODULE.StrategyStats(
        decisions_generated=10,
        level_touched=6,
        confirmed=4,
        expired_no_touch=4,
        expired_touched_unconfirmed=2,
        wins=3,
        losses=1,
        trade_pnl_usd=[100.0, -50.0, 100.0, 100.0],
        trade_r_multiple=[1.0, -1.0, 1.0, 1.0],
    )

    summary = stats.summary()

    assert summary["level_touch_rate"] == 0.6
    assert summary["conversion_rate"] == 0.4
    assert summary["win_rate_closed"] == 0.75
    assert summary["false_entry_rate"] == 0.25
    assert summary["total_realized_pnl_usd"] == 250.0
    assert summary["expectancy_usd"] == 62.5
    # equity path: 100 -> 50 -> 150 -> 250; only drawdown is 100 -> 50 (-50)
    assert summary["max_drawdown_usd"] == -50.0


def test_ambiguous_trades_are_excluded_from_win_rate_and_expectancy():
    stats = MODULE.StrategyStats(
        decisions_generated=5,
        confirmed=3,
        wins=1,
        losses=1,
        ambiguous=1,
        trade_pnl_usd=[100.0, -100.0],
        trade_r_multiple=[1.0, -1.0],
    )

    summary = stats.summary()

    assert summary["closed_trades"] == 2  # ambiguous not counted as closed
    assert summary["ambiguous_outcomes"] == 1
    assert summary["win_rate_closed"] == 0.5
    assert summary["expectancy_usd"] == 0.0
