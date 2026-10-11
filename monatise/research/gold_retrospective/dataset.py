"""Frozen download vintages and explicitly assumed research availability."""
from __future__ import annotations

import json
from datetime import timedelta

from monatise.application.gold_sessions import GoldSessionCalendar
from monatise.application.hierarchy.policy import INTERVAL_SECONDS
from monatise.application.hierarchy.candles import CandleBoundaryNormalizer
from monatise.research.broker_xauusd.models import BrokerIdentity, TIMEFRAMES, canonical, digest, expected_opens, instant
from monatise.research.gold_retrospective import AVAILABILITY_POLICY, H1_RESEARCH, POLICY

GRACE_SECONDS = CandleBoundaryNormalizer().grace_seconds


def coverage(calendar, rows, *, start, end):
    start, end = instant(start), instant(end)
    if not calendar.start <= start < end <= calendar.end or end-start > timedelta(days=90):
        raise ValueError("bounded reviewed dataset window required (maximum 90 days)")
    result = {}
    for tf in TIMEFRAMES:
        expected = []
        cursor = start
        while cursor < end:
            boundary = min(cursor+timedelta(days=7),end)
            expected.extend(expected_opens(calendar,tf,cursor,boundary))
            cursor = boundary
        available = [r["opened_at"] for r in rows if r["timeframe"] == tf]
        result[tf] = {"expected":len(expected), "available":len(available),
            "missing": sorted(set(t.isoformat() for t in expected)-set(available)),
            "duplicate_opens": len(available)-len(set(available)),
            "first":min(available) if available else None, "last":max(available) if available else None}
    return result


def historical_units(manifest, identity, at, row, *, engineering):
    """Capture-date point/tick/spread cannot silently become historical risk inputs."""
    at = instant(at)
    if manifest.get("schema") != "gold-historical-units-v1" or manifest.get("identity") != identity:
        raise ValueError("reviewed historical broker unit identity required")
    matches = [era for era in manifest["eras"] if instant(era["from"]) <= at < instant(era["until"])]
    if len(matches) != 1:
        raise ValueError("historical unit coverage unavailable or ambiguous")
    era = matches[0]
    from math import isfinite
    if not era.get("review_reference") or any(type(era.get(k)) not in (int,float) or not isfinite(era[k]) or era[k] <= 0 for k in ("point","tick_size")):
        raise ValueError("historical point/tick review unavailable")
    spread_points = row["original"].get("spread_points")
    if type(spread_points) is int and spread_points > 0:
        spread = spread_points*era["point"]
        source = "REPORTED_BAR_SPREAD_ESTIMATE_NOT_EXECUTABLE_QUOTE"
    elif engineering and type(era.get("engineering_spread_price")) in (int,float) and isfinite(era["engineering_spread_price"]) and era["engineering_spread_price"] >= 0:
        spread = era["engineering_spread_price"]
        source = "ENGINEERING_SPREAD_ASSUMPTION"
    else:
        raise ValueError("historical spread evidence unavailable")
    return {"point":era["point"], "tick_size":era["tick_size"], "spread_price":spread}, {
        "review_reference":era["review_reference"], "spread_source":source, "execution_quote":False}


async def build_dataset(archive, *, cutoff, start, end, evidence_kind, unit_manifest, source_review=None):
    if evidence_kind not in {"ENGINEERING_SYNTHETIC", "RETROSPECTIVE_HISTORICAL_DOWNLOAD"}:
        raise ValueError("retrospective research requires an explicit download vintage")
    start,end = instant(start),instant(end)
    batches = [b for b in await archive.batches(cutoff=cutoff) if b["evidence_kind"] == evidence_kind]
    chosen, revisions, sources, exclusions = {}, [], [], []
    for batch in batches:
        sources.append({k:batch[k] for k in ("batch_id","body_sha256","raw_sha256","availability_at","source_reference","evidence_kind")})
        for row in batch["rows"]:
            if not start <= instant(row["opened_at"]) < end:
                continue
            if instant(batch["raw_payload"]["captured_at"]) < instant(row["scheduled_close_at"])+timedelta(seconds=GRACE_SECONDS):
                exclusions.append({"batch_id":batch["batch_id"],"timeframe":row["timeframe"],"opened_at":row["opened_at"],"reason":"FORMING_AT_DOWNLOAD_CAPTURE"})
                continue
            key = (row["timeframe"],row["opened_at"])
            prior = chosen.get(key)
            if prior and prior["value_sha256"] != row["value_sha256"]:
                revisions.append({"timeframe":key[0], "opened_at":key[1], "old_hash":prior["value_sha256"],
                                  "new_hash":row["value_sha256"], "batch_id":batch["batch_id"]})
            # Vintage choice uses admitted ordering, not a fictional historical
            # observation. Every later revision remains disclosed in provenance.
            selected = {**row, "batch_id":batch["batch_id"], "body_sha256":batch["body_sha256"],
                "captured_at":batch["raw_payload"]["captured_at"], "received_at":batch["raw_payload"]["received_at"],
                "archive_available_at":batch["availability_at"],
                "assumed_available_at":(instant(row["scheduled_close_at"])+timedelta(seconds=GRACE_SECONDS)).isoformat(),
                "original_observation_availability":None, "original_finalization_observations":None}
            ambiguous = bool(prior and prior["archive_available_at"] == batch["availability_at"] and
                             (prior.get("vintage_ordering_ambiguous") or prior["value_sha256"] != row["value_sha256"]))
            selected["vintage_ordering_ambiguous"] = ambiguous
            if ambiguous:
                exclusions.append({"batch_id":batch["batch_id"],"timeframe":row["timeframe"],
                    "opened_at":row["opened_at"],"reason":"AMBIGUOUS_VINTAGE_ORDERING"})
            chosen[key] = selected
    rows = [chosen[key] for key in sorted(chosen) if not chosen[key]["vintage_ordering_ambiguous"]]
    if len(rows) > 200_000:
        raise ValueError("bounded research row limit exceeded")
    report = coverage(archive.calendar,rows,start=start,end=end)
    payload = {"schema":"gold-retrospective-dataset-v1", "evidence_kind":evidence_kind,
        "result_class":"ENGINEERING_TEST_RESULTS" if evidence_kind == "ENGINEERING_SYNTHETIC" else "RETROSPECTIVE_RESEARCH",
        "policy_id":POLICY, "h1_research_commit":H1_RESEARCH, "availability_policy":AVAILABILITY_POLICY,
        "identity":archive.identity.__dict__, "calendar":archive.calendar_manifest,
        "calendar_fingerprint":archive.calendar.fingerprint, "start":start.isoformat(),"end":end.isoformat(),
        "vintage_cutoff":instant(cutoff).isoformat(), "vintage_policy":"LATEST_ADMITTED_AT_FROZEN_CUTOFF",
        "unit_manifest":json.loads(canonical(unit_manifest)), "source_review":source_review,
        "source_authenticity":"ENGINEERING_SYNTHETIC" if evidence_kind == "ENGINEERING_SYNTHETIC" else "REQUIRES_INDEPENDENT_REVIEW",
        "rows":rows, "source_batches":sources, "revisions":revisions, "coverage":report,"exclusions":exclusions,
        "missing_original_observation_evidence":True, "assumed_finalization":"ONE_FINAL_VINTAGE_AFTER_CLOSE_PLUS_10_SECONDS",
        "execution_enabled":False, "pit_verified":False}
    payload["sha256"] = digest(payload)
    return payload


