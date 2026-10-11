"""Deterministic point-in-time preparation only; no selector or engine changes."""
from __future__ import annotations

from datetime import timedelta

from monatise.application.hierarchy.candles import CandleBoundaryNormalizer
from monatise.application.hierarchy.coordinator import HierarchyConfiguration
from monatise.application.hierarchy.models import Provenance
from monatise.core.models import Candle
from monatise.engines.liquidity import LiquidityRequest
from monatise.engines.regime import RegimeRequest
from monatise.research.broker_xauusd import CANONICAL_SOURCE
from monatise.research.broker_xauusd.models import KINDS, TIMEFRAMES, digest, expected_opens, instant


async def prepare_replay(archive, *, cutoff, start, end, evidence_kind):
    """No eventual-OHLC substitution: use only admitted versions at cutoff.

    Finalization requires two distinct increasing captures of identical content
    after the actual close + canonical grace, and both must have been admitted.
    New content revokes prior finalization until independently observed again.
    Retrospective series remain descriptive even if downloaded twice.
    """
    if evidence_kind not in KINDS:
        raise ValueError("explicit replay evidence kind required")
    now = instant(cutoff)
    all_batches = await archive.batches(cutoff=now)
    batches = [b for b in all_batches if b["evidence_kind"] == evidence_kind]
    states, events, rejections, observations, all_availability = {}, [], [], [], set()
    normalizer = CandleBoundaryNormalizer()
    provenance = Provenance("ftmo_mt5_archive", archive.identity.server, "XAU/USD", "broker-archive-v1", "hierarchy-candle-v1")
    latest_units = None
    for batch in batches:
        available, captured = instant(batch["availability_at"]), instant(batch["raw_payload"]["captured_at"])
        if available in all_availability:
            rejections.append({"batch_id": batch["batch_id"], "reason": "AMBIGUOUS_OBSERVATION_AVAILABILITY"})
        all_availability.add(available)
        latest_units = {k: batch["raw_payload"][k] for k in ("point", "tick_size", "spread_price")}
        accepted_frames, touched = {}, set()
        for row in batch["rows"]:
            key = (row["timeframe"], row["opened_at"])
            previous = states.get(key)
            if previous is not None and captured <= previous["captured"]:
                rejections.append({"batch_id": batch["batch_id"], "timeframe": key[0], "opened_at": key[1],
                    "reason": "DUPLICATE_CAPTURE" if captured == previous["captured"] else "OUT_OF_ORDER_CAPTURE"})
                continue
            revision = previous is not None and previous["row"]["value_sha256"] != row["value_sha256"]
            if revision and previous["row"]["content_hash"] == row["content_hash"]:
                rejections.append({"batch_id": batch["batch_id"], "reason": "NORMALIZER_HASH_COLLISION"})
            closed = captured >= instant(row["scheduled_close_at"]) + timedelta(seconds=normalizer.grace_seconds)
            stable_previous = previous is not None and not revision and previous["closed"]
            confirmations = 2 if closed and stable_previous else 1
            normalized = normalizer.normalize(Candle(**row["candle"]), symbol="XAU/USD", timeframe=key[0],
                received_at=captured, provenance=provenance, confirmation_observations=confirmations)
            final = normalized.is_final
            first_final = (previous["first_final"] if stable_previous and previous["final"] else available) if final else None
            states[key] = {"row": row, "captured": captured, "closed": closed, "final": final,
                "first_final": first_final, "batch_id": batch["batch_id"], "availability": available}
            events.append({"batch_id": batch["batch_id"], "timeframe": key[0], "opened_at": key[1],
                "content_hash": row["content_hash"], "value_sha256": row["value_sha256"], "availability_at": available.isoformat(),
                "captured_at": captured.isoformat(), "revision": revision,
                "confirmation_observations": confirmations, "is_final": final,
                "first_final_available_at": first_final.isoformat() if first_final else None,
                "point_in_time_eligible": final and evidence_kind != "RETROSPECTIVE_HISTORICAL_DOWNLOAD"})
            if closed:
                touched.add(key[0])
        # Export only genuinely closed-at-capture rows. Availability replaces
        # bar-close time as observation time; no historical warmup is invented.
        for tf in touched:
            accepted_frames[tf] = [s["row"]["candle"] for k, s in sorted(states.items()) if k[0] == tf and s["closed"]]
        if accepted_frames:
            try:
                archive.calendar.require_regular_session(available)
            except ValueError:
                rejections.append({"batch_id": batch["batch_id"], "reason": "ADMISSION_OUTSIDE_REGULAR_SESSION"})
            else:
                observations.append({"at": available.isoformat(), "candles": accepted_frames})
    coverage = {}
    for tf in TIMEFRAMES:
        expected = expected_opens(archive.calendar, tf, start, end, cutoff=now)
        missing, unfinalized = [], []
        for opened in expected:
            state = states.get((tf, opened.isoformat()))
            if state is None:
                missing.append(opened.isoformat())
            elif not state["final"]:
                unfinalized.append(opened.isoformat())
        try:
            latest_expected = archive.calendar.expected_closed_open(tf, now).isoformat()
        except ValueError:
            latest_expected = None
        latest = states.get((tf, latest_expected))
        coverage[tf] = {"expected": len(expected), "missing": missing, "unfinalized": unfinalized,
                       "latest_expected_open": latest_expected,
                       "latest_expected_finalized": bool(latest and latest["final"]),
                       "available_rows": sum(k[0] == tf for k in states),
                       "finalized_rows": sum(k[0] == tf and s["final"] for k, s in states.items())}
    blockers = []
    minimum_history = max(RegimeRequest.__dataclass_fields__["slow_window"].default,
                          LiquidityRequest.__dataclass_fields__["range_window"].default)
    if any(c["finalized_rows"] < minimum_history for c in coverage.values()):
        blockers.append("CANONICAL_MINIMUM_HISTORY_UNAVAILABLE")
    if evidence_kind == "RETROSPECTIVE_HISTORICAL_DOWNLOAD":
        blockers.append("HISTORICAL_AVAILABILITY_NOT_OBSERVED")
    if not batches:
        blockers.append("NO_ADMITTED_OBSERVATIONS")
    if any(c["missing"] or c["unfinalized"] or not c["latest_expected_finalized"] for c in coverage.values()):
        blockers.append("REQUIRED_FINALIZED_COVERAGE_UNAVAILABLE")
    if any(r["reason"] == "AMBIGUOUS_OBSERVATION_AVAILABILITY" for r in rejections):
        blockers.append("AMBIGUOUS_OBSERVATION_AVAILABILITY")
    if any(r["reason"] == "NORMALIZER_HASH_COLLISION" for r in rejections):
        blockers.append("NORMALIZER_HASH_COLLISION")
    if any(len(rows) > 5000 for o in observations for rows in o["candles"].values()):
        blockers.append("F0_HISTORY_ROW_LIMIT_EXCEEDED")
    try:
        archive.calendar.require_regular_session(now)
    except ValueError:
        blockers.append("ASSESSMENT_OUTSIDE_REGULAR_SESSION")
    # A proof reference is an external-review requirement, not authentication.
    if evidence_kind == "POINT_IN_TIME_OBSERVATION":
        blockers.append("CAPTURE_PROOF_REQUIRES_PHASE4_INDEPENDENT_REVIEW")
    artifact = {"schema": "broker-xauusd-replay-preparation-v1", "evidence_kind": evidence_kind,
        "cutoff": now.isoformat(), "window": {"start": instant(start).isoformat(), "end": instant(end).isoformat()},
        "namespace": archive.namespace, "calendar_fingerprint": archive.calendar.fingerprint,
        "batch_ids": [b["batch_id"] for b in batches], "events": events, "coverage": coverage,
        "batch_provenance": [{k: b[k] for k in ("batch_id", "body_sha256", "raw_sha256", "evidence_kind",
            "source_reference", "capture_proof_reference", "capture_proof_verified_by_archive", "calendar_fingerprint",
            "capture_calendar_fingerprint", "availability_at")} for b in batches],
        "rejections": rejections, "blockers": blockers, "observations": observations,
        "broker_units": latest_units, "execution_enabled": False, "selector_invoked": False,
        "canonical_default_candle_limit": HierarchyConfiguration().candle_limit,
        "canonical_minimum_history": minimum_history,
        "canonical_default_history_complete": all(c["finalized_rows"] >= HierarchyConfiguration().candle_limit for c in coverage.values()),
        "phase4_ready": False,
        "f0_input_ready": not blockers}
    artifact["sha256"] = digest(artifact)
    return artifact


