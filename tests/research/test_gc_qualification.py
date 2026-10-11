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


@pytest.mark.parametrize("short",[False,True])
def test_actual_full_chain_positive_native_long_and_short(tmp_path,short):
    r = replay(tmp_path,fixture(short=short))["records"][0]
    assert r["decision"] == ("SHORT" if short else "LONG")
    assert r["qualification_status"] == "QUALIFIED_ANALYTICAL"
    assert r["m15_context"]["evidence"]["gold_pattern"]["confirmed"]
    assert r["m5_context"]["state"] == "trigger_confirmed"
    assert r["waiting_for_entry"] and r["observed_market_price"] != r["entry"]
    assert Decimal(r["tp1_rr"]) >= Decimal('1.5')
    assert len(r["targets"]) == 4
    assert sum(Decimal(t["allocation_pct"]) for t in r["targets"]) == 100
    assert all(Decimal(t["normalized_price"]) % Decimal('.1') == 0 for t in r["targets"])
    assert Decimal(str(r["stop_loss"])) % Decimal('.1') == 0
    costs = r["cost_components"]
    entry,structural = Decimal(str(r["entry"])),Decimal(str(r["structural_invalidation"]))
    buffer = max(Decimal('.1'),Decimal(str(costs["m1_atr_times_configured_multiplier"])))
    buffer += max(Decimal(costs["observed_spread_price"]),entry*Decimal('.0002'))+entry*Decimal('.0003')
    raw = structural+buffer if short else structural-buffer
    expected = (raw/Decimal('.1')).to_integral_value(rounding=ROUND_CEILING if short else ROUND_FLOOR)*Decimal('.1')
    assert Decimal(str(r["stop_loss"])) == expected
    assert Decimal(r["risk_ticks"])*Decimal('.1') == Decimal(r["risk_distance"])
    assert all(r[k] is False for k in SAFETY)
    assert "realized_pnl" not in json.dumps(r) and "win_rate" not in json.dumps(r)


def change_bar(value,tf,index,**changes):
    rows = [r for r in value["bars"] if r["timeframe"] == tf]
    rows[index].update(changes)


