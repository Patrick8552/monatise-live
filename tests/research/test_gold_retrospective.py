"""Offline Phase 4 engineering; every market-like series here is synthetic."""
import ast
import asyncio
import copy
import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from monatise.research.broker_xauusd.models import TIMEFRAMES, digest, instant
from monatise.research.gold_retrospective.acquisition import acquisition_plan, import_export, validate_export
from monatise.research.gold_retrospective.dataset import build_dataset, historical_units, validate_dataset
from monatise.research.gold_retrospective.outcomes import price_path, summarize
from monatise.research.gold_retrospective.runner import run_replay, verify_research_checkout
from monatise.research.gold_retrospective.comparison import evaluate
from tests.research.test_broker_xauusd_archive import NOW, START, END, add, archive, payload, prepared

ROOT = Path(__file__).parents[2]


def run(c):
    return asyncio.run(c)


def plan(a, **kwargs):
    return acquisition_plan(a.identity,a.calendar,start=START,end=END,mapping_reference="engineering native mapping",**kwargs)


def export(a,page):
    p = payload(a)
    rows = [dict(r,spread_points=20,real_volume=0) for r in p["timeframes"][page["timeframe"]]
            if a.calendar.normalize_broker_epoch(r["t_broker"]).isoformat() in page["expected_opens"]]
    return {**{k:p[k] for k in ("account_id","server","symbol","captured_at","broker_time_offset","point","tick_size","spread_price")},
        "schema":"gold-mt5-historical-export-v1","page_id":page["page_id"],"timeframe":page["timeframe"],
        "from_broker_epoch":page["from_broker_epoch"],"until_broker_epoch_exclusive":page["until_broker_epoch_exclusive"],
        "rows":rows,"copied_count":len(rows),"last_error":0,"series_first_broker_epoch":page["from_broker_epoch"]}


def units(a):
    return {"schema":"gold-historical-units-v1","identity":a.identity.__dict__,"eras":[
        {"from":a.calendar.start.isoformat(),"until":a.calendar.end.isoformat(),"point":.01,"tick_size":.01,
         "review_reference":"synthetic engineering units","engineering_spread_price":.2}]}


async def dataset(a=None, *, kind="ENGINEERING_SYNTHETIC", history=True):
    a = a or archive()
    await add(a,payload(a,history=history),kind=kind)
    ds = await build_dataset(a,cutoff=NOW,start=START,end=END,evidence_kind=kind,unit_manifest=units(a))
    return a,ds


def test_pages_bound_identity_all_five_frames_and_no_download():
    a=archive(); p=plan(a,page_bars=17)
    assert {r["timeframe"] for r in p["pages"]} == set(TIMEFRAMES)
    assert all(len(r["expected_opens"]) <= 17 for r in p["pages"])
    assert not p["automatic_download"] and not p["connection_authorized"] and not p["execution_enabled"]
    assert len({r["page_id"] for r in p["pages"]}) == len(p["pages"])
    for page in p["pages"]:
        assert page["identity"] == a.identity.__dict__
        assert validate_export(export(a,page),page,a)["coverage_complete"]


@pytest.mark.parametrize("kwargs",[{"page_bars":0},{"page_bars":241},{"page_bars":True},{"mapping_reference":""}])
def test_bad_plan_inputs(kwargs):
    a=archive()
    params=dict(start=START,end=END,mapping_reference="fixture",page_bars=20);params.update(kwargs)
    with pytest.raises(ValueError): acquisition_plan(a.identity,a.calendar,**params)


@pytest.mark.parametrize("defect,reason",[("missing","PARTIAL_OR_MISSING_HISTORY"),("duplicate","DUPLICATE_BROKER_BARS"),
    ("count","COPIED_COUNT_MISMATCH"),("identity","BROKER_IDENTITY_MISMATCH"),("clock","INVALID_BROKER_BARS"),
    ("ohlc","INVALID_BROKER_BARS"),("meta","EXPORT_METADATA_MISSING"),("truncated","BROKER_HISTORY_TRUNCATED_AT_START"),
    ("range","EXPORT_RANGE_MISMATCH"),("nan","INVALID_BROKER_BARS"),("unordered","UNORDERED_BROKER_BARS")])
