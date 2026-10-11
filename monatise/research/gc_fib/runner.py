"""Credential-free, isolated subprocess calling the unchanged pinned selector."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from monatise.research.gold_retrospective.runner import verify_research_checkout
from monatise.research.gc_fib import ISOLATION


def run_diagnostics(input_path, output_path, *, h1_checkout, timeout_seconds=120):
    source = verify_research_checkout(h1_checkout)
    file, destination = Path(input_path).resolve(), Path(output_path).resolve()
    if file.stat().st_size > 50_000_000 or destination.exists():
        raise ValueError("bounded input and immutable fresh output required")
    environment = {"PATH": str(Path(sys.executable).parent)+os.pathsep+"/usr/bin:/bin", "LANG":"en_US.UTF-8"}
    bootstrap = Path(__file__).with_name("bootstrap.py")
    result = subprocess.run([sys.executable,"-I",str(bootstrap),str(source),
                             str(Path(__file__).parents[3]),str(file),str(destination)],
                            env=environment,capture_output=True,text=True,timeout=timeout_seconds)
    if result.returncode:
        raise RuntimeError("isolated GC diagnostics failed: "+result.stderr[-1500:])
    value = json.loads(destination.read_text())
    if any(value.get(k) is not False for k in ISOLATION):
        raise ValueError("GC research output isolation failure")
    return value
