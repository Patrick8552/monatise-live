#!/usr/bin/env python3
"""Backtest: fixed_v1 vs adaptive_atr_v2 BTC grid spacing, side by side.

Walks a chronological window of real BTC 15m candles and, at every boundary,
builds a grid with build_moving_grid_plan() under each spacing strategy,
tracks whether price reaches a level within the real SETUP_VALIDITY_CANDLES
window, runs the real PriceActionEngine to decide confirmation, and -- once
confirmed -- simulates the trade forward to its nearest-opposite-side-level
target or its invalidation level using only real subsequent candles.

Deliberately in scope: level-touch rate, confirmation/conversion rate,
expiry rate, false-entry (loss) rate, expectancy, drawdown -- all fully
backtestable from price data alone, using the real production engines.

Deliberately NOT in scope: whether the decision engine would have actually
classified each point as GRID. That needs order_flow (funding/OI/CVD),
which CoinGlass's API doesn't expose as point-in-time history -- there is
no "as of timestamp T in the past" query, only "recent window ending now".
This backtest assumes a grid decision holds at every boundary and measures
spacing's effect on what happens after that, which is the specific
question in scope. Candle data is a public market feed (OKX spot BTC-USDT,
15m), not CoinGlass, for exactly that reason -- it needs deep history with
no API key, and is not the piece being compared.

Usage: uv run python scripts/backtest_grid_spacing.py [--days 30]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monatise.application.production_analysis import SETUP_VALIDITY_CANDLES, build_moving_grid_plan
from monatise.core.models import Candle
from monatise.engines.market_data.models import DataQuality, DataStatus, MarketSnapshot
from monatise.engines.price_action.engine import PriceActionEngine
from monatise.engines.price_action.models import PriceActionDirection, PriceActionRequest


OKX_RECENT_URL = "https://www.okx.com/api/v5/market/candles"
OKX_HISTORY_URL = "https://www.okx.com/api/v5/market/history-candles"
STRATEGIES = ("fixed_v1", "adaptive_atr_v2")
WARMUP_CANDLES = 60  # 15h at 15m -- needed for a full 1H ATR(14) resample
MAX_HOLD_CANDLES = 96  # 24h cap on an open simulated trade before "unresolved"


def _okx_request(url: str, params: dict[str, str]) -> dict:
    query = "&".join(f"{key}={value}" for key, value in params.items())
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "monatise-backtest/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
        return json.load(response)


def fetch_okx_15m_candles(days: int) -> list[Candle]:
    """Paginate OKX's public spot klines back far enough to cover `days`."""
    target_count = int(days * 24 * 4) + WARMUP_CANDLES + 50
    rows: list[list[str]] = []
    after: str | None = None
    for _ in range(max(1, target_count // 300 + 2)):
        params = {"instId": "BTC-USDT", "bar": "15m", "limit": "300"}
        if after:
            params["after"] = after
        payload = _okx_request(OKX_HISTORY_URL, params)
        page = payload.get("data") or []
        if not page:
            break
        rows.extend(page)
        after = page[-1][0]
        if len(rows) >= target_count:
            break
        time.sleep(0.2)
    rows.sort(key=lambda row: int(row[0]))
    candles = [Candle(row[0], float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])) for row in rows]
    return candles[-target_count:] if len(candles) > target_count else candles


@dataclass
class PendingSetup:
    grid: dict
    level: float
    direction: PriceActionDirection
    zone_low: float
    zone_high: float
    expiry_index: int
    touched: bool = False


@dataclass
class ActiveTrade:
    entry_index: int
    entry_price: float
    target_price: float
    invalidation_price: float
    direction: PriceActionDirection
    deadline_index: int


@dataclass
class StrategyStats:
    decisions_generated: int = 0
    grid_unavailable: int = 0
    level_touched: int = 0
    confirmed: int = 0
    expired_no_touch: int = 0
    expired_touched_unconfirmed: int = 0
    wins: int = 0
    losses: int = 0
    unresolved: int = 0
    trade_pnl_usd: list[float] = field(default_factory=list)
    trade_r_multiple: list[float] = field(default_factory=list)

    def summary(self) -> dict:
        activated = self.confirmed
        resolved = self.wins + self.losses
        equity_curve, peak, max_drawdown = 0.0, 0.0, 0.0
        for pnl in self.trade_pnl_usd:
            equity_curve += pnl
            peak = max(peak, equity_curve)
            max_drawdown = min(max_drawdown, equity_curve - peak)
        return {
            "decisions_generated": self.decisions_generated,
            "grid_unavailable": self.grid_unavailable,
            "level_touch_rate": round(self.level_touched / self.decisions_generated, 4) if self.decisions_generated else None,
            "conversion_rate": round(activated / self.decisions_generated, 4) if self.decisions_generated else None,
            "expiry_rate": round((self.expired_no_touch + self.expired_touched_unconfirmed) / self.decisions_generated, 4) if self.decisions_generated else None,
            "expired_no_touch": self.expired_no_touch,
            "expired_touched_unconfirmed": self.expired_touched_unconfirmed,
            "activated_trades": activated,
            "wins": self.wins,
            "losses": self.losses,
            "unresolved_timeouts": self.unresolved,
            "false_entry_rate": round(self.losses / resolved, 4) if resolved else None,
            "win_rate": round(self.wins / resolved, 4) if resolved else None,
            "expectancy_usd": round(sum(self.trade_pnl_usd) / len(self.trade_pnl_usd), 2) if self.trade_pnl_usd else None,
            "expectancy_r": round(sum(self.trade_r_multiple) / len(self.trade_r_multiple), 4) if self.trade_r_multiple else None,
            "total_pnl_usd": round(sum(self.trade_pnl_usd), 2) if self.trade_pnl_usd else 0.0,
            "max_drawdown_usd": round(max_drawdown, 2),
        }


