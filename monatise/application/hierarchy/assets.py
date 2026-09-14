"""Stock and index adapters for the unchanged crypto hierarchy evaluator."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from monatise.application.hierarchy.approval import SIGNALS, CURRENT
from monatise.application.hierarchy.broker_candles import BrokerCandleService, is_index
from monatise.application.hierarchy.coordinator import (
    HierarchyConfiguration,
    ShadowHierarchyCoordinator,
)
from monatise.application.hierarchy.evaluator import HierarchyLayerEvaluator
from monatise.application.hierarchy.lifecycle import HierarchyRepository
from monatise.application.hierarchy.models import Provenance
from monatise.application.hierarchy.policy import (
    SHARED_TIMEFRAME_POLICY as POLICY,
    INTERVAL_SECONDS,
)
from monatise.application.hierarchy.risk import StructuralRiskInputBuilder
from monatise.application.hierarchy.service import ShadowHierarchyService
from monatise.application.take_profit import (
    MultiTPConfiguration,
    plan_fields,
    route_for,
)
from monatise.core.models import Candle
from monatise.engines.fibonacci_liquidity import (
    FibonacciLiquidityEngine,
    FibonacciRequest,
)


class _ReadOnlyRepository:
    """Standalone analysis has no durable publication/approval capability."""

    async def record_candle_revision(self, **kwargs):
        pass


class _BatchProvider:
    def __init__(self):
        self.rows = {}

    def candles(self, symbol, limit, interval):
        return self.rows[interval][-limit:]


def alpaca_timeframe(timeframe: str) -> str:
    seconds = INTERVAL_SECONDS[timeframe]
    return f"{seconds // 3600}Hour" if seconds >= 3600 else f"{seconds // 60}Min"


def _timestamp(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("candle timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def _candles(rows: Any, timeframe: str, now: datetime) -> list[Candle]:
    if not isinstance(rows, list) or len(rows) < 50:
        raise ValueError(f"{timeframe}_candles_incomplete")
    candles = []
    previous = None
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("malformed candle")
        values = [row.get(key) for key in ("o", "h", "l", "c", "v")]
        if any(isinstance(value, bool) or value is None for value in values):
            raise ValueError("candle OHLCV is incomplete")
        candle = Candle(str(row["t"]), *map(float, values))
        candle.validate()
        opened = _timestamp(candle.timestamp)
        if opened > now or (previous is not None and opened <= previous):
            raise ValueError("candle timestamps are future, duplicate or unordered")
        previous = opened
        candles.append(candle)
    closed = [
        c
        for c in candles
        if _timestamp(c.timestamp) + timedelta(seconds=INTERVAL_SECONDS[timeframe] + 10)
        <= now
    ]
    if len(closed) < 50:
        raise ValueError(f"{timeframe}_closed_candles_incomplete")
    age = (
        now
        - _timestamp(closed[-1].timestamp)
        - timedelta(seconds=INTERVAL_SECONDS[timeframe])
    ).total_seconds()
    if age > INTERVAL_SECONDS[timeframe] * 2:
        raise ValueError(f"{timeframe}_candles_stale")
    return candles


class AssetHierarchyAnalysis:
    def __init__(
        self,
        *,
        alpaca: Any = None,
        master: Any = None,
        environment: Mapping[str, str] | None = None,
    ):
        self.alpaca, self.master = alpaca, master
        self.environment = environment or {}
        self.configuration = replace(
            HierarchyConfiguration.from_environment(self.environment),
            enabled=True,
            telegram_publish_enabled=False,
        )
        self.repository = (
            HierarchyRepository(master.repository.store)
            if master is not None
            else _ReadOnlyRepository()
        )
        self._engines = {}
        self._closed_values = {}
        self._locks = {}
        self._previous_signal = {}

    async def invalidate(self, instrument: Any) -> None:
        self._engines.pop(instrument.ftmo_symbol, None)
        self._closed_values.pop(instrument.ftmo_symbol, None)
        if self.master is not None:
            await self.master.repository.store.put(
                CURRENT,
                instrument.ftmo_symbol,
                {"state": "invalidated", "bundle_id": None},
            )

    async def _batch(
        self, instrument: Any, now: datetime
    ) -> tuple[dict, datetime, dict]:
        if is_index(instrument):
            if self.master is None:
                raise ValueError(
                    "index_candles_unavailable: authenticated MT5 bridge required"
                )
            batch = await BrokerCandleService(self.master).fetch(
                instrument, self.configuration.candle_limit
            )
            if not batch.get("session_open") or str(batch.get("trade_mode")) != "4":
                raise ValueError("broker_session_closed_or_break")
            close = _timestamp(batch.get("session_close"))
            return (
                batch["timeframes"],
                close,
                {
                    "provider": "ftmo_mt5",
                    "instrument": instrument.ftmo_symbol,
                    "captured_at": batch["captured_at"],
                    "volume_kind": "tick_volume",
                    "broker_time_offset": batch.get("broker_time_offset"),
                },
            )
        if self.alpaca is None or instrument.exchange not in {"NASDAQ", "NYSE"}:
            raise ValueError("stock_candle_provider_unsupported")
        day = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        if not callable(getattr(self.alpaca, "market_calendar", None)):
            raise ValueError("stock_calendar_unavailable")
        calendar = await asyncio.to_thread(self.alpaca.market_calendar, day)
        row = next((item for item in calendar if item.get("date") == day), None)
        if row is None:
            raise ValueError("stock_exchange_closed")
        zone = ZoneInfo("America/New_York")
        opened = (
            datetime.fromisoformat(f"{day}T{row['open']}")
            .replace(tzinfo=zone)
            .astimezone(timezone.utc)
        )
        close = (
            datetime.fromisoformat(f"{day}T{row['close']}")
            .replace(tzinfo=zone)
            .astimezone(timezone.utc)
        )
        if not opened <= now < close:
            raise ValueError("stock_regular_session_closed")
        # Stock candle history can contain overnight gaps. Never fabricate
        # missing bars; the latest closed bar on each layer must still be fresh.
        values = await asyncio.gather(
            *(
                asyncio.to_thread(
                    self.alpaca.stock_bars,
                    instrument.provider_symbol or instrument.underlying_symbol,
                    alpaca_timeframe(tf),
                    self.configuration.candle_limit,
                )
                for tf in POLICY.timeframes
            )
        )
        return (
            dict(zip(POLICY.timeframes, values)),
            close,
            {
                "provider": "alpaca",
                "instrument": instrument.provider_symbol
                or instrument.underlying_symbol,
                "feed": getattr(self.alpaca, "feed", "unknown"),
            },
        )

    async def analyse(
        self,
        instrument: Any,
        *,
        context: dict | None = None,
        now: datetime | None = None,
    ) -> dict:
        symbol = instrument.ftmo_symbol
        lock = self._locks.setdefault(symbol, asyncio.Lock())
        async with lock:
            current_record = (
                await self.master.repository.store.get(CURRENT, symbol)
                if self.master is not None
                else None
            )
            try:
                async with asyncio.timeout(75):
                    result = await self._analyse(
                        instrument, context=context or {}, now=now
                    )
            except asyncio.CancelledError:
                await self.invalidate(instrument)
                raise
            except TimeoutError:
                await self.invalidate(instrument)
                return {
                    **POLICY.metadata(),
                    "asset": instrument.underlying_symbol,
                    "ftmo_symbol": symbol,
                    "decision": "INSUFFICIENT_MARKET_DATA",
                    "setup_status": "insufficient_market_data",
                    "publication_valid": False,
                    "reason_code": "hierarchy_analysis_timeout",
                    "reasons": ["hierarchy_analysis_timeout"],
                    "analysis_sources": [],
                }
            if self.master is not None:
                store = self.master.repository.store
                proof = result.get("evidence_bundle")
                if result.get("publication_valid") and proof:
                    prior = await store.get(SIGNALS, proof["bundle_id"])
                    expiry = result["expires_at"]
                    if prior:
                        if (
                            prior.value["evidence"] != proof
                            or prior.value.get("market_price_observation")
                            != result.get("market_price_observation")
                            or any(
                                str(prior.value[key]) != str(result[field])
                                for key, field in (
                                    ("entry", "entry"),
                                    ("stop", "stop_loss"),
                                    ("target", "target"),
                                )
                            )
                        ):
                            await self.invalidate(instrument)
                            return {
                                **result,
                                "publication_valid": False,
                                "decision": "NO_TRADE",
                                "setup_status": "invalidated",
                                "reasons": ["confirmed_hierarchy_changed"],
                            }
                        expiry = min(expiry, prior.value["expires_at"])
                    if result.get("take_profit_plan"):
                        result["take_profit_plan"]["expires_at"] = expiry
                    try:
                        await store.put(
                            SIGNALS,
                            proof["bundle_id"],
                            {
                                "evidence": proof,
                                "expires_at": expiry,
                                "symbol": symbol,
                                "direction": result["direction"],
                                "entry": result["entry"],
                                "stop": result["stop_loss"],
                                "target": result["target"],
                                "take_profit_plan": result.get("take_profit_plan"),
                                "market_price_observation": result[
                                    "market_price_observation"
                                ],
                            },
                            expected_version=prior.version if prior else 0,
                        )
                        await store.put(
                            CURRENT,
                            symbol,
                            {"state": "valid", "bundle_id": proof["bundle_id"]},
                            expected_version=current_record.version
                            if current_record
                            else 0,
                        )
                    except RuntimeError:
                        # A concurrent analysis/invalidation wins. Do not let
                        # an older observation restore its previous setup.
                        result.update(
                            publication_valid=False,
                            decision="NO_TRADE",
                            setup_status="invalidated",
                            reasons=["hierarchy_persistence_conflict"],
                        )
                        self._engines.pop(symbol, None)
                        return result
                    for key in ("expires_at", "valid_until", "setup_expires_at"):
                        result[key] = expiry
                elif result.get("reasons") != ["awaiting_next_closed_candle"]:
                    await store.put(
                        CURRENT, symbol, {"state": "invalidated", "bundle_id": None}
                    )
            return result

    async def _analyse(
        self, instrument: Any, *, context: dict, now: datetime | None
    ) -> dict:
        observed = now or datetime.now(timezone.utc)
        symbol = instrument.ftmo_symbol
        route = route_for(instrument)
        provider = "ftmo_mt5" if is_index(instrument) else "alpaca"
        result = {
            **POLICY.metadata(),
            "asset": instrument.underlying_symbol,
            "ftmo_symbol": symbol,
            "asset_class": instrument.asset_class.value,
            "analysis_provider": provider,
            "analysis_instrument": symbol
            if is_index(instrument)
            else instrument.provider_symbol or instrument.underlying_symbol,
            "analysis_exchange": instrument.exchange,
            "decision": "NO_TRADE",
            "direction": "NONE",
            "score": 0,
            "score_threshold": 3,
            "signal_core_score": 0,
            "setup_status": "not_confirmed",
            "publication_valid": False,
            "execution": {"enabled": False, "orders_placed": 0},
            "generated_at": observed.isoformat(),
            "strategy": self.configuration.strategy_version,
            "analysis_sources": [],
            "ftmo_execution_quote": {
                "provider": "ftmo_mt5",
                "status": "not_requested",
                "reason": "awaiting_qualification",
            },
        }
        try:
            if symbol not in self._engines:
                batch_provider = _BatchProvider()
                provenance = Provenance(
                    provider,
                    instrument.exchange,
                    result["analysis_instrument"],
                    "v1",
                    "hierarchy-candle-v1",
                )
                coordinator = ShadowHierarchyCoordinator(
                    batch_provider,
                    self.repository,
                    configuration=self.configuration,
                    provenance=provenance,
                )
                minimum_rr = (
                    max(
                        Decimal("1.5"),
                        Decimal(
                            self.environment.get(
                                "MONATISE_STOCK_MINIMUM_REWARD_RISK", "1.5"
                            )
                        ),
                    )
                    if route == "stocks"
                    else Decimal("1.5")
                )
                multi_tp = MultiTPConfiguration.from_environment(self.environment)
                multi_tp = replace(
                    multi_tp, minimum_rr=max(multi_tp.minimum_rr, minimum_rr)
                )
                evaluator = HierarchyLayerEvaluator(
                    configuration=self.configuration,
                    risk_builder=StructuralRiskInputBuilder(
                        minimum_reward_to_risk=float(minimum_rr)
                    ),
                    multi_tp=multi_tp,
                    asset_route=route,
                )
                self._engines[symbol] = batch_provider, coordinator, evaluator
            batch_provider, coordinator, evaluator = self._engines[symbol]
            evaluation = None
            session_close = None
            # Two independent provider observations retain crypto's closed-bar
            # confirmation rule. Entry layers remain dormant until setup watch.
            for attempt in range(4):
                current = now or datetime.now(timezone.utc)
                batch, session_close, provenance = await self._batch(
                    instrument, current
                )
                current = now or datetime.now(timezone.utc)
                batch_provider.rows = {
                    tf: _candles(batch[tf], tf, current) for tf in POLICY.timeframes
                }
                closed_values = {
                    (tf, c.timestamp): (c.open, c.high, c.low, c.close, c.volume)
                    for tf, candles in batch_provider.rows.items()
                    for c in candles
                    if _timestamp(c.timestamp)
                    + timedelta(
                        seconds=INTERVAL_SECONDS[tf]
                        + self.configuration.provider_grace_seconds
                    )
                    <= current
                }
                previous_values = self._closed_values.get(symbol, {})
                if any(
                    key in previous_values and previous_values[key] != values
                    for key, values in closed_values.items()
                ):
                    raise ValueError("closed_candle_revision")
                self._closed_values[symbol] = closed_values
                snapshots = await coordinator.collect_due(
                    symbol, watching=evaluator.watching(symbol), observed_at=current
                )
                if snapshots:
                    evaluation = evaluator.evaluate(
                        symbol,
                        snapshots,
                        evaluated_at=current,
                        macro_degraded=not bool(context),
                    )
                    if isinstance(self.repository, HierarchyRepository):
                        for evidence in (
                            evaluation.macro_context,
                            evaluation.regime_4h,
                            evaluation.strategy_1h,
                            evaluation.setup_15m,
                            evaluation.trigger_5m,
                        ):
                            if evidence is not None:
                                await self.repository.append_context(evidence)
                if evaluation and (
                    evaluation.bundle
                    or (evaluation.strategy_1h is not None and not evaluation.watching)
                ):
                    break
                if now is not None or attempt == 3:
                    break
                await asyncio.sleep(self.configuration.confirmation_retry_seconds)
            result.update(
                {
                    "market_data_provenance": provenance,
                    "session_close": session_close.isoformat(),
                    "freshness": "fresh",
                }
            )
            result["analysis_sources"] = [
                {
                    "provider": provider,
                    "role": "primary_candle_analysis",
                    "requested": True,
                    "status": "used",
                    "affected_score": True,
                    "provider_symbol": result["analysis_instrument"],
                    "timeframes": {
                        tf: {"candle_count": len(batch_provider.rows[tf])}
                        for tf in POLICY.timeframes
                    },
                    "evidence_contributed": ["shared crypto hierarchy"],
                }
            ]
            if evaluation is None:
                result["reasons"] = ["awaiting_next_closed_candle"]
                return result
            core = ShadowHierarchyService._signal_core_evidence(evaluation)
            result.update(
                {
                    "signal_core_score": core["score"],
                    "signal_core_evidence": core["evidence"],
                    "reasons": list(evaluation.reasons),
                    "watching": evaluation.watching,
                }
            )
            result["market_structure"] = (
                dict(evaluation.strategy_1h.evidence) if evaluation.strategy_1h else {}
            )
            result["liquidity"] = (
                dict(evaluation.setup_15m.evidence) if evaluation.setup_15m else {}
            )
            result["supply_demand"] = {
                "timeframe": POLICY.setup,
                "price_inside_zone": result["liquidity"].get("price_inside_zone"),
            }
            result["trigger"] = (
                dict(evaluation.trigger_5m.evidence) if evaluation.trigger_5m else {}
            )
            # The same Fibonacci engine used by crypto's multi-TP producer.
            state = evaluator._state[symbol.upper()]
            fib = {}
            for tf, snapshot in (state.snapshots or {}).items():
                layer = (
                    evaluator._analyse_structure(snapshot, state.regime_assessment)
                    if state.regime_assessment
                    else None
                )
                if layer:
                    assessment = FibonacciLiquidityEngine().assess(
                        FibonacciRequest(
                            layer.market,
                            layer.structure,
                            layer.liquidity,
                            layer.zones,
                            layer.reclaim,
                        )
                    )
                    fib[tf] = {
                        "has_valid_anchor": assessment.has_valid_anchor,
                        "direction": assessment.direction.value,
                    }
            result["fibonacci"] = fib
            from monatise.engines.order_flow import (
                OrderFlowIntelligenceEngine,
                OrderFlowRequest,
                FlowInput,
            )

            order_flow = OrderFlowIntelligenceEngine().assess(
                OrderFlowRequest(symbol, FlowInput(), regime=state.regime_assessment)
            )
            result["order_flow"] = {
                "evaluation_timeframe": POLICY.analysis,
                "kind": "verified_positioning_context",
                "context": context,
                "direct_order_flow_available": False,
                "health": order_flow.health.value,
                "inputs_used": order_flow.inputs_used,
                "reasons": list(order_flow.reasons),
            }
            if (
                not evaluation.bundle
                or not evaluation.validation
                or not evaluation.validation.eligible_for_shadow_decision
                or core["score"] < 3
            ):
                if evaluation.validation:
                    result["reasons"].extend(evaluation.validation.reasons)
                return result
            bundle = evaluation.bundle
            from monatise.application.flashalpha_analysis import (
                flashalpha_directional_bias,
            )

            bias = flashalpha_directional_bias(context) if context else None
            quiver_score = int(context.get("quiver_score") or 0)
            if (
                bundle.trigger_5m.direction == "long"
                and (bias == "bearish" or quiver_score <= -2)
            ) or (
                bundle.trigger_5m.direction == "short"
                and (bias == "bullish" or quiver_score >= 2)
            ):
                result.update(
                    setup_status="provider_conflict",
                    reasons=["positioning_context_conflicts_with_shared_hierarchy"],
                )
                self._engines.pop(symbol, None)
                return result
            risk = bundle.risk_inputs
            current_price = state.snapshots[POLICY.entry].latest_finalized.close
            result["current_price"] = current_price
            entry_candle = state.snapshots[POLICY.entry].latest_finalized
            result["market_observed_at"] = entry_candle.scheduled_close_time.isoformat()
            result["market_price_observation"] = {
                "price": current_price,
                "source": provider,
                "kind": "closed_candle",
                "timeframe": POLICY.entry,
                "observed_at": result["market_observed_at"],
            }
            result["entry_zone"] = {
                "low": risk.entry_zone_low,
                "high": risk.entry_zone_high,
            }
            result["entry_zone_low"], result["entry_zone_high"] = (
                risk.entry_zone_low,
                risk.entry_zone_high,
            )
            if not risk.entry_zone_low <= current_price <= risk.entry_zone_high:
                result.update(
                    setup_status="awaiting_entry_zone",
                    reasons=["closed_entry_price_outside_setup_zone"],
                )
                return result
            expiry = min(
                risk.expires_at,
                session_close,
                *(
                    c.expires_at
                    for c in (
                        bundle.macro_context,
                        bundle.regime_4h,
                        bundle.strategy_1h,
                        bundle.setup_15m,
                        bundle.trigger_5m,
                    )
                ),
            )
            if expiry <= observed:
                raise ValueError("hierarchical_setup_expired")
            result.update(
                {
                    "decision": "BUY_WATCH"
                    if bundle.trigger_5m.direction == "long"
                    else "SELL_WATCH",
                    "direction": bundle.trigger_5m.direction.upper(),
                    "setup_status": "confirmed",
                    "publication_valid": True,
                    "entry": risk.reference_entry,
                    "current_price": current_price,
                    "stop_loss": risk.final_stop,
                    "structural_invalidation": risk.structural_invalidation,
                    "target": risk.target_liquidity,
                    "targets": [risk.target_liquidity],
                    "reward_risk": risk.calculated_reward_to_risk,
                    "score": core["score"]
                    * (1 if bundle.trigger_5m.direction == "long" else -1),
                    "score_scale": 4,
                    "conviction": core["score"] / 4 * 10,
                    "expires_at": expiry.isoformat(),
                    "valid_until": expiry.isoformat(),
                    "setup_expires_at": expiry.isoformat(),
                    "setup_state": "ACTIVE",
                    "setup_id": bundle.bundle_id,
                    "as_of": bundle.trigger_5m.source_close_time.isoformat(),
                    "evidence_bundle": {
                        "bundle_id": bundle.bundle_id,
                        "entry_candle": {
                            "timeframe": POLICY.entry,
                            "candle_id": state.snapshots[
                                POLICY.entry
                            ].latest_finalized.candle_id,
                            "closed_at": state.snapshots[
                                POLICY.entry
                            ].latest_finalized.scheduled_close_time.isoformat(),
                        },
                        "contexts": [
                            asdict(c.identity)
                            for c in (
                                bundle.macro_context,
                                bundle.regime_4h,
                                bundle.strategy_1h,
                                bundle.setup_15m,
                                bundle.trigger_5m,
                            )
                        ],
                        **POLICY.metadata(),
                    },
                    "management_structure": evaluation.management_structure,
                }
            )
            if evaluation.take_profit_plan:
                plan = replace(evaluation.take_profit_plan, expires_at=expiry)
                result.update(plan_fields(plan))
            previous = self._previous_signal.get(symbol)
            if previous and previous != bundle.bundle_id:
                result["supersedes_signal_id"] = previous
            self._previous_signal[symbol] = bundle.bundle_id
            return result
        except (ValueError, TypeError, KeyError, RuntimeError, TimeoutError) as exc:
            # Discard cached parents after a provider failure, session boundary
            # or revision; they must never rehabilitate a stale setup later.
            self._engines.pop(symbol, None)
            self._closed_values.pop(symbol, None)
            result.update(
                {
                    "decision": "INSUFFICIENT_MARKET_DATA",
                    "setup_status": "insufficient_market_data",
                    "reason_code": str(exc),
                    "reasons": [str(exc)],
                    "freshness": "invalid",
                }
            )
            return result
