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



def test_selector_runner_is_permanently_retired_without_subprocess(tmp_path,monkeypatch):
    from monatise.research.native_futures.retired import RetiredFuturesWorkflow
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('retired subprocess called'))
    with pytest.raises(RetiredFuturesWorkflow):
        run_diagnostics(tmp_path/'missing',tmp_path/'output',h1_checkout=tmp_path)
    assert not (tmp_path/'output').exists()
