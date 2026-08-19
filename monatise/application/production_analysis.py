"""Canonical, analysis-only request construction for production."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from monatise.analysis.liquidity_clusters import estimate_liquidation_clusters
from monatise.application.models import AnalysisRun, PipelineExecutionMetadata
from monatise.application.registry import PRODUCTION_ENGINE_ORDER
from monatise.engines.decision.models import DecisionRequest
from monatise.engines.fibonacci_liquidity.models import FibonacciRequest
from monatise.engines.intelligence_learning.models import LearningRequest
from monatise.engines.liquidity.models import LiquidityRequest
from monatise.engines.liquidity_sweep.models import SweepRequest
from monatise.engines.market_data.models import MarketDataRequest
from monatise.engines.market_structure.models import MarketStructureRequest
from monatise.engines.order_flow.models import FlowInput, OrderFlowRequest
from monatise.engines.portfolio_intelligence.models import PortfolioIntelligenceRequest
from monatise.engines.price_action.models import PriceActionDirection, PriceActionRequest
from monatise.engines.reclaim.models import ReclaimRequest
from monatise.engines.regime.models import RegimeRequest
from monatise.engines.rsi.models import RSIRequest
from monatise.engines.supply_demand.models import ZoneRequest


SUPPORTED_PRODUCTION_SYMBOLS = frozenset({"BTC", "ETH", "SOL"})
MINIMUM_MOVING_GRID_SPACING = {"BTC": 500.0}
# Grid spacing strategy in effect for live production traffic. "fixed_v1" is
# the original static-floor behavior (MINIMUM_MOVING_GRID_SPACING); do not
# flip this to "adaptive_atr_v2" until the two have been backtested
# side-by-side -- callers that want to evaluate the new strategy without
# touching production behavior can pass spacing_strategy explicitly to
# build_moving_grid_plan().
ACTIVE_GRID_SPACING_STRATEGY = "fixed_v1"
# adaptive_atr_v2: spacing = clamp(max(natural_spacing, ATR_MULTIPLIER *
# ATR(14) on 1H candles), price * lower_bound_pct, price * upper_bound_pct).
# Values are a starting point pending backtesting, not validated doctrine.
ADAPTIVE_ATR_WINDOW = 14
ADAPTIVE_ATR_MULTIPLIER = 0.75
ADAPTIVE_SPACING_BOUNDS_PCT = {"BTC": (0.0008, 0.0040)}
SUPPORTED_PRODUCTION_INTERVALS = frozenset({"1m", "3m", "5m", "15m", "30m", "1h", "4h", "6h", "8h", "12h", "1d", "1w"})
PRODUCTION_SIGNAL_SCORE_THRESHOLD = 6
INTERVAL_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1_800,
    "1h": 3_600, "4h": 14_400, "6h": 21_600, "8h": 28_800,
    "12h": 43_200, "1d": 86_400, "1w": 604_800,
}
SETUP_VALIDITY_CANDLES = 4


def strongest_confirmation_signal(price_action: Any) -> Any | None:
    signals = tuple(getattr(price_action, "confirming_signals", ()) or ())
    pattern = getattr(price_action, "strongest_confirming_pattern", None)
    matching = tuple(signal for signal in signals if getattr(signal, "pattern", None) == pattern)
    candidates = matching or signals
    return max(
        candidates,
        key=lambda signal: (
            float(getattr(signal, "confidence", 0.0) or 0.0),
            float(getattr(signal, "evidence_score", 0.0) or 0.0),
        ),
        default=None,
    )


def build_setup_validity(interval: str | None, generated_at: datetime, *, validity_candles: int = SETUP_VALIDITY_CANDLES, age_candles: int = 0) -> dict[str, Any] | None:
    seconds = INTERVAL_SECONDS.get(str(interval or ""))
    if seconds is None or generated_at.tzinfo is None or validity_candles < 1 or age_candles < 0:
        return None
    generated_utc = generated_at.astimezone(timezone.utc)
    boundary_epoch = int(generated_utc.timestamp()) // seconds * seconds
    remaining_candles = max(1, validity_candles - age_candles)
    expires_at = datetime.fromtimestamp(boundary_epoch, tz=timezone.utc) + timedelta(seconds=seconds * remaining_candles)
    if expires_at <= generated_utc:
        expires_at += timedelta(seconds=seconds)
    return {
        "generated_at": generated_utc,
        "expires_at": expires_at,
        "validity_candles": validity_candles,
        "remaining_candles": remaining_candles,
        "validity_seconds": int((expires_at - generated_utc).total_seconds()),
    }


def build_grid_plan(center: float | None, *, levels_per_side: int = 3, half_width_pct: float = 0.02) -> dict[str, Any] | None:
    """Build a symmetric, analysis-only grid around the current market price."""
    if not isinstance(center, (int, float)) or isinstance(center, bool) or center <= 0:
        return None
    if levels_per_side < 2:
        raise ValueError("a grid requires at least two levels per side")
    if not 0 < half_width_pct < 1:
        raise ValueError("half_width_pct must be between zero and one")

    center_value = float(center)
    spacing = center_value * half_width_pct / levels_per_side
    buy_levels = [center_value - spacing * index for index in range(1, levels_per_side + 1)]
    sell_levels = [center_value + spacing * index for index in range(1, levels_per_side + 1)]
    return {
        "center": round(center_value, 8),
        "buy_levels": [round(value, 8) for value in buy_levels],
        "sell_levels": [round(value, 8) for value in sell_levels],
        "lower_boundary": round(buy_levels[-1], 8),
        "upper_boundary": round(sell_levels[-1], 8),
        "lower_invalidation": round(buy_levels[-1] - spacing, 8),
        "upper_invalidation": round(sell_levels[-1] + spacing, 8),
        "spacing": round(spacing, 8),
        "levels_per_side": levels_per_side,
    }


def _resample_to_hourly_ohlc(market: Any) -> list[tuple[float, float, float]] | None:
    """Aggregate market.candles into complete 1H (high, low, close) buckets.

    Uses market.candles directly (not the lookback_candles-truncated window)
    since ATR(14) on 1H needs up to 15 hourly candles of history. Returns
    None when the source interval can't be resampled cleanly into 1H (finer
    than 1H and evenly divides it), leaving the shortfall to the caller.
    """
    interval = str(getattr(market, "interval", "") or "")
    interval_seconds = INTERVAL_SECONDS.get(interval)
    candles = tuple(getattr(market, "candles", ()) or ())
    if not interval_seconds or interval_seconds > 3600 or 3600 % interval_seconds != 0 or not candles:
        return None
    per_hour = 3600 // interval_seconds
    if per_hour == 1:
        return [(float(c.high), float(c.low), float(c.close)) for c in candles]
    # Align from the end so the most recent bucket is always complete,
    # dropping any incomplete leading remainder instead of the trailing one.
    usable = candles[len(candles) % per_hour:]
    buckets = []
    for start in range(0, len(usable), per_hour):
        group = usable[start:start + per_hour]
        if len(group) < per_hour:
            continue
        buckets.append((
            max(float(c.high) for c in group),
            min(float(c.low) for c in group),
            float(group[-1].close),
        ))
    return buckets


def _hourly_atr(market: Any, window: int = ADAPTIVE_ATR_WINDOW) -> float | None:
    """ATR(window) computed on 1H candles resampled from market.candles."""
    hourly = _resample_to_hourly_ohlc(market)
    if hourly is None or len(hourly) < window + 1:
        return None
    segment = hourly[-(window + 1):]
    ranges = [
        max(high - low, abs(high - segment[index - 1][2]), abs(low - segment[index - 1][2]))
        for index, (high, low, _close) in enumerate(segment)
        if index > 0
    ]
    return sum(ranges) / len(ranges) if ranges else None


def build_moving_grid_plan(
    market: Any,
    *,
    levels_per_side: int = 3,
    lookback_candles: int = 20,
    spacing_strategy: str | None = None,
) -> dict[str, Any] | None:
    """Build a rolling range grid that moves only as its candle window moves.

    Unlike latest-price centering, the rolling high/low midpoint lets price
    approach an actual grid level and therefore supplies meaningful location
    context to the pre-decision price-action stage. Returns None instead of
    a grid the live price has already moved past its innermost band on one
    side -- that's a breakout, not a range, and callers already treat None
    the same as "no grid data available."
    """
    symbol = str(getattr(market, "symbol", "")).strip().upper()
    strategy = spacing_strategy or ACTIVE_GRID_SPACING_STRATEGY
    minimum_spacing = MINIMUM_MOVING_GRID_SPACING.get(symbol, 0.0)
    live_price = getattr(market, "price", None)
    has_live_price = isinstance(live_price, (int, float)) and not isinstance(live_price, bool) and live_price > 0
    candles = tuple(getattr(market, "candles", ()) or ())[-lookback_candles:]
    if len(candles) < 5:
        fallback = build_grid_plan(getattr(market, "price", None), levels_per_side=levels_per_side)
        if fallback is None or fallback["spacing"] >= minimum_spacing:
            return fallback
        center = fallback["center"]
        lower, upper = center - minimum_spacing * levels_per_side, center + minimum_spacing * levels_per_side
    else:
        lower = min(float(candle.low) for candle in candles)
        upper = max(float(candle.high) for candle in candles)
    if lower <= 0 or upper <= lower:
        return build_grid_plan(getattr(market, "price", None), levels_per_side=levels_per_side)
    center = (lower + upper) / 2
    natural_spacing = (upper - lower) / (levels_per_side * 2)

    atr_1h: float | None = None
    spacing_basis = "rolling_range"
    if strategy == "adaptive_atr_v2" and symbol in ADAPTIVE_SPACING_BOUNDS_PCT:
        atr_1h = _hourly_atr(market)
        if atr_1h is not None:
            lower_bound_pct, upper_bound_pct = ADAPTIVE_SPACING_BOUNDS_PCT[symbol]
            bound_price = live_price if has_live_price else center
            candidate = max(natural_spacing, ADAPTIVE_ATR_MULTIPLIER * atr_1h)
            spacing = min(max(candidate, bound_price * lower_bound_pct), bound_price * upper_bound_pct)
            spacing_basis = "adaptive_atr_v2"
        else:
            # No clean 1H resample available (interval too coarse, or not
            # enough history yet) -- fail over to the fixed-floor strategy
            # rather than build an unguarded, ATR-less grid.
            spacing = max(natural_spacing, minimum_spacing)
            spacing_basis = "adaptive_atr_v2_fallback_fixed"
    else:
        spacing = max(natural_spacing, minimum_spacing)
        spacing_basis = "rolling_range_minimum_spacing" if spacing > natural_spacing else "rolling_range"

    buy_levels = [center - spacing * index for index in range(1, levels_per_side + 1)]
    sell_levels = [center + spacing * index for index in range(1, levels_per_side + 1)]
    lower_boundary, upper_boundary = buy_levels[-1], sell_levels[-1]

    if has_live_price:
        # The rolling range can lag a fast move: its midpoint stays behind
        # live price, so a structurally fine grid can still hand back levels
        # price has already blown through on one side. Fail closed rather
        # than present a range that's already been exited.
        if not (buy_levels[0] < live_price < sell_levels[0]):
            return None

    return {
        "center": round(center, 8),
        "buy_levels": [round(value, 8) for value in buy_levels],
        "sell_levels": [round(value, 8) for value in sell_levels],
        "lower_boundary": round(lower_boundary, 8),
        "upper_boundary": round(upper_boundary, 8),
        "lower_invalidation": round(lower_boundary - spacing, 8),
        "upper_invalidation": round(upper_boundary + spacing, 8),
        "spacing": round(spacing, 8),
        "spacing_strategy": strategy,
        "atr_1h": round(atr_1h, 8) if atr_1h is not None else None,
        "levels_per_side": levels_per_side,
        "basis": spacing_basis,
        "lookback_candles": len(candles),
        "minimum_spacing": minimum_spacing,
    }


def nearest_grid_level(grid: dict[str, Any], price: float) -> tuple[float, PriceActionDirection]:
    """The grid level (and its implied direction) closest to price.

    Shared by the live price-action stage and the grid-spacing backtester so
    both select an entry the same way -- a change to the tie-break or level
    selection here applies to both instead of silently drifting apart.
    """
    candidates = (
        *((level, PriceActionDirection.BULLISH) for level in grid["buy_levels"]),
        *((level, PriceActionDirection.BEARISH) for level in grid["sell_levels"]),
    )
    return min(candidates, key=lambda item: abs(price - item[0]))


def build_directional_plan(price: float | None, direction: str | None) -> dict[str, float] | None:
    """Project analysis levels without approval, sizing, or risk-engine semantics."""
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
        return None
    normalized = str(direction or "").lower()
    if normalized not in {"long", "short"}:
        return None
    entry = float(price)
    if normalized == "short":
        invalidation, target = entry * 1.02, entry * 0.96
    else:
        invalidation, target = entry * 0.98, entry * 1.04
    return {"entry": round(entry, 8), "invalidation": round(invalidation, 8), "target": round(target, 8)}


def build_production_analysis_run(symbol: str, *, interval: str = "1h", correlation_id: str | None = None, source: str = "monatise.production", verified_dynamic: bool = False) -> AnalysisRun:
    normalized = symbol.strip().upper()
    if normalized not in SUPPORTED_PRODUCTION_SYMBOLS and not verified_dynamic:
        raise ValueError("supported production symbols are BTC, ETH, and SOL")
    if verified_dynamic and (not normalized.isalnum() or not 2 <= len(normalized) <= 20):
        raise ValueError("invalid verified dynamic crypto symbol")
    interval = interval.strip()
    if interval not in SUPPORTED_PRODUCTION_INTERVALS:
        raise ValueError("unsupported production analysis interval")
    now = datetime.now(timezone.utc)
    interval_seconds = INTERVAL_SECONDS[interval]
    maximum_age_seconds = max(120, interval_seconds * 2)

    def output(context: Any, name: str) -> Any:
        return context.outputs[name]

    def flow(context: Any) -> OrderFlowRequest:
        market = output(context, "market_data")
        derivatives = market.derivatives
        cluster_map = estimate_liquidation_clusters(
            price=getattr(market, "price", None),
            open_interest_usd=derivatives.get("open_interest"),
            funding_rate=derivatives.get("funding_rate"),
        )
        return OrderFlowRequest(
            normalized,
            FlowInput(
                open_interest_change_pct=derivatives.get("open_interest_change_pct"),
                cvd_change=derivatives.get("cvd_delta"),
                liquidation_short_usd=derivatives.get("liquidation_short_usd"),
                liquidation_long_usd=derivatives.get("liquidation_long_usd"),
                bid_ask_imbalance=derivatives.get("order_book_imbalance"),
                funding_rate=derivatives.get("funding_rate"),
                liquidity_magnet_bias=cluster_map.magnet_bias if cluster_map is not None else None,
            ),
            output(context, "regime"),
            output(context, "market_structure"),
        )

    def price_action(context: Any) -> PriceActionRequest:
        market = output(context, "market_data")
        return PriceActionRequest(market)

    inputs = {
        "market_data": MarketDataRequest(normalized, interval=interval, candle_limit=240, max_age_seconds=maximum_age_seconds),
        "regime": lambda c: RegimeRequest(output(c, "market_data")),
        "liquidity": lambda c: LiquidityRequest(output(c, "market_data"), output(c, "regime")),
        "liquidity_sweep": lambda c: SweepRequest(output(c, "market_data"), output(c, "liquidity"), output(c, "regime")),
        "supply_demand": lambda c: ZoneRequest(output(c, "market_data"), output(c, "regime"), output(c, "liquidity")),
        "reclaim": lambda c: ReclaimRequest(output(c, "market_data"), output(c, "liquidity_sweep"), output(c, "regime"), output(c, "supply_demand"), require_follow_through=False),
        "market_structure": lambda c: MarketStructureRequest(output(c, "market_data"), output(c, "regime"), output(c, "liquidity"), output(c, "liquidity_sweep"), output(c, "reclaim"), output(c, "supply_demand"), swing_window=1, displacement_body_ratio=0.5),
        "fibonacci_liquidity": lambda c: FibonacciRequest(output(c, "market_data"), output(c, "market_structure"), output(c, "liquidity"), output(c, "supply_demand"), output(c, "reclaim"), minimum_structure_confidence=0),
        "order_flow": flow,
        "price_action": price_action,
        "decision": lambda c: DecisionRequest(output(c, "market_data"), None, output(c, "regime"), output(c, "liquidity"), output(c, "liquidity_sweep"), output(c, "supply_demand"), output(c, "reclaim"), output(c, "market_structure"), output(c, "fibonacci_liquidity"), output(c, "order_flow"), minimum_conviction=0.55, high_conviction=0.75, maximum_conflict_ratio=0.45, grid_regime_bonus=0.12, trend_regime_bonus=0.12, require_structure_for_trend=True, require_two_sided_liquidity_for_grid=True, minimum_signal_score=PRODUCTION_SIGNAL_SCORE_THRESHOLD),
        "rsi": lambda c: RSIRequest(output(c, "market_data"), output(c, "market_structure"), output(c, "regime")),
        "portfolio_intelligence": PortfolioIntelligenceRequest(100_000, ()),
        "intelligence_learning": LearningRequest((), minimum_samples=1),
    }
    kwargs = {"correlation_id": correlation_id} if correlation_id else {}
    return AnalysisRun(normalized, inputs, metadata=PipelineExecutionMetadata(source=source, retry_delay_seconds=0.1), **kwargs)


def sanitized_result(result: Any) -> dict[str, Any]:
    decision = result.context.outputs.get("decision")
    market = result.context.outputs.get("market_data")
    price_action = result.context.outputs.get("price_action")
    classification = getattr(getattr(decision, "classification", None), "value", None)
    direction = getattr(getattr(decision, "direction", None), "value", None)
    metadata = getattr(decision, "metadata", {}) or {}
    price = getattr(market, "price", None)
    directional_plan = build_directional_plan(price, direction)
    confirmation_status = getattr(getattr(price_action, "status", None), "value", "pending")
    confirmation_signal = strongest_confirmation_signal(price_action)
    confirmation_age = int(getattr(confirmation_signal, "age_candles", 0) or 0)
    run = getattr(getattr(result, "context", None), "run", None)
    generated_at = getattr(result, "finished_at", None) or getattr(run, "requested_at", None) or datetime.now(timezone.utc)
    validity = build_setup_validity(
        getattr(market, "interval", None),
        generated_at, age_candles=0,
    )
    return {
        "run_id": result.run_id,
        "correlation_id": result.correlation_id,
        "symbol": result.symbol,
        "interval": getattr(market, "interval", None),
        "status": result.status.value,
        "classification": classification,
        "direction": direction,
        "conviction": getattr(decision, "conviction", None),
        "score": metadata.get("signed_signal_score"),
        "score_threshold": metadata.get("minimum_signal_score", 7),
        "entry": directional_plan["entry"] if directional_plan else None,
        "invalidation": directional_plan["invalidation"] if directional_plan else None,
        "target": directional_plan["target"] if directional_plan else None,
        "reward_risk": None,
        "entry_confirmation_status": confirmation_status,
        "entry_confirmation_required": bool(getattr(price_action, "entry_confirmation_required", True)),
        "price_action_confirmed": bool(getattr(price_action, "has_confirmation", False)),
        "price_action_aggregate_confidence": float(getattr(price_action, "aggregate_confidence", 0.0) or 0.0),
        "price_action_aligned_family_count": int(getattr(price_action, "aligned_family_count", 0) or 0),
        "price_action_conflicting_family_count": int(getattr(price_action, "conflicting_family_count", 0) or 0),
        "price_action_reasons": list(getattr(price_action, "reasons", ()) or ()),
        "price_action_signals": [
            {
                "family": signal.family.value,
                "pattern": signal.pattern,
                "direction": signal.direction.value,
                "confidence": signal.confidence,
                "age_candles": signal.age_candles,
                "direction_aligned": signal.direction_aligned,
                "location_aligned": signal.location_aligned,
                "fresh": signal.fresh,
                "invalidated": signal.invalidated,
                "distance_to_entry_ratio": signal.distance_to_entry_ratio,
                "evidence_score": signal.evidence_score,
                "metadata": signal.metadata,
            }
            for signal in tuple(getattr(price_action, "signals", ()) or ())
        ],
        "risk_decision": None,
        "risk_issues": [],
        "risk_reasons": [],
        "generated_at": validity["generated_at"].isoformat() if validity else None,
        "expires_at": validity["expires_at"].isoformat() if validity else None,
        "validity_candles": validity["validity_candles"] if validity else None,
        "remaining_validity_candles": validity["remaining_candles"] if validity else None,
        "validity_seconds": validity["validity_seconds"] if validity else None,
        "data_source": getattr(getattr(market, "quality", None), "source", None),
        "reasons": list(getattr(decision, "reasons", ()) or ()),
        "blockers": list(getattr(decision, "blockers", ()) or ()),
        "blocked_by": result.blocked_by,
        "completed_stages": result.statistics.completed_stages,
        "stage_total": len(PRODUCTION_ENGINE_ORDER),
        "risk_validation_invoked": False,
        "allocation_produced": False,
        "execution_policy_produced": False,
        "execution_enabled": False,
        "audit_reference": result.run_id,
        "state_reference": result.run_id,
    }
