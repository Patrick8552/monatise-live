from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Any, Mapping

from monatise.application.hierarchy.adapter import CanonicalEvidenceAdapter, HierarchicalAnalysisRequest, HierarchyValidation
from monatise.application.hierarchy.coordinator import HierarchyConfiguration, TimeframeSnapshot
from monatise.application.hierarchy.models import (
    DataQualityState,
    EvidenceBundle,
    EvidenceContext,
    EvidenceIdentity,
    Provenance,
    SetupState,
    StrategicState,
    TriggerState,
)
from monatise.application.hierarchy.risk import StructuralRiskInputBuilder
from monatise.core.models import Candle
from monatise.engines.liquidity import LiquidityEngine, LiquidityRequest
from monatise.engines.liquidity_sweep import LiquiditySweepEngine, SweepRequest
from monatise.engines.market_data.models import DataQuality, DataStatus, MarketSnapshot
from monatise.engines.market_structure import MarketStructureEngine, MarketStructureRequest
from monatise.engines.market_structure.models import StructureBias
from monatise.engines.reclaim import ReclaimEngine, ReclaimRequest
from monatise.engines.regime import RegimeEngine, RegimeRequest
from monatise.engines.regime.models import RegimeState
from monatise.engines.supply_demand import SupplyDemandEngine, ZoneRequest


@dataclass(frozen=True)
class LayerAnalysis:
    market: MarketSnapshot
    liquidity: Any
    sweep: Any
    zones: Any
    reclaim: Any
    structure: Any


@dataclass(frozen=True)
class ShadowEvaluation:
    symbol: str
    evaluated_at: datetime
    macro_context: EvidenceContext | None
    regime_4h: EvidenceContext | None
    strategy_1h: EvidenceContext | None
    setup_15m: EvidenceContext | None
    trigger_5m: EvidenceContext | None
    bundle: EvidenceBundle | None
    validation: HierarchyValidation | None
    watching: bool
    reasons: tuple[str, ...]
    execution_enabled: bool = False


@dataclass
class _SymbolState:
    macro_context: EvidenceContext | None = None
    regime_context: EvidenceContext | None = None
    regime_assessment: Any | None = None
    strategy_context: EvidenceContext | None = None
    setup_context: EvidenceContext | None = None
    trigger_context: EvidenceContext | None = None
    snapshots: dict[str, TimeframeSnapshot] | None = None


def _confidence(value: float) -> float:
    return max(0.0, min(1.0, value if isfinite(value) else 0.0))


