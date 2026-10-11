"""Separate retrospective algorithm; never calls or weakens OfflineReplay."""
from __future__ import annotations

import json
from bisect import bisect_right
from collections import Counter
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from monatise.application.hierarchy.candles import CandleBoundaryNormalizer
from monatise.application.hierarchy.coordinator import TimeframeSnapshot
from monatise.application.hierarchy.models import Provenance, StrategicState
from monatise.core.models import Candle
from monatise.engines.liquidity import LiquidityRequest
from monatise.engines.regime import RegimeRequest
from monatise.research.broker_xauusd.models import TIMEFRAMES, digest, instant
from monatise.research.broker_xauusd.models import expected_opens
from monatise.research.gold_retrospective.dataset import GRACE_SECONDS, historical_units, validate_dataset
from monatise.research.gold_retrospective import H1_RESEARCH, POLICY


def run(dataset, *, assessment_start, assessment_end, maximum_decisions=5000):
    # Imports are intentionally deferred: the pinned subprocess owns these types.
    from monatise.research.gold_fib.capture import CaptureGoldLayerEvaluator
    from monatise.research.gold_fib.f0 import H1FibF0
    from monatise.research.gold_fib.models import encode
    from monatise.research.gold_fib.diagnostics import diagnostics
    calendar = validate_dataset(dataset)
    start,end = instant(assessment_start),instant(assessment_end)
    if not instant(dataset["start"]) <= start < end <= instant(dataset["end"])+timedelta(seconds=GRACE_SECONDS):
        raise ValueError("assessment window outside frozen dataset")
    if type(maximum_decisions) is not int or not 1 <= maximum_decisions <= 5000:
        raise ValueError("bounded decision budget required")
    rows = {tf:sorted([r for r in dataset["rows"] if r["timeframe"] == tf],key=lambda r:instant(r["assumed_available_at"])) for tf in TIMEFRAMES}
    known_at = {tf:[instant(r["assumed_available_at"]) for r in cs] for tf,cs in rows.items()}
    # Missing M1 decisions also count and revoke eligibility at their first
    # expected assessment, rather than silently disappearing from the sample.
    expected_times=[]
    cursor=max(calendar.start,start-timedelta(minutes=1,seconds=GRACE_SECONDS))
    while cursor < end:
        boundary=min(cursor+timedelta(days=7),end)
        expected_times.extend(t+timedelta(minutes=1,seconds=GRACE_SECONDS)
            for t in expected_opens(calendar,"1m",cursor,boundary)
            if start <= t+timedelta(minutes=1,seconds=GRACE_SECONDS) < end)
        cursor=boundary
    times=sorted(set(expected_times))
    missing_decisions=sorted(set(times)-set(known_at["1m"]))
    if len(times) > maximum_decisions:
        raise ValueError("decision budget exceeded; narrow assessment range (no silent sampling)")
    normalizer = CandleBoundaryNormalizer()
    provider = "retrospective_broker_xauusd_"+dataset["identity"]["broker"]
    provenance = Provenance(provider,dataset["identity"]["server"],"XAU/USD",dataset["sha256"],"hierarchy-candle-v1")
    evaluator, f0 = CaptureGoldLayerEvaluator(),H1FibF0()
    records, admissions, seeds, invalidations, active, seen, cache, seed_rejections = [],[],[],[],{},set(),{},[]
    for at in times:
        snapshots, unavailable, knowledge = {},[],{}
        try:
            calendar.require_regular_session(at)
        except ValueError:
            admissions.append({"at":at.isoformat(),"reason":"ASSESSMENT_OUTSIDE_REVIEWED_SESSION"})
            continue
        for tf in TIMEFRAMES:
            count = bisect_right(known_at[tf],at)
            prefix = rows[tf][:count]
            if not prefix:
                unavailable.append(tf+":NO_HISTORY"); continue
            # All earlier rows remain in the frozen dataset; engines see at most
            # the canonical trailing history. No future row is made available.
            history = prefix[-evaluator.configuration.candle_limit:]
            knowledge[tf] = {"available_count":count,"last_open":history[-1]["opened_at"],
                             "last_assumed_available":history[-1]["assumed_available_at"],
                             "window_sha256":digest(history)}
            minimum_history = max(RegimeRequest.__dataclass_fields__["slow_window"].default,
                                  LiquidityRequest.__dataclass_fields__["range_window"].default)
            if len(history) < minimum_history:
                unavailable.append(tf+":CANONICAL_HISTORY_INSUFFICIENT"); continue
            expected = calendar.expected_closed_open(tf,at).isoformat()
            if history[-1]["opened_at"] != expected:
                unavailable.append(tf+":LATEST_EXPECTED_BAR_MISSING"); continue
            # Detect any missing regular bar inside the actual engine history,
            # not just the newest row. Reviewed closures are legitimate gaps.
            from monatise.application.hierarchy.policy import INTERVAL_SECONDS
            cache_key = (tf,count)
            if cache_key not in cache:
                expected_history = []
                cursor, window_end = instant(history[0]["opened_at"]),instant(history[-1]["scheduled_close_at"])
                while cursor < window_end:
                    boundary = min(cursor+timedelta(days=7),window_end)
                    expected_history.extend(t.isoformat() for t in expected_opens(calendar,tf,cursor,boundary))
                    cursor = boundary
                missing = set(expected_history)-{r["opened_at"] for r in history}
                normalized = tuple(normalizer.normalize(Candle(**r["candle"]),symbol="XAU/USD",timeframe=tf,
                    received_at=instant(r["assumed_available_at"]),provenance=provenance,
                    confirmation_observations=2) for r in history)
                # At most one cached native history per timeframe, bounded memory.
                for old in [key for key in cache if key[0] == tf]: cache.pop(old)
                cache[cache_key] = (missing, normalized)
            missing, normalized = cache[cache_key]
            if missing:
                unavailable.append(tf+":INTERNAL_HISTORY_GAP"); continue
            # confirmation_observations=2 is an EXPLICIT retrospective assumption,
            # never proof of two original captures. No PIT runner input is created.
            snapshots[tf] = TimeframeSnapshot("XAU/USD",tf,at,normalized,normalized[-1])
        if unavailable:
            for seed_id in active:
                invalidations.append({"setup_identifier":seed_id,"at":at.isoformat(),"reason":"REQUIRED_DATA_ELIGIBILITY_LOST"})
            active.clear()
            # A data gap must not leave a cached usable setup/parent behind.
            seed_rejections.extend(encode(evaluator.seed_rejections))
            evaluator = CaptureGoldLayerEvaluator()
            admissions.append({"at":at.isoformat(),"reason":"CAUSAL_HISTORY_UNAVAILABLE","details":unavailable,"knowledge":knowledge})
            continue
        try:
            m1 = rows["1m"][bisect_right(known_at["1m"],at)-1]
            units, unit_proof = historical_units(dataset["unit_manifest"],dataset["identity"],at,m1,
                                                engineering=dataset["evidence_kind"] == "ENGINEERING_SYNTHETIC")
            evaluator.broker_units = units
            canonical = evaluator.evaluate("XAU/USD",snapshots,evaluated_at=at,macro_degraded=False)
            state = evaluator._state.get("XAU/USD")
            for seed_id, prior in list(active.items()):
                expiry = instant(prior["expiry"])
                directional = StrategicState.LONG_ONLY if prior["side"] == "long" else StrategicState.SHORT_ONLY
                if at >= expiry:
                    invalidations.append({"setup_identifier":seed_id,"at":expiry.isoformat(),"reason":"SETUP_EXPIRED"}); active.pop(seed_id)
                elif state and state.strategy_context and state.strategy_context.state is not directional:
                    invalidations.append({"setup_identifier":seed_id,"at":at.isoformat(),"reason":"H1_DIRECTIONAL_AUTHORITY_LOST"}); active.pop(seed_id)
                elif state and state.setup_context and state.setup_context.identity.context_id != prior["m15_setup_id"]:
                    invalidations.append({"setup_identifier":seed_id,"at":at.isoformat(),"reason":"M15_SETUP_SUPERSEDED"}); active.pop(seed_id)
            seed = evaluator.capture_seed(canonical,calendar=calendar,broker_identity=dataset["identity"],at=at)
            admissions.append({"at":at.isoformat(),"canonical":encode(canonical),"seed_created":seed is not None,
                               "knowledge":knowledge,"historical_risk_inputs":unit_proof})
            if seed is not None and seed.association_id not in seen:
                seen.add(seed.association_id)
                assessed = f0.assess(seed,canonical=canonical)
                data = assessed.data
                # Keep original engine checksum and disclose its internal PIT
                # field's different meaning under this separate research adapter.
                data["unchanged_engine_sha256"] = assessed.sha256
                data["engine_internal_data_status"] = data["data_status"]
                data["data_status"] = "RETROSPECTIVE_RESEARCH_ASSUMED_AVAILABILITY"
                data["evidence_kind"] = dataset["evidence_kind"]
                data["pit_verified"] = False
                data["observed_price_kind"] = "HISTORICAL_CANDLE_REFERENCE_NOT_EXECUTABLE_QUOTE"
                data["historical_risk_inputs"] = unit_proof
                session_open, session_close = next((a,b) for a,b in calendar.sessions if a <= at < b)
                data["session_id"] = digest({"identity":dataset["identity"],"open":session_open.isoformat(),"close":session_close.isoformat()})
                data["session"] = {"open":session_open.isoformat(),"close":session_close.isoformat(),"decision_utc_hour":at.hour}
                data["advisory_regime"] = state.regime_context.evidence.get("regime","UNAVAILABLE") if state and state.regime_context else "UNAVAILABLE"
                records.append(data)
                seeds.append({"setup_identifier":seed.seed_id,"seed_hash":seed.record.sha256,"record":seed.record.data})
                active[seed.seed_id] = {"expiry":data["expiry"],"side":data["anchor"].get("episode_provenance",{}).get("active",{}).get("direction") if data["anchor"].get("episode_provenance",{}).get("active") else seed.objects()[1].direction,
                                       "m15_setup_id":data["m15_setup_id"]}
        except (ValueError,KeyError) as exc:
            for seed_id in active:
                invalidations.append({"setup_identifier":seed_id,"at":at.isoformat(),"reason":"RESEARCH_ELIGIBILITY_LOST"})
            active.clear()
            seed_rejections.extend(encode(evaluator.seed_rejections))
            evaluator = CaptureGoldLayerEvaluator()
            admissions.append({"at":at.isoformat(),"reason":str(exc),"knowledge":knowledge})
    output = {"schema":"gold-retrospective-replay-v1", "result_class":dataset["result_class"],
        "evidence_kind":dataset["evidence_kind"], "policy_id":POLICY,"h1_research_commit":H1_RESEARCH,
        "dataset_sha256":dataset["sha256"],"availability_policy":dataset["availability_policy"],
        "missing_original_observation_evidence":True,"execution_enabled":False,"pit_verified":False,
        "assessment_start":start.isoformat(),"assessment_end":end.isoformat(),
        "assessed_decisions":len(times),"missing_m1_decision_times":[t.isoformat() for t in missing_decisions],
        "admissions":admissions,"records":records,"seeds":seeds,
        "invalidations":invalidations,"seed_rejections":seed_rejections+encode(evaluator.seed_rejections),
        "diagnostics":diagnostics(records),"assumption":"Closed final download vintage is available at close+10s; original observation/finalization timestamps are unknown. Pivot right-window confirmation and original v1 selection remain unchanged."}
    output["sha256"] = digest(output)
    return output


def main(input_file,output_file):
    request = json.loads(Path(input_file).read_text())
    output = run(request["dataset"],assessment_start=request["assessment_start"],assessment_end=request["assessment_end"],
                 maximum_decisions=request.get("maximum_decisions",5000))
    path = Path(output_file)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x") as stream:
        stream.write(json.dumps(output,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n")
