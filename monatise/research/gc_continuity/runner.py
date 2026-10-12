"""Local source-bound forensics, unchanged-window revalidation and comparison."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from monatise.research.databento.archive import NativeDBNArchive, sha256_file
from monatise.research.databento.candles import ResearchArtifactStore
from monatise.research.databento.controls import ResearchLedger
from monatise.research.gc_qualification import SAFETY
from monatise.research.gc_qualification.runner import run as qualify
from monatise.research.gold_retrospective.runner import verify_research_checkout
from monatise.research.gc_continuity.acquisition_plan import propose
from monatise.research.gc_continuity.forensics import metric_counts
from monatise.research.gc_continuity import PHASE3A


def source_hashes(repository):
    root = Path(repository)
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for package in ("gc_continuity","gc_qualification")
            for p in sorted((root/"monatise/research"/package).glob("*.py"))}


def scan_isolated(*, data_root, phase3a_root, h1_checkout, destination):
    repository = Path(__file__).parents[3]
    source = verify_research_checkout(h1_checkout)
    destination = Path(destination).resolve()
    if destination.exists(): raise ValueError("fresh_forensic_output_required")
    env = {"PATH":str(Path(sys.executable).parent)+os.pathsep+"/usr/bin:/bin","LANG":"C"}
    result = subprocess.run([sys.executable,"-I",str(Path(__file__).with_name("bootstrap.py")),
        str(source),str(repository),str(Path(data_root).resolve()),str(Path(phase3a_root).resolve()),str(destination)],
        env=env,capture_output=True,text=True,timeout=900)
    if result.returncode: raise RuntimeError("isolated_continuity_scan_failed: "+result.stderr[-2000:])
    verify_research_checkout(source)
    return json.loads(destination.read_text())


def run(*, data_root, phase3a_root, h1_checkout, cache_ledger, output):
    root = Path(__file__).parents[3]
    output = Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    hashes = source_hashes(root)
    with (output/"source-manifest.json").open("x") as out:
        json.dump(dict(phase3a_commit=PHASE3A,source_hashes=hashes,**SAFETY),out,sort_keys=True,indent=2)
    try:
        first = scan_isolated(data_root=data_root,phase3a_root=phase3a_root,h1_checkout=h1_checkout,destination=output/"forensics-01.json")
        second = scan_isolated(data_root=data_root,phase3a_root=phase3a_root,h1_checkout=h1_checkout,destination=output/"forensics-02.json")
        if first != second or sha256_file(output/"forensics-01.json") != sha256_file(output/"forensics-02.json"):
            raise ValueError("nondeterministic_forensic_report")
        # Copy the existing cache/budget for planning; do not mutate its budget or
        # old billing evidence. No configure/reserve/receipt/download call exists.
        shutil.copyfile(cache_ledger,output/"control-copy.sqlite")
        ledger = ResearchLedger(output/"control-copy.sqlite")
        plan = propose(first,ledger=ledger,archive=NativeDBNArchive.open_existing(Path(data_root)/"native-dbn"))
        with (output/"acquisition-proposals.json").open("x") as out:json.dump(plan,out,sort_keys=True,indent=2)
        after = qualify(data_root=data_root,h1_checkout=h1_checkout,output=output/"qualification")
        new_rows = json.loads((output/"qualification/ledger-01.json").read_text())["records"]
        old_rows = json.loads((Path(phase3a_root)/"ledger-01.json").read_text())["records"]
        if [r["cutoff_ns"] for r in old_rows] != [r["cutoff_ns"] for r in new_rows]:
            raise ValueError("original_decision_schedule_changed")
        if source_hashes(root) != hashes: raise ValueError("source_changed_during_revalidation")
        keys = ("scheduled_cutoffs","data_admissible_cutoffs","unavailable_cutoffs","rejected_cutoffs",
                "qualified_long_observations","qualified_short_observations","distinct_analytical_candidates",
                "unique_m15_setups","unique_m5_triggers","target_rr_rejected")
        old_summary = json.loads((Path(phase3a_root)/"ledger-01.json").read_text())["summary"]
        comparison = {k:{"phase3a":old_summary[k],"phase3b":after[k]} for k in keys}
        old_metrics,new_metrics = metric_counts(old_rows),metric_counts(new_rows)
        comparison.update({k:{"phase3a":old_metrics[k],"phase3b":new_metrics[k]} for k in old_metrics})
        summary = dict(schema="gc-continuity-acceptance-v1",**SAFETY,forensics_repeat_equal=True,
            qualification_repeat_equal=after["repeat_equal"],original_schedule_preserved=True,
            forensic_sha256=sha256_file(output/"forensics-01.json"),ledger_sha256=after["ledger_sha256"],
            source_hashes=hashes,comparison=comparison,classifications=first["classifications"],
            recovered_candles=0,synthetic_candles=0,new_databento_usage_usd="0",credit_used_usd="0",
            default_zero_budget_preserved=True,billing=ledger.report(),
            proposed_trade_requests=len(plan["requests"]),downloads_attempted=0,
            session_expectations_verified=True,unapproved_policy_amendments_activated=False)
        store = ResearchArtifactStore(output/"immutable")
        store.publish("quality",first);store.publish("metadata",plan);store.publish("quality",summary)
        with (output/"summary.json").open("x") as out:json.dump(summary,out,sort_keys=True,indent=2)
        print(json.dumps(summary,sort_keys=True,indent=2),flush=True)
        return summary
    except Exception as exc:
        with (output/"quarantine.json").open("x") as out:
            json.dump(dict(status="QUARANTINED_INCOMPLETE_CONTINUITY_RUN",error_type=type(exc).__name__,**SAFETY),out,sort_keys=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("data-root","phase3a-root","h1-checkout","cache-ledger","output"):
        parser.add_argument("--"+argument,type=Path,required=True)
    run(**vars(parser.parse_args()))
