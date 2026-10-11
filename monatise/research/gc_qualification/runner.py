"""Explicit local CLI, no production registration and no acquisition capability."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from monatise.research.databento.archive import sha256_file
from monatise.research.databento.candles import ResearchArtifactStore
from monatise.research.gc_qualification import SAFETY
from monatise.research.gc_qualification.models import research_sources
from monatise.research.gold_retrospective.runner import verify_research_checkout


def isolated(mode, input_file, output_file, *, h1_checkout, timeout=900):
    source = verify_research_checkout(h1_checkout)
    input_file,output_file = Path(input_file).resolve(),Path(output_file).resolve()
    if output_file.exists() or (input_file.is_file() and input_file.stat().st_size > 100_000_000):
        raise ValueError("bounded_input_and_fresh_output_required")
    if mode == "replay":
        hashes = json.loads(input_file.read_text())["configuration"].get("research_source_hashes")
        if hashes is not None and hashes != research_sources(Path(__file__).parents[3]):
            raise ValueError("research_source_changed_since_preparation")
    environment = {"PATH":str(Path(sys.executable).parent)+os.pathsep+"/usr/bin:/bin","LANG":"C"}
    result = subprocess.run([sys.executable,"-I",str(Path(__file__).with_name("bootstrap.py")),mode,
        str(source),str(Path(__file__).parents[3]),str(input_file),str(output_file)],
        env=environment,capture_output=True,text=True,timeout=timeout)
    if result.returncode:
        raise RuntimeError("isolated_gc_qualification_failed: "+result.stderr[-2000:])
    verify_research_checkout(source)
    value = json.loads(output_file.read_text())
    if any(value.get(k) is not False for k in SAFETY):
        raise ValueError("research_output_activation_forbidden")
    return value


def run(*, data_root, h1_checkout, output):
    output = Path(output).resolve(); output.mkdir(parents=True,exist_ok=False)
    source = verify_research_checkout(h1_checkout)
    with (output/"run-intent.json").open("x") as out:
        json.dump(dict(status="INCOMPLETE_UNTIL_SUMMARY_VALIDATED",**SAFETY),out,sort_keys=True)
    try:
        isolated("prepare",data_root,output/"prepared-input.json",h1_checkout=source)
        first = isolated("replay",output/"prepared-input.json",output/"ledger-01.json",h1_checkout=source)
        second = isolated("replay",output/"prepared-input.json",output/"ledger-02.json",h1_checkout=source)
    except Exception as exc:
        with (output/"quarantine.json").open("x") as out:
            json.dump(dict(status="QUARANTINED_INCOMPLETE_RESEARCH_RUN",error_type=type(exc).__name__,**SAFETY),out,sort_keys=True)
        raise
    if first != second or sha256_file(output/"ledger-01.json") != sha256_file(output/"ledger-02.json"):
        raise ValueError("nondeterministic_qualification_ledger")
    store = ResearchArtifactStore(output/"immutable")
    path,sha = store.publish("replays",first)
    summary = dict(**first["summary"],status="VALIDATED_REPRODUCIBLE_RESEARCH",repeat_equal=True,ledger_sha256=sha,
        ledger_path=str(path),prepared_input_sha256=sha256_file(output/"prepared-input.json"),
        ledger_file_sha256=sha256_file(output/"ledger-01.json"),**SAFETY)
    store.publish("quality",summary)
    with (output/"summary.json").open("x") as out: json.dump(summary,out,sort_keys=True,indent=2)
    print(json.dumps(summary,sort_keys=True,indent=2),flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root",type=Path,required=True)
    parser.add_argument("--h1-checkout",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    run(**vars(parser.parse_args()))