@pytest.mark.parametrize("mutation,reason",[
    ("no_sweep","m15_gold_setup_unconfirmed"),("wick","m15_gold_setup_unconfirmed"),
    ("no_displacement","m15_gold_setup_unconfirmed"),("no_retest","m15_gold_setup_unconfirmed"),
    ("no_trigger","m5_gold_trigger_unconfirmed"),("no_zone","gold_entry_zone_unavailable"),
    ("invalid_stop","stop and target are inconsistent with direction"),
    ("rr","tp1_reward_risk_below_minimum"),("no_quote","quote_missing"),
    ("stale_quote","quote_stale"),("future_quote","quote_future_or_outside_session"),
    ("closed_session","exchange_closed_or_unreviewed_session"),("missing_minute","1m:missing_or_no_trade_bar"),
    ("parent_expiry","gold_parent_or_pattern_expired"),
])
def test_real_engines_negative_admission_and_sequence(tmp_path,mutation,reason):
    v = fixture()
    if mutation == "no_sweep": change_bar(v,"15m",-4,low="2491.0")
    if mutation == "wick": change_bar(v,"15m",-4,close="2489.9")
    if mutation == "no_displacement": change_bar(v,"15m",-3,open="2514.0")
    if mutation == "no_retest": change_bar(v,"15m",-2,low="2511.0")
    if mutation == "no_trigger":
        for i in range(-3,0): change_bar(v,"5m",i,open="2500",high="2502",low="2499",close="2500")
    if mutation == "no_zone":
        for b in v["bars"]:
            if b["timeframe"] == "1m":b.update(open="2519",high="2520",low="2518",close="2519")
    if mutation == "rr":v = fixture(positive=False)
    if mutation == "invalid_stop":
        for b in v['bars']:
            if b['timeframe']=='1m':
                for k in ('open','high','low','close'):b[k]=str(Decimal(b[k])-10)
    if mutation == "no_quote":v["quotes"] = {}
    if mutation == "stale_quote":v["quotes"][str(NOW_NS)].update(event_ns=NOW_NS-61*10**9,receive_ns=NOW_NS-61*10**9)
    if mutation == "future_quote":v["quotes"][str(NOW_NS)].update(event_ns=NOW_NS+1,receive_ns=NOW_NS+1)
    if mutation == "closed_session":v["sessions"][0]["end_ns"] = NOW_NS//(60*10**9)*60*10**9
    if mutation == "missing_minute":
        row = [b for b in v["bars"] if b["timeframe"] == "1m"][-5];v["bars"].remove(row)
    if mutation == "parent_expiry":
        # Keep a fresh M1 receipt but no complete new H4 bar: a closure does
        # not renew the old Gold source lifetime.
        for b in v["bars"]:
            if b["timeframe"] == "4h":
                for k in ("open_ns","close_ns","assumed_available_ns"):b[k] -= 4*3600*10**9
        # Move evaluation two hours later within the declared scope; H4 6h old.
        # This case can be transport-stale before the more restrictive TTL.
        v["configuration"]["end_ns"] = NOW_NS+3*3600*10**9
        new = NOW_NS+2*3600*10**9;v["cutoffs_ns"] = [new]
        v["quotes"] = {str(new):{**v["quotes"][str(NOW_NS)],"event_ns":new-10**9,"receive_ns":new-10**9}}
        v["sessions"][0]["end_ns"] += 3*3600*10**9
        # Shift other source bars by 2h so only H4's existing TTL fails.
        for b in v["bars"]:
            if b["timeframe"] != "4h":
                for k in ("open_ns","close_ns","assumed_available_ns"):b[k] += 2*3600*10**9
        closed_end = NOW_NS-10*10**9
        closed_start = closed_end-4*3600*10**9
        end = v['sessions'][0]['end_ns']
        v['sessions'][0]['end_ns'] = closed_start
        v['sessions'].append(dict(start_ns=closed_end,end_ns=end))
        v['bars'] = [b for b in v['bars'] if b['close_ns'] <= closed_start or b['open_ns'] >= closed_end]
        template = next(b for b in v['bars'] if b['timeframe']=='5m')
        for i in range(50):
            opened=closed_start-(50-i)*300*10**9
            v['bars'].append({**template,'open_ns':opened,'close_ns':opened+300*10**9,
                             'assumed_available_ns':opened+310*10**9,
                             'source_hashes':[digest({'preclosure_warmup':opened})]})
    v["configuration_sha256"] = digest(v["configuration"])
    r = replay(tmp_path,v)["records"][0]
    assert r["candidate_id"] is None
    assert any(reason in e for e in r["rejection_reasons"]),r["rejection_reasons"]


def test_future_perturbation_cannot_change_prior_decision(tmp_path):
    value = fixture()
    original = replay(tmp_path,value,"original")
    future = copy.deepcopy([b for b in value["bars"] if b["timeframe"] == "1m"][-1])
    for k in ("open_ns","close_ns","assumed_available_ns"):future[k] += 60*10**9
    future.update(open="4000",high="5000",low="2000",close="4500")
    value["bars"].append(future)
    assert replay(tmp_path,value,"future") == original


@pytest.mark.parametrize("conflict",[False,True])
def test_duplicate_or_historical_revision_rejected(tmp_path,conflict):
    v = fixture();row = copy.deepcopy(v["bars"][0])
    if conflict:row["close"] = row["open"]
    v["bars"].append(row)
    with pytest.raises(RuntimeError,match="duplicate_or_revised_bars"):replay(tmp_path,v)


def test_repeat_is_deterministic_and_same_trigger_not_independent(tmp_path):
    v = fixture();new = NOW_NS+10*10**9
    v["cutoffs_ns"].append(new)
    v["quotes"][str(new)] = v["quotes"][str(NOW_NS)]
    first = replay(tmp_path,v,"first");second = replay(tmp_path,v,"second")
    assert first == second
    assert first["summary"]["qualified_long_observations"] == 2
    assert first["summary"]["distinct_analytical_candidates"] == 1
    assert first["records"][0]["expires_at"] == first["records"][1]["expires_at"]


