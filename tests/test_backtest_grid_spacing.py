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


def test_touch_confirm_and_target_hit_records_a_win():
    # Flat warmup centers the fixed_v1 grid at 63000 with $500 spacing, so
    # the nearest level is a tie broken toward buy_levels[0] = 62500 (BULLISH).
    candles = _flat_candles(63_000, MODULE.WARMUP_CANDLES + 1)
    # A dip through the entry zone (62425-62575) confirms the setup...
    candles.append(Candle("touch", 62500, 62550, 62450, 62480, 10))
    # ...then price rallies through the target (nearest sell level, 63500).
    candles.append(Candle("rally", 63400, 63600, 63400, 63550, 10))

    with patch.object(MODULE.PriceActionEngine, "assess", lambda self, request: _confirmed(request.expected_direction)):
        stats = MODULE.run_backtest(candles, strategies=("fixed_v1",))

    result = stats["fixed_v1"]
    assert result.confirmed == 1
    assert result.wins == 1
    assert result.losses == 0
    assert result.trade_pnl_usd == [1000.0]  # |63500 - 62500|
    assert result.trade_r_multiple == [1000.0 / 1500.0]  # risk = |62500 - 61000|


def test_touch_confirm_and_invalidation_hit_records_a_loss():
    candles = _flat_candles(63_000, MODULE.WARMUP_CANDLES + 1)
    candles.append(Candle("touch", 62500, 62550, 62450, 62480, 10))
    # Price instead breaks down through the lower invalidation (61000).
    candles.append(Candle("breakdown", 62000, 62100, 60900, 60950, 10))

    with patch.object(MODULE.PriceActionEngine, "assess", lambda self, request: _confirmed(request.expected_direction)):
        stats = MODULE.run_backtest(candles, strategies=("fixed_v1",))

    result = stats["fixed_v1"]
    assert result.confirmed == 1
    assert result.wins == 0
    assert result.losses == 1
    assert result.trade_pnl_usd == [-1500.0]  # -|62500 - 61000|
    assert result.trade_r_multiple == [-1.0]


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
    assert summary["win_rate"] == 0.75
    assert summary["false_entry_rate"] == 0.25
    assert summary["total_pnl_usd"] == 250.0
    assert summary["expectancy_usd"] == 62.5
    # equity path: 100 -> 50 -> 150 -> 250; only drawdown is 100 -> 50 (-50)
    assert summary["max_drawdown_usd"] == -50.0
