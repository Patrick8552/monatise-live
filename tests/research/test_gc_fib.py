"""Synthetic engineering only: these observations are not real GC history."""
import ast
import json
import os
import subprocess
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from monatise.research.gc_fib import ISOLATION
from monatise.research.gc_fib.candles import GCBar, GCIdentity, GCSession, MINUTE, aggregate, from_observation
from monatise.research.gc_fib.preflight import START_NS, END_NS, requests, prepare, assess_metadata, partition_scopes
from monatise.research.gc_fib.runner import run_diagnostics

ROOT = Path(__file__).parents[2]
PINNED = Path(os.environ.get("GC_H1_RESEARCH_CHECKOUT",str(ROOT.parent / "monatise-gold-h1-fib-f0")))


def minute(index=0, **changes):
    opened = START_NS+index*MINUTE
    data = dict(identity=GCIdentity(),timeframe="1m",open_ns=opened,close_ns=opened+MINUTE,
                assumed_available_ns=opened+MINUTE+10*10**9,retrieval_ns=END_NS,admission_ns=END_NS,
                open="4000.0",high="4001.0",low="3999.0",close="4000.5",volume=index+1,
                source_hashes=(f"{index+1:064x}",),evidence_kind="ENGINEERING_SYNTHETIC")
    return GCBar(**(data|changes))


def test_all_five_timeframes_deterministic_without_filling():
    rows = [minute(i) for i in range(240)]
    session = GCSession(START_NS,START_NS+240*MINUTE,"synthetic-reviewed-session")
    output,rejected = aggregate(rows,sessions=[session])
    second = aggregate(list(reversed(rows)),sessions=[session])
    assert (output,rejected) == second
    assert {tf:len(bs) for tf,bs in output.items()} == {"1m":240,"5m":48,"15m":16,"1h":4,"4h":1}
    assert output["4h"][0].volume == sum(b.volume for b in rows)
    assert output["4h"][0].open == rows[0].open
    assert output["4h"][0].close == rows[-1].close
    assert not rejected


def test_missing_minutes_are_unknown_and_no_zero_bar_is_fabricated():
    rows = [minute(i) for i in range(5) if i != 2]
    result, rejected = aggregate(rows,sessions=[GCSession(START_NS,START_NS+5*MINUTE,"fixture")])
    assert len(result["1m"]) == 4 and not result["5m"]
    assert rejected[0]["reason"] == "MISSING_OR_NO_TRADE_MINUTES_UNCERTIFIED"


def test_duplicate_dedup_and_revision_quarantine():
    session = GCSession(START_NS,START_NS+5*MINUTE,"fixture")
    result,_ = aggregate([minute(),minute()],sessions=[session])
    assert len(result["1m"]) == 1
    with pytest.raises(ValueError,match="revision"):
        aggregate([minute(),minute(close="4000.6")],sessions=[session])


def test_session_boundary_not_crossed_or_truncated():
    rows = [minute(i) for i in range(1,5)]
    result,rejected = aggregate(rows,sessions=[GCSession(START_NS+MINUTE,START_NS+5*MINUTE,"fixture")])
    assert not result["5m"] and rejected[0]["reason"] == "PARTIAL_SESSION_BOUNDARY"
    with pytest.raises(ValueError,match="outside"):
        aggregate([minute(0)],sessions=[GCSession(START_NS+MINUTE,START_NS+5*MINUTE,"fixture")])


@pytest.mark.parametrize("change",[
    {"raw_symbol":"XAUUSD"},{"raw_symbol":"GCG7"},{"publisher_id":4},
    {"instrument_id":123},{"economic_exchange":"GLBX"},{"dataset":"TEST"}])
def test_native_gc_identity_separation(change):
    with pytest.raises(ValueError): GCIdentity(**change)


@pytest.mark.parametrize("change",[
    {"open":"NaN"},{"high":"3990"},{"volume":-1},{"open_ns":START_NS+1},
    {"assumed_available_ns":START_NS},{"source_hashes":("no",)},
    {"evidence_kind":"VERIFIED_POINT_IN_TIME"}])
def test_invalid_candle_rejected(change):
    with pytest.raises(ValueError): minute(**change)