def test_export_defects_reported_without_filling(defect,reason):
    a=archive();page=next(p for p in plan(a)["pages"] if p["timeframe"]=="1m"); raw=export(a,page)
    if defect=="missing":raw["rows"].pop();raw["copied_count"]-=1
    elif defect=="duplicate":raw["rows"][1]=copy.deepcopy(raw["rows"][0])
    elif defect=="count":raw["copied_count"]=-1
    elif defect=="identity":raw["symbol"]="GCZ6"
    elif defect=="clock":raw["rows"][0]["t_broker"]+=1
    elif defect=="ohlc":raw["rows"][0]["l"]=5000
    elif defect=="meta":del raw["point"]
    elif defect=="truncated":raw["series_first_broker_epoch"]+=60
    elif defect=="range":raw["from_broker_epoch"]+=1
    elif defect=="nan":raw["rows"][0]["c"]=float("nan")
    elif defect=="unordered":raw["rows"].reverse()
    q=validate_export(raw,page,a)
    assert reason in q["errors"]+q["warnings"]
    assert q["session_gaps_filled"]==0 and not q["coverage_complete"]
    assert q["archive_eligible"] == (defect in {"missing","truncated"})


def test_exact_wire_reimport_is_one_observation_and_revisions_preserve_vintage(tmp_path):
    async def scenario():
        a=archive();page=next(p for p in plan(a)["pages"] if p["timeframe"]=="1m")
        raw=export(a,page);file=tmp_path/"export.json";file.write_text(json.dumps(raw))
        first=await import_export(a,file,page,source_reference="synthetic manual export",engineering=True)
        a.fixture_clock[0]=NOW+timedelta(seconds=1)
        second=await import_export(a,file,page,source_reference="synthetic manual export",engineering=True)
        assert first["receipt"]==second["receipt"] and first["wire_sha256"]==second["wire_sha256"]
        assert len(await a.batches(cutoff=a.clock()))==1
        original=await build_dataset(a,cutoff=NOW,start=START,end=END,evidence_kind="ENGINEERING_SYNTHETIC",unit_manifest=units(a))
        raw["captured_at"]=(NOW+timedelta(seconds=2)).isoformat();raw["rows"][-1]["c"]=2499
        a.fixture_clock[0]=NOW+timedelta(seconds=2);file.write_text(json.dumps(raw))
        third=await import_export(a,file,page,source_reference="synthetic manual export",engineering=True)
        assert third["archive_eligible"] and third["receipt"] != first["receipt"]
        revised=await build_dataset(a,cutoff=a.clock(),start=START,end=END,evidence_kind="ENGINEERING_SYNTHETIC",unit_manifest=units(a))
        assert len(revised["revisions"])==1
        assert original==await build_dataset(a,cutoff=NOW,start=START,end=END,evidence_kind="ENGINEERING_SYNTHETIC",unit_manifest=units(a))
        assert revised["rows"][-1]["original"]["spread_points"]==20
    run(scenario())


@pytest.mark.parametrize("value",[[],None,{"schema":"wrong"}])
def test_bad_wire_has_durable_quarantine(tmp_path,value):
    async def scenario():
        a=archive();page=plan(a)["pages"][0];file=tmp_path/"bad.json";file.write_text(json.dumps(value))
        q=await import_export(a,file,page,source_reference="synthetic bad source",engineering=True)
        assert not q["archive_eligible"] and not await a.batches(cutoff=NOW)
        docs=await a.store.list_namespace(a.namespace)
        assert len(docs)==1 and docs[0].value["wire_base64"] and not docs[0].value["execution_enabled"]
    run(scenario())