@pytest.mark.parametrize("key,value",[("tick_size",".01"),("multiplier","1"),("monetary_tick_usd","1")])
def test_native_units_reject_broker_substitution(tmp_path,key,value):
    v = fixture();v["contract"][key] = value
    with pytest.raises(RuntimeError,match="unreviewed GC units"):replay(tmp_path,v)


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


def test_prepared_output_activation_is_rejected(tmp_path):
    v = fixture();v['execution_enabled'] = True
    with pytest.raises(RuntimeError,match='research_activation_forbidden'):replay(tmp_path,v)


def test_incomplete_input_runs_only_unadmitted_price_diagnostics(tmp_path):
    v=fixture();v['bars'].remove([b for b in v['bars'] if b['timeframe']=='1m'][-5])
    r=replay(tmp_path,v)['records'][0]
    assert r['decision']=='UNAVAILABLE' and r['candidate_id'] is None
    assert r['unadmitted_price_diagnostic']['engines_executed']
    assert r['unadmitted_price_diagnostic']['candidate_eligible'] is False


def test_future_frozen_anchor_never_linked(tmp_path):
    v=fixture()
    v['frozen_associations']=[dict(h1_parent_cutoff='2026-10-05T16:00:10+00:00',cutoff_ns=NOW_NS,
        anchor={'A':{'known_at':'2026-10-05T17:00:10+00:00'}})]
    with pytest.raises(RuntimeError,match='future_frozen_anchor'):replay(tmp_path,v)


def test_research_source_mutation_blocks_replay(tmp_path):
    v=fixture();v['configuration']['research_source_hashes']={'worker.py':'0'*64}
    v['configuration_sha256']=digest(v['configuration'])
    with pytest.raises(ValueError,match='research_source_changed'):replay(tmp_path,v)


def test_failed_run_stays_quarantined_without_immutable_promotion(tmp_path,monkeypatch):
    from monatise.research.gc_qualification import runner
    monkeypatch.setattr(runner,'verify_research_checkout',lambda p:p)
    def failed(*args,**kwargs):raise ValueError('incomplete')
    monkeypatch.setattr(runner,'isolated',failed)
    folder=tmp_path/'failed'
    with pytest.raises(ValueError,match='incomplete'):runner.run(data_root=tmp_path,h1_checkout=tmp_path,output=folder)
    assert json.loads((folder/'quarantine.json').read_text())['status']=='QUARANTINED_INCOMPLETE_RESEARCH_RUN'
    assert not (folder/'immutable').exists() and not (folder/'summary.json').exists()


