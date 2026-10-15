"""All-cutoff research ledger using actual pinned canonical analytical engines."""
from collections import Counter
from dataclasses import asdict
from decimal import Decimal
import json

from monatise.application.hierarchy.models import SetupState, TriggerState
from monatise.research.gc_fib.candles import GCIdentity
from monatise.research.gc_fib.worker import instant, parse_bar
from monatise.research.gold_fib.models import encode
from monatise.research.gc_qualification import AVAILABILITY, SAFETY, VERSION
from monatise.research.gc_qualification.models import NativeContract, Quote, digest
from monatise.research.gc_qualification.adapter import CutoffAdapter, NativeGoldEvaluator


def make_contract(value):
    v = dict(value); v["identity"] = GCIdentity(**v["identity"])
    v["native_terms"] = tuple(tuple(t) for t in v["native_terms"])
    return NativeContract(**v)


def associations(value):
    result = {}
    for row in value:
        if row.get("h1_parent_cutoff"):
            result[row["h1_parent_cutoff"]] = row
    return result


def target_record(t):
    # Do not export execution-plan fields such as realized_pnl, fill/hit state,
    # allocated lot sizes or automatic exit management into candidate evidence.
    return encode(dict(name=t.name,raw_price=t.analysis_price,normalized_price=t.price,
        rr=t.rr,allocation_pct=t.allocation_pct,evidence_type=t.evidence_type,
        source=t.source,source_provider=t.source_provider,confidence=t.confidence,
        timeframe=t.timeframe,observed_at=t.observed_at,agreement=t.agreement))


def pattern_identity(layer, pattern):
    if not pattern.get("confirmed"): return None
    points = {key: layer.market.candles[pattern[key]].timestamp
              for key in ("liquidity_index","sweep_index","displacement_index","retest_index")}
    return digest(dict(symbol="GCZ6",**points,shift_level=pattern["shift_level"],structural=pattern["structural_invalidation"]))


def pivot_records(layer,frame):
    result = []
    for kind,points in (("high",layer.structure.swing_highs),("low",layer.structure.swing_lows)):
        confirmed_levels = {e.level for e in layer.structure.events if e.confirmed}
        selected = [p for p in points if p in points[-3:] or p[1] in confirmed_levels]
        for index,price in selected:
            if index+3 >= len(frame.candles): continue
            result.append(dict(kind=kind,price=price,pivot_open=frame.candles[index].open_time.isoformat(),
                known_at=frame.candles[index+3].received_at.isoformat(),
                confirming_hashes=[b.content_hash for b in frame.candles[index+1:index+4]]))
    return result


def link_frozen(record, frames, frozen, now):
    if "1h" not in frames: return
    association = frozen.get(frames["1h"].latest_finalized.received_at.isoformat())
    if not association: return
    anchor = association.get("anchor",{})
    active = association.get("h1_episode",{}).get("active") or {}
    record.update(h1_episode_id=anchor.get("h1_episode_id") or active.get("h1_episode_id"),
        structural_leg_id=anchor.get("h1_leg_id"),
        fibonacci_assessment_id=digest(dict(anchor=association.get("anchor_hash"),cutoff=association["cutoff_ns"])),
        frozen_fibonacci=dict(parent_hash=association.get("h1_parent_hash"),anchor_sha256=association.get("anchor_hash"),
            anchor={k:v for k,v in anchor.items() if k != "episode_provenance"},
            valid_constrained_fib=association.get("valid_constrained_fib",False),
            raw_slots=association.get("raw_slots",[]),advisory_only=True))
    for endpoint in ("A","B"):
        if anchor.get(endpoint) and anchor[endpoint].get("known_at") > now.isoformat():
            raise ValueError("future_frozen_anchor")