def test_historical_units_do_not_reuse_capture_units_or_zero_spread():
    a=archive();m=units(a);row={"original":{"spread_points":20}}
    u,proof=historical_units(m,a.identity.__dict__,NOW,row,engineering=False)
    assert u["spread_price"]==.2 and not proof["execution_quote"]
    with pytest.raises(ValueError,match="spread"):historical_units(m,a.identity.__dict__,NOW,{"original":{"spread_points":0}},engineering=False)
    m["eras"][0]["until"]=START.isoformat()
    with pytest.raises(ValueError,match="coverage"):historical_units(m,a.identity.__dict__,NOW,row,engineering=True)


def test_frozen_dataset_requires_review_and_never_becomes_pit():
    async def scenario():
        a,ds=await dataset(kind="RETROSPECTIVE_HISTORICAL_DOWNLOAD")
        assert ds["result_class"]=="RETROSPECTIVE_RESEARCH" and not ds["pit_verified"]
        with pytest.raises(ValueError,match="review"):validate_dataset(ds)
        ds["source_review"]={"review_reference":"SYNTHETIC REVIEW, NOT MARKET DATA","source_batches_sha256":digest(ds["source_batches"]),
            "rows_sha256":digest(ds["rows"]),"unit_manifest_sha256":digest(ds["unit_manifest"]),"calendar_fingerprint":ds["calendar_fingerprint"]}
        ds["sha256"]=digest({k:v for k,v in ds.items() if k!="sha256"})
        assert validate_dataset(ds).fingerprint==a.calendar.fingerprint
        assert all(r["original_observation_availability"] is None for r in ds["rows"])
        assert not (await prepared(a,kind="RETROSPECTIVE_HISTORICAL_DOWNLOAD"))["f0_input_ready"]
    run(scenario())


@pytest.mark.parametrize("defect",["clock","native","future_available","proof","ohlc","duplicate","policy","execution","pit"])
def test_dataset_semantic_integrity_even_after_rehash(defect):
    _,ds=run(dataset());r=ds["rows"][0]
    if defect=="clock":r["received_at"]=(NOW+timedelta(days=1)).isoformat()
    elif defect=="native":r["original"]["t_broker"]+=1
    elif defect=="future_available":r["assumed_available_at"]=NOW.isoformat()
    elif defect=="proof":r["original_observation_availability"]=r["assumed_available_at"]
    elif defect=="ohlc":r["original"]["c"]+=1
    elif defect=="duplicate":ds["rows"].append(copy.deepcopy(r))
    elif defect=="policy":ds["policy_id"]="v2"
    elif defect=="execution":ds["execution_enabled"]=True
    elif defect=="pit":ds["pit_verified"]=True
    ds["sha256"]=digest({k:v for k,v in ds.items() if k!="sha256"})
    with pytest.raises(ValueError):validate_dataset(ds)


def record(*,short=False,at=END):
    return {"setup_identifier":"engineering-seed","h1_episode_id":"engineering-episode","h1_context_id":"ctx",
        "seed_observed_at":at.isoformat(),"expiry":(END+timedelta(minutes=3)).isoformat(),"entry":100.,"stop":110. if short else 90.,
        "eligible_target_count":1,"valid_constrained_fib":True,
        "raw_slots":[{"identity":"FIB_TP1","ratio":1.272,"raw_price":80. if short else 120.,"eligible":True},
                     {"identity":"FIB_TP2","ratio":1.414,"raw_price":70. if short else 130.,"eligible":False,"rejection_reason":"technical conflict"},
                     {"identity":"FIB_TP3","ratio":1.618,"raw_price":None,"eligible":False,"rejection_reason":"unavailable"}]}