def _nearest_level_and_direction(grid: dict, price: float) -> tuple[float, PriceActionDirection]:
    candidates = (
        *((level, PriceActionDirection.BULLISH) for level in grid["buy_levels"]),
        *((level, PriceActionDirection.BEARISH) for level in grid["sell_levels"]),
    )
    return min(candidates, key=lambda item: abs(price - item[0]))


def run_backtest(candles: list[Candle], strategies: tuple[str, ...] = STRATEGIES) -> dict[str, StrategyStats]:
    engine = PriceActionEngine()
    stats = {strategy: StrategyStats() for strategy in strategies}
    pending: dict[str, PendingSetup | None] = {strategy: None for strategy in strategies}
    active: dict[str, ActiveTrade | None] = {strategy: None for strategy in strategies}

    for i in range(WARMUP_CANDLES, len(candles)):
        candle = candles[i]
        window = tuple(candles[: i + 1])
        now = datetime.now(timezone.utc)
        market_now = MarketSnapshot("BTC", "15m", candle.close, window, DataQuality(DataStatus.READY, "okx", now, now, 0))

        for strategy in strategies:
            st = stats[strategy]

            trade = active[strategy]
            if trade is not None:
                if trade.direction is PriceActionDirection.BULLISH:
                    hit_target = candle.high >= trade.target_price
                    hit_invalid = candle.low <= trade.invalidation_price
                else:
                    hit_target = candle.low <= trade.target_price
                    hit_invalid = candle.high >= trade.invalidation_price
                resolved = False
                if hit_invalid:
                    risk = abs(trade.entry_price - trade.invalidation_price)
                    st.losses += 1
                    st.trade_pnl_usd.append(-risk)
                    st.trade_r_multiple.append(-1.0)
                    resolved = True
                elif hit_target:
                    reward = abs(trade.target_price - trade.entry_price)
                    risk = abs(trade.entry_price - trade.invalidation_price)
                    st.wins += 1
                    st.trade_pnl_usd.append(reward)
                    st.trade_r_multiple.append(reward / risk if risk else 0.0)
                    resolved = True
                elif i >= trade.deadline_index:
                    st.unresolved += 1
                    resolved = True
                if resolved:
                    active[strategy] = None
                continue  # one trade at a time per strategy; don't also open a new setup this candle

            setup = pending[strategy]
            if setup is not None:
                touched_now = candle.low <= setup.zone_high and candle.high >= setup.zone_low
                if touched_now:
                    setup.touched = True
                    request = PriceActionRequest(
                        market_now,
                        expected_direction=setup.direction,
                        entry_price=setup.level,
                        entry_zone_low=setup.zone_low,
                        entry_zone_high=setup.zone_high,
                    )
                    assessment = engine.assess(request)
                    if assessment.has_confirmation:
                        st.level_touched += 1
                        st.confirmed += 1
                        grid = setup.grid
                        if setup.direction is PriceActionDirection.BULLISH:
                            target = grid["sell_levels"][0]
                            invalidation = grid["lower_invalidation"]
                        else:
                            target = grid["buy_levels"][0]
                            invalidation = grid["upper_invalidation"]
                        active[strategy] = ActiveTrade(
                            entry_index=i, entry_price=setup.level, target_price=target,
                            invalidation_price=invalidation, direction=setup.direction,
                            deadline_index=i + MAX_HOLD_CANDLES,
                        )
                        pending[strategy] = None
                        continue
                if i >= setup.expiry_index:
                    if setup.touched:
                        st.level_touched += 1
                        st.expired_touched_unconfirmed += 1
                    else:
                        st.expired_no_touch += 1
                    pending[strategy] = None
                continue  # still waiting (or just expired this candle); don't open a new setup same tick

            grid = build_moving_grid_plan(market_now, spacing_strategy=strategy)
            if grid is None:
                st.grid_unavailable += 1
                continue
            st.decisions_generated += 1
            level, direction = _nearest_level_and_direction(grid, candle.close)
            zone_half_width = grid["spacing"] * 0.15
            pending[strategy] = PendingSetup(
                grid=grid, level=level, direction=direction,
                zone_low=level - zone_half_width, zone_high=level + zone_half_width,
                expiry_index=i + SETUP_VALIDITY_CANDLES,
            )

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    print(f"Fetching ~{args.days} days of real 15m BTC-USDT candles from OKX...", file=sys.stderr)
    candles = fetch_okx_15m_candles(args.days)
    print(f"Fetched {len(candles)} candles, {candles[0].timestamp} -> {candles[-1].timestamp}", file=sys.stderr)

    stats = run_backtest(candles)

    result = {
        "candle_count": len(candles),
        "span": {"first": candles[0].timestamp, "last": candles[-1].timestamp},
        "setup_validity_candles": SETUP_VALIDITY_CANDLES,
        "max_hold_candles": MAX_HOLD_CANDLES,
        "strategies": {strategy: stats[strategy].summary() for strategy in STRATEGIES},
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