@pytest.mark.parametrize('short',[False,True])
def test_pinned_canonical_math_parity_and_actual_event_type_semantics(tmp_path,short):
    if not PINNED.exists():pytest.skip('explicit frozen H1 checkout required')
    inp = tmp_path/'fixture.json';inp.write_text(json.dumps(fixture(short=short)))
    code = '''
import sys,json
from pathlib import Path
from dataclasses import replace
sys.path.insert(0,sys.argv[1])
import monatise.research
monatise.research.__path__.append(str(Path(sys.argv[2])/'monatise/research'))
from monatise.research.gc_qualification.adapter import NativeGoldEvaluator,CutoffAdapter,native_plan
from monatise.research.gc_qualification.worker import make_contract
from monatise.research.gc_fib.worker import parse_bar,instant
from monatise.application.gold_analysis import GoldLayerEvaluator,sweep_reversal
from monatise.application.hierarchy.coordinator import HierarchyConfiguration
from monatise.engines.market_structure.models import BreakType
from monatise.application.take_profit import TargetCandidate
from monatise.application.target_evidence import candidate
from datetime import timedelta
from decimal import Decimal
v=json.loads(Path(sys.argv[3]).read_text());contract=make_contract(v['contract'])
adapter=CutoffAdapter(tuple(parse_bar(b) for b in v['bars']),v['sessions'])
frames,issues,_=adapter.frames(v['cutoffs_ns'][0]);assert not issues
now=instant(v['cutoffs_ns'][0]);native=NativeGoldEvaluator(contract)
n=native.evaluate_native(frames,now=now,spread=Decimal('.2'))
canonical=GoldLayerEvaluator(asset_route='gold',configuration=native.configuration)
canonical.broker_units=contract.units('.2')
c=canonical.evaluate('GCZ6',frames,evaluated_at=now,macro_degraded=True)
assert c.validation.eligible_for_shadow_decision and n.validation.eligible_for_shadow_decision
for field in ('reference_entry','structural_invalidation','volatility_buffer','estimated_spread_allowance','estimated_slippage_allowance','final_stop'):
    assert getattr(c.bundle.risk_inputs,field)==getattr(n.bundle.risk_inputs,field),field
for field in ('regime_4h','strategy_1h','setup_15m','trigger_5m'):
    assert getattr(c,field)==getattr(n,field),field
assert c.take_profit_plan.targets[0].price != native.plan.targets[0].price # explicitly reported native tick difference
# Preparation uses the actual M15 sweep, never Fibonacci invalidation.
prepared=canonical.prepare_entry_stop(c.trigger_5m,now,entry_layer=native.layers['1m'],stop_layer=native.layers['15m'])
assert prepared==native.prepared
layer=native.layers['5m'];direction=c.trigger_5m.direction
events=tuple(replace(e,break_type=BreakType.FAILED_BULLISH_BREAK if direction=='long' else BreakType.FAILED_BEARISH_BREAK) if e.confirmed else e for e in layer.structure.events)
failed=replace(layer,structure=replace(layer.structure,events=events))
assert canonical._trigger_state(failed,direction)==native._trigger_state(failed,direction)
assert native._trigger_state(failed,direction).value=='trigger_confirmed' # existing accepted semantics, no new enum restriction
# Chronology must fail if the parent's retest is later than the current M5 event.
parent=canonical._state['GCZ6'].setup_context
canonical._state['GCZ6'].setup_context=replace(parent,evidence={**parent.evidence,'gold_pattern':{**parent.evidence['gold_pattern'],'retest_close':now.isoformat()}})
assert canonical._trigger_state(layer,direction).value=='trigger_rejected'
cs=native.layers['15m'].market.candles
assert sweep_reversal(cs,direction,'15m')['confirmed']
assert not sweep_reversal(cs[:-2],direction,'15m')['confirmed']
# A near target fails even when a farther objective is attractive.
sign=1 if direction=='long' else -1;entry=prepared.reference_entry;risk=abs(entry-prepared.final_stop)
near=candidate(entry+sign*risk,provider='canonical',kind='SWING_HIGH',timeframe='1h',observed=now)
far=candidate(entry+sign*risk*5,provider='canonical',kind='SWING_HIGH',timeframe='1h',observed=now)
try:native_plan([near,far],prepared,now=now,config=native.target_config,tick=Decimal('.1'))
except ValueError as e:assert 'cannot skip first objective' in str(e)
else:raise AssertionError('weak nearest objective skipped')
# Independent right-side swing confirmation: the pivot itself is never known at its open.
for kind,points in [('high',layer.structure.swing_highs),('low',layer.structure.swing_lows)]:
    for index,price in points:
        assert index+3<len(frames['5m'].candles)
        assert frames['5m'].candles[index+3].received_at > frames['5m'].candles[index].scheduled_close_time
print('canonical components verified')
'''
    result = subprocess.run([sys.executable,'-I','-c',code,str(PINNED),str(ROOT),str(inp)],
                            env={'PATH':'/usr/bin:/bin'},capture_output=True,text=True)
    assert result.returncode == 0,result.stderr
    assert 'canonical components verified' in result.stdout