def bar(i,lo,hi):
    opened=END+timedelta(minutes=i)
    return {"timeframe":"1m","opened_at":opened.isoformat(),"scheduled_close_at":(opened+timedelta(minutes=1)).isoformat(),
            "candle":{"timestamp":opened.isoformat(),"open":100.,"high":hi,"low":lo,"close":100.,"volume":100}}


@pytest.mark.parametrize("short",[False,True])
def test_outcomes_thresholds_stop_first_and_rejected_candidates_are_retained(short):
    r=record(short=short);bars=[bar(0,95,105),bar(1,79 if short else 95,105 if short else 131),bar(2,69 if short else 95,105 if short else 141)]
    result=price_path(r,bars,archive().calendar)
    assert result["candidates"][0]["status"]=="TARGET_TOUCHED_BEFORE_OBSERVED_STOP"
    assert result["candidates"][1]["raw_price_touched"] and not result["candidates"][1]["eligible"]
    assert result["candidates"][2]["status"]=="NO_RAW_CANDIDATE_PRICE"
    assert result["expiry_observed"] and result["profitability"] is None and not result["planned_entry_assumed_filled"]
    bars[0]=bar(0,95 if short else 89,111 if short else 105)
    assert price_path(r,bars,archive().calendar)["candidates"][0]["status"]=="STOP_FIRST_PRICE_PATH"
    s=summarize([r], [result],sessions=1)
    assert s["qualified_h1_episode_clusters"]==1 and s["executed_trades"]==0


def test_same_bar_missing_partial_expiry_and_invalidation():
    r=record();cal=archive().calendar;bars=[bar(0,89,131),bar(1,95,105),bar(2,95,105)]
    assert price_path(r,bars,cal)["candidates"][0]["status"]=="AMBIGUOUS_SAME_BAR_TP_SL"
    result=price_path(r,bars[1:],cal)
    assert result["data_gaps"] and result["candidates"][0]["status"]=="INCOMPLETE_PATH_ORDERING_UNKNOWN"
    r["seed_observed_at"]=(END+timedelta(seconds=10)).isoformat()
    result=price_path(r,bars,cal)
    assert result["partial_bars_excluded"]==1 and result["candidates"][0]["status"]=="INCOMPLETE_PATH_ORDERING_UNKNOWN"
    invalid={"setup_identifier":r["setup_identifier"],"at":(END+timedelta(minutes=2)).isoformat(),"reason":"parent lost"}
    assert price_path(r,bars,cal,invalidation=invalid)["end"]==invalid["at"]
    with pytest.raises(ValueError,match="belong"):price_path(r,bars,cal,invalidation={**invalid,"setup_identifier":"other"})


@pytest.mark.parametrize("short",[False,True])
def test_ordered_quotes_use_bid_for_long_ask_for_short(short):
    quotes=[{"at":END.isoformat(),"sequence":1,"bid":99.,"ask":101.},
        {"at":(END+timedelta(seconds=1)).isoformat(),"sequence":2,"bid":79. if short else 119.,"ask":81. if short else 121.}]
    r=record(short=short);cal=archive().calendar
    result=price_path(r,[],cal,quotes=quotes,quote_source_reference="ENGINEERING QUOTES")
    assert not result["candidates"][0]["raw_price_touched"] # Ask/Bid crosses, executable exit side does not.
    with pytest.raises(ValueError,match="source"):price_path(r,[],cal,quotes=quotes)
    with pytest.raises(ValueError,match="ordered"):price_path(r,[],cal,quotes=quotes+quotes[:1],quote_source_reference="fixture")


