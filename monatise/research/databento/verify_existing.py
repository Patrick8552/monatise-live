"""Offline verification of existing authorized GC artifacts and frozen replay.

Usage: python -m monatise.research.databento.verify_existing --data-root PATH
       --h1-checkout PATH --output NEW_DIRECTORY
Creates versioned local outputs; makes no provider, broker or production calls.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from monatise.research.databento.acquisition import HistoricalRequest, inspect_request_archive
from monatise.research.databento.archive import NativeDBNArchive, dbn_records, sha256_file
from monatise.research.databento.controls import ResearchLedger
from monatise.research.gc_fib import ISOLATION
from monatise.research.gc_fib.runner import run_diagnostics
from monatise.research.gold_retrospective.runner import verify_research_checkout


def load(path):
    return json.loads(path.read_text())


def verify(*, data_root, h1_checkout, output):
    root,output = Path(data_root).resolve(),Path(output).resolve()
    source = verify_research_checkout(h1_checkout)
    output.mkdir(parents=True,exist_ok=False)
    archive = NativeDBNArchive.open_existing(root/"native-dbn")
    ledger = ResearchLedger(output/"research.sqlite")
    manifests,quarantined,minute_sources,counts = [],[],{},Counter()
    for path in sorted([*root.glob("acquisition-result-*.json"),*root.glob("warmup-result-*.json")]):
        manifest = load(path)
        if "result" in manifest: manifest = manifest["result"]
        if manifest["status"] != "ARCHIVED":
            quarantined.append({"manifest_file":path.name,"sha256":sha256_file(path),
                                "status":manifest["status"],"actual_billed_usd":manifest.get("actual_billed_usd")})
            continue
        data=dict(manifest["request"]);data["contracts"]=tuple(tuple(c) for c in data["contracts"])
        request=HistoricalRequest(**data)
        actual=inspect_request_archive(archive.verify(manifest["archive_sha256"]),request)
        if actual != manifest["coverage"]: raise ValueError("saved manifest coverage mismatch")
        ledger.register_existing(request,manifest,archive=archive,
            provenance_review_reference="existing-authorized-gc-artifact-audit")
        counts[request.schema]+=actual["record_count"]
        if request.schema == "ohlcv-1m":
            import databento_dbn as dbn
            import hashlib
            for record in dbn_records(archive.verify(manifest["archive_sha256"])):
                if isinstance(record,dbn.Metadata):continue
                minute_sources[hashlib.sha256(bytes(record)).hexdigest()]=(record,manifest)
        manifests.append({"manifest_file":path.name,"manifest_sha256":sha256_file(path),
            "archive_sha256":manifest["archive_sha256"],"schema":request.schema,
            "record_count":actual["record_count"],"request_sha256":request.sha256,
            "historical_estimated_usd":manifest["preflight"]["estimated_usd"],
            "actual_billed_usd":manifest.get("actual_billed_usd")})
    input_path=root/"expanded-gc-h1-input-01.json"
    data=load(input_path)
    minutes={b["open_ns"]:b for b in data["bars"] if b["timeframe"]=="1m"}
    if len(minutes) != sum(b["timeframe"]=="1m" for b in data["bars"]):
        raise ValueError("duplicate normalized minutes")
    for bar in minutes.values():
        if len(bar["source_hashes"]) != 1:raise ValueError("native minute source hash required")
        record,manifest=minute_sources[bar["source_hashes"][0]]
        if (record.instrument_id,record.publisher_id,record.ts_event) != (41271,1,bar["open_ns"]):
            raise ValueError("native contract or exchange timestamp mismatch")
        for key in ("open","high","low","close"):
            if Decimal(bar[key]) != Decimal(getattr(record,key))/Decimal(10**9):
                raise ValueError("normalized price differs from native source")
        if (record.volume != bar["volume"] or manifest["retrieval_ns"] != bar["retrieval_ns"]
                or manifest["ingestion_ns"] != bar["admission_ns"]):
            raise ValueError("normalized volume/acquisition clocks mismatch")
    for bar in data["bars"]:
        if bar["timeframe"]=="1m":continue
        children=[minutes[t] for t in range(bar["open_ns"],bar["close_ns"],60*10**9)]
        expected=(Decimal(children[0]["open"]),max(Decimal(c["high"]) for c in children),
                  min(Decimal(c["low"]) for c in children),Decimal(children[-1]["close"]))
        if tuple(Decimal(bar[k]) for k in ("open","high","low","close")) != expected:
            raise ValueError("derived OHLC differs from source aggregation")
        if bar["volume"] != sum(c["volume"] for c in children):
            raise ValueError("derived volume mismatch")
        if bar["source_hashes"] != [h for c in children for h in c["source_hashes"]]:
            raise ValueError("derived candle source lineage mismatch")
    print(f"Verified {len(manifests)} native archives and {len(minutes)} source-matched minutes; replaying frozen selector.",flush=True)
    first=run_diagnostics(input_path,output/"expanded-replay-v1.json",h1_checkout=source,timeout_seconds=600)
    second=run_diagnostics(input_path,output/"expanded-replay-v2.json",h1_checkout=source,timeout_seconds=600)
    if first != second or first != load(root/"expanded-gc-h1-report-01.json"):
        raise ValueError("replay is not deterministic or differs from preserved report")
    for field in ISOLATION:
        if first[field] is not False:raise ValueError("research isolation violation")
    valid=[r for r in first["records"] if r.get("valid_constrained_fib")]
    episodes={r["anchor"]["h1_episode_id"] for r in valid}
    for r in valid:
        for endpoint in ("A","B"):
            from datetime import datetime
            from monatise.adapters.databento_identity import datetime_ns
            anchor=r["anchor"][endpoint]
            if datetime_ns(datetime.fromisoformat(anchor["known_at"])) > r["cutoff_ns"]:
                raise ValueError("future anchor confirmation")
            if any(datetime_ns(datetime.fromisoformat(c["known_at"])) > r["cutoff_ns"] for c in anchor["confirming_candles"]):
                raise ValueError("future confirming candle")
        a,b=(Decimal(str(r["anchor"][k]["price"])) for k in ("A","B"))
        if [s["ratio"] for s in r["raw_slots"]] != [1.272,1.414,1.618]:
            raise ValueError("raw extension ratio mismatch")
        for slot in r["raw_slots"]:
            if slot["eligible"] is not False or abs(Decimal(str(slot["raw_price"]))-(a+(b-a)*Decimal(str(slot["ratio"])))) > Decimal(".000001"):
                raise ValueError("extension formula or eligibility mismatch")
        if any(r[k] is not None for k in ("entry","stop","rr")):
            raise ValueError("manufactured trade qualification")
    reach=load(root/"expanded-raw-level-observations-02.json")
    touches=0
    for record in reach["records"]:
        for width,window in record["windows"].items():
            timestamp=window["first_touch_bar_open_ns"]
            if timestamp is not None:
                bar=minutes[timestamp]
                if (bar["open_ns"] < record["cutoff_ns"] or bar["close_ns"] > record["cutoff_ns"]+int(width)*10**9
                        or not Decimal(bar["low"]) <= Decimal(record["raw_fib_price"]) <= Decimal(bar["high"])):
                    raise ValueError("reported touch lacks complete native-minute price evidence")
                touches+=1
            if window["trade_fill_inference"] is not False:raise ValueError("trade-fill inference forbidden")
    if reach["win_rate"] is not None:raise ValueError("win rate requires qualified trades")
    verify_research_checkout(source)
    from monatise.research.gc_fib.preflight import requests
    cache_plan=ledger.plan(next(r for r in requests() if r.schema=="ohlcv-1m"),archive=archive)
    summary={"schema":"cme-offline-acceptance-v1","source_checkout":str(source),
        "frozen_selector_commit":"f1de9d46cb5f3458726b81cfbc9f1d0dfba73f35",
        "input_sha256":sha256_file(input_path),"replay_sha256":sha256_file(output/"expanded-replay-v1.json"),
        "preserved_report_equal":True,"repeat_equal":True,"native_archives":manifests,
        "quarantined_manifests":quarantined,"native_schema_record_counts":dict(counts),
        "source_matched_minutes":len(minutes),"derived_bars_verified":len(data["bars"])-len(minutes),
        "assessments":len(first["records"]),"valid_fibonacci_assessments":len(valid),
        "distinct_valid_h1_episodes":len(episodes),"raw_level_records":len(reach["records"]),
        "touch_window_observations_verified":touches,"qualified_trades":None,"trade_win_rate":None,
        "new_databento_usage_usd":"0","credit_consumed_this_run_usd":"0",
        "historical_billing":ledger.report(),"cache_overlaps_found":len(cache_plan["overlapping_request_hashes"]),
        "cache_plan_action":"REUSE_EXISTING_PARTITIONS_NO_DOWNLOAD",
        "pit_verified":False,"coverage_certified":False,"gil_enabled":False,"trading_enabled":False}
    with (output/"summary.json").open("x") as destination:
        json.dump(summary,destination,sort_keys=True,indent=2,allow_nan=False)
    print(json.dumps({k:summary[k] for k in ("assessments","valid_fibonacci_assessments","distinct_valid_h1_episodes","repeat_equal","new_databento_usage_usd")}),flush=True)
    return summary


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root",type=Path,required=True)
    parser.add_argument("--h1-checkout",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    verify(data_root=args.data_root,h1_checkout=args.h1_checkout,output=args.output)
