"""Offline native GC qualification acceptance; no provider credentials or charges."""
import ast
import copy
from dataclasses import asdict, replace
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from monatise.research.gc_qualification import SAFETY
from monatise.research.gc_qualification.models import NativeContract, Quote, digest
from monatise.research.gc_qualification.prepare import verify_bar_lineage
from monatise.research.gc_qualification.runner import isolated
from tests.research.gc_qualification_fixtures import fixture, NOW_NS

ROOT = Path(__file__).parents[2]
PINNED = Path(os.environ.get("GC_H1_RESEARCH_CHECKOUT",str(ROOT.parent/"monatise-gold-h1-fib-f0")))


def replay(tmp_path, value, name="case"):
    if not PINNED.exists(): pytest.skip("explicit frozen H1 checkout required")
    source,destination = tmp_path/(name+".input.json"),tmp_path/(name+".ledger.json")
    source.write_text(json.dumps(value))
    return isolated("replay",source,destination,h1_checkout=PINNED)




def change_bar(value,tf,index,**changes):
    rows = [r for r in value["bars"] if r["timeframe"] == tf]
    rows[index].update(changes)












def test_lineage_requires_native_price_volume_and_acquisition_clocks():
    v = fixture();bar = next(b for b in v["bars"] if b["timeframe"] == "1m")
    record = SimpleNamespace(publisher_id=1,instrument_id=41271,ts_event=bar["open_ns"],volume=bar["volume"],
                            **{k:int(Decimal(bar[k])*10**9) for k in ("open","high","low","close")})
    manifest = dict(retrieval_ns=bar["retrieval_ns"],ingestion_ns=bar["admission_ns"])
    data = dict(bars=[bar]); sources = {bar["source_hashes"][0]:(record,manifest)}
    assert len(verify_bar_lineage(data,sources)) == 1
    for field,val in (("close","1"),("volume",0),("retrieval_ns",bar["retrieval_ns"]-1)):
        changed = copy.deepcopy(data);changed["bars"][0][field] = val
        with pytest.raises(ValueError):verify_bar_lineage(changed,sources)
    with pytest.raises(ValueError,match="unadmitted"):verify_bar_lineage(data,{})


def test_isolation_guard_blocks_network_processes_credentials_and_external_writes(tmp_path):
    code = '''
from pathlib import Path
import socket, subprocess, sys
from monatise.research.gc_qualification.isolation import install_guard
install_guard(read_roots=(Path.cwd(),Path(sys.prefix),Path(sys.base_prefix)),output=Path(sys.argv[1])/'out')
actions=[lambda:socket.create_connection(('127.0.0.1',1)),lambda:subprocess.run(['true']),
lambda:open('/tmp/mon-gc-forbidden-credential','w'),lambda:open('.env')]
for action in actions:
    try:action()
    except PermissionError:continue
    raise AssertionError('isolation failed')
print('blocked all')
'''
    result = subprocess.run([sys.executable,"-c",code,str(tmp_path)],cwd=ROOT,
                            env={"PATH":"/usr/bin:/bin"},capture_output=True,text=True)
    assert result.returncode == 0,result.stderr
    assert "blocked all" in result.stdout


def test_worker_cannot_import_production_actions_or_acquisition_client():
    names = []
    for file in (ROOT/"monatise/research/gc_qualification").glob('*.py'):
        tree = ast.parse(file.read_text())
        names.extend(n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom))
        assert not any(isinstance(n,ast.Attribute) and n.attr in {'get_range','submit_order','publish_signal'} for n in ast.walk(tree))
    assert not any(any(x in name for x in ('deployment','ftmo_master','telegram','gold_options','gold_analysis.GoldAnalysisCoordinator')) for name in names)