def test_isolation_graph_no_transport_or_production_imports_and_script_no_trading():
    forbidden=("monatise.application.ftmo","monatise.application.telegram","MetaTrader5","requests","httpx","socket","urllib","monatise.research.databento")
    for file in (ROOT/"monatise/research/gold_retrospective").glob("*.py"):
        tree=ast.parse(file.read_text())
        for n in ast.walk(tree):
            modules=[n.module or ""] if isinstance(n,ast.ImportFrom) else [m.name for m in n.names] if isinstance(n,ast.Import) else []
            assert not any(m.startswith(forbidden) for m in modules)
    for folder in ("application","live"):
        for file in (ROOT/"monatise"/folder).rglob("*.py"):
            assert "research.gold_retrospective" not in file.read_text()
    script=(ROOT/"research/mt5/MonatiseGoldHistoricalExport.mq5").read_text()
    assert "CopyRates" in script and "OnStart" in script
    assert not any(s in script for s in ("OrderSend","CTrade","OnTimer","WebRequest","AccountLogin","OnTick"))


def research_checkout():
    value=os.environ.get("MONATISE_H1_F0_CHECKOUT")
    if not value: pytest.skip("explicit pinned H1-F0 checkout required for cross-checkout replay")
    return verify_research_checkout(value)


def synthetic_replay_dataset(source, *, short=False,forming_b=False,origin_latency=False):
    code=f"from tests.research.gold_fib_fixtures import archive;import json;print(json.dumps(archive(short={short},forming_b={forming_b},origin_latency={origin_latency})))"
    fixture=json.loads(subprocess.check_output([sys.executable,"-c",code],cwd=source,text=True))
    a=archive(calendar=fixture["calendar"])
    p=payload(a);p["timeframes"]={tf:[{"t_broker":int(instant(c["timestamp"]).timestamp()),"o":c["open"],"h":c["high"],"l":c["low"],"c":c["close"],"v":c["volume"],"spread_points":20} for c in cs] for tf,cs in fixture["observations"][-1]["candles"].items()}
    captured=instant("2026-10-06T12:00:20Z");p.update(captured_at=captured.isoformat(),received_at=captured.isoformat());a.fixture_clock[0]=captured
    async def scenario():
        await add(a,p)
        return await build_dataset(a,cutoff=captured,start="2026-09-20T00:00:00Z",end="2026-10-05T15:05:00Z",evidence_kind="ENGINEERING_SYNTHETIC",unit_manifest=units(a))
    return run(scenario())


@pytest.mark.parametrize("short,forming_b,origin_latency",[(False,False,False),(True,False,False),(False,True,False),(False,False,True)])
def test_pinned_replay_causal_deterministic_selector_and_canonical_comparison(tmp_path,short,forming_b,origin_latency):
    source=research_checkout();ds=synthetic_replay_dataset(source,short=short,forming_b=forming_b,origin_latency=origin_latency)
    request={"dataset":ds,"assessment_start":"2026-10-05T15:04:10Z","assessment_end":"2026-10-05T15:04:11Z"}
    input_file=tmp_path/"input.json";input_file.write_text(json.dumps(request))
    first=run_replay(input_file,tmp_path/"one.json",h1_checkout=source)
    second=run_replay(input_file,tmp_path/"two.json",h1_checkout=source)
    assert first==second and not first["pit_verified"] and not first["execution_enabled"]
    assert first["assessed_decisions"]==1
    assert first["records"], first["admissions"]
    for admission in first["admissions"]:
        at=instant(admission["at"])
        assert all(instant(p["last_assumed_available"])<=at for p in admission["knowledge"].values())
    row=first["records"][0]
    assert row["canonical"] is not None and row["raw_slots"] and row["policy_id"]=="gold-fib-h1-structural-leg-v1"
    assert not row["pit_verified"] and row["observed_price_kind"].startswith("HISTORICAL_CANDLE")
    if forming_b or origin_latency:
        assert not row["valid_constrained_fib"] and row["reason"]
    else:
        assert row["valid_constrained_fib"] and row["candidate_admitted_count"]==3
        assert row["eligible_target_count"]==0 and row["reason"]=="NEAREST_OBJECTIVE_RR_REJECTED"
        assert [s["ratio"] for s in row["raw_slots"]]==[1.272,1.414,1.618]
        for endpoint in (row["anchor"]["A"],row["anchor"]["B"]):
            assert instant(endpoint["known_at"]) <= instant(row["h1_parent_cutoff"])
    verify_research_checkout(source)
    outcome=evaluate(first,ds)
    assert outcome==evaluate(first,ds)
    assert outcome["summary"]["setup_level"]["setup_events"]==1
    assert outcome["comparisons"][0]["canonical_target_plan"] is None
    assert not outcome["comparisons"][0]["f0_resolved_targets"]
    assert outcome["profitability"] is None
    if row["reason"]=="NEAREST_OBJECTIVE_RR_REJECTED":
        assert all(c["decision_rejection_reason"]==row["reason"] for c in outcome["comparisons"][0]["f0_raw_price_path"]["candidates"])