class HierarchyLayerEvaluator:
    """Runs existing analytical engines as evidence producers, never as a publisher."""

    def __init__(self, *, configuration: HierarchyConfiguration | None = None, risk_builder: StructuralRiskInputBuilder | None = None) -> None:
        self.configuration = configuration or HierarchyConfiguration()
        self.regime_engine = RegimeEngine()
        self.liquidity_engine = LiquidityEngine()
        self.sweep_engine = LiquiditySweepEngine()
        self.zone_engine = SupplyDemandEngine()
        self.reclaim_engine = ReclaimEngine()
        self.structure_engine = MarketStructureEngine()
        self.risk_builder = risk_builder or StructuralRiskInputBuilder()
        self.adapter = CanonicalEvidenceAdapter()
        self._state: dict[str, _SymbolState] = {}

    def watching(self, symbol: str) -> bool:
        setup = self._state.get(symbol.upper(), _SymbolState()).setup_context
        return setup is not None and setup.state in {SetupState.WATCHING, SetupState.SETUP_CONFIRMED}

    def evaluate(self, symbol: str, snapshots: Mapping[str, TimeframeSnapshot], *, evaluated_at: datetime, macro_degraded: bool) -> ShadowEvaluation:
        normalized = symbol.upper()
        state = self._state.setdefault(normalized, _SymbolState())
        if state.snapshots is None:
            state.snapshots = {}
        state.snapshots.update(snapshots)
        self._expire_state(state, evaluated_at)
        reasons: list[str] = []

        macro_bucket = int(evaluated_at.timestamp()) // self.configuration.macro_refresh_seconds
        previous_bucket = state.macro_context.evidence.get("refresh_bucket") if state.macro_context else None
        macro_changed = state.macro_context is None or previous_bucket != macro_bucket
        if macro_changed:
            state.macro_context = self._macro_context(normalized, evaluated_at, macro_degraded, self._provenance(snapshots))

        regime_changed = False
        if macro_changed or "4h" in snapshots:
            regime_snapshot = state.snapshots.get("4h")
            market = self._market(regime_snapshot) if regime_snapshot is not None else None
            if market is None:
                reasons.append("4h_closed_candle_unavailable")
            else:
                assessment = self.regime_engine.assess(RegimeRequest(market))
                state.regime_assessment = assessment
                strategic = self._regime_state(assessment.state)
                previous_regime_id = state.regime_context.identity.context_id if state.regime_context else None
                state.regime_context = self._context(
                    "regime", regime_snapshot, state.macro_context, strategic,
                    self._direction(strategic), self._regime_confidence(assessment), evaluated_at, timedelta(hours=5),
                    {"regime": assessment.state.value, "score": assessment.score, "reasons": list(assessment.reasons)},
                )
                regime_changed = previous_regime_id != state.regime_context.identity.context_id
                if regime_changed:
                    state.strategy_context = None
                    state.setup_context = None
                    state.trigger_context = None

        strategy_changed = False
        if (regime_changed or "1h" in snapshots) and state.regime_context is not None and state.regime_assessment is not None:
            strategy_snapshot = state.snapshots.get("1h")
            layer = self._analyse_structure(strategy_snapshot, state.regime_assessment) if strategy_snapshot is not None else None
            if layer is None:
                reasons.append("1h_closed_candle_unavailable")
            else:
                strategic = self._strategy_state(layer, state.regime_assessment.state)
                previous_strategy_id = state.strategy_context.identity.context_id if state.strategy_context else None
                state.strategy_context = self._context(
                    "strategy", strategy_snapshot, state.regime_context, strategic,
                    self._direction(strategic), layer.structure.confidence, evaluated_at, timedelta(hours=2),
                    self._layer_evidence(layer),
                )
                strategy_changed = previous_strategy_id != state.strategy_context.identity.context_id
                if strategy_changed:
                    state.setup_context = None
                    state.trigger_context = None

        if (strategy_changed or "15m" in snapshots) and state.strategy_context is not None and state.regime_assessment is not None:
            setup_snapshot = state.snapshots.get("15m")
            layer = self._analyse_structure(setup_snapshot, state.regime_assessment) if setup_snapshot is not None else None
            if layer is None:
                reasons.append("15m_closed_candle_unavailable")
            else:
                setup_state, direction = self._setup_state(layer, state.strategy_context.state)
                previous_setup_id = state.setup_context.identity.context_id if state.setup_context else None
                state.setup_context = self._context(
                    "setup", setup_snapshot, state.strategy_context, setup_state,
                    direction, layer.structure.confidence, evaluated_at, timedelta(minutes=45),
                    self._layer_evidence(layer),
                )
                if previous_setup_id != state.setup_context.identity.context_id:
                    state.trigger_context = None

        bundle = None
        validation = None
        if "5m" in snapshots and state.setup_context is not None and state.setup_context.state is SetupState.SETUP_CONFIRMED and state.regime_assessment is not None:
            layer = self._analyse_structure(snapshots["5m"], state.regime_assessment)
            if layer is None:
                reasons.append("5m_closed_candle_unavailable")
            else:
                trigger_state = self._trigger_state(layer, state.setup_context.direction)
                state.trigger_context = self._context(
                    "trigger", snapshots["5m"], state.setup_context, trigger_state,
                    state.setup_context.direction, layer.structure.confidence, evaluated_at, timedelta(minutes=15),
                    self._layer_evidence(layer),
                )
                if trigger_state is TriggerState.TRIGGER_CONFIRMED:
                    try:
                        entry_layer = self._analyse_structure(snapshots["1m"], state.regime_assessment) if "1m" in snapshots else None
                        if entry_layer is None:
                            reasons.append("1m_closed_candle_unavailable")
                            raise ValueError("1m entry refinement is unavailable")
                        setup_snapshot = state.snapshots.get("15m") if state.snapshots is not None else None
                        stop_layer = self._analyse_structure(setup_snapshot, state.regime_assessment) if setup_snapshot is not None else None
                        if stop_layer is None:
                            reasons.append("15m_stop_structure_unavailable")
                            raise ValueError("15m stop structure is unavailable")
                        risk = self._risk(layer, state.trigger_context, evaluated_at, entry_layer=entry_layer, stop_layer=stop_layer)
                        bundle = EvidenceBundle.create(
                            symbol=normalized, created_at=evaluated_at, macro_context=state.macro_context,
                            regime_4h=state.regime_context, strategy_1h=state.strategy_context,
                            setup_15m=state.setup_context, trigger_5m=state.trigger_context,
                            risk_inputs=risk, strategy_version=self.configuration.strategy_version,
                        )
                        validation = self.adapter.validate(HierarchicalAnalysisRequest(normalized, bundle, evaluated_at))
                    except (TypeError, ValueError) as exc:
                        reasons.append(f"risk_proposal_rejected:{type(exc).__name__}")

        return ShadowEvaluation(normalized, evaluated_at, state.macro_context, state.regime_context, state.strategy_context, state.setup_context, state.trigger_context, bundle, validation, self.watching(normalized), tuple(reasons))

    @staticmethod
    def _expire_state(state: _SymbolState, now: datetime) -> None:
        if state.macro_context is not None and now >= state.macro_context.expires_at:
            state.macro_context = state.regime_context = state.strategy_context = state.setup_context = state.trigger_context = None
            state.regime_assessment = None
            return
        if state.regime_context is not None and now >= state.regime_context.expires_at:
            state.regime_context = state.strategy_context = state.setup_context = state.trigger_context = None
            state.regime_assessment = None
            return
        if state.strategy_context is not None and now >= state.strategy_context.expires_at:
            state.strategy_context = state.setup_context = state.trigger_context = None
        if state.setup_context is not None and now >= state.setup_context.expires_at:
            state.setup_context = state.trigger_context = None
        if state.trigger_context is not None and now >= state.trigger_context.expires_at:
            state.trigger_context = None

    def _macro_context(self, symbol: str, now: datetime, degraded: bool, provenance: Provenance) -> EvidenceContext:
        state = StrategicState.NEUTRAL
        refresh_bucket = int(now.timestamp()) // self.configuration.macro_refresh_seconds
        identity = EvidenceIdentity.create(kind="macro", symbol=symbol, timeframe="macro", candle_id=f"macro-{refresh_bucket}", parent_id=None, strategy_version=self.configuration.strategy_version)
        return EvidenceContext(identity, None, None, now, now + timedelta(seconds=self.configuration.macro_refresh_seconds * 2), state, "neutral", 0.0 if degraded else 0.5, DataQualityState.DEGRADED if degraded else DataQualityState.READY, provenance, {"degraded": degraded, "refresh_bucket": refresh_bucket})

    def _market(self, snapshot: TimeframeSnapshot) -> MarketSnapshot | None:
        finalized = tuple(item for item in snapshot.candles if item.is_final)
        if not finalized:
            return None
        candles = tuple(Candle(item.open_time.isoformat(), item.open, item.high, item.low, item.close, item.volume) for item in finalized)
        latest = finalized[-1]
        quality = DataQuality(DataStatus.READY, latest.provenance.provider, snapshot.observed_at, latest.scheduled_close_time, max(0.0, (snapshot.observed_at - latest.scheduled_close_time).total_seconds()))
        return MarketSnapshot(snapshot.symbol, snapshot.timeframe, latest.close, candles, quality, metadata={"latest_candle_id": latest.candle_id, "content_hash": latest.content_hash})

    def _analyse_structure(self, snapshot: TimeframeSnapshot, regime: Any) -> LayerAnalysis | None:
        market = self._market(snapshot)
        if market is None:
            return None
        liquidity = self.liquidity_engine.assess(LiquidityRequest(market, regime))
        sweep = self.sweep_engine.assess(SweepRequest(market, liquidity, regime))
        zones = self.zone_engine.assess(ZoneRequest(market, regime, liquidity))
        reclaim = self.reclaim_engine.assess(ReclaimRequest(market, sweep, regime, zones))
        structure = self.structure_engine.assess(MarketStructureRequest(market, regime, liquidity, sweep, reclaim, zones))
        return LayerAnalysis(market, liquidity, sweep, zones, reclaim, structure)

    def _context(self, kind: str, snapshot: TimeframeSnapshot, parent: EvidenceContext, state: Any, direction: str, confidence: float, now: datetime, lifetime: timedelta, evidence: dict[str, Any]) -> EvidenceContext:
        candle = snapshot.latest_finalized
        if candle is None:
            raise ValueError("context requires a finalized candle")
        identity = EvidenceIdentity.create(kind=kind, symbol=snapshot.symbol, timeframe=snapshot.timeframe, candle_id=candle.candle_id, parent_id=parent.identity.context_id, strategy_version=self.configuration.strategy_version)
        return EvidenceContext(identity, candle.open_time, candle.scheduled_close_time, now, now + lifetime, state, direction, _confidence(confidence), DataQualityState.READY, candle.provenance, evidence)

    @staticmethod
    def _regime_state(regime: RegimeState) -> StrategicState:
        if regime is RegimeState.TREND_UP:
            return StrategicState.LONG_ONLY
        if regime is RegimeState.TREND_DOWN:
            return StrategicState.SHORT_ONLY
        if regime in {RegimeState.RANGE, RegimeState.COMPRESSION}:
            return StrategicState.NEUTRAL
        if regime in {RegimeState.UNSTABLE, RegimeState.UNKNOWN}:
            return StrategicState.BLOCKED
        return StrategicState.NEUTRAL

    @staticmethod
    def _strategy_state(layer: LayerAnalysis, regime: RegimeState) -> StrategicState:
        if regime in {RegimeState.UNSTABLE, RegimeState.UNKNOWN}:
            return StrategicState.BLOCKED
        if regime in {RegimeState.RANGE, RegimeState.COMPRESSION}:
            return StrategicState.NEUTRAL
        if layer.structure.bias is StructureBias.BULLISH:
            return StrategicState.LONG_ONLY
        if layer.structure.bias is StructureBias.BEARISH:
            return StrategicState.SHORT_ONLY
        return StrategicState.NEUTRAL

    @staticmethod
    def _setup_state(layer: LayerAnalysis, strategic: Any) -> tuple[SetupState, str]:
        if strategic in {StrategicState.BLOCKED, StrategicState.NEUTRAL}:
            return SetupState.NO_SETUP, "neutral"
        expected = "long" if strategic is StrategicState.LONG_ONLY else "short"
        bias_aligned = (expected == "long" and layer.structure.bias is StructureBias.BULLISH) or (expected == "short" and layer.structure.bias is StructureBias.BEARISH)
        # A confirmed sweep and a confirmed reclaim are alternative forms of
        # 15m displacement evidence. Requiring both suppressed otherwise clean
        # setups before the mandatory 5m trigger could evaluate them.
        displacement_confirmed = layer.sweep.has_confirmed_sweep or layer.reclaim.has_confirmed_reclaim
        if displacement_confirmed and bias_aligned:
            return SetupState.SETUP_CONFIRMED, expected
        if layer.sweep.has_possible_sweep or layer.sweep.has_confirmed_sweep or layer.zones.price_inside_zone:
            return SetupState.WATCHING, expected
        return SetupState.NO_SETUP, expected

    @staticmethod
    def _trigger_state(layer: LayerAnalysis, direction: str) -> TriggerState:
        aligned = (direction == "long" and layer.structure.bias is StructureBias.BULLISH) or (direction == "short" and layer.structure.bias is StructureBias.BEARISH)
        if aligned and (layer.reclaim.has_confirmed_reclaim or layer.structure.has_confirmed_break):
            return TriggerState.TRIGGER_CONFIRMED
        return TriggerState.TRIGGER_REJECTED

    def _risk(self, layer: LayerAnalysis, trigger: EvidenceContext, now: datetime, *, entry_layer: LayerAnalysis | None = None, stop_layer: LayerAnalysis | None = None):
        direction = trigger.direction
        if direction not in {"long", "short"}:
            raise ValueError("directional risk proposal requires long or short direction")
        refinement = entry_layer or layer
        stop_structure = stop_layer or layer
        price = refinement.market.price
        if price is None:
            raise ValueError("current price is unavailable")
        if direction == "long":
            zone = refinement.zones.active_demand or refinement.zones.nearest_demand
            swing = stop_structure.structure.swing_lows[-1][1] if stop_structure.structure.swing_lows else min(item.low for item in stop_structure.market.candles[-10:])
            target = layer.liquidity.nearest_buy_side.price if layer.liquidity.nearest_buy_side else max(item.high for item in layer.market.candles[-20:])
        else:
            zone = refinement.zones.active_supply or refinement.zones.nearest_supply
            swing = stop_structure.structure.swing_highs[-1][1] if stop_structure.structure.swing_highs else max(item.high for item in stop_structure.market.candles[-10:])
            target = layer.liquidity.nearest_sell_side.price if layer.liquidity.nearest_sell_side else min(item.low for item in layer.market.candles[-20:])
        low, high = (zone.lower_bound, zone.upper_bound) if zone is not None else (price * 0.999, price * 1.001)
        atr = self._atr(refinement.market.candles)
        reference_entry = min(max(price, low), high)
        return self.risk_builder.build(direction=direction, entry_zone_low=low, entry_zone_high=high, structural_invalidation=swing, target_liquidity=target, atr=atr, movement_tolerance_pct=0.002, expires_at=now + timedelta(minutes=15), reference_entry=reference_entry)

    @staticmethod
    def _atr(candles: tuple[Candle, ...], window: int = 14) -> float:
        recent = candles[-max(2, window + 1):]
        ranges = []
        for previous, current in zip(recent, recent[1:]):
            ranges.append(max(current.high - current.low, abs(current.high - previous.close), abs(current.low - previous.close)))
        if not ranges:
            raise ValueError("ATR requires at least two candles")
        return sum(ranges[-window:]) / len(ranges[-window:])

    @staticmethod
    def _regime_confidence(assessment: Any) -> float:
        return {"high": 0.9, "medium": 0.7, "low": 0.4, "none": 0.0}.get(assessment.confidence.value, 0.0)

    @staticmethod
    def _direction(state: StrategicState) -> str:
        return "long" if state is StrategicState.LONG_ONLY else "short" if state is StrategicState.SHORT_ONLY else "neutral"

    @staticmethod
    def _layer_evidence(layer: LayerAnalysis) -> dict[str, Any]:
        return {
            "regime": layer.structure.metadata.get("regime"),
            "structure_bias": layer.structure.bias.value,
            "structure_state": layer.structure.state.value,
            "confirmed_break": layer.structure.has_confirmed_break,
            "confirmed_sweep": layer.sweep.has_confirmed_sweep,
            "possible_sweep": layer.sweep.has_possible_sweep,
            "confirmed_reclaim": layer.reclaim.has_confirmed_reclaim,
            "price_inside_zone": layer.zones.price_inside_zone,
            "liquidity_balanced": layer.liquidity.balanced,
        }

    @staticmethod
    def _provenance(snapshots: Mapping[str, TimeframeSnapshot]) -> Provenance:
        for snapshot in snapshots.values():
            if snapshot.candles:
                return snapshot.candles[-1].provenance
        return Provenance("unknown", "unknown", "unknown", "unknown", "hierarchy-candle-v1")
