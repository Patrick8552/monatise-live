"""Canonical, analysis-only request construction for production."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from monatise.application.models import AnalysisRun, PipelineExecutionMetadata
from monatise.engines.capital_allocation.models import AllocationRequest, PortfolioExposure
from monatise.engines.decision.models import DecisionRequest
from monatise.engines.execution_policy.models import ExecutionMode, ExecutionPolicyRequest
from monatise.engines.fibonacci_liquidity.models import FibonacciRequest
from monatise.engines.governance_loss_control.models import GovernanceRequest, LossControlSnapshot
from monatise.engines.integration.models import IntegrationChannel, IntegrationRequest
from monatise.engines.intelligence_learning.models import LearningRequest
from monatise.engines.liquidity.models import LiquidityRequest
from monatise.engines.liquidity_sweep.models import SweepRequest
from monatise.engines.market_data.models import MarketDataRequest
from monatise.engines.market_structure.models import MarketStructureRequest
from monatise.engines.order_flow.models import FlowInput, OrderFlowRequest
from monatise.engines.portfolio_intelligence.models import PortfolioIntelligenceRequest
from monatise.engines.reclaim.models import ReclaimRequest
from monatise.engines.regime.models import RegimeRequest
from monatise.engines.reporting_intelligence.models import ReportChannel, ReportRequest
from monatise.engines.risk_validation.models import RiskRequest
from monatise.engines.rsi.models import RSIRequest
from monatise.engines.supply_demand.models import ZoneRequest


SUPPORTED_PRODUCTION_SYMBOLS = frozenset({"BTC", "ETH", "SOL"})


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


def build_production_analysis_run(symbol: str, *, correlation_id: str | None = None, source: str = "monatise.production") -> AnalysisRun:
    normalized = symbol.strip().upper()
    if normalized not in SUPPORTED_PRODUCTION_SYMBOLS:
        raise ValueError("supported production symbols are BTC, ETH, and SOL")
    now = datetime.now(timezone.utc)

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

    def risk(context: Any) -> RiskRequest:
        market = output(context, "market_data")
        decision = output(context, "decision")
        direction = getattr(decision.direction, "value", "none")
        classification = getattr(decision.classification, "value", "no_trade")
        entry = market.price
        grid = None
        if entry is None:
            proposed = (None, None, None)
        elif classification == "grid":
            grid = build_grid_plan(entry)
            proposed = (entry, grid["lower_boundary"], grid["upper_boundary"])
        elif direction == "short":
            proposed = (entry, entry * 1.02, entry * 0.96)
        else:
            proposed = (entry, entry * 0.98, entry * 1.04)
        return RiskRequest(output(context, "market_data"), output(context, "decision"), None, output(context, "regime"), output(context, "market_structure"), output(context, "fibonacci_liquidity"), output(context, "supply_demand"), output(context, "order_flow"), output(context, "rsi"), now, now + timedelta(minutes=30), proposed_entry=proposed[0], proposed_invalidation=proposed[1], proposed_target=proposed[2], proposed_grid_buy_levels=tuple(grid["buy_levels"]) if grid else (), proposed_grid_sell_levels=tuple(grid["sell_levels"]) if grid else (), proposed_grid_lower_invalidation=grid["lower_invalidation"] if grid else None, proposed_grid_upper_invalidation=grid["upper_invalidation"] if grid else None, account_equity=100_000, minimum_reward_risk=1.0)

    inputs = {
        "market_data": MarketDataRequest(normalized, interval="1h", candle_limit=200, max_age_seconds=7200),
        "regime": lambda c: RegimeRequest(output(c, "market_data")),
        "liquidity": lambda c: LiquidityRequest(output(c, "market_data"), output(c, "regime")),
        "liquidity_sweep": lambda c: SweepRequest(output(c, "market_data"), output(c, "liquidity"), output(c, "regime")),
        "supply_demand": lambda c: ZoneRequest(output(c, "market_data"), output(c, "regime"), output(c, "liquidity")),
        "reclaim": lambda c: ReclaimRequest(output(c, "market_data"), output(c, "liquidity_sweep"), output(c, "regime"), output(c, "supply_demand"), require_follow_through=False),
        "market_structure": lambda c: MarketStructureRequest(output(c, "market_data"), output(c, "regime"), output(c, "liquidity"), output(c, "liquidity_sweep"), output(c, "reclaim"), output(c, "supply_demand"), swing_window=1, displacement_body_ratio=0.5),
        "fibonacci_liquidity": lambda c: FibonacciRequest(output(c, "market_data"), output(c, "market_structure"), output(c, "liquidity"), output(c, "supply_demand"), output(c, "reclaim"), minimum_structure_confidence=0),
        "order_flow": flow,
        "decision": lambda c: DecisionRequest(output(c, "market_data"), None, output(c, "regime"), output(c, "liquidity"), output(c, "liquidity_sweep"), output(c, "supply_demand"), output(c, "reclaim"), output(c, "market_structure"), output(c, "fibonacci_liquidity"), output(c, "order_flow"), minimum_conviction=0.55, high_conviction=0.75, maximum_conflict_ratio=0.45, grid_regime_bonus=0.12, trend_regime_bonus=0.12, require_structure_for_trend=True, require_two_sided_liquidity_for_grid=True, minimum_signal_score=7),
        "rsi": lambda c: RSIRequest(output(c, "market_data"), output(c, "market_structure"), output(c, "regime")),
        "risk_validation": risk,
        "capital_allocation": lambda c: AllocationRequest(output(c, "risk_validation"), PortfolioExposure(100_000, 0, 0, 0, 0, 0, 0, 0), output(c, "decision").classification, requested_capital=1_000),
        "execution_policy": lambda c: ExecutionPolicyRequest(output(c, "decision"), output(c, "risk_validation"), output(c, "capital_allocation"), ExecutionMode.PAPER, now),
        "portfolio_intelligence": PortfolioIntelligenceRequest(100_000, ()),
        "reporting_intelligence": lambda c: ReportRequest(now, ReportChannel.API, output(c, "market_data"), None, output(c, "regime"), output(c, "liquidity"), output(c, "liquidity_sweep"), output(c, "supply_demand"), output(c, "reclaim"), output(c, "market_structure"), output(c, "fibonacci_liquidity"), output(c, "order_flow"), output(c, "decision"), output(c, "rsi"), output(c, "risk_validation"), output(c, "capital_allocation"), output(c, "execution_policy"), output(c, "portfolio_intelligence")),
        "intelligence_learning": LearningRequest((), minimum_samples=1),
        "integration": lambda c: IntegrationRequest(output(c, "reporting_intelligence"), output(c, "execution_policy"), (IntegrationChannel.DATABASE, IntegrationChannel.AUDIT_LOG), now, enable_coinglass=True, enable_telegram=False, enable_openclaw=False, enable_dashboard=False),
        "governance_loss_control": lambda c: GovernanceRequest(LossControlSnapshot(100_000, 100_000, 100_000, 0, 0, 0, 0, 0, kill_switch_active=False), output(c, "risk_validation"), output(c, "capital_allocation"), output(c, "execution_policy"), output(c, "portfolio_intelligence"), now),
    }
    kwargs = {"correlation_id": correlation_id} if correlation_id else {}
    return AnalysisRun(normalized, inputs, metadata=PipelineExecutionMetadata(source=source, retry_delay_seconds=0.1), **kwargs)


def sanitized_result(result: Any) -> dict[str, Any]:
    decision = result.context.outputs.get("decision")
    risk = result.context.outputs.get("risk_validation")
    market = result.context.outputs.get("market_data")
    classification = getattr(getattr(decision, "classification", None), "value", None)
    direction = getattr(getattr(decision, "direction", None), "value", None)
    metadata = getattr(decision, "metadata", {}) or {}
    risk_decision = getattr(getattr(risk, "decision", None), "value", None)
    risk_issues = list(getattr(risk, "issues", ()) or ())
    risk_metadata = getattr(risk, "metadata", {}) or {}
    grid_plan = risk_metadata.get("grid_plan") if classification == "grid" else None
    if classification == "grid" and grid_plan is None:
        grid_plan = build_grid_plan(getattr(risk, "validated_entry", None) or getattr(market, "price", None))
    return {
        "run_id": result.run_id,
        "correlation_id": result.correlation_id,
        "symbol": result.symbol,
        "status": result.status.value,
        "classification": classification,
        "direction": direction,
        "conviction": getattr(decision, "conviction", None),
        "score": metadata.get("signed_signal_score"),
        "grid_score": metadata.get("grid_signal_score"),
        "score_threshold": metadata.get("minimum_signal_score", 7),
        "entry": getattr(risk, "validated_entry", None),
        "invalidation": getattr(risk, "validated_invalidation", None),
        "target": getattr(risk, "validated_target", None),
        "reward_risk": getattr(risk, "reward_risk", None),
        "grid_plan": grid_plan,
        "risk_decision": risk_decision,
        "risk_issues": [
            {
                "code": getattr(issue, "code", None),
                "severity": getattr(getattr(issue, "severity", None), "value", None),
                "message": getattr(issue, "message", str(issue)),
            }
            for issue in risk_issues
        ],
        "risk_reasons": list(getattr(risk, "reasons", ()) or ()),
        "expires_at": getattr(getattr(risk, "signal_expires_at", None), "isoformat", lambda: None)(),
        "data_source": getattr(getattr(market, "quality", None), "source", None),
        "reasons": list(getattr(decision, "reasons", ()) or ()),
        "blockers": list(getattr(decision, "blockers", ()) or ()),
        "blocked_by": result.blocked_by,
        "completed_stages": result.statistics.completed_stages,
        "risk_validation_invoked": "risk_validation" in result.context.outputs,
        "allocation_produced": "capital_allocation" in result.context.outputs,
        "execution_policy_produced": "execution_policy" in result.context.outputs,
        "execution_enabled": False,
        "audit_reference": result.run_id,
        "state_reference": result.run_id,
    }
