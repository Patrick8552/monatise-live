from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from monatise.application import AnalysisRun, PipelineExecutionMetadata, PipelineStage, create_application
from monatise.core.models import Candle
from monatise.engines.capital_allocation.models import AllocationRequest, PortfolioExposure
from monatise.engines.capital_allocation.engine import CapitalAllocationEngine
from monatise.engines.decision.engine import DecisionEngine
from monatise.engines.decision.models import DecisionRequest, DecisionState
from monatise.engines.execution_policy.engine import ExecutionPolicyEngine
from monatise.engines.execution_policy.models import ExecutionMode, ExecutionPolicyRequest
from monatise.engines.fibonacci_liquidity.models import FibonacciRequest
from monatise.engines.governance_loss_control.models import GovernanceRequest, LossControlSnapshot
from monatise.engines.governance_loss_control.engine import GovernanceLossControlEngine
from monatise.engines.integration.models import IntegrationChannel, IntegrationRequest
from monatise.engines.intelligence_learning.models import LearningRequest
from monatise.engines.liquidity.models import LiquidityRequest
from monatise.engines.liquidity_sweep.models import SweepRequest
from monatise.engines.macro.models import MacroEvent, MacroEventImpact, MacroRequest
from monatise.engines.market_data.models import DataStatus, MarketDataRequest
from monatise.engines.market_structure.models import MarketStructureRequest
from monatise.engines.order_flow.models import FlowInput, OrderFlowRequest
from monatise.engines.portfolio_intelligence.engine import PortfolioIntelligenceEngine
from monatise.engines.portfolio_intelligence.models import PortfolioHealth, PortfolioIntelligenceRequest, PortfolioPosition
from monatise.engines.reclaim.models import ReclaimRequest
from monatise.engines.regime.models import RegimeRequest
from monatise.engines.reporting_intelligence.models import ReportChannel, ReportRequest
from monatise.engines.risk_validation.models import RiskRequest
from monatise.engines.risk_validation.engine import RiskValidationEngine
from monatise.engines.risk_validation.models import RiskDecision
from monatise.engines.rsi.models import RSIRequest
from monatise.engines.supply_demand.models import ZoneRequest


