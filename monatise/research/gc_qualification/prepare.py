"""Read-only native verification and predeclared quote sampling; no data client."""
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
import hashlib
import json

from monatise.adapters.databento_identity import DatabentoPublisherPolicy
from monatise.research.databento.acquisition import HistoricalRequest, inspect_request_archive
from monatise.research.databento.archive import NativeDBNArchive, dbn_records, sha256_file
from monatise.research.gc_fib.native_contract import reconstruct_native_gcz6
from monatise.research.gc_fib.worker import parse_bar
from monatise.research.gc_qualification import AVAILABILITY, BASELINE, FROZEN, SAFETY, VERSION
from monatise.research.gc_qualification.models import NativeContract, digest, research_sources
from monatise.application.take_profit import encode
from monatise.research.gc_qualification.adapter import required_history

# Declared by admitted MBP-1 request boundaries BEFORE qualification is run.
START = 1791158400 * 10**9
END = 1791401400 * 10**9  # October 7 19:30 UTC exclusive
MINUTE = 60 * 10**9
GRACE = 10 * 10**9
QUOTE_MAX_AGE_NS = 60 * 10**9  # conservative research receipt admission; no strategy calibration


def load(path):
    return json.loads(Path(path).read_text())


def verify_bar_lineage(data, minute_sources):
    bars = tuple(parse_bar(b) for b in data["bars"])
    keys = [(b.timeframe,b.open_ns) for b in bars]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate_or_revised_bars")
    minutes = {b.open_ns:b for b in bars if b.timeframe == "1m"}
    for bar in minutes.values():
        if len(bar.source_hashes) != 1 or bar.source_hashes[0] not in minute_sources:
            raise ValueError("unadmitted_minute_source")
        record,manifest = minute_sources[bar.source_hashes[0]]
        if (record.publisher_id,record.instrument_id,record.ts_event) != (1,41271,bar.open_ns):
            raise ValueError("native_minute_identity_mismatch")
        if any(Decimal(getattr(bar,k)) != Decimal(getattr(record,k))/Decimal(10**9)
               for k in ("open","high","low","close")) or bar.volume != record.volume:
            raise ValueError("native_minute_price_or_volume_mismatch")
        if (bar.retrieval_ns,bar.admission_ns) != (manifest["retrieval_ns"],manifest["ingestion_ns"]):
            raise ValueError("native_minute_acquisition_clock_mismatch")
        if any(Decimal(getattr(bar,k)) % Decimal(".1") for k in ("open","high","low","close")):
            raise ValueError("minute_off_native_tick")
    for bar in bars:
        if bar.timeframe == "1m": continue
        children = [minutes[t] for t in range(bar.open_ns,bar.close_ns,MINUTE)]
        expected = (Decimal(children[0].open),max(Decimal(c.high) for c in children),
                    min(Decimal(c.low) for c in children),Decimal(children[-1].close))
        if tuple(Decimal(getattr(bar,k)) for k in ("open","high","low","close")) != expected:
            raise ValueError("derived_OHLC_mismatch")
        if bar.volume != sum(c.volume for c in children) or bar.source_hashes != tuple(h for c in children for h in c.source_hashes):
            raise ValueError("derived_lineage_or_volume_mismatch")
        if (bar.retrieval_ns,bar.admission_ns) != (max(c.retrieval_ns for c in children),max(c.admission_ns for c in children)):
            raise ValueError("derived_acquisition_clock_mismatch")
    return bars


