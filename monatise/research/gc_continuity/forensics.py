"""Verified native/source-window diagnostics, never a download or candidate filter."""
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

from monatise.research.databento.acquisition import HistoricalRequest, inspect_request_archive
from monatise.research.databento.archive import NativeDBNArchive, dbn_records, sha256_file
from monatise.research.gc_fib.candles import GCIdentity, MINUTE, INTERVALS
from monatise.research.gc_qualification.models import digest
from monatise.research.gc_continuity import VERSION, PHASE3A
from monatise.research.gc_continuity.classification import classify
from monatise.research.gc_continuity.sessions import (
    status_sessions, complete_minute_sessions, expected_opens, expectation,
    nominal_gc_state, session_presentations,
)


def load(path):
    return json.loads(Path(path).read_text())


def metric_counts(records):
    """Disjoint meanings, overlapping per-timeframe reasons counted once per row."""
    return dict(
        scheduled_cutoffs=len(records),
        continuity_rejected=sum(any(":missing_or_no_trade_bar" in e or ":latest_expected_bar_missing" in e
                                   for e in r["rejection_reasons"]) for r in records),
        candle_transport_freshness_rejected=sum(any(":canonical_source_stale" in e for e in r["rejection_reasons"]) for r in records),
        quote_freshness_rejected=sum("quote_stale" in r["rejection_reasons"] for r in records),
        closed_session_rejected=sum("exchange_closed_or_unreviewed_session" in r["rejection_reasons"] for r in records),
    )


