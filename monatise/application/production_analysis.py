"""Canonical, analysis-only request construction for production."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from monatise.application.models import AnalysisRun, PipelineExecutionMetadata
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
SUPPORTED_PRODUCTION_INTERVALS = frozenset({"1m", "3m", "5m", "15m", "30m", "1h", "4h", "6h", "8h", "12h", "1d", "1w"})
INTERVAL_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1_800,
    "1h": 3_600, "4h": 14_400, "6h": 21_600, "8h": 28_800,
    "12h": 43_200, "1d": 86_400, "1w": 604_800,
}
SETUP_VALIDITY_CANDLES = 4


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


def build_moving_grid_plan(market: Any, *, levels_per_side: int = 3, lookback_candles: int = 20) -> dict[str, Any] | None:
    """Build a rolling range grid that moves only as its candle window moves.

    Unlike latest-price centering, the rolling high/low midpoint lets price
    approach an actual grid level and therefore supplies meaningful location
    context to the pre-decision price-action stage.
    """
    symbol = str(getattr(market, "symbol", "")).strip().upper()
    minimum_spacing = MINIMUM_MOVING_GRID_SPACING.get(symbol, 0.0)
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
    spacing = max(natural_spacing, minimum_spacing)
    buy_levels = [center - spacing * index for index in range(1, levels_per_side + 1)]
    sell_levels = [center + spacing * index for index in range(1, levels_per_side + 1)]
    lower_boundary, upper_boundary = buy_levels[-1], sell_levels[-1]
    floor_applied = spacing > natural_spacing
    return {
        "center": round(center, 8),
        "buy_levels": [round(value, 8) for value in buy_levels],
        "sell_levels": [round(value, 8) for value in sell_levels],
        "lower_boundary": round(lower_boundary, 8),
        "upper_boundary": round(upper_boundary, 8),
        "lower_invalidation": round(lower_boundary - spacing, 8),
        "upper_invalidation": round(upper_boundary + spacing, 8),
        "spacing": round(spacing, 8),
        "levels_per_side": levels_per_side,
        "basis": "rolling_range_minimum_spacing" if floor_applied else "rolling_range",
        "lookback_candles": len(candles),
        "minimum_spacing": minimum_spacing,
    }


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


def build_production_analysis_run(symbol: str, *, interval: str = "1h", correlation_id: str | None = None, source: str = "monatise.production") -> AnalysisRun:
    normalized = symbol.strip().upper()
    if normalized not in SUPPORTED_PRODUCTION_SYMBOLS:
        raise ValueError("supported production symbols are BTC, ETH, and SOL")
    interval = interval.strip()
    if interval not in SUPPORTED_PRODUCTION_INTERVALS:
        raise ValueError("unsupported production analysis interval")
    now = datetime.now(timezone.utc)
    interval_seconds = INTERVAL_SECONDS[interval]
    maximum_age_seconds = max(120, interval_seconds * 2)

    def output(context: Any, name: str) -> Any:
        return context.outputs[name]

    def flow(context: Any) -> OrderFlowRequest:
        derivatives = output(context, "market_data").derivatives
        return OrderFlowRequest(
            normalized,
            FlowInput(
                open_interest_change_pct=derivatives.get("open_interest"),
                cvd_change=derivatives.get("cvd"),
                liquidation_short_usd=derivatives.get("liquidation_volume"),
                liquidation_long_usd=derivatives.get("liquidation_volume"),
                bid_ask_imbalance=derivatives.get("order_book_imbalance"),
                funding_rate=derivatives.get("funding_rate"),
            ),
            output(context, "regime"),
            output(context, "market_structure"),
        )

    def price_action(context: Any) -> PriceActionRequest:
        market = output(context, "market_data")
        grid = build_moving_grid_plan(market)
        if grid is None or market.price is None:
            return PriceActionRequest(market)
        candidates = (
            *((level, PriceActionDirection.BULLISH) for level in grid["buy_levels"]),
            *((level, PriceActionDirection.BEARISH) for level in grid["sell_levels"]),
        )
        level, expected_direction = min(candidates, key=lambda item: abs(float(market.price) - item[0]))
        zone_half_width = grid["spacing"] * 0.15
        return PriceActionRequest(
            market,
            expected_direction=expected_direction,
            entry_price=level,
            entry_zone_low=level - zone_half_width,
            entry_zone_high=level + zone_half_width,
        )

    inputs = {
        "market_data": MarketDataRequest(normalized, interval=interval, candle_limit=200, max_age_seconds=maximum_age_seconds),
        "regime": lambda c: RegimeRequest(output(c, "market_data")),
        "liquidity": lambda c: LiquidityRequest(output(c, "market_data"), output(c, "regime")),
        "liquidity_sweep": lambda c: SweepRequest(output(c, "market_data"), output(c, "liquidity"), output(c, "regime")),
        "supply_demand": lambda c: ZoneRequest(output(c, "market_data"), output(c, "regime"), output(c, "liquidity")),
        "reclaim": lambda c: ReclaimRequest(output(c, "market_data"), output(c, "liquidity_sweep"), output(c, "regime"), output(c, "supply_demand"), require_follow_through=False),
        "market_structure": lambda c: MarketStructureRequest(output(c, "market_data"), output(c, "regime"), output(c, "liquidity"), output(c, "liquidity_sweep"), output(c, "reclaim"), output(c, "supply_demand"), swing_window=1, displacement_body_ratio=0.5),
        "fibonacci_liquidity": lambda c: FibonacciRequest(output(c, "market_data"), output(c, "market_structure"), output(c, "liquidity"), output(c, "supply_demand"), output(c, "reclaim"), minimum_structure_confidence=0),
        "order_flow": flow,
        "price_action": price_action,
        "decision": lambda c: DecisionRequest(output(c, "market_data"), None, output(c, "regime"), output(c, "liquidity"), output(c, "liquidity_sweep"), output(c, "supply_demand"), output(c, "reclaim"), output(c, "market_structure"), output(c, "fibonacci_liquidity"), output(c, "order_flow"), minimum_conviction=0.55, high_conviction=0.75, maximum_conflict_ratio=0.45, grid_regime_bonus=0.12, trend_regime_bonus=0.12, require_structure_for_trend=True, require_two_sided_liquidity_for_grid=True, minimum_signal_score=7),
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
    grid_plan = build_moving_grid_plan(market) if classification == "grid" else None
    confirmation_status = getattr(getattr(price_action, "status", None), "value", "pending")
    confirming = tuple(getattr(price_action, "confirming_signals", ()) or ())
    confirmation_age = min((int(getattr(signal, "age_candles", 0) or 0) for signal in confirming), default=0)
    run = getattr(getattr(result, "context", None), "run", None)
    generated_at = getattr(result, "finished_at", None) or getattr(run, "requested_at", None) or datetime.now(timezone.utc)
    validity = build_setup_validity(
        getattr(market, "interval", None),
        generated_at, age_candles=confirmation_age if classification == "grid" else 0,
    ) if classification != "grid" or confirmation_status == "confirmed" else None
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
        "grid_score": metadata.get("grid_signal_score"),
        "score_threshold": metadata.get("minimum_signal_score", 7),
        "entry": directional_plan["entry"] if directional_plan else price if classification == "grid" else None,
        "invalidation": directional_plan["invalidation"] if directional_plan else None,
        "target": directional_plan["target"] if directional_plan else None,
        "reward_risk": None,
        "grid_plan": grid_plan,
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
        "risk_validation_invoked": False,
        "allocation_produced": False,
        "execution_policy_produced": False,
        "execution_enabled": False,
        "audit_reference": result.run_id,
        "state_reference": result.run_id,
    }