def validate_dataset(dataset):
    if dataset.get("schema") != "gold-retrospective-dataset-v1" or digest({k:v for k,v in dataset.items() if k != "sha256"}) != dataset.get("sha256"):
        raise ValueError("research dataset integrity failure")
    if dataset.get("evidence_kind") not in {"ENGINEERING_SYNTHETIC","RETROSPECTIVE_HISTORICAL_DOWNLOAD"} or dataset.get("pit_verified") is not False or dataset.get("execution_enabled") is not False:
        raise ValueError("retrospective evidence/isolation contract violated")
    if dataset.get("policy_id") != POLICY or dataset.get("availability_policy") != AVAILABILITY_POLICY or dataset.get("h1_research_commit") != H1_RESEARCH:
        raise ValueError("fixed research policy mismatch")
    calendar = GoldSessionCalendar.from_manifest(dataset["calendar"])
    identity = BrokerIdentity(**dataset["identity"])
    identity.validate_calendar(calendar)
    if calendar.fingerprint != dataset["calendar_fingerprint"]:
        raise ValueError("calendar integrity failure")
    if dataset["evidence_kind"] != "ENGINEERING_SYNTHETIC":
        review = dataset.get("source_review") or {}
        if (not review.get("review_reference") or review.get("source_batches_sha256") != digest(dataset["source_batches"])
            or review.get("rows_sha256") != digest(dataset["rows"])
            or review.get("unit_manifest_sha256") != digest(dataset["unit_manifest"])
            or review.get("calendar_fingerprint") != dataset["calendar_fingerprint"]):
            raise ValueError("independent source-vintage review required before market research")
    from monatise.core.models import Candle
    seen = set()
    for row in dataset["rows"]:
        tf = row["timeframe"]
        if tf not in TIMEFRAMES:
            raise ValueError("unsupported research timeframe")
        opened = calendar.normalize_broker_epoch(row["original"]["t_broker"])
        if opened.isoformat() != row["opened_at"] or not calendar.regular_bar(opened,tf):
            raise ValueError("historical timestamp/session mismatch")
        close = opened+timedelta(seconds=INTERVAL_SECONDS[tf])
        if row["scheduled_close_at"] != close.isoformat() or row["assumed_available_at"] != (close+timedelta(seconds=GRACE_SECONDS)).isoformat():
            raise ValueError("causal availability assumption mismatch")
        if row["original_observation_availability"] is not None or row["original_finalization_observations"] is not None:
            raise ValueError("retrospective evidence cannot claim original observation proof")
        if row.get("vintage_ordering_ambiguous"):
            raise ValueError("ambiguous vintage must be excluded")
        c = Candle(**row["candle"]); c.validate()
        from math import isfinite
        if any(type(v) not in (int,float) or not isfinite(v) for v in (c.open,c.high,c.low,c.close,c.volume)):
            raise ValueError("finite native numeric OHLCV required")
        if c.low <= 0 or c.volume < 0 or not instant(dataset["start"]) <= opened < instant(dataset["end"]):
            raise ValueError("invalid vintage range/price/volume")
        if not instant(row["captured_at"]) <= instant(row["received_at"]) <= instant(row["archive_available_at"]) <= instant(dataset["vintage_cutoff"]):
            raise ValueError("original provenance clock order invalid")
        if instant(row["captured_at"]) < close+timedelta(seconds=GRACE_SECONDS):
            raise ValueError("forming captured vintage cannot become assumed final history")
        if c.timestamp != row["opened_at"] or digest(row["candle"]) != row["value_sha256"]:
            raise ValueError("candle identity/value integrity failure")
        if tuple(row["original"][k] for k in ("o","h","l","c","v")) != (c.open,c.high,c.low,c.close,c.volume):
            raise ValueError("original OHLCV mismatch")
        if (tf,opened) in seen:
            raise ValueError("duplicate vintage candle")
        seen.add((tf,opened))
    return calendar