def test_worker_missing_history_does_not_fabricate_seed(tmp_path):
    source=research_checkout();ds=synthetic_replay_dataset(source)
    ds["rows"]=[r for r in ds["rows"] if not (r["timeframe"]=="1h" and r["opened_at"]=="2026-10-05T13:00:00+00:00")]
    ds["sha256"]=digest({k:v for k,v in ds.items() if k!="sha256"})
    file=tmp_path/"input.json";file.write_text(json.dumps({"dataset":ds,"assessment_start":"2026-10-05T15:00:10Z","assessment_end":"2026-10-05T15:04:10Z"}))
    result=run_replay(file,tmp_path/"out.json",h1_checkout=source)
    assert not result["records"]
    assert all("1h:INTERNAL_HISTORY_GAP" in r["details"] for r in result["admissions"])


def test_cli_plan_and_inspect_are_offline_and_refuse_overwrite(tmp_path):
    from monatise.research.gold_retrospective.cli import main
    a=archive();identity=tmp_path/"identity.json";calendar=tmp_path/"calendar.json";output=tmp_path/"plan.json"
    identity.write_text(json.dumps(a.identity.__dict__));calendar.write_text(json.dumps(a.calendar_manifest))
    args=["plan","--identity",str(identity),"--calendar",str(calendar),"--output",str(output),"--start",START.isoformat(),"--end",END.isoformat(),"--mapping-reference","ENGINEERING"]
    main(args);p=json.loads(output.read_text());assert not p["automatic_download"]
    with pytest.raises(ValueError,match="immutable"):main(args)
    page=tmp_path/"page.json";file=tmp_path/"export.json";quality=tmp_path/"quality.json"
    page.write_text(json.dumps(p["pages"][0]));file.write_text(json.dumps(export(a,p["pages"][0])))
    main(["inspect","--identity",str(identity),"--calendar",str(calendar),"--page",str(page),"--export",str(file),"--output",str(quality)])
    assert json.loads(quality.read_text())["coverage_complete"]


def test_unknown_evidence_cannot_export_as_point_in_time():
    async def scenario():
        a=archive();await add(a,kind="UNKNOWN_OR_UNVERIFIED")
        r=await prepared(a,kind="UNKNOWN_OR_UNVERIFIED")
        assert "UNVERIFIED_EVIDENCE" in r["blockers"] and not r["f0_input_ready"]
        assert not any(e["point_in_time_eligible"] for e in r["events"])
    run(scenario())


def test_pages_split_historical_offset_eras_and_closed_sessions():
    from tests.test_gold_sessions import manifest
    m=manifest();m.update(account_id="ENGINEERING_ONLY",server="SYNTHETIC_NOT_BROKER")
    a=archive(calendar=m)
    p=acquisition_plan(a.identity,a.calendar,start="2026-10-23T00:00:00Z",end="2026-10-29T00:00:00Z",mapping_reference="synthetic historical mapping")
    for page in p["pages"]:
        opened,closed=instant(page["start"]),instant(page["end"])
        assert any(x<=opened<closed<=y for x,y in a.calendar.sessions)
        assert any(x<=opened<closed<=y for x,y,_ in a.calendar.offsets)
        assert page["from_broker_epoch"]==int(opened.timestamp())+a.calendar.offset(opened)
    assert not any(instant(t).day==27 for page in p["pages"] for t in page["expected_opens"])