def f0_input(archive, prepared):
    """Produce the existing selector's input contract; never run it here.

    Phase 3 can export synthetic engineering material only. Real capture review
    remains a Phase 4 gate; historical downloads cannot satisfy this contract.
    """
    if digest({k: v for k, v in prepared.items() if k != "sha256"}) != prepared.get("sha256"):
        raise ValueError("preparation integrity failure")
    if prepared["namespace"] != archive.namespace or not prepared["f0_input_ready"]:
        raise ValueError("replay preparation blocked:" + ",".join(prepared["blockers"]))
    if prepared["evidence_kind"] != "ENGINEERING_SYNTHETIC":
        raise ValueError("real-market replay requires separate Phase 4 review")
    return {"schema": "gold-h1-fib-observation-archive-v1", "evidence_kind": "ENGINEERING_SYNTHETIC",
        "source_commit": CANONICAL_SOURCE, "source_version": "broker-archive-v1",
        "calendar": archive.calendar_manifest,
        "broker_identity": {"broker": archive.identity.broker, "broker_symbol": archive.identity.broker_symbol,
                            "account_id": archive.identity.account_id, "server": archive.identity.server, "symbol": "XAU/USD"},
        "broker_units": prepared["broker_units"], "observations": prepared["observations"],
        "archive_provenance": {"preparation_sha256": prepared["sha256"], "batch_ids": prepared["batch_ids"],
                               "batches": prepared["batch_provenance"]}}