def test_phase2_normalized_record_precision_and_identity():
    obs = SimpleNamespace(dataset="GLBX.MDP3",schema="ohlcv-1m",namespace="COMEX:GC:GCZ6",
        publisher_id=1,instrument_id=41271,historical_retrieval_ns=END_NS,ingestion_ns=END_NS+123,
        event_ns=START_NS,payload=(4000123456789,4001123456789,3999123456789,4000123456789,2),
        record_sha256="a"*64)
    bar = from_observation(obs,identity=GCIdentity(),retrieval_ns=END_NS,admission_ns=END_NS+123)
    assert bar.open == "4000.123456789" and bar.admission_ns == END_NS+123
    obs.namespace="XAUUSD"
    with pytest.raises(ValueError):
        from_observation(obs,identity=GCIdentity(),retrieval_ns=END_NS,admission_ns=END_NS+123)


def test_metadata_scopes_are_bounded_exact_and_no_download_capability(tmp_path):
    scopes = requests()
    assert len(scopes) == 5
    assert all(r.contracts == ((1,41271,"GCZ6"),) and r.end_ns-r.start_ns == 5*86400*10**9 for r in scopes)
    assert all(r.record_limit == 1_000_000 and r.wire_byte_limit == 256*1024**2 for r in scopes)
    p = prepare(archive_root=tmp_path)
    assert p["entitlement"] == "UNKNOWN" and p["billable_download_authorized"] is False


def test_metadata_path_detects_truncation_without_download(tmp_path):
    from monatise.research.databento.acquisition import DownloadPreflight
    class Metadata:
        def get_record_count(self,**kwargs):
            assert "limit" not in kwargs
            return 1_000_000
        def get_billable_size(self,**kwargs): return 100_000_000
    class Source:
        _client=SimpleNamespace(metadata=Metadata())
        def preflight(self,request,now_ns):
            return DownloadPreflight(request.sha256,now_ns,START_NS,END_NS,"0.10",True,True,"a"*64)
        def download(self,*args,**kwargs): raise AssertionError("billable path forbidden")
    p=assess_metadata(Source(),archive_root=tmp_path)
    assert p["estimated_usd"] == "0.50" and not p["acquisition_ready"]
    assert all(r["completeness_preflight"] == "PARTITION_REQUIRED_NO_DOWNLOAD" for r in p["requests"])


def test_metadata_partition_complete_nonoverlapping_and_bounded():
    class Metadata:
        def get_record_count(self,**kwargs):
            return int((kwargs["end"]-kwargs["start"])/10**9*10) if kwargs["schema"] == "mbp-1" else 10
        def get_billable_size(self,**kwargs): return self.get_record_count(**kwargs)*80
    scopes=partition_scopes(SimpleNamespace(_client=SimpleNamespace(metadata=Metadata())))
    chunks=[r for r in scopes if r.schema == "mbp-1"]
    assert len(chunks) == 8 and chunks[0].start_ns == START_NS and chunks[-1].end_ns == END_NS
    assert all(a.end_ns == b.start_ns for a,b in zip(chunks,chunks[1:]))
    assert all(Metadata().get_record_count(**r.api_parameters()) < r.record_limit for r in chunks)


def fixture_dataset(*,short=False,forming_b=False):
    # Import only the frozen test fixture in a sanitized subprocess, never from production.
    if not PINNED.exists(): pytest.skip("pinned H1 research checkout unavailable")
    script = '''import sys,json; sys.path.insert(0,sys.argv[1]);
from tests.research.gold_fib_fixtures import h1_leg
from dataclasses import asdict
print(json.dumps([asdict(c) for c in h1_leg(short=sys.argv[2]=='1',forming_b=sys.argv[3]=='1')]))'''
    import sys
    raw = json.loads(subprocess.check_output([sys.executable,"-I","-c",script,str(PINNED),
            str(int(short)),str(int(forming_b))],text=True,env={"PATH":"/usr/bin:/bin"}))
    from datetime import datetime
    bars=[]
    for index,c in enumerate(raw):
        opened=int(datetime.fromisoformat(c["timestamp"]).timestamp())*10**9
        bars.append(asdict(GCBar(GCIdentity(),"1h",opened,opened+3600*10**9,
            opened+3610*10**9,END_NS,END_NS,str(c["open"]),str(c["high"]),str(c["low"]),
            str(c["close"]),int(c["volume"]),(f"{index+1:064x}",),"ENGINEERING_SYNTHETIC")))
    return dict(schema="gc-h1-diagnostics-v1",pit_verified=False,evidence_kind="ENGINEERING_SYNTHETIC",
                bars=bars,cutoffs_ns=[bars[-1]["assumed_available_ns"]])