def test_absent_m1_decision_remains_in_denominator(tmp_path):
    source=research_checkout();ds=synthetic_replay_dataset(source)
    ds["rows"]=[r for r in ds["rows"] if not (r["timeframe"]=="1m" and r["opened_at"]=="2026-10-05T15:03:00+00:00")]
    ds["sha256"]=digest({k:v for k,v in ds.items() if k!="sha256"})
    file=tmp_path/"input.json";file.write_text(json.dumps({"dataset":ds,"assessment_start":"2026-10-05T15:04:10Z","assessment_end":"2026-10-05T15:04:11Z"}))
    result=run_replay(file,tmp_path/"out.json",h1_checkout=source)
    assert result["assessed_decisions"]==1 and len(result["missing_m1_decision_times"])==1
    assert not result["records"]
    assert evaluate(result,ds)["summary"]["total_historical_sessions"]==1


def test_equal_admission_revision_is_excluded_until_later_vintage():
    async def scenario():
        a=archive();p=payload(a);await add(a,p)
        p=payload(a,request_id="same-clock-revision");p["timeframes"]["1h"][-1]["c"]=2499
        await add(a,p)
        r=await build_dataset(a,cutoff=NOW,start=START,end=END,evidence_kind="ENGINEERING_SYNTHETIC",unit_manifest=units(a))
        assert any(x["reason"]=="AMBIGUOUS_VINTAGE_ORDERING" for x in r["exclusions"])
        assert len([c for c in r["rows"] if c["timeframe"]=="1h"])==3
        later=NOW+timedelta(seconds=1);p.update(request_id="unambiguous-revision",captured_at=later.isoformat(),received_at=later.isoformat())
        await add(a,p)
        restored=await build_dataset(a,cutoff=later,start=START,end=END,evidence_kind="ENGINEERING_SYNTHETIC",unit_manifest=units(a))
        assert len([c for c in restored["rows"] if c["timeframe"]=="1h"])==4
    run(scenario())


def test_future_price_bar_cannot_change_prior_assessment(tmp_path):
    source=research_checkout();ds=synthetic_replay_dataset(source)
    def replay(data,name):
        file=tmp_path/(name+"-in.json");file.write_text(json.dumps({"dataset":data,"assessment_start":"2026-10-05T15:04:10Z","assessment_end":"2026-10-05T15:04:11Z"}))
        return run_replay(file,tmp_path/(name+"-out.json"),h1_checkout=source)["records"][0]
    first=replay(ds,"before")
    tail=copy.deepcopy(next(r for r in ds["rows"] if r["timeframe"]=="1m" and r["opened_at"]=="2026-10-05T15:03:00+00:00"))
    tail.update(opened_at="2026-10-05T15:04:00+00:00",scheduled_close_at="2026-10-05T15:05:00+00:00",assumed_available_at="2026-10-05T15:05:10+00:00")
    tail["original"]["t_broker"]+=60;tail["candle"]["timestamp"]=tail["opened_at"]
    for native,key in (("o","open"),("h","high"),("l","low"),("c","close")):
        tail["original"][native]+=1000;tail["candle"][key]+=1000
    tail["value_sha256"]=digest(tail["candle"])
    ds["rows"].append(tail);ds["sha256"]=digest({k:v for k,v in ds.items() if k!="sha256"})
    second=replay(ds,"after")
    assert (first["entry"],first["stop"],first["reason"],first["raw_slots"]) == (second["entry"],second["stop"],second["reason"],second["raw_slots"])
    assert first["anchor"]["A"]==second["anchor"]["A"] and first["anchor"]["B"]==second["anchor"]["B"]