def scan(data_root, *, phase3a_root, repository):
    import databento_dbn as dbn
    root,old,repo = map(lambda p:Path(p).resolve(),(data_root,phase3a_root,repository))
    acceptance = load(repo/"docs/audits/gc-qualification-validation.json")
    for name,key in (("prepared-input.json","prepared_input_sha256"),("ledger-01.json","ledger_file_sha256"),
                     ("ledger-02.json","ledger_file_sha256")):
        if sha256_file(old/name) != acceptance[key]: raise ValueError("phase3a_evidence_changed")
    prepared,ledger = load(old/"prepared-input.json"),load(old/"ledger-01.json")
    archive = NativeDBNArchive.open_existing(root/"native-dbn")
    manifests,raw_minutes,statuses,counts = [],{},[],Counter()
    native_positions,trade_buckets,event_counts,trade_flags = set(),{},Counter(),Counter()
    duplicates = 0
    # Bind to the original immutable acceptance manifests, not arbitrary globbed
    # replacements. Quarantined artifacts are never scanned as market evidence.
    for item in prepared["source_archives"]:
        path = root/item["manifest_file"]
        if sha256_file(path) != item["manifest_sha256"]: raise ValueError("manifest_tampered")
        manifest = load(path)
        if "result" in manifest: manifest = manifest["result"]
        if manifest["status"] != "ARCHIVED": raise ValueError("quarantined_source_forbidden")
        r = dict(manifest["request"]);r["contracts"] = tuple(tuple(c) for c in r["contracts"])
        request = HistoricalRequest(**r)
        native = archive.verify(manifest["archive_sha256"])
        coverage = inspect_request_archive(native,request)
        if coverage != manifest["coverage"]: raise ValueError("native_coverage_changed")
        manifests.append({**item,"request_sha256":request.sha256,
            "continuity_certified":coverage["continuity_certified"],"transport_complete":coverage["transport_complete"]})
        counts[request.schema] += coverage["record_count"]
        if request.schema not in {"ohlcv-1m","status","trades"}: continue
        for ordinal,row in enumerate(r for r in dbn_records(native) if not isinstance(r,dbn.Metadata)):
            h = hashlib.sha256(bytes(row)).hexdigest()
            if (row.publisher_id,row.instrument_id) != (1,41271): raise ValueError("native_identity_changed")
            source = dict(archive_sha256=manifest["archive_sha256"],record_sha256=h,ordinal=ordinal,
                retrieval_ns=manifest["retrieval_ns"],admission_ns=manifest["ingestion_ns"],manifest_file=path.name)
            if request.schema == "ohlcv-1m":
                if row.ts_event in raw_minutes: raise ValueError("duplicate_or_revised_native_minute")
                raw_minutes[row.ts_event] = dict(**source,prices_fixed=[row.open,row.high,row.low,row.close],volume=row.volume)
            elif request.schema == "status":
                statuses.append(dict(**source,ts_event=str(row.ts_event),ts_recv=str(row.ts_recv),
                    is_trading=str(row.is_trading),is_quoting=str(row.is_quoting),action=str(row.action),reason=str(row.reason)))
            else:
                if str(row.action) != "T" or row.price % 100_000_000 or row.size <= 0:
                    raise ValueError("unsupported_executed_trade")
                if h in native_positions: duplicates += 1
                native_positions.add(h)
                trade_flags[row.flags] += 1
                t = row.ts_recv//MINUTE*MINUTE
                event_counts[row.ts_event//MINUTE*MINUTE] += 1
                if t not in trade_buckets:
                    trade_buckets[t] = dict(prices_fixed=[row.price]*4,volume=0,record_count=0,
                        source_hash_chain="0"*64,first_source=source,last_source=source)
                b = trade_buckets[t];p = b["prices_fixed"]
                p[1],p[2],p[3] = max(p[1],row.price),min(p[2],row.price),row.price
                b["volume"] += row.size;b["record_count"] += 1;b["last_source"] = source
                b["source_hash_chain"] = digest([b["source_hash_chain"],ordinal,h])
    if dict(counts) != acceptance["native_schema_record_counts"]: raise ValueError("native_record_counts_changed")
    review = load(root/"expanded-session-review-01.json")
    if sha256_file(root/"expanded-session-review-01.json") != prepared["session_review_sha256"]:
        raise ValueError("session_review_changed")
    expected_status = [{k:s[k] for k in ("ts_event","ts_recv","is_trading","is_quoting","action","reason")} for s in statuses]
    if sorted(expected_status,key=digest) != sorted(review["status_records"],key=digest):
        raise ValueError("native_status_lineage_mismatch")
    sessions = status_sessions(statuses,end_ns=max(m["end_ns"] for m in manifests))
    complete = complete_minute_sessions(sessions)
    if list(map(list,sessions)) != review["native_sessions"]:
        raise ValueError("independent_status_sessions_disagree_with_review")
    if list(complete) != [(s["start_ns"],s["end_ns"]) for s in prepared["sessions"]]:
        raise ValueError("independent_complete_minutes_disagree_with_review")
    bars = prepared["bars"]
    admitted = {b["open_ns"]:b for b in bars if b["timeframe"] == "1m"}
    first,last = min(admitted),max(admitted)+MINUTE
    expected = expected_opens(complete,width_ns=MINUTE,start_ns=first,end_ns=last)
    missing = sorted(set(expected)-set(admitted))
    normalization = load(root/"expanded-normalization-01.json")
    if missing != normalization["missing_or_no_trade_minutes_uncertified"]:
        raise ValueError("independent_missing_minute_schedule_disagrees")
    trade_requests = [m for m in manifests if m["schema"] == "trades"]
    ohlcv_requests = [m for m in manifests if m["schema"] == "ohlcv-1m"]
    records = []
    for t in missing:
        containing = [m for m in ohlcv_requests if m["start_ns"] <= t < t+MINUTE <= m["end_ns"]]
        trade_cover = [m for m in trade_requests if m["start_ns"] <= t < t+MINUTE <= m["end_ns"]]
        n = trade_buckets.get(t,{}).get("record_count",0) if trade_cover else None
        state = expectation(t,t+MINUTE,sessions=sessions)
        label = classify(session_state=state,raw_present=t in raw_minutes,admitted_present=False,trade_count=n,
                         independently_complete_trades=False)
        parents = []
        for tf,width in INTERVALS.items():
            if tf == "1m": continue
            start = t//(width*10**9)*(width*10**9)
            parents.append(dict(timeframe=tf,open_ns=start,end_ns=start+width*10**9,
                session_state=expectation(start,start+width*10**9,sessions=complete),
                observed_derived_bar=any(b["timeframe"] == tf and b["open_ns"] == start for b in bars)))
        records.append(dict(**label,start_ns=t,end_ns=t+MINUTE,utc=datetime.fromtimestamp(t//10**9,UTC).isoformat(),
            identity=asdict(GCIdentity()),session_state=state,nominal_regular_state=nominal_gc_state(t),
            source_ohlcv_requests=containing,trade_requests=trade_cover,native_ohlcv_present=t in raw_minutes,
            observed_trade_count=n,observed_event_clock_trade_count=event_counts[t] if trade_cover else None,
            evidence_availability="RETROSPECTIVE_ARCHIVE_ADMISSION",trade_continuity="UNCERTIFIED" if trade_cover else "NO_ARCHIVE",
            parent_omissions=parents,confidence=dict(native_absence="VERIFIED",cause="UNRESOLVED"),
            remedy="KEEP_REJECTED_PENDING_INDEPENDENT_COMPLETE_TRADE_EVIDENCE_OR_APPROVED_SOURCE_POLICY"))
    matches,mismatches = 0,[]
    for t,b in sorted(trade_buckets.items()):
        native = raw_minutes.get(t)
        if native and (native["prices_fixed"],native["volume"]) == (b["prices_fixed"],b["volume"]): matches += 1
        else: mismatches.append(t)
    # Data for the particular missing H4: all native observations remain visible;
    # absent September trade coverage is null, not an invented zero trade count.
    h4_start = 1789963200*10**9
    h4_end = h4_start+4*3600*10**9
    h4_minutes = [t for t in range(h4_start,h4_end,MINUTE) if t in raw_minutes]
    h4 = dict(identity=asdict(GCIdentity()),start_ns=h4_start,end_ns=h4_end,
        session_state=expectation(h4_start,h4_end,sessions=sessions),
        native_sessions=[list(s) for s in sessions if s[0] < h4_end and h4_start < s[1]],
        status_events_inside=[s for s in statuses if h4_start <= int(s["ts_event"]) < h4_end],
        native_ohlcv_minutes=len(h4_minutes),native_ohlcv_volume=sum(raw_minutes[t]["volume"] for t in h4_minutes),
        observed_trade_count=None,trade_archive_coverage=False,missing_child_minutes=[t for t in range(h4_start,h4_end,MINUTE) if t not in raw_minutes],
        expected_full_bucket=expectation(h4_start,h4_end,sessions=complete) == "FULLY_OPEN",
        root_cause="MISSING_CHILD_04_37_NO_TRADE_VERSUS_PROVIDER_LOSS_UNRESOLVED",classification="E",
        request_fully_covers_bucket=any(m["start_ns"] <= h4_start < h4_end <= m["end_ns"] for m in ohlcv_requests),
        transport_complete_does_not_certify_exchange_continuity=True,
        recovery="NOT_SUPPORTED_BY_EXISTING_TRADE_ARCHIVES",confidence="HIGH_FOR_OMISSION_MECHANISM_UNRESOLVED_FOR_CHILD_CAUSE")
    excluded = [dict(open_ns=t,source=raw_minutes[t],session_state=expectation(t,t+MINUTE,sessions=sessions),
        explanation="OBSERVED_NATIVE_BAR_EXCLUDED_BY_UNCHANGED_FULL_MINUTE_SESSION_POLICY") for t in sorted(set(raw_minutes)-set(admitted))]
    propagation = Counter()
    for r in ledger["records"]:
        for tf,evidence in r["candle_evidence"].items():
            for t in evidence["missing_or_no_trade_opens_ns"]: propagation[(tf,t)] += 1
    missing_derived = []
    for tf,width in INTERVALS.items():
        if tf == "1m": continue
        present = {b["open_ns"] for b in bars if b["timeframe"] == tf}
        starts = expected_opens(complete,width_ns=width*10**9,start_ns=min(present),end_ns=max(present)+width*10**9)
        for t in sorted(set(starts)-present):
            children = [r["start_ns"] for r in records if t <= r["start_ns"] < t+width*10**9]
            missing_derived.append(dict(timeframe=tf,open_ns=t,end_ns=t+width*10**9,
                missing_children_ns=children,classification="E",phase3a_affected_cutoffs=propagation[(tf,t)],
                source="STRICT_FULL_CHILD_AGGREGATION_POLICY",recovery_eligible=False))
    return dict(schema=VERSION,phase3a_commit=PHASE3A,phase3a_ledger_sha256=acceptance["ledger_sha256"],
        phase3a_input_sha256=acceptance["prepared_input_sha256"],original_metrics=metric_counts(ledger["records"]),
        archive_record_counts=dict(counts),native_archives=manifests,raw_archives_modified=False,
        status_sessions_independently_equal=True,expected_minutes_independently_equal=True,
        sessions=session_presentations(sessions),session_review_sha256=prepared["session_review_sha256"],
        missing_minutes=records,missing_derived_buckets=missing_derived,excluded_native_minutes=excluded,
        h4_investigation=h4,trade_reconciliation=dict(trade_records=counts["trades"],native_byte_repeats=duplicates,
            identical_bytes_are_not_unique_trade_ids=True,flags=dict(trade_flags),
            observed_minutes=len(trade_buckets),native_ohlcv_exact_matches=matches,discrepancies=mismatches,
            multiplicity_preserved=True,continuity_certified=False),
        classifications=dict(Counter(r["classification"] for r in records)),
        recoveries_admitted=0,synthetic_price_bars=0,new_databento_usage_usd="0",
        proposed_policy_changes_activated=False)