@pytest.mark.parametrize("short",[False,True])
def test_unchanged_selector_native_long_short_determinism_and_raw_ratios(tmp_path,short):
    data=fixture_dataset(short=short)
    input=tmp_path/"input.json"; input.write_text(json.dumps(data))
    first=run_diagnostics(input,tmp_path/"one.json",h1_checkout=PINNED)
    second=run_diagnostics(input,tmp_path/"two.json",h1_checkout=PINNED)
    assert first == second and all(first[k] is False for k in ISOLATION)
    r=first["records"][0]
    assert r["symbol"] == "GCZ6" and r["anchor"]["valid_b"]
    assert r["anchor"]["A"]["price"] == (2550 if short else 2450)
    assert r["anchor"]["B"]["price"] == (2470 if short else 2530)
    assert [s["ratio"] for s in r["raw_slots"]] == [1.272,1.414,1.618]
    assert r["valid_constrained_fib"]
    for s in r["raw_slots"]:
        expected=(2550-80*s["ratio"]) if short else (2450+80*s["ratio"])
        assert s["raw_price"] == pytest.approx(expected) and s["eligible"] is False
    assert r["final_targets"] == [] and r["entry"] is None and r["rr"] is None


def test_unconfirmed_b_no_future_pivots_or_fallback(tmp_path):
    data=fixture_dataset(forming_b=True)
    input=tmp_path/"input.json"; input.write_text(json.dumps(data))
    result=run_diagnostics(input,tmp_path/"result.json",h1_checkout=PINNED)
    r=result["records"][0]
    assert r["reason"] == "B_UNCONFIRMED_AT_PARENT_CUTOFF"
    assert all(s["raw_price"] is None for s in r["raw_slots"])


def test_causal_prefix_ignores_future_and_parent_expiry_not_renewed(tmp_path):
    data=fixture_dataset()
    last=data["cutoffs_ns"][0]
    # After H1 expires, rereading the same candles must not renew it.
    data["cutoffs_ns"].append(last+3*3600*10**9)
    input=tmp_path/"input.json"; input.write_text(json.dumps(data))
    report=run_diagnostics(input,tmp_path/"result.json",h1_checkout=PINNED)
    one,two=report["records"]
    assert one["anchor_hash"] == two["anchor_hash"]
    assert two["reason"] == "H1_PARENT_EXPIRED"


def test_later_pivot_confirmation_cannot_enter_earlier_parent(tmp_path):
    data=fixture_dataset()
    final=data["cutoffs_ns"][0]
    data["cutoffs_ns"]=[data["bars"][59]["assumed_available_ns"],final]
    input=tmp_path/"input.json"; input.write_text(json.dumps(data))
    report=run_diagnostics(input,tmp_path/"result.json",h1_checkout=PINNED)
    early,later=report["records"]
    assert early["reason"] == "B_UNCONFIRMED_AT_PARENT_CUTOFF"
    assert all(s["raw_price"] is None for s in early["raw_slots"])
    assert later["anchor"]["valid_b"] is True
    assert early["h1_parent_hash"] != later["h1_parent_hash"]


def test_isolated_runner_strips_credentials_and_rejects_output_overwrite(tmp_path,monkeypatch):
    data=fixture_dataset()
    input=tmp_path/"input.json"; input.write_text(json.dumps(data))
    original=subprocess.run
    def check(args,**kwargs):
        if "-I" in args:
            assert set(kwargs["env"]) == {"PATH","LANG"}
        return original(args,**kwargs)
    monkeypatch.setattr(subprocess,"run",check)
    result=tmp_path/"result.json"
    run_diagnostics(input,result,h1_checkout=PINNED)
    with pytest.raises(ValueError,match="immutable"):
        run_diagnostics(input,result,h1_checkout=PINNED)


def test_no_production_registration_and_no_worker_io_capabilities():
    for directory in ("application","engines","adapters","interfaces"):
        for file in (ROOT/"monatise"/directory).rglob("*.py"):
            assert "research.gc_fib" not in file.read_text()
    for name in ("worker.py","runner.py","bootstrap.py","candles.py"):
        content=(ROOT/"monatise/research/gc_fib"/name).read_text()
        tree=ast.parse(content)
        imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        assert not any(x and any(b in x for b in ("telegram","execution","approval","mt5")) for x in imports)
        assert "get_range(" not in content and "ApprovedDownload(" not in content
