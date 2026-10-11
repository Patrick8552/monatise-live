"""Local subprocess boundary to the unchanged, pinned H1 research checkout."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from monatise.research.gold_retrospective import H1_RESEARCH


def verify_research_checkout(path):
    path = Path(path).resolve()
    def git(*args):
        return subprocess.check_output(["git","-C",str(path),*args],text=True).strip()
    if git("rev-parse","HEAD") != H1_RESEARCH or git("diff","HEAD","--name-only"):
        raise ValueError("unchanged pinned H1-Fib research checkout required")
    # Reject untracked source overrides; bytecode/cache files are ignored by git.
    if git("ls-files","--others","--exclude-standard","--","monatise"):
        raise ValueError("untracked research source overrides forbidden")
    return path


def run_replay(input_path, output_path, *, h1_checkout, timeout_seconds=120):
    source = verify_research_checkout(h1_checkout)
    file, destination = Path(input_path).resolve(),Path(output_path).resolve()
    if file.stat().st_size > 100_000_000 or destination.exists():
        raise ValueError("bounded input and fresh immutable output required")
    bootstrap = Path(__file__).with_name("bootstrap.py")
    phase4_root = Path(__file__).parents[3]
    # No production environment, credentials, DSN, broker settings or API keys.
    environment = {"PATH": str(Path(sys.executable).parent)+os.pathsep+"/usr/bin:/bin", "LANG":"en_US.UTF-8"}
    result = subprocess.run([sys.executable,"-I",str(bootstrap),str(source),str(phase4_root),str(file),str(destination)],
                            env=environment,capture_output=True,text=True,timeout=timeout_seconds)
    if result.returncode != 0:
        raise RuntimeError("isolated retrospective worker failed: "+result.stderr[-2000:])
    value = json.loads(destination.read_text())
    if value.get("execution_enabled") is not False or value.get("pit_verified") is not False:
        raise ValueError("worker output isolation failure")
    return value
