"""Offline SDK-shaped fixtures; no provider credentials, requests or charges."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from decimal import Decimal
from datetime import UTC, datetime

import pytest

dbn = pytest.importorskip("databento_dbn")

from monatise.research.databento.advanced import AdvancedAdapters, book_metrics, visible_changes
from monatise.research.databento.candles import (
    ExchangeCalendar, HistoricalBar, ResearchArtifactStore, RollSelection, WIDTHS,
    aggregate, normalize_candle, quality,
)
from monatise.research.databento.controls import LocalHistoricalMetadata, ResearchLedger
from monatise.research.databento.datasets import (
    DatasetCapability, DatasetRegistry, discover, select_contracts,
)
from monatise.research.databento.options import join_inputs, normalize_open_interest
from monatise.research.databento.archive import NativeDBNArchive
from monatise.research.databento.acquisition import HistoricalAcquisition
from tests.research.test_databento_foundations import NOW_NS, DAY, future, option, policy
from tests.research.test_databento_history import (
    START, END, FixtureSource, request, preflight, approval, trade, service,
)


def capability():
    return DatasetCapability("GLBX.MDP3",("definition","trades","ohlcv-1m","ohlcv-1h","mbp-1","mbp-10","mbo"),
                             NOW_NS-DAY,"a"*64)


def identity(**changes):
    record = future(**({"ts_event":NOW_NS-10*DAY,"ts_recv":NOW_NS-10*DAY+1}|changes))
    return discover(record,publishers={1:("GLBX.MDP3","GLBX")},capability=capability(),as_of_ns=NOW_NS)


def ledger(tmp_path, budget="20"):
    result = ResearchLedger(tmp_path/"control.sqlite")
    result.configure(approved_budget_usd=budget,review_reference="synthetic-budget",historical_credit_usd="125")
    return result


def test_dataset_schema_origin_and_entitlement_are_separate():
    registry = DatasetRegistry()
    with pytest.raises(ValueError): registry.get("GLBX.MDP3")
    registry.observe(capability())
    registry.get("GLBX.MDP3").require("mbp-10",at_ns=NOW_NS)
    with pytest.raises(ValueError,match="entitlement"):
        registry.get("GLBX.MDP3").require("mbp-10",at_ns=NOW_NS,licensed=True)
    with pytest.raises(ValueError): registry.get("XNAS.ITCH")
    with pytest.raises(ValueError): registry.observe(capability())
    assert len(registry.sha256)==64


@pytest.mark.parametrize("product,exchange,symbol",[("GC","XCEC","GCZ6"),("ES","XCME","ESZ6"),
                                                   ("NQ","XCME","NQZ6"),("CL","XNYM","CLZ6")])
def test_definition_discovery_and_exact_cme_requests(product,exchange,symbol):
    value = identity(asset=product,exchange=exchange,raw_symbol=symbol)
    assert value.product==product and value.raw_symbol==symbol
    assert select_contracts([value],product=product,at_ns=NOW_NS)==(value,)
    scope = request(contracts=((1,value.instrument_id,symbol),))
    assert scope.api_parameters()["symbols"]==[symbol]
    assert scope.api_parameters()["stype_in"]=="raw_symbol"
    with pytest.raises(ValueError): select_contracts([value,value],product=product,at_ns=NOW_NS)


@pytest.mark.parametrize("changes",[{"raw_symbol":"GC.v.0"},{"raw_symbol":"GCZ7"},
                                      {"exchange":"XCME"},{"leg_count":2},{"expiration":NOW_NS}])
def test_discovery_rejects_aliases_maturity_spreads_and_expiry(changes):
    with pytest.raises(ValueError): identity(**changes)


def test_options_discovery_retains_underlying_and_native_strike():
    value=discover(option(),publishers={1:("GLBX.MDP3","GLBX")},capability=capability(),as_of_ns=NOW_NS)
    assert value.product=="OG" and value.strike_fixed and value.underlying_id==41271


def test_local_metadata_cas_checkpoint_and_restart(tmp_path):
    store=LocalHistoricalMetadata(tmp_path/"control.sqlite")
    first=asyncio.run(store.create("test",{"n":1}))
    assert asyncio.run(LocalHistoricalMetadata(store.path).get("test")).value=={"n":1}
    second=asyncio.run(store.replace(first,{"n":2}))
    assert second.version==2
    with pytest.raises(RuntimeError,match="conflict"): asyncio.run(store.replace(first,{"n":3}))
    checkpoint=dict(config_sha256="a"*64,archive_sha256="b"*64,record_ordinal=3)
    asyncio.run(store.checkpoint("r1",checkpoint))
    with pytest.raises(ValueError): asyncio.run(store.checkpoint("r1",{**checkpoint,"record_ordinal":2}))


def test_zero_budget_credit_does_not_make_download_free(tmp_path):
    svc=HistoricalAcquisition(metadata=LocalHistoricalMetadata(tmp_path/"metadata.sqlite"),
        archive=NativeDBNArchive(tmp_path/"raw"),source=FixtureSource([trade()]),clock_ns=lambda:NOW_NS)
    with pytest.raises(ValueError,match="budget"):
        asyncio.run(svc.acquire(request(),preflight(),approval()))
    assert svc.source.calls==0
    assert svc.cost_control.report()["approved_budget_usd"]=="0"


def test_reservations_atomic_across_researchers_and_unknown_billing_retained(tmp_path):
    control=ledger(tmp_path,budget="2")
    def reserve(index):
        req=request(start_ns=START+index*2*10**9,end_ns=END+index*2*10**9)
        p=preflight(req,available_to_ns=req.end_ns+1)
        a=approval(req,p,approval_id=f"review-{index}")
        try: ResearchLedger(control.path).reserve(req,p,a);return True
        except ValueError:return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve,[0,1]))==[False,True]
    report=control.report()
    assert report["unreconciled_attempts"]==1 and Decimal(report["remaining_budget_usd"])==0
    assert report["historical_credit_usd"]=="125" and report["settled_api_usage_usd"]=="0"


def test_overlap_cache_superset_and_cost_settlement(tmp_path):
    svc=service(tmp_path)
    manifest=asyncio.run(svc.acquire(request(),preflight(),approval()))
    subset=request(start_ns=START+1,end_ns=END-1)
    plan=svc.cost_control.plan(subset,archive=svc.archive)
    assert plan["incremental_cost_usd"]=="0" and len(plan["covering_manifests"])==1
    # Cache reuse needs no new preflight, approval or payment.
    assert asyncio.run(svc.acquire(subset,None,None))["status"]=="CACHE_AVAILABLE"
    overlapping=request(end_ns=END+1)
    p=preflight(overlapping,available_to_ns=END+2)
    with pytest.raises(ValueError,match="overlap"):
        svc.cost_control.reserve(overlapping,p,approval(overlapping,p,approval_id="new"))
    svc.cost_control.settle("review-1",actual_billed_usd="1.80",credit_used_usd="1.00",billing_review_reference="fixture-bill")
    assert svc.cost_control.report()["settled_cash_usd"]=="0.80"
    assert svc.cost_control.report()["settled_api_usage_usd"]=="1.80"
    assert manifest["actual_billed_usd"] is None and svc.source.calls==1


def test_lowest_transport_budget_permit_is_one_use(tmp_path):
    control=ledger(tmp_path)
    control.reserve(request(),preflight(),approval())
    control.authorize_transport(request(),preflight(),approval())
    with pytest.raises(ValueError,match="unused"):
        control.authorize_transport(request(),preflight(),approval())


def test_partition_cache_covers_union_and_reports_only_true_uncovered_ranges(tmp_path):
    svc=service(tmp_path)
    original=request()
    midpoint=START+(END-START)//2
    first=request(end_ns=midpoint)
    second=request(start_ns=midpoint)
    for i,req in enumerate((first,second)):
        p=preflight(req)
        # Native fixture events fall inside their explicit partition.
        svc.source=FixtureSource([trade(offset=100 if i==0 else (midpoint-START)+100)])
        asyncio.run(svc.acquire(req,p,approval(req,p,approval_id=f"partition-{i}")))
    plan=svc.cost_control.plan(original,archive=svc.archive)
    assert not plan["covering_manifests"] and len(plan["reusable_manifests"])==2
    assert not plan["new_download_required"] and plan["incremental_cost_usd"]=="0"
    wider=request(end_ns=END+100)
    assert svc.cost_control.plan(wider,archive=svc.archive)["uncovered_ranges"]==[
        {"contract":original.contracts[0],"start_ns":END,"end_ns":END+100}]


OPEN=1791158400*10**9


def calendar():
    return ExchangeCalendar("GLBX.MDP3","XCEC","synthetic-session","a"*64,"test-v1",
                            OPEN,OPEN+DAY,((OPEN,OPEN+4*WIDTHS["1h"]),))


def bar(i=0, **changes):
    data=dict(identity=identity(),timeframe="1m",open_ns=OPEN+i*WIDTHS["1m"],
        close_ns=OPEN+(i+1)*WIDTHS["1m"],prices_fixed=(2500*10**9,2501*10**9,2499*10**9,2500*10**9),
        volume=2,retrieval_ns=NOW_NS,source_hashes=(f"{i+1:064x}",),
        schema="ohlcv-1m",evidence_kind="ENGINEERING_SYNTHETIC")
    return HistoricalBar(**(data|changes))


def test_candles_all_timeframes_replay_determinism_and_holiday_closure():
    rows=[bar(i) for i in range(240)]
    for tf,count in [("5m",48),("15m",16),("1h",4),("4h",1)]:
        first=aggregate(rows,target=tf,calendar=calendar())
        assert first==aggregate(reversed(rows),target=tf,calendar=calendar())
        assert len(first[0])==count and not first[1]
        assert sum(b.volume for b in first[0])==480
    ready,report=quality(rows,identity=identity(),timeframe="1m",start_ns=OPEN,
        end_ns=OPEN+DAY,as_of_ns=NOW_NS,calendar=calendar())
    assert len(ready)==240 and not report["missing_or_no_trade_intervals"]


def test_missing_duplicate_forming_and_expired_bars():
    rows=[bar(i) for i in range(5) if i!=2]
    result,rejected=aggregate(rows,target="5m",calendar=calendar())
    assert not result and rejected[0]["missing_ns"]==[OPEN+2*WIDTHS["1m"]]
    with pytest.raises(ValueError,match="duplicate"):aggregate([bar(),bar()],target="5m",calendar=calendar())
    ready,report=quality([bar()],identity=identity(),timeframe="1m",start_ns=OPEN,
        end_ns=OPEN+WIDTHS["1m"],as_of_ns=OPEN+WIDTHS["1m"],calendar=calendar())
    assert not ready and report["forming_or_not_finalized"]==[OPEN]
    with pytest.raises(ValueError):bar(retrieval_ns=OPEN+1)
    with pytest.raises(ValueError):bar(prices_fixed=(1,0,2,1))


def test_native_one_hour_schema_no_price_scaling_and_roll_is_explicit():
    record=dbn.OHLCVMsg(rtype=dbn.RType.OHLCV_1H,publisher_id=1,instrument_id=41271,
        ts_event=OPEN,open=2500*10**9,high=2501*10**9,low=2499*10**9,close=2500*10**9,volume=3)
    normalized=normalize_candle(record,schema="ohlcv-1h",identity=identity(),retrieval_ns=NOW_NS,
                                evidence_kind="ENGINEERING_SYNTHETIC")
    assert normalized.prices_fixed[0]==2500*10**9
    with pytest.raises(ValueError):normalize_candle(record,schema="ohlcv-1m",identity=identity(),retrieval_ns=NOW_NS,
                                                  evidence_kind="ENGINEERING_SYNTHETIC")
    new=identity(raw_symbol="GCG7",instrument_id=42,maturity_month=2,maturity_year=2027,expiration=NOW_NS+60*DAY)
    roll=RollSelection(identity(),new,NOW_NS,"synthetic-roll")
    assert roll.old.raw_symbol!=roll.new.raw_symbol
    with pytest.raises(ValueError):aggregate([bar(),bar(1,identity=new)],target="5m",calendar=calendar())


def quote(schema="mbp-10", *, extra_size=0, offset=0, **changes):
    levels=[dbn.BidAskPair(bid_px=(2500-i)*10**9,ask_px=(2501+i)*10**9,
        bid_sz=3+extra_size,ask_sz=1,bid_ct=1,ask_ct=1) for i in range(10 if schema=="mbp-10" else 1)]
    params=dict(publisher_id=1,instrument_id=41271,ts_event=START+100+offset,ts_recv=START+101+offset,
        price=2500*10**9,size=1,action=dbn.Action.TRADE,side=dbn.Side.NONE,depth=0,sequence=1,flags=0)
    params.update(changes)
    return dbn.MBP10Msg(**params,levels=levels) if schema=="mbp-10" else dbn.MBP1Msg(**params,levels=levels[0])


def test_advanced_default_disabled_and_mbo_requires_question():
    adapters=AdvancedAdapters(identity=identity())
    with pytest.raises(ValueError,match="disabled"):adapters.normalize("trades",trade())
    with pytest.raises(ValueError,match="question"):AdvancedAdapters(identity=identity(),enabled_schemas=("mbo",))
    with pytest.raises(ValueError):request(schema="mbo")
    with pytest.raises(ValueError):request(schema="mbp-10")


@pytest.mark.parametrize("schema",["mbp-1","mbp-10"])
def test_native_depth_metrics_visible_liquidity_never_trade_volume(schema):
    adapters=AdvancedAdapters(identity=identity(),enabled_schemas=(schema,))
    before=adapters.normalize(schema,quote(schema))
    metrics=book_metrics(before)
    assert Decimal(metrics["imbalance"])==Decimal(".5") and metrics["spread"]=="1"
    assert metrics["executed_volume"] is None and metrics["institutional_intent"] is None
    after=adapters.normalize(schema,quote(schema,extra_size=1,offset=1))
    assert visible_changes(before,after)["cause"]=="UNKNOWN_FROM_SNAPSHOTS"
    with pytest.raises(ValueError):adapters.normalize(schema,quote(schema,flags=8))
    with pytest.raises(ValueError):adapters.normalize(schema,quote(schema,instrument_id=999))


def test_unknown_trade_side_and_mbo_events_preserve_native_semantics():
    adapters=AdvancedAdapters(identity=identity(),enabled_schemas=("trades","mbo"),mbo_research_reference="fixture-lifecycle")
    assert adapters.normalize("trades",trade(side=dbn.Side.NONE)).payload[2] is None
    for action in (dbn.Action.ADD,dbn.Action.MODIFY,dbn.Action.CANCEL,dbn.Action.FILL):
        r=dbn.MBOMsg(publisher_id=1,instrument_id=41271,ts_event=START+100,ts_recv=START+101,
            price=2500*10**9,size=1,action=action,side=dbn.Side.BID,sequence=1,flags=0,order_id=99,channel_id=1)
        observation=adapters.normalize("mbo",r)
        assert observation.payload[0]==99 and not observation.execution_eligible
    assert observation.payload[-1]=="INFORMATIONAL_FILL_NO_DOUBLE_COUNT"


def test_empty_depth_sentinels_and_bad_book_order_rejected():
    adapters=AdvancedAdapters(identity=identity(),enabled_schemas=("mbp-10",))
    r=quote()
    kwargs=dict(publisher_id=1,instrument_id=41271,ts_event=r.ts_event,ts_recv=r.ts_recv,
                price=r.price,size=r.size,action=r.action,side=r.side,depth=0,sequence=1,flags=0)
    empty=dbn.BidAskPair(bid_px=2**63-1,ask_px=2**63-1,bid_sz=0,ask_sz=0,bid_ct=0,ask_ct=0)
    levels=[r.levels[0]]+[empty]*9
    observed=adapters.normalize("mbp-10",dbn.MBP10Msg(**kwargs,levels=levels))
    assert observed.payload[-1][0] is None and book_metrics(observed)["visible_bid_quantity"]==3
    for bad in ([empty,r.levels[0]]+[empty]*8,[r.levels[0]]*10):
        with pytest.raises(ValueError):adapters.normalize("mbp-10",dbn.MBP10Msg(**kwargs,levels=bad))


def test_options_input_join_missing_oi_and_future_publication_rejected():
    from monatise.application.gold_options import normalize_option
    from monatise.adapters.databento_gold import definition
    f=definition(future(),publishers=policy().mapping,now=datetime.fromtimestamp(NOW_NS//10**9,UTC),identity_policy=policy())
    from monatise.research.databento.registry import STANDARD_OG
    normalized=normalize_option(option(),futures={41271:f},publishers=policy().mapping,
        now=datetime.fromtimestamp(NOW_NS//10**9,UTC),
        convention=STANDARD_OG,identity_policy=policy())
    oi=discover(option(),publishers=policy().mapping,capability=capability(),as_of_ns=NOW_NS)
    oq=AdvancedAdapters(identity=oi,enabled_schemas=("mbp-1",)).normalize("mbp-1",
        quote("mbp-1",instrument_id=oi.instrument_id))
    fq=AdvancedAdapters(identity=identity(),enabled_schemas=("mbp-1",)).normalize("mbp-1",quote("mbp-1"))
    kwargs=dict(definition=normalized,definition_available_ns=NOW_NS,option_quote=oq,
                underlying_quote=fq,quote_available_ns=NOW_NS,cutoff_ns=NOW_NS,
                maximum_quote_age_ns=60*10**9)
    # Quotes in the shared fixtures are a day old; point-in-time joins fail closed.
    with pytest.raises(ValueError,match="stale"):join_inputs(**kwargs)
    oq=replace(oq,event_ns=NOW_NS-1,receive_ns=NOW_NS)
    fq=replace(fq,event_ns=NOW_NS-1,receive_ns=NOW_NS)
    kwargs.update(option_quote=oq,underlying_quote=fq)
    result=join_inputs(**kwargs)
    assert result["open_interest"] is None and result["gamma_flip"] is None and not result["gil_enabled"]
    record=dbn.StatMsg(publisher_id=1,instrument_id=oi.instrument_id,ts_event=NOW_NS-1,ts_recv=NOW_NS,
        ts_ref=NOW_NS-DAY,price=2**63-1,quantity=50,stat_type=dbn.StatType.OPEN_INTEREST,sequence=1,
        update_action=dbn.StatUpdateAction.NEW,stat_flags=0)
    interest=normalize_open_interest(record,available_ns=NOW_NS+1)
    with pytest.raises(ValueError,match="OI"):join_inputs(**kwargs,open_interest=interest)


def test_immutable_derived_artifacts_and_replay_hash(tmp_path):
    store=ResearchArtifactStore(tmp_path)
    value=dict(version="fixture-v1",input_sha256="a"*64,formula="unchanged-canonical",trading_eligible=False)
    path,digest=store.publish("replays",value)
    assert store.publish("replays",value)==(path,digest)
    assert json.loads(path.read_text())==value
