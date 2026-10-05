"""Versioned XAU/USD shadow analysis; no provider can grant order authority."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from math import isfinite

from monatise.application.hierarchy.assets import AssetHierarchyAnalysis, _timestamp
from monatise.application.hierarchy.broker_candles import is_xauusd
from monatise.application.hierarchy.evaluator import HierarchyLayerEvaluator
from monatise.application.hierarchy.models import SetupState, TriggerState
from monatise.application.hierarchy.policy import INTERVAL_SECONDS


@dataclass(frozen=True)
class GoldPolicy:
    strategy: str = "gold-sweep-reversal-technical-v1"
    version: str = "xauusd-technical-v1"
    required_sources: tuple[str, ...] = ("broker_candles",)
    minimum_groups: int = 3

    def __post_init__(self):
        contracts = {
            "gold-sweep-reversal-technical-v1": ("broker_candles",),
            "gold-sweep-reversal-gc-v1": ("broker_candles", "gc_futures"),
            "gold-sweep-reversal-options-v1": (
                "broker_candles",
                "gc_futures",
                "gold_options",
                "basis",
            ),
        }
        if (
            self.version != "xauusd-technical-v1"
            or contracts.get(self.strategy) != self.required_sources
            or self.minimum_groups != 3
        ):
            raise ValueError("unknown or modified Gold strategy contract")


def sweep_reversal(candles, direction: str, timeframe: str) -> dict:
    """A causal contract: pivots are confirmed BEFORE the sweep is considered.

    Prior 2-sided, two-bar liquidity pivot -> sweep and rejection close ->
    later displacement and break of opposing pre-existing structure -> later
    holding retest. All supplied rows must already be finalized. No labels or
    retrospective pivots participate. Search only the latest 12 sweep bars.
    """
    failure = {"confirmed": False, "reason": "ordered_sweep_reversal_unconfirmed"}
    if direction not in {"long", "short"} or len(candles) < 12:
        return failure
    long = direction == "long"
    for sweep in range(max(6, len(candles) - 12), len(candles) - 2):
        prior = candles[:sweep]
        lows, highs = [], []
        for i in range(2, len(prior) - 2):
            neighbors = prior[i - 2 : i] + prior[i + 1 : i + 3]
            if prior[i].low < min(c.low for c in neighbors):
                lows.append((i, prior[i].low))
            if prior[i].high > max(c.high for c in neighbors):
                highs.append((i, prior[i].high))
        liquidity = lows if long else highs
        opposing = highs if long else lows
        if not liquidity or not opposing:
            continue
        li, level = liquidity[-1]
        oi, shift = opposing[-1]
        bar = candles[sweep]
        rejection = (
            bar.low < level < bar.close if long else bar.high > level > bar.close
        )
        if not rejection:
            continue
        for break_index in range(sweep + 1, len(candles) - 1):
            b = candles[break_index]
            span = b.high - b.low
            displacement = span > 0 and abs(b.close - b.open) / span >= 0.55
            crosses = (
                b.close > max(shift, b.open) if long else b.close < min(shift, b.open)
            )
            if not displacement or not crosses:
                continue
            for retest in range(break_index + 1, min(len(candles), break_index + 4)):
                r = candles[retest]
                held = r.low <= shift <= r.close if long else r.high >= shift >= r.close
                # Subsequent closes must hold the reclaimed structure and the
                # original structural invalidation remains intact.
                intact = (
                    all(c.close >= shift and c.low > bar.low for c in candles[retest:])
                    if long
                    else all(
                        c.close <= shift and c.high < bar.high for c in candles[retest:]
                    )
                )
                if not held or not intact:
                    continue
                start = min(li, oi)
                seconds = INTERVAL_SECONDS[timeframe]
                if any(
                    (
                        _timestamp(candles[i].timestamp)
                        - _timestamp(candles[i - 1].timestamp)
                    ).total_seconds()
                    != seconds
                    for i in range(start + 1, len(candles))
                ):
                    return {
                        "confirmed": False,
                        "reason": "pattern_crosses_gap_or_session_boundary",
                    }
                return {
                    "confirmed": True,
                    "direction": direction,
                    "liquidity_index": li,
                    "liquidity_level": level,
                    "sweep_index": sweep,
                    "rejection_index": sweep,
                    "displacement_index": break_index,
                    "shift_index": break_index,
                    "shift_level": shift,
                    "retest_index": retest,
                    "retest_close": (
                        _timestamp(r.timestamp) + timedelta(seconds=seconds)
                    ).isoformat(),
                    "structural_invalidation": bar.low if long else bar.high,
                }
    return failure


class _MarketAwareEngine:
    """Reuse audited candle mathematics with explicit instrument scope metadata."""

    def __init__(self, engine):
        self.engine = engine

    def assess(self, request):
        output = self.engine.assess(request)
        return replace(
            output,
            metadata={
                **output.metadata,
                "engine_scope": "broker_xauusd_candles",
                "algorithm_origin": "canonical_candle_engine",
                "volume_kind": "tick_volume",
            },
        )


class GoldLayerEvaluator(HierarchyLayerEvaluator):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        for attr in (
            "regime_engine",
            "liquidity_engine",
            "sweep_engine",
            "zone_engine",
            "reclaim_engine",
            "structure_engine",
        ):
            setattr(self, attr, _MarketAwareEngine(getattr(self, attr)))
        self.multi_tp = replace(
            self.multi_tp,
            enabled=True,
            routes=tuple(set(self.multi_tp.routes) | {"gold"}),
            minimum_rr=max(self.multi_tp.minimum_rr, Decimal("1.5")),
        )
        self.broker_units = None

    def _setup_state(self, layer, strategic):
        state, direction = super()._setup_state(layer, strategic)
        pattern = sweep_reversal(layer.market.candles, direction, "15m")
        if state is SetupState.SETUP_CONFIRMED and pattern["confirmed"]:
            return state, direction
        return (
            SetupState.WATCHING if state is not SetupState.NO_SETUP else state
        ), direction

    def _trigger_state(self, layer, direction):
        state = super()._trigger_state(layer, direction)
        # A current, aligned M5 structural break/reclaim must occur AFTER the
        # M15 setup retest, rather than reusing a historical CHoCH.
        parent = self._state[layer.market.symbol.upper()].setup_context
        retest = (
            parent.evidence.get("gold_pattern", {}).get("retest_close")
            if parent
            else None
        )
        events = [e for e in layer.structure.events if e.confirmed]
        if not retest or not events:
            return TriggerState.TRIGGER_REJECTED
        latest = events[-1]
        closes = _timestamp(
            layer.market.candles[latest.candle_index].timestamp
        ) + timedelta(minutes=5)
        pivots = (
            layer.structure.swing_highs
            if direction == "long"
            else layer.structure.swing_lows
        )
        causal = any(
            index + 3 < latest.candle_index and level == latest.level
            for index, level in pivots
        )
        if (
            not causal
            or closes <= _timestamp(retest)
            or latest.candle_index < len(layer.market.candles) - 3
        ):
            return TriggerState.TRIGGER_REJECTED
        return state

    def _layer_evidence(self, layer):
        evidence = super()._layer_evidence(layer)
        if layer.market.interval == "15m":
            direction = (
                "long"
                if layer.structure.bias.value == "bullish"
                else "short"
                if layer.structure.bias.value == "bearish"
                else "none"
            )
            evidence["gold_pattern"] = sweep_reversal(
                layer.market.candles, direction, "15m"
            )
        return evidence

    def _context(
        self,
        kind,
        snapshot,
        parent,
        state,
        direction,
        confidence,
        now,
        lifetime,
        evidence,
    ):
        context = super()._context(
            kind,
            snapshot,
            parent,
            state,
            direction,
            confidence,
            now,
            lifetime,
            evidence,
        )
        # Gold context lifetime binds to the original finalized candle. Reading
        # the same bar again cannot renew any parent proof.
        expiry = min(
            context.expires_at, context.source_close_time + lifetime, parent.expires_at
        )
        if kind == "setup" and evidence.get("gold_pattern", {}).get("confirmed"):
            expiry = min(
                expiry, _timestamp(evidence["gold_pattern"]["retest_close"]) + lifetime
            )
        if expiry <= now:
            raise ValueError("gold_parent_or_pattern_expired")
        return replace(context, expires_at=expiry)

    def _risk(self, layer, trigger, now, *, entry_layer=None, stop_layer=None):
        if self.broker_units is None:
            raise ValueError("gold_broker_units_unavailable")
        if entry_layer is None or stop_layer is None:
            raise ValueError("gold_entry_or_stop_structure_unavailable")
        zone = (
            (entry_layer.zones.active_demand or entry_layer.zones.nearest_demand)
            if trigger.direction == "long"
            else (entry_layer.zones.active_supply or entry_layer.zones.nearest_supply)
        )
        if zone is None:
            raise ValueError("gold_entry_zone_unavailable")
        risk = super()._risk(
            layer, trigger, now, entry_layer=entry_layer, stop_layer=stop_layer
        )
        pattern = sweep_reversal(stop_layer.market.candles, trigger.direction, "15m")
        if not pattern["confirmed"]:
            raise ValueError("gold_stop_pattern_unavailable")
        point, tick, spread = (
            Decimal(str(self.broker_units[k]))
            for k in ("point", "tick_size", "spread_price")
        )
        structural = Decimal(str(pattern["structural_invalidation"]))
        buffer = (
            max(point, tick, Decimal(str(risk.volatility_buffer)))
            + max(spread, Decimal(str(risk.estimated_spread_allowance)))
            + Decimal(str(risk.estimated_slippage_allowance))
        )
        stop = (
            structural - buffer if trigger.direction == "long" else structural + buffer
        )
        stop = (stop / tick).to_integral_value(
            rounding=ROUND_FLOOR if trigger.direction == "long" else ROUND_CEILING
        ) * tick
        entry, target = (
            Decimal(str(risk.reference_entry)),
            Decimal(str(risk.target_liquidity)),
        )
        distance, reward = (
            (entry - stop, target - entry)
            if trigger.direction == "long"
            else (stop - entry, entry - target)
        )
        if distance <= 0 or reward <= 0:
            raise ValueError("invalid_stop_target_geometry")
        return replace(
            risk,
            structural_invalidation=float(structural),
            final_stop=float(stop),
            calculated_reward_to_risk=float(reward / distance),
            expires_at=min(risk.expires_at, trigger.expires_at),
        )


class GoldHierarchyAnalysis(AssetHierarchyAnalysis):
    def __init__(self, *, policy=None, **kwargs):
        super().__init__(evaluator_factory=GoldLayerEvaluator, **kwargs)
        self.configuration = replace(
            self.configuration,
            strategy_version=(policy or GoldPolicy()).strategy,
            always_collect_5m=True,
        )

    async def _batch(self, instrument, now):
        batch, close, provenance, calendar = await super()._batch(instrument, now)
        if close <= now:
            raise ValueError("gold_broker_session_closed")
        units = {k: provenance.get(k) for k in ("point", "tick_size", "spread_price")}
        if any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not isfinite(v)
            or (v < 0 if k == "spread_price" else v <= 0)
            for k, v in units.items()
        ):
            raise ValueError("gold_broker_units_unavailable")
        self._engines[instrument.ftmo_symbol][2].broker_units = units
        return batch, close, provenance, calendar

    async def _analyse(self, instrument, *, context, now):
        result = await super()._analyse(instrument, context={}, now=now)
        # This runs before AssetHierarchyAnalysis can persist an approval proof.
        groups = {
            "structure": result.get("market_structure", {}).get("structure_bias")
            in {"bullish", "bearish"},
            "liquidity": bool(
                result.get("liquidity", {}).get("gold_pattern", {}).get("confirmed")
            ),
            "value": False,  # Fib/reclaim/location remain advisory, no repeated vote.
            "confirmation": bool(result.get("trigger", {}).get("confirmed_break")),
        }
        qualified = bool(result.get("publication_valid")) and all(
            groups[g] for g in ("structure", "liquidity", "confirmation")
        )
        bias = result.get("market_structure", {}).get("structure_bias")
        count = sum(groups.values()) if bias is not None else None
        score = (
            count * (1 if bias == "bullish" else -1 if bias == "bearish" else 0)
            if count is not None
            else None
        )
        result.update(
            signal_core_evidence=groups,
            score_components=groups,
            signal_core_score=count,
            score=score,
            score_scale=3,
            conviction=None,
            technical_bias=bias or "unavailable",
            score_meaning="Independent mandatory evidence groups; not win probability",
        )
        result.update(
            analytical_qualified=qualified,
            publication_valid=False,
            publication_eligible=False,
            approval_eligible=False,
            pending_order_eligible=False,
            execution_eligible=False,
            approval_blocking_reasons=["gold_shadow_policy_not_released"],
            assessment_mode="replay" if now else "shadow",
            live_certified=False,
            timeframe_policy="xauusd-technical-v1",
        )
        if (
            result.get("market_data_provenance", {}).get("timestamp_policy")
            == "current_offset_uncertified_history"
        ):
            result["analytical_qualified"] = False
            result.setdefault("reasons", []).append("gold_history_timezone_uncertified")
        proof = result.get("evidence_bundle")
        if proof:
            proof["timeframe_policy"] = "xauusd-technical-v1"
        return result


class GoldAnalysisCoordinator:
    def __init__(
        self,
        *,
        master=None,
        environment=None,
        technical=None,
        gc_provider=None,
        options_provider=None,
        basis_provider=None,
        policy=None,
    ):
        self.policy = policy or GoldPolicy()
        self.technical = technical or GoldHierarchyAnalysis(
            master=master, environment=environment, policy=self.policy
        )
        self.providers = {
            "gc_futures": gc_provider,
            "gold_options": options_provider,
            "basis": basis_provider,
        }
        self._locks = {}
        self._qualified = {}
        self._expired = set()

    async def _optional(self, name, provider, instrument, now):
        if provider is None:
            return {"status": "unavailable", "reason": "not_configured"}
        try:
            async with asyncio.timeout(2):
                value = await provider.snapshot(instrument, now=now)
            if not isinstance(value, dict) or value.get("status") != "usable":
                return {
                    "status": "unavailable",
                    "reason": "invalid_or_unavailable_snapshot",
                }
            if (
                value.get("symbol") != instrument.ftmo_symbol
                or value.get("strategy_version") != self.policy.version
            ):
                return {"status": "unavailable", "reason": "snapshot_identity_mismatch"}
            if not _timestamp(value["as_of"]) <= now < _timestamp(value["expires_at"]):
                return {"status": "unavailable", "reason": "stale_or_future_snapshot"}
            if name == "gold_options" and value.get("gil_state") not in {
                "CERTIFIED",
                "CONFIRMED",
            }:
                return {"status": "unavailable", "reason": "gold_options_quarantined"}
            return value
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - isolate optional providers; never expose exception payloads
            return {"status": "unavailable", "reason": type(exc).__name__}

    async def analyse(self, instrument, *, now=None, reference=None):
        if not is_xauusd(instrument):
            raise ValueError("Gold coordinator requires registered XAU/USD")
        async with self._locks.setdefault(instrument.ftmo_symbol, asyncio.Lock()):
            try:
                result = await self.technical.analyse(instrument, context={}, now=now)
                current = now or datetime.now(UTC)
                evidence = dict(
                    zip(
                        self.providers,
                        await asyncio.gather(
                            *(
                                self._optional(name, provider, instrument, current)
                                for name, provider in self.providers.items()
                            )
                        ),
                    )
                )
                missing = [
                    name
                    for name in self.policy.required_sources
                    if name != "broker_candles" and evidence[name]["status"] != "usable"
                ]
                qualified = bool(result.get("analytical_qualified")) and not missing
                reasons = list(result.get("reasons") or []) + [
                    f"required_{name}_unavailable" for name in missing
                ]
                identity = result.get("setup_id")
                if qualified and not identity:
                    qualified = False
                    reasons.append("gold_setup_identity_unavailable")
                if qualified and identity:
                    expiry = _timestamp(result["expires_at"])
                    for source in self.policy.required_sources:
                        if source != "broker_candles":
                            expiry = min(
                                expiry, _timestamp(evidence[source]["expires_at"])
                            )
                    key = (self.policy.strategy, identity)
                    expiry = min(expiry, self._qualified.get(key, expiry))
                    if key in self._expired or current >= expiry:
                        qualified = False
                        reasons.append("gold_setup_expired_or_invalidated")
                    elif key not in self._qualified and len(self._qualified) >= 512:
                        qualified = False
                        reasons.append("gold_lifecycle_capacity_exceeded")
                    else:
                        for prior in self._qualified:
                            if prior != key and prior[0] == self.policy.strategy:
                                self._expired.add(prior)
                        self._qualified[key] = expiry
                        for field in ("expires_at", "valid_until", "setup_expires_at"):
                            result[field] = expiry.isoformat()
                if not qualified and any(
                    key[0] == self.policy.strategy for key in self._qualified
                ):
                    for key in list(self._qualified):
                        if key[0] == self.policy.strategy:
                            self._expired.add(key)
                    await self.technical.invalidate(instrument)
                result.update(
                    strategy=self.policy.strategy,
                    gold_policy_version=self.policy.version,
                    required_evidence=list(self.policy.required_sources),
                    optional_evidence=evidence,
                    analytical_qualified=qualified,
                    reasons=reasons,
                    publication_valid=False,
                    publication_eligible=False,
                    approval_eligible=False,
                    execution_eligible=False,
                    pending_order_eligible=False,
                    execution={"enabled": False, "orders_placed": 0},
                )
                if not qualified and missing:
                    result.update(
                        setup_status="required_evidence_unavailable",
                        decision="NO_TRADE",
                    )
                if reference:
                    result["tradingview_reference"] = {
                        "symbol": reference.get("symbol"),
                        "reference_only": True,
                    }
                return result
            except asyncio.CancelledError:
                await self.technical.invalidate(instrument)
                raise