def prepare(root, output, *, repository):
    import databento_dbn as dbn
    root,output,repository = Path(root).resolve(),Path(output).resolve(),Path(repository).resolve()
    baseline = load(repository/"docs/audits/databento-cme-validation.json")
    archive = NativeDBNArchive.open_existing(root/"native-dbn")
    catalog = load(root/"publisher-catalog-01.json")
    policy = DatabentoPublisherPolicy.from_metadata(catalog["rows"],observed_at_ns=catalog["observed_at_ns"],
                                                   source_sha256=sha256_file(root/"publisher-catalog-01.json"))
    manifests,minutes,definitions,statuses,quotes = [],{},[],[],[]
    # Admission is anchored to the audited implementation's exact manifest hashes.
    for item in baseline["native_archives"]:
        path = root/item["manifest_file"]
        if sha256_file(path) != item["manifest_sha256"]:
            raise ValueError("changed_acquisition_manifest")
        manifest = load(path)
        if "result" in manifest: manifest = manifest["result"]
        if manifest["status"] != "ARCHIVED" or manifest["archive_sha256"] != item["archive_sha256"]:
            raise ValueError("quarantined_or_mismatched_archive")
        data = dict(manifest["request"]); data["contracts"] = tuple(tuple(c) for c in data["contracts"])
        request = HistoricalRequest(**data)
        native_path = archive.verify(item["archive_sha256"])
        if inspect_request_archive(native_path,request) != manifest["coverage"]:
            raise ValueError("native_request_coverage_mismatch")
        manifests.append({**item,"start_ns":request.start_ns,"end_ns":request.end_ns,
                          "retrieval_ns":manifest["retrieval_ns"],"admission_ns":manifest["ingestion_ns"]})
        if request.schema == "mbp-1":
            quotes.append((request,manifest,native_path)); continue
        if request.schema == "trades": continue
        for record in dbn_records(native_path):
            if isinstance(record,dbn.Metadata): continue
            sha = hashlib.sha256(bytes(record)).hexdigest()
            if request.schema == "ohlcv-1m":
                if sha in minutes: raise ValueError("duplicate_native_minute")
                minutes[sha] = (record,manifest)
            elif request.schema == "definition":
                reference = reconstruct_native_gcz6(record,identity_policy=policy,retrieval_ns=manifest["retrieval_ns"])
                definitions.append(asdict(reference))
            elif request.schema == "status":
                statuses.append(dict(action=str(record.action),is_quoting=str(record.is_quoting),
                    is_trading=str(record.is_trading),reason=str(record.reason),
                    ts_event=str(record.ts_event),ts_recv=str(record.ts_recv)))
    input_path = root/"expanded-gc-h1-input-01.json"
    if sha256_file(input_path) != baseline["input_sha256"]:
        raise ValueError("changed_derived_input")
    data = load(input_path); bars = verify_bar_lineage(data,minutes)
    if data["pit_verified"] is not False or data["evidence_kind"] != "AUTHENTIC_HISTORICAL_DOWNLOAD":
        raise ValueError("explicit_authentic_retrospective_input_required")
    review = load(root/"expanded-session-review-01.json")
    if sorted(review["status_records"],key=digest) != sorted(statuses,key=digest):
        raise ValueError("reviewed_sessions_native_status_lineage_mismatch")
    chosen = next(d for d in definitions if d["reference"]["definition_receive_ns"] == START)
    ref = chosen["reference"]
    contract = NativeContract(bars[0].identity,ref["definition_sha256"],ref["catalog_sha256"],
        ref["definition_event_ns"],ref["definition_receive_ns"],ref["expiration_ns"],
        str(ref["contract"]["tick"]),str(ref["contract"]["multiplier"]),
        str(Decimal(str(ref["contract"]["tick"]))*Decimal(str(ref["contract"]["multiplier"]))),
        tuple(tuple(t) for t in chosen["native_terms"]))
    cutoffs = tuple(t+MINUTE+GRACE for t in range(START,END,MINUTE) if t+MINUTE+GRACE < END)
    # Stream every admitted top-of-book event; retain only the final as-of event
    # at each declared minute cutoff. Never use a future record or skip a bad BBO.
    samples,latest,index,previous_receive = {},None,0,0
    coverage = []
    for request,manifest,path in sorted(quotes,key=lambda v:v[0].start_ns):
        coverage.append((request.start_ns,request.end_ns))
        for ordinal,record in enumerate(r for r in dbn_records(path) if not isinstance(r,dbn.Metadata)):
            if record.ts_recv < previous_receive:
                raise ValueError("quote_receive_order_regressed")
            previous_receive = record.ts_recv
            while index < len(cutoffs) and cutoffs[index] < record.ts_recv:
                samples[str(cutoffs[index])] = latest; index += 1
            level = record.levels[0]
            valid = lambda p: str(Decimal(p)/Decimal(10**9)) if 0 < p < 2**63-1 else None
            latest = dict(event_ns=record.ts_event,receive_ns=record.ts_recv,
                admission_ns=manifest["ingestion_ns"],retrieval_ns=manifest["retrieval_ns"],
                bid=valid(level.bid_px),ask=valid(level.ask_px),archive_sha256=manifest["archive_sha256"],
                record_sha256=hashlib.sha256(bytes(record)).hexdigest(),ordinal=ordinal,
                publisher_id=record.publisher_id,instrument_id=record.instrument_id)
        print(f"Verified quote partition {request.start_ns} -> {request.end_ns}",flush=True)
    while index < len(cutoffs):
        samples[str(cutoffs[index])] = latest; index += 1
    frozen_path = root/"expanded-gc-h1-report-01.json"
    if sha256_file(frozen_path) != baseline["replay_sha256"]:
        raise ValueError("changed_frozen_associations")
    config = dict(schema=VERSION,decision_grid="UTC_M1_CLOSE_PLUS_10S",start_ns=START,end_ns=END,
        quote_max_age_ns=QUOTE_MAX_AGE_NS,history_limit=200,minimum_history=50,
        admission_policy_version="gc-admission-v2-h4-regime-warmup-correction",
        minimum_history_by_timeframe={tf:required_history(tf) for tf in ("4h","1h","15m","5m","1m")},
        continuity_policy_amendment_approved=False,
        native_point_convention="MINIMUM_EXCHANGE_PRICE_QUANTUM_EQUALS_TICK",
        session_policy="REVIEWED_NATIVE_STATUS_COMPLETE_MINUTES",h4_anchor="UTC_GRID_UNCHANGED",
        continuity_policy="REJECT_ANY_MISSING_EXPECTED_BAR_IN_CONFIGURED_200_BAR_WINDOW",
        source_commit=BASELINE,frozen_commit=FROZEN,research_source_hashes=research_sources(repository),
        additional_databento_budget_usd="0",
        exact_canonical_parity_claim=False,
        differences=["native_gc_identity_and_exchange_volume", "retrospective_availability_and_sessions",
                     "observed_mbp1_spread", "native_0.1_target_tick_and_inward_rounding",
                     "target_independent_preparation_in_place_of_target_dependent_preliminary_risk"])
    value = dict(schema=VERSION,**SAFETY,pit_verified=False,historical_availability=AVAILABILITY,
        configuration=config,configuration_sha256=digest(config),contract=asdict(contract),
        source_archives=manifests,derived_input_sha256=baseline["input_sha256"],
        session_review_sha256=sha256_file(root/"expanded-session-review-01.json"),
        definition_review_sha256=sha256_file(root/"definition-validation-02-native.json"),
        native_definitions=definitions,quarantined_manifests=baseline["quarantined_manifests"],
        sessions=review["conservative_complete_minute_sessions"],bars=data["bars"],
        cutoffs_ns=cutoffs,quotes=samples,quote_coverage=coverage,
        frozen_associations=load(frozen_path)["records"],frozen_associations_sha256=baseline["replay_sha256"],
        new_databento_usage_usd="0",cache_action="REUSE_VERIFIED_ADMITTED_ARCHIVES")
    with output.open("x") as out: json.dump(encode(value),out,sort_keys=True,separators=(",",":"),allow_nan=False)
    output.chmod(0o400)
    return dict(prepared_input_sha256=sha256_file(output),native_archives=len(manifests),
                source_matched_minutes=len([b for b in bars if b.timeframe == "1m"]),scheduled_cutoffs=len(cutoffs))
