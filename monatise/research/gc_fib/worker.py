"""Native GC H1 diagnostic interface; no synthetic GoldSetupSeed or trade plan.

Broker-specific qualification and final canonical validation are unavailable.
This distinction is intentional: selector research is not a qualified setup.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from monatise.application.gold_analysis import GoldLayerEvaluator, sweep_reversal
from monatise.application.hierarchy.coordinator import TimeframeSnapshot
from monatise.application.hierarchy.models import (
    BoundaryStatus, DataQualityState, EvidenceContext, EvidenceIdentity, NormalizedCandle,
    Provenance, StrategicState)
from monatise.application.hierarchy.policy import SHARED_TIMEFRAME_POLICY
from monatise.engines.fibonacci_liquidity import FibonacciLiquidityEngine, FibonacciRequest
from monatise.engines.regime import RegimeRequest
from monatise.engines.liquidity import LiquidityRequest
from monatise.research.gc_fib import H1_RESEARCH, ISOLATION, POLICY
from monatise.research.gc_fib.candles import GCBar, GCIdentity, INTERVALS, timestamp_ns


def instant(ns):
    # Analysis bars are exactly second-aligned. Original ns remain in provenance.
    return datetime.fromtimestamp(ns // 10**9, UTC)


def parse_bar(value):
    data = dict(value)
    data["identity"] = GCIdentity(**data["identity"])
    data["source_hashes"] = tuple(data["source_hashes"])
    return GCBar(**data)


def snapshot(rows, *, timeframe, cutoff):
    prefix = tuple(b for b in rows if b.timeframe == timeframe and b.assumed_available_ns <= cutoff)[-200:]
    if not prefix: return None
    provenance = Provenance("databento-retrospective-gc", "XCEC", "GCZ6",
                            "native-ohlcv-1m", "gc-research-utc-grid-v1")
    normalized = tuple(NormalizedCandle(b.sha256,"GCZ6",timeframe,instant(b.open_ns),instant(b.close_ns),
        instant(b.open_ns),instant(b.assumed_available_ns),float(b.open),float(b.high),float(b.low),
        float(b.close),float(b.volume),True,BoundaryStatus.FINALIZED,b.sha256,provenance) for b in prefix)
    # Explicitly retrospective finalization assumption; never claim two local observations.
    return TimeframeSnapshot("GCZ6",timeframe,instant(cutoff),normalized,normalized[-1])


def assess(dataset):
    from monatise.research.gold_fib.episode import H1StructuralEpisodeAdapter, GoldH1StructuralLegSelector
    from monatise.research.gold_fib.models import H1ParentSnapshot, encode
    if dataset.get("schema") != "gc-h1-diagnostics-v1" or dataset.get("pit_verified") is not False:
        raise ValueError("explicit retrospective GC-only diagnostic input required")
    rows = tuple(parse_bar(b) for b in dataset["bars"])
    if not rows or len(rows) > 100_000 or dataset["evidence_kind"] != rows[0].evidence_kind:
        raise ValueError("bounded nonempty diagnostic input required")
    if any(b.identity != rows[0].identity or b.evidence_kind != rows[0].evidence_kind for b in rows):
        raise ValueError("mixed evidence or contracts forbidden")
    keys = [(b.timeframe,b.open_ns) for b in rows]
    if len(set(keys)) != len(keys): raise ValueError("duplicate/revised bars not admitted")
    rows = tuple(sorted(rows,key=lambda b:(b.open_ns,b.timeframe)))
    cutoffs = dataset["cutoffs_ns"]
    if (not cutoffs or len(cutoffs) > 1000 or any(type(t) is not int for t in cutoffs)
            or cutoffs != sorted(set(cutoffs))):
        raise ValueError("bounded ordered unique integer cutoffs required")
    for cutoff in cutoffs:
        timestamp_ns(cutoff)
        if cutoff % 10**9:
            raise ValueError("analysis cutoffs must be exactly second aligned; native ns remain archived")
    evaluator, results, frozen = GoldLayerEvaluator(), [], {}
    for cutoff in cutoffs:
        frames = {tf:snapshot(rows,timeframe=tf,cutoff=cutoff) for tf in INTERVALS}
        latest = frames["1h"]
        if latest is None:
            results.append({"cutoff_ns":cutoff,"reason":"H1_HISTORY_UNAVAILABLE"}); continue
        minimum_history = max(RegimeRequest.__dataclass_fields__["slow_window"].default,
                              LiquidityRequest.__dataclass_fields__["range_window"].default)
        if len(latest.candles) < minimum_history:
            results.append({"cutoff_ns":cutoff,"reason":"H1_CANONICAL_HISTORY_INSUFFICIENT"}); continue
        # Each parent is captured only at its original assumed H1 availability.
        parent_cutoff = latest.latest_finalized.received_at
        parent_ns = int(parent_cutoff.timestamp()) * 10**9
        parent_frame = snapshot(rows,timeframe="1h",cutoff=parent_ns)
        if latest.latest_finalized.candle_id not in frozen:
            layer = evaluator._analyse_structure(parent_frame,None)
            direction = "long" if layer.structure.bias.value == "bullish" else "short" if layer.structure.bias.value == "bearish" else "none"
            state = StrategicState.LONG_ONLY if direction == "long" else StrategicState.SHORT_ONLY if direction == "short" else StrategicState.NEUTRAL
            bar = parent_frame.latest_finalized
            identity = EvidenceIdentity.create(kind="gc-research-h1",symbol="GCZ6",timeframe="1h",
                candle_id=bar.candle_id,parent_id=None,strategy_version=POLICY)
            # Authentic H1 lifetime from pinned hierarchy config; never renewed by reread.
            lifetime = SHARED_TIMEFRAME_POLICY.analysis_lifetime
            context = EvidenceContext(identity,bar.open_time,bar.scheduled_close_time,parent_cutoff,
                bar.scheduled_close_time+lifetime,state,direction,layer.structure.confidence,
                DataQualityState.READY,bar.provenance,{"scope":"NATIVE_GC_RESEARCH_NOT_GOLD_SIGNAL"})
            parent = H1ParentSnapshot.capture(context,parent_frame,layer)
            episode = H1StructuralEpisodeAdapter().assess(parent)
            selected = GoldH1StructuralLegSelector().select(parent,episode)
            frozen[bar.candle_id] = (parent,episode,selected,layer)
        parent,episode,selected,layer = frozen[latest.latest_finalized.candle_id]
        context = parent.objects()[0]
        result = {"cutoff_ns":cutoff,"symbol":"GCZ6","h1_parent_cutoff":parent.cutoff,
            "h1_parent_hash":parent.record.sha256,"h1_episode":episode.record.data,
            "anchor":selected.record.data,"anchor_hash":selected.record.sha256,
            "raw_slots":[{"identity":f"FIB_TP{i}","ratio":r,"raw_price":None,"eligible":False}
                         for i,r in enumerate((1.272,1.414,1.618),1)],
            "qualified_gold_setup":False,"final_targets":[],"entry":None,"stop":None,"rr":None,
            "canonical_comparison":{"scope":"REUSED_NATIVE_PRICE_ANALYTICS_ONLY",
                "canonical_xauusd_decision":"UNAVAILABLE_NATIVE_GC_SOURCE_CONTRACT",
                "canonical_target_plan":"UNAVAILABLE_BROKER_UNITS_SPREAD_STOP_ALLOWANCES"},
            "lower_timeframes":{},"reason":selected.record.data["reason"],
            "gil_evidence":None,"basis_mapping":None,"outcomes":None}
        for tf in ("4h","15m","5m","1m"):
            frame = frames[tf]
            if frame is None:
                result["lower_timeframes"][tf] = {"status":"UNAVAILABLE"}; continue
            if len(frame.candles) < minimum_history:
                result["lower_timeframes"][tf] = {"status":"CANONICAL_HISTORY_INSUFFICIENT",
                    "received":len(frame.candles),"required":minimum_history}; continue
            age = (instant(cutoff)-frame.latest_finalized.scheduled_close_time).total_seconds()
            if age > INTERVALS[tf]+10:
                result["lower_timeframes"][tf] = {"status":"STALE_OR_LATEST_BAR_MISSING"}; continue
            computed = evaluator._analyse_structure(frame,None)
            info = {"status":"PRICE_ANALYTICS_ONLY","source_hash":frame.latest_finalized.content_hash,
                    "structure":computed.structure}
            if tf == "15m": info["gold_pattern"] = sweep_reversal(computed.market.candles,context.direction,"15m")
            result["lower_timeframes"][tf] = info
        if instant(cutoff) >= context.expires_at:
            result["reason"] = "H1_PARENT_EXPIRED"
        elif selected.constraint:
            request = FibonacciRequest(layer.market,layer.structure,layer.liquidity,layer.zones,layer.reclaim,
                extension_ratios=(1.272,1.414,1.618),anchor_constraint=selected.constraint)
            atr = FibonacciLiquidityEngine._atr(list(layer.market.candles),14)
            result["h1_atr"] = atr
            result["h1_leg_atr_multiple"] = selected.record.data["range_usd"] / atr if atr > 0 else None
            gate = None
            if len(layer.market.candles) < 15 or atr <= 0: gate = "H1_HISTORY_OR_ATR_UNAVAILABLE"
            elif layer.structure.confidence < request.minimum_structure_confidence: gate = "STRUCTURE_CONFIDENCE_REJECTED"
            elif min(selected.constraint.start_index,selected.constraint.end_index) < len(layer.market.candles)-request.maximum_anchor_age_candles:
                gate = "ANCHOR_AGE_REJECTED"
            elif selected.record.data["range_usd"] < request.minimum_anchor_range_atr * atr: gate = "TWO_ATR_REJECTED"
            fib = FibonacciLiquidityEngine().assess(request)
            result["fib_assessment"] = fib
            result["valid_constrained_fib"] = fib.has_valid_anchor
            if gate or not fib.has_valid_anchor:
                result["valid_constrained_fib"] = False
                result["reason"] = gate or "CONSTRAINED_FIB_REJECTED"
            else:
                levels = {level.ratio:level for level in fib.extension_levels}
                for slot in result["raw_slots"]:
                    level = levels[slot["ratio"]]
                    slot.update(raw_price=level.price,technical_confluence=bool(level.liquidity_confluence
                        or level.zone_confluence or level.structure_confluence),
                        rejection_reason="QUALIFIED_NATIVE_GC_SETUP_ENTRY_STOP_UNAVAILABLE")
                result["reason"] = "ANCHOR_DIAGNOSTIC_ONLY_SETUP_QUALIFICATION_UNAVAILABLE"
        results.append(encode(result))
    counts = Counter(r["reason"] for r in results)
    clusters = {}
    for r in results:
        episode_id = r.get("anchor",{}).get("h1_episode_id")
        if episode_id: clusters.setdefault(episode_id,[]).append(r["cutoff_ns"])
    return {"schema":"gc-h1-diagnostic-report-v1","policy":POLICY,"h1_research":H1_RESEARCH,
            **ISOLATION,"evidence_kind":dataset["evidence_kind"],"records":results,
            "diagnostic_counts":dict(counts),"h1_episode_clusters":clusters,
            "gold_setup_seed_count":None,"eligible_target_distribution":None,
            "limitation":"Native GC price diagnostics do not manufacture a broker-qualified GoldSetupSeed."}


def main(input_file,output_file):
    value = assess(json.loads(input_file.read_text()))
    with output_file.open("x") as destination:
        json.dump(value,destination,sort_keys=True,indent=2,allow_nan=False)