class CandleProvider:
    def __init__(self, now: datetime, direction: str = "long") -> None:
        self.now = now
        self.direction = direction

    def latest_price(self, symbol: str) -> float:
        return 120.0

    def candles(self, symbol: str, limit: int, interval: str):
        start = self.now - timedelta(minutes=limit - 1)
        pattern = ((100, 102, 99, 101), (101, 104, 100, 103), (103, 105, 101, 102), (102, 103, 98, 99), (99, 101, 97, 100), (100, 106, 99, 105), (105, 107, 103, 104), (104, 105, 100, 101), (101, 103, 99, 102), (102, 110, 101, 109))
        candles = []
        for index in range(limit):
            offset = (index // len(pattern)) * 0.5
            open_price, high, low, close = pattern[index % len(pattern)]
            values = (open_price + offset, high + offset, low + offset, close + offset)
            if self.direction == "short":
                open_value, high_value, low_value, close_value = values
                values = (240 - open_value, 240 - low_value, 240 - high_value, 240 - close_value)
            candles.append(Candle((start + timedelta(minutes=index)).isoformat(), *values, 1_000 + index))
        return candles


class MacroProvider:
    def __init__(self, direction: str = "long") -> None: self.direction = direction
    def economic_events(self): return []
    def context_snapshot(self, symbol: str):
        sign = 1 if self.direction == "long" else -1
        return {"risk_sentiment_score": 0.8 * sign, "usd_liquidity_score": 0.7 * sign, "stablecoin_market_cap_change_pct": 1.0 * sign, "crypto_open_interest_change_pct": 2.0 * sign}


def run_real_pipeline(direction: str = "long", *, grid: bool = False):
    now = datetime.now(timezone.utc)
    application = create_application(market_data_providers={"mock": CandleProvider(now, direction)}, macro_provider=MacroProvider(direction))
    sign = 1 if direction == "long" else -1

    def output(context, name): return context.outputs[name]

    inputs = {
        "market_data": MarketDataRequest("BTC", interval="1m", candle_limit=200, max_age_seconds=120),
        "regime": lambda c: RegimeRequest(output(c, "market_data"), trend_threshold=0.5, compression_threshold=0.01, expansion_threshold=100, high_volatility_threshold=200),
        "liquidity": lambda c: LiquidityRequest(output(c, "market_data"), output(c, "regime")),
        "liquidity_sweep": lambda c: SweepRequest(output(c, "market_data"), output(c, "liquidity"), output(c, "regime")),
        "supply_demand": lambda c: ZoneRequest(output(c, "market_data"), output(c, "regime"), output(c, "liquidity")),
        "reclaim": lambda c: ReclaimRequest(output(c, "market_data"), output(c, "liquidity_sweep"), output(c, "regime"), output(c, "supply_demand"), require_follow_through=False),
        "market_structure": lambda c: MarketStructureRequest(output(c, "market_data"), output(c, "regime"), output(c, "liquidity"), output(c, "liquidity_sweep"), output(c, "reclaim"), output(c, "supply_demand"), swing_window=1, displacement_body_ratio=0.5),
        "fibonacci_liquidity": lambda c: FibonacciRequest(output(c, "market_data"), output(c, "market_structure"), output(c, "liquidity"), output(c, "supply_demand"), output(c, "reclaim"), minimum_structure_confidence=0),
        "order_flow": lambda c: OrderFlowRequest("BTC", FlowInput(open_interest_change_pct=2, price_change_pct=sign, cvd_change=100 * sign, liquidation_short_usd=200 if sign > 0 else 100, liquidation_long_usd=100 if sign > 0 else 200, footprint_delta=0.6 * sign, large_trade_net_usd=1000 * sign, bid_ask_imbalance=0.5 * sign, funding_rate=0.0001 * sign), output(c, "regime"), output(c, "market_structure")),
        "decision": lambda c: DecisionRequest(output(c, "market_data"), None, output(c, "regime"), output(c, "liquidity"), output(c, "liquidity_sweep"), output(c, "supply_demand"), output(c, "reclaim"), output(c, "market_structure"), output(c, "fibonacci_liquidity"), output(c, "order_flow"), minimum_conviction=0, maximum_conflict_ratio=1, grid_regime_bonus=1 if grid else 0.12, require_structure_for_trend=False, require_two_sided_liquidity_for_grid=False),
        "rsi": lambda c: RSIRequest(output(c, "market_data"), output(c, "market_structure"), output(c, "regime")),
        "risk_validation": lambda c: RiskRequest(output(c, "market_data"), output(c, "decision"), None, output(c, "regime"), output(c, "market_structure"), output(c, "fibonacci_liquidity"), output(c, "supply_demand"), output(c, "order_flow"), output(c, "rsi"), now, now + timedelta(minutes=30), proposed_entry=120, proposed_invalidation=117 if sign > 0 else 123, proposed_target=126 if sign > 0 else 114, account_equity=100_000, minimum_reward_risk=1),
        "capital_allocation": lambda c: AllocationRequest(output(c, "risk_validation"), PortfolioExposure(100_000, 0, 0, 0, 0, 0, 0, 0), output(c, "decision").classification, requested_capital=1_000),
        "execution_policy": lambda c: ExecutionPolicyRequest(output(c, "decision"), output(c, "risk_validation"), output(c, "capital_allocation"), ExecutionMode.PAPER, now),
        "portfolio_intelligence": PortfolioIntelligenceRequest(100_000, ()),
        "reporting_intelligence": lambda c: ReportRequest(now, ReportChannel.API, output(c, "market_data"), None, output(c, "regime"), output(c, "liquidity"), output(c, "liquidity_sweep"), output(c, "supply_demand"), output(c, "reclaim"), output(c, "market_structure"), output(c, "fibonacci_liquidity"), output(c, "order_flow"), output(c, "decision"), output(c, "rsi"), output(c, "risk_validation"), output(c, "capital_allocation"), output(c, "execution_policy"), output(c, "portfolio_intelligence")),
        "intelligence_learning": LearningRequest((), minimum_samples=1),
        "integration": lambda c: IntegrationRequest(output(c, "reporting_intelligence"), output(c, "execution_policy"), (IntegrationChannel.DATABASE, IntegrationChannel.AUDIT_LOG), now, enable_coinglass=False, enable_telegram=False, enable_openclaw=False, enable_dashboard=False),
        "governance_loss_control": lambda c: GovernanceRequest(LossControlSnapshot(100_000, 100_000, 100_000, 0, 0, 0, 0, 0), output(c, "risk_validation"), output(c, "capital_allocation"), output(c, "execution_policy"), output(c, "portfolio_intelligence"), now),
    }
    result = asyncio.run(application.orchestrator.run(AnalysisRun("BTC", inputs, metadata=PipelineExecutionMetadata(retry_delay_seconds=0))))
    return result, inputs


def test_real_nineteen_engine_trend_long_pipeline():
    result, inputs = run_real_pipeline()
    assert result.status is PipelineStage.COMPLETED, (result.blocked_by, result.failure)
    assert tuple(result.context.outputs) == tuple(inputs)
    assert result.statistics.completed_stages == 19
    assert result.context.outputs["decision"].direction.value == "long"


def test_real_nineteen_engine_trend_short_pipeline():
    result, _ = run_real_pipeline("short")
    assert result.status is PipelineStage.COMPLETED, (result.blocked_by, result.failure)
    assert result.context.outputs["decision"].direction.value == "short"


def test_real_nineteen_engine_grid_pipeline():
    result, _ = run_real_pipeline(grid=True)
    assert result.status is PipelineStage.COMPLETED, (result.blocked_by, result.failure)
    assert result.context.outputs["decision"].classification.value == "grid"


def decision_request(outputs, **kwargs):
    return DecisionRequest(outputs["market_data"], None, outputs["regime"], outputs["liquidity"], outputs["liquidity_sweep"], outputs["supply_demand"], outputs["reclaim"], outputs["market_structure"], outputs["fibonacci_liquidity"], outputs["order_flow"], require_structure_for_trend=False, require_two_sided_liquidity_for_grid=False, **kwargs)


def test_real_no_trade_and_high_threshold_decision_paths_block():
    completed, _ = run_real_pipeline()
    outputs = completed.context.outputs
    degraded = replace(outputs["market_data"], quality=replace(outputs["market_data"].quality, status=DataStatus.DEGRADED))
    no_trade = DecisionEngine().assess(replace(decision_request(outputs), market=degraded))
    assert no_trade.classification.value == "no_trade"
    registration = next(item for item in completed.context.run.stage_inputs if item == "decision")
    assert registration == "decision"
    conditional = DecisionEngine().assess(decision_request(outputs, minimum_conviction=1, high_conviction=1, maximum_conflict_ratio=1))
    assert conditional.state is DecisionState.BLOCKED
    from monatise.application.registry import canonical_registrations
    predicate = next(item.blocking for item in canonical_registrations() if item.name == "decision")
    assert predicate(conditional)


def test_real_expired_signal_risk_rejection_and_allocation_block():
    completed, _ = run_real_pipeline()
    outputs = completed.context.outputs
    now = datetime.now(timezone.utc)
    expired = RiskValidationEngine().assess(RiskRequest(outputs["market_data"], outputs["decision"], None, outputs["regime"], outputs["market_structure"], outputs["fibonacci_liquidity"], outputs["supply_demand"], outputs["order_flow"], outputs["rsi"], now, now - timedelta(seconds=1), proposed_entry=120, proposed_invalidation=117, proposed_target=126, account_equity=100_000))
    assert expired.decision is RiskDecision.REJECTED
    blocked = CapitalAllocationEngine().assess(AllocationRequest(outputs["risk_validation"], PortfolioExposure(100_000, 100_000, 10_000, 1, 1, 1, 99, 99), outputs["decision"].classification, requested_capital=1_000))
    assert blocked.decision.value == "blocked"


def test_real_execution_portfolio_and_governance_blocks():
    completed, _ = run_real_pipeline()
    outputs = completed.context.outputs
    disabled = ExecutionPolicyEngine().assess(ExecutionPolicyRequest(outputs["decision"], outputs["risk_validation"], outputs["capital_allocation"], ExecutionMode.DISABLED, datetime.now(timezone.utc)))
    assert disabled.decision.value == "blocked"
    fragile = PortfolioIntelligenceEngine().assess(PortfolioIntelligenceRequest(100_000, (PortfolioPosition("one", "BTC", "long", 90_000, 9_000, 5, "majors", "low"),)))
    assert fragile.health in {PortfolioHealth.FRAGILE, PortfolioHealth.BLOCKED}
    for snapshot, expected in ((LossControlSnapshot(100_000, 100_000, 100_000, 0, 0, 0, 0, 0, manual_freeze_active=True), "frozen"), (LossControlSnapshot(100_000, 100_000, 100_000, 0, 0, 0, 0, 0, kill_switch_active=True), "kill_switch")):
        governance = GovernanceLossControlEngine().assess(GovernanceRequest(snapshot, outputs["risk_validation"], outputs["capital_allocation"], outputs["execution_policy"], outputs["portfolio_intelligence"], datetime.now(timezone.utc)))
        assert governance.state.value == expected


def test_real_market_no_data_stops_pipeline():
    now = datetime.now(timezone.utc)

    class EmptyProvider:
        def latest_price(self, symbol): return None
        def candles(self, symbol, limit, interval): return []

    no_data_app = create_application(market_data_providers={"empty": EmptyProvider()}, macro_provider=MacroProvider())
    no_data = asyncio.run(no_data_app.orchestrator.run(AnalysisRun("BTC", {"market_data": MarketDataRequest("BTC")}, metadata=PipelineExecutionMetadata(retry_delay_seconds=0))))
    assert no_data.status is PipelineStage.BLOCKED and no_data.blocked_by == "market_data"