def unadmitted_diagnostic(contract, frames, now, spread):
    """Actual price engines, NEVER an eligibility path through a data rejection."""
    if set(frames) != {"4h","1h","15m","5m","1m"} or spread is None:
        # Independent price mathematics has no spread/risk dependency. These
        # results never become an admitted parent, seed, entry or candidate.
        evaluator = NativeGoldEvaluator(contract)
        layers, failures = {}, {}
        for tf, frame in frames.items():
            try:
                layer = evaluator._analyse_structure(frame, None)
                if layer is not None:
                    layers[tf] = encode(layer)
            except (ValueError, TypeError, ArithmeticError) as exc:
                failures[tf] = type(exc).__name__
        return dict(engines_executed=bool(layers),scope="UNADMITTED_PREFIX_DIAGNOSTIC_ONLY",
                    analytical_availability="CONTEXT_ONLY" if layers else "UNAVAILABLE",
                    price_layers=layers,failures=failures,candidate_eligible=False,
                    quote_dependent_risk_available=False)
    evaluator = NativeGoldEvaluator(contract)
    try:
        result = evaluator.evaluate_native(frames,now=now,spread=spread)
    except ValueError as exc:
        if str(exc) != "gold_parent_or_pattern_expired": raise
        return dict(engines_executed=True,scope="UNADMITTED_PREFIX_DIAGNOSTIC_ONLY",
                    reason="gold_parent_or_pattern_expired",candidate_eligible=False)
    return encode(dict(engines_executed=True,scope="UNADMITTED_PREFIX_DIAGNOSTIC_ONLY",candidate_eligible=False,
        h4_context=result.regime_4h,h1_context=result.strategy_1h,m15_context=result.setup_15m,
        m5_context=result.trigger_5m,canonical_reasons=result.reasons,risk_rejection=evaluator.risk_error))


def qualify(value):
    if value["schema"] != VERSION or value["historical_availability"] != AVAILABILITY or value["pit_verified"] is not False:
        raise ValueError("explicit_retrospective_contract_required")
    if any(value.get(k) is not False for k in SAFETY):
        raise ValueError("research_activation_forbidden")
    if digest(value["configuration"]) != value["configuration_sha256"]:
        raise ValueError("configuration_hash_mismatch")
    bars = tuple(parse_bar(b) for b in value["bars"])
    if not bars or len(bars) > 100_000 or any(b.identity != bars[0].identity or b.evidence_kind != bars[0].evidence_kind for b in bars):
        raise ValueError("bounded_exact_contract_input_required")
    contract = make_contract(value["contract"])
    cutoffs = value["cutoffs_ns"]
    if not cutoffs or len(cutoffs) > 10000 or cutoffs != sorted(set(cutoffs)) or any(type(c) is not int or c % 10**9 for c in cutoffs):
        raise ValueError("bounded_ordered_second_aligned_cutoffs_required")
    config = value["configuration"]
    if any(not config["start_ns"] <= c < config["end_ns"] for c in cutoffs):
        raise ValueError("cutoff_outside_predeclared_scope")
    adapter = CutoffAdapter(bars,value["sessions"])
    evaluator = NativeGoldEvaluator(contract)
    frozen = associations(value.get("frozen_associations",[]))
    run_id = digest(dict(config=value["configuration_sha256"],input=value["derived_input_sha256"],
                         archives=[m["archive_sha256"] for m in value["source_archives"]]))
    records = []
    for cutoff in cutoffs:
        now = instant(cutoff)
        frames,issues,lineage = adapter.frames(cutoff)
        session = adapter.session(cutoff)
        record = dict(schema=VERSION,research_run_id=run_id,cutoff_ns=cutoff,decision_timestamp=now.isoformat(),
            evidence_kind=bars[0].evidence_kind,
            historical_availability=AVAILABILITY,source_commit=config["source_commit"],frozen_selector_commit=config["frozen_commit"],
            raw_archive_hashes=[m["archive_sha256"] for m in value["source_archives"]],
            derived_input_sha256=value["derived_input_sha256"],definition_sha256=contract.definition_sha256,
            frozen_associations_sha256=value.get("frozen_associations_sha256"),
            configuration_sha256=value["configuration_sha256"],contract=asdict(contract),
            research_source_hashes=config.get("research_source_hashes",{}),
            exact_canonical_parity_claim=False,**SAFETY,decision="UNAVAILABLE",qualification_status="UNAVAILABLE",
            entry=None,entry_zone=None,observed_market_price=None,structural_invalidation=None,stop_loss=None,
            tick_size=contract.tick_size,risk_distance=None,risk_ticks=None,targets=[],tp1_rr=None,
            expires_at=None,waiting_for_entry=None,candidate_id=None,h1_episode_id=None,fibonacci_assessment_id=None,
            structural_leg_id=None,frozen_fibonacci=None,m15_setup_id=None,m5_trigger_id=None,m1_zone_id=None,
            h4_context=None,h1_context=None,m15_context=None,m5_context=None,quote=None,cost_components=None,
            session_admission=dict(state="OPEN" if session else "CLOSED_OR_UNREVIEWED",interval=session,
                review_sha256=value["session_review_sha256"],point_in_time_certified=False),
            candle_evidence=lineage,pivot_confirmations={},rejection_reasons=[],data_admissible=False)
        if not contract.definition_receive_ns <= cutoff < contract.expiration_ns:
            issues.append("native_instrument_definition_unavailable_or_expired")
        # Coverage is a union of exact admitted partitions, not a bounding box.
        if not any(a <= cutoff < b for a,b in value["quote_coverage"]):
            issues.append("quote_coverage_unavailable")
        quote_value = value["quotes"].get(str(cutoff))
        spread = None
        if quote_value is None: issues.append("quote_missing")
        else:
            try:
                quote = Quote(**quote_value)
                record["quote"] = {**asdict(quote),"availability_basis":AVAILABILITY}
                if session:
                    spread = quote.spread_at(cutoff,session[0],config["quote_max_age_ns"])
            except ValueError as exc:
                issues.append(str(exc))
        if issues:
            # Never keep earlier snapshots/context through missing/revised/stale
            # evidence. Every unavailable cutoff remains in the ledger.
            evaluator = NativeGoldEvaluator(contract)
            record["rejection_reasons"] = sorted(set(issues))
            link_frozen(record,frames,frozen,now)
            record["unadmitted_price_diagnostic"] = unadmitted_diagnostic(contract,frames,now,spread)
            records.append(record); continue
        record["data_admissible"] = True
        record.update(decision="NO_TRADE",qualification_status="REJECTED")
        # Association is advisory and captured at the original H1 cutoff, never
        # an extra Gold entry gate or refreshed with future selector output.
        link_frozen(record,frames,frozen,now)
        try:
            result = evaluator.evaluate_native(frames,now=now,spread=spread)
            reasons = list(result.reasons)
            if evaluator.risk_error: reasons.append(evaluator.risk_error)
            if not result.strategy_1h or result.strategy_1h.direction not in {"long","short"}:
                reasons.append("h1_direction_unavailable_or_neutral")
            if not result.setup_15m or result.setup_15m.state is not SetupState.SETUP_CONFIRMED:
                reasons.append("m15_gold_setup_unconfirmed")
            if not result.trigger_5m or result.trigger_5m.state is not TriggerState.TRIGGER_CONFIRMED:
                reasons.append("m5_gold_trigger_unconfirmed")
            if result.validation: reasons.extend(result.validation.reasons)
            if not result.bundle and not reasons: reasons.append("canonical_bundle_unavailable")
            record["rejection_reasons"] = sorted(set(reasons))
            for key,context in (("h4_context",result.regime_4h),("h1_context",result.strategy_1h),
                                ("m15_context",result.setup_15m),("m5_context",result.trigger_5m)):
                record[key] = encode(context) if context else None
            for tf,layer in evaluator.layers.items():
                record["pivot_confirmations"][tf] = pivot_records(layer,frames[tf])
            if result.setup_15m and "15m" in evaluator.layers:
                pattern = result.setup_15m.evidence.get("gold_pattern",{})
                record["m15_setup_id"] = pattern_identity(evaluator.layers["15m"],pattern)
            if result.trigger_5m and "5m" in evaluator.layers:
                events = [e for e in evaluator.layers["5m"].structure.events if e.confirmed]
                if events:
                    event = events[-1]; layer = evaluator.layers["5m"]
                    record["m5_trigger_id"] = digest(dict(setup=record["m15_setup_id"],
                        event=layer.market.candles[event.candle_index].timestamp,type=event.break_type.value,
                        level=event.level,direction=result.trigger_5m.direction))
                    record["m5_event"] = encode(event)
            prepared = evaluator.prepared
            if prepared is not None:
                entry = evaluator.layers["1m"]
                zone = (entry.zones.active_demand or entry.zones.nearest_demand) if prepared.direction == "long" else (entry.zones.active_supply or entry.zones.nearest_supply)
                record["m1_zone_id"] = digest(dict(origin=entry.market.candles[zone.created_index].timestamp,
                    type=zone.zone_type.value,low=zone.lower_bound,high=zone.upper_bound))
                distance = abs(Decimal(str(prepared.reference_entry))-Decimal(str(prepared.final_stop)))
                record.update(entry=prepared.reference_entry,entry_zone=[prepared.entry_zone_low,prepared.entry_zone_high],
                    observed_market_price=entry.market.price,structural_invalidation=prepared.structural_invalidation,
                    stop_loss=prepared.final_stop,risk_distance=str(distance),risk_ticks=str(distance/Decimal(contract.tick_size)),
                    expires_at=min(prepared.expires_at,instant(session[1])).isoformat(),
                    waiting_for_entry=not zone.contains(entry.market.price),
                    cost_components=dict(observed_spread_price=str(spread),observed_spread=True,
                        native_price_quantum=contract.tick_size,m1_atr_times_configured_multiplier=prepared.volatility_buffer,
                        estimated_spread_floor=prepared.estimated_spread_allowance,
                        estimated_slippage_allowance=prepared.estimated_slippage_allowance,
                        slippage_observed=False,allowances_recalibrated=False))
                record["target_candidates"] = encode([asdict(c) for c in evaluator.target_candidates])
                if evaluator.plan:
                    record["targets"] = [target_record(t) for t in evaluator.plan.targets]
                    record["tp1_rr"] = str(evaluator.plan.targets[0].rr)
                    record["target_rejection_log"] = list(evaluator.plan.rejection_log)
            if result.validation and result.validation.eligible_for_shadow_decision and not record["rejection_reasons"]:
                record.update(decision=prepared.direction.upper(),qualification_status="QUALIFIED_ANALYTICAL",
                    candidate_id=digest(dict(setup=record["m15_setup_id"],trigger=record["m5_trigger_id"],
                        zone=record["m1_zone_id"],direction=prepared.direction,version=VERSION)))
        except ValueError as exc:
            if str(exc) != "gold_parent_or_pattern_expired": raise
            record["rejection_reasons"] = ["gold_parent_or_pattern_expired"]
            evaluator = NativeGoldEvaluator(contract)
        records.append(encode(record))
    qualified = [r for r in records if r["qualification_status"] == "QUALIFIED_ANALYTICAL"]
    unique = lambda key,rows: len({r[key] for r in rows if r.get(key)})
    reasons = Counter(reason for r in records for reason in r["rejection_reasons"])
    summary = dict(scheduled_cutoffs=len(records),data_admissible_cutoffs=sum(r["data_admissible"] for r in records),
        unavailable_cutoffs=sum(r["decision"] == "UNAVAILABLE" for r in records),
        rejected_cutoffs=sum(r["decision"] == "NO_TRADE" for r in records),
        qualified_long_observations=sum(r["decision"] == "LONG" for r in qualified),
        qualified_short_observations=sum(r["decision"] == "SHORT" for r in qualified),
        distinct_long_candidates=unique("candidate_id",[r for r in qualified if r["decision"] == "LONG"]),
        distinct_short_candidates=unique("candidate_id",[r for r in qualified if r["decision"] == "SHORT"]),
        waiting_for_entry_observations=sum(r["waiting_for_entry"] is True for r in qualified),
        unique_h1_episodes=unique("h1_episode_id",records),unique_m15_setups=unique("m15_setup_id",records),
        unique_m5_triggers=unique("m5_trigger_id",records),distinct_analytical_candidates=unique("candidate_id",qualified),
        target_rr_rejected=sum(any(any(code in e for code in ("tp1_reward","insufficient target evidence",
            "target reversed, duplicated or insufficiently spaced")) for e in r["rejection_reasons"]) for r in records),
        risk_or_entry_rejected=sum(any("risk_proposal_rejected" in e for e in r["rejection_reasons"]) for r in records),
        freshness_rejected=sum(any("expired" in e or "stale" in e for e in r["rejection_reasons"]) for r in records),
        quote_freshness_rejected=sum("quote_stale" in r["rejection_reasons"] for r in records),
        candle_transport_freshness_rejected=sum(any(":canonical_source_stale" in e for e in r["rejection_reasons"]) for r in records),
        continuity_rejected=sum(any(":missing_or_no_trade_bar" in e or ":latest_expected_bar_missing" in e
                                   for e in r["rejection_reasons"]) for r in records),
        closed_session_rejected=sum("exchange_closed_or_unreviewed_session" in r["rejection_reasons"] for r in records),
        incomplete_market_evidence=sum(not r["data_admissible"] for r in records),
        unadmitted_price_diagnostics_executed=sum(r.get("unadmitted_price_diagnostic",{}).get("engines_executed",False) for r in records),
        instrument_assumptions_prevented=sum(any("instrument" in e for e in r["rejection_reasons"]) for r in records),
        rejection_counts=dict(sorted(reasons.items())),new_databento_usage_usd="0")
    return dict(schema=VERSION,research_run_id=run_id,**SAFETY,historical_availability=AVAILABILITY,
        evidence_kind=bars[0].evidence_kind,
        configuration=value["configuration"],summary=summary,records=records,
        limitation="Analytical GC research only; no fills, outcomes or broker-equivalent parity claim.")


def main(input_file, output_file):
    value = qualify(json.loads(input_file.read_text()))
    with output_file.open("x") as out: json.dump(value,out,sort_keys=True,separators=(",",":"),allow_nan=False)
    output_file.chmod(0o400)
    print(json.dumps(value["summary"],sort_keys=True),flush=True)
