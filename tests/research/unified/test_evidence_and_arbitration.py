from dataclasses import replace
from decimal import Decimal as D
import concurrent.futures
import json
import pytest
from monatise.research.unified.models import *
from monatise.research.unified.evidence import confirmed_pivots, structural_breaks, displacement, aggregate, Frame, reversal_observations
from monatise.research.unified.eligibility import validate
from monatise.research.unified.arbitration import arbitrate
from monatise.research.unified.store import Store
from monatise.research.unified.service import DecisionService
from .helpers import fixture, NOW, later


def candidate():
    snap,policy,frames,o=fixture()
    c=validate(o,snap,policy,frames)
    assert c.eligible
    return replace(c,context_category='TREND_CONTEXT')


def test_opposing_candidates_abstain_without_consuming_selection():
    a=candidate()
    origin=replace(a.observation.origin,side=Side.SELL)
    o=replace(a.observation,side=Side.SELL,origin=origin)
    b=replace(a,observation=o,plan=replace(a.plan,side=Side.SELL,opportunity_id=o.opportunity_id))
    winner,reason,_=arbitrate([a,b])
    assert winner is None and reason=='OPPOSING_ELIGIBLE_OPPORTUNITIES'


def test_dominance_ties_and_incomparability_are_explicit():
    a=candidate()
    o=replace(a.observation,origin=replace(a.observation.origin,bar_id='new-independent-break'))
    b=replace(a,observation=o,plan=replace(a.plan,opportunity_id=o.opportunity_id))
    assert arbitrate([a,b])[1]=='NO_UNIQUE_DOMINANT_OPPORTUNITY'
    better=replace(a,plan=replace(a.plan,net_rr=(D(4),),cost_risk_ratio=D('.01'),lateness_ns=0))
    assert arbitrate([better,b])[0]==better
    incomparable=replace(b,plan=replace(b.plan,net_rr=(D(5),),cost_risk_ratio=D('.5')))
    assert arbitrate([better,incomparable])[1]=='NO_UNIQUE_DOMINANT_OPPORTUNITY'
    assert arbitrate([better,replace(b,context_category='DIFFERENT_PERMISSION')])[0] is None


def test_extra_c_sweep_evidence_does_not_create_a_competing_identical_plan():
    a=candidate()
    c=replace(a,observation=replace(a.observation,pathway='C'),plan=replace(a.plan,evidence_ids=a.plan.evidence_ids+('sweep',)))
    assert arbitrate([a,c])[0] is not None
    assert len(arbitrate([a,c])[2])==1


def test_same_level_different_episode_and_contract_are_distinct():
    snap,_,_,o=fixture()
    assert o.opportunity_id==replace(o,pathway='B').opportunity_id
    assert o.opportunity_id!=replace(o,origin=replace(o.origin,at_ns=o.origin.at_ns+1)).opportunity_id
    inst=replace(snap.instrument,instrument_id=41272,symbol='GCG7')
    assert o.opportunity_id!=replace(o,origin=replace(o.origin,contract=inst.key)).opportunity_id
    assert o.origin.key==replace(o.origin,available_ns=o.origin.available_ns+1).key


def test_pivot_confirmation_equality_and_outside_bar_ambiguity():
    snap,_,_,_=fixture(); k=snap.instrument.key
    def bars(values):
        return tuple(Bar(k,'1m',NOW-(len(values)-i)*MINUTE,NOW-(len(values)-i-1)*MINUTE,
                         NOW-(len(values)-i-1)*MINUTE,D(x),D(x)+1,D(x)-1,D(x),1,str(i)) for i,x in enumerate(values))
    rows=bars([100,102,105,102,100])
    assert not confirmed_pivots(rows[:-1],2)
    p=confirmed_pivots(rows,2)[0]
    assert p.kind=='HIGH' and p.confirmed_ns==rows[-1].close_ns
    assert not confirmed_pivots(bars([100,102,105,105,100]),2)
    outside=tuple(replace(b,open=D(100),close=D(100),high=D(110),low=D(90)) if i==2 else b for i,b in enumerate(rows))
    assert not confirmed_pivots(outside,2)


def test_missing_minutes_cannot_make_a_parent_but_reviewed_no_print_can():
    snap,_,_,_=fixture();start=NOW-WIDTHS['5m']; k=snap.instrument.key
    rows=tuple(Bar(k,'1m',start+i*MINUTE,start+(i+1)*MINUTE,start+(i+1)*MINUTE,
                   D(100),D(101),D(99),D(100),1,str(i)) for i in range(5) if i!=2)
    x=replace(snap,bars=rows)
    assert not aggregate(x,'5m')
    proof=Coverage('ohlcv-1m',start,NOW,NOW,'SOURCE_RECONCILED_PROVIDER_NO_PRINT')
    parents=aggregate(replace(x,coverage=(proof,)),'5m')
    assert len(parents)==1 and parents[0].volume==4
    assert len(x.bars)==4  # No synthetic flat candle.


def test_future_data_mixed_contracts_and_nonfutures_symbols_are_rejected():
    snap,_,_,_=fixture()
    with pytest.raises(ValueError,match='future_record'):
        replace(snap,quotes=(replace(snap.quotes[0],available_ns=NOW+1),))
    with pytest.raises(ValueError,match='exact_contract'):
        replace(snap,quotes=(replace(snap.quotes[0],contract='wrong'),))
    with pytest.raises(ValueError,match='native_definition'):
        replace(snap.instrument,symbol='BTCUSDT')


def test_target_establishing_touch_before_arm_is_not_a_missed_trade():
    snap,policy,frames,o=fixture()
    old=replace(frames['1m'].bars[0],open_ns=NOW-20*MINUTE,close_ns=NOW-19*MINUTE,
                available_ns=NOW-19*MINUTE,high=D(110))
    f=dict(frames);f['1m']=replace(frames['1m'],bars=(old,)+frames['1m'].bars)
    assert validate(o,snap,policy,f).eligible
    post=replace(old,open_ns=NOW-7*MINUTE,close_ns=NOW-6*MINUTE,available_ns=NOW-6*MINUTE)
    f['1m']=replace(f['1m'],bars=(post,)+frames['1m'].bars)
    assert 'TARGET_PASSED_POST_ARM_BEFORE_SELECTION' in validate(o,snap,policy,f).reasons


def test_concurrent_workers_and_crash_retry_create_one_selection(tmp_path):
    snap,policy,frames,o=fixture()
    path=tmp_path/'parallel.sqlite';Store(path).close()
    def worker(_):
        store=Store(path)
        try:
            return DecisionService(store,policy,stream='parallel').evaluate(snap,'same',observation_override=(o,),frame_override=frames)
        finally:store.close()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        rows=list(pool.map(worker,range(8)))
    assert all(r==rows[0] for r in rows)
    check=Store(path)
    assert check.db.execute('SELECT COUNT(*) FROM selections').fetchone()[0]==1
    assert check.db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]==1
    assert len(check.pending_outbox())==1


def test_clean_process_runtime_import_isolation():
    import subprocess,sys
    code="""import sys,json
from monatise.research.unified.service import DecisionService
from monatise.research.unified.evidence import build_frames
bad=[m for m in sys.modules if m.startswith(('monatise.engines','monatise.application.gold','monatise.crypto'))]
assert not bad,bad
print(json.dumps(sorted(m for m in sys.modules if m.startswith('monatise'))))
"""
    r=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,check=True)
    assert 'monatise.engines' not in r.stdout


@pytest.mark.parametrize('side',[Side.BUY,Side.SELL])
@pytest.mark.parametrize('sweep',[False,True])
def test_models_derive_break_retest_and_reversal_from_price_bars(tmp_path,side,sweep):
    from monatise.research.unified.evidence import observations
    snap,policy,frames,_=fixture(side)
    policy=replace(policy,pivot_radius=1,baseline_bars=3)
    values=[(100,101,99,100),(100,103,100,102),(102,102,98,99),
            ('99.8',101,'99.5','100.5'),('100.5',102,'97.5' if sweep else 99,101),
            (101,108,100,107),(103,'104.2','102.8',104)]
    def mirror(x):return D(x) if side==Side.BUY else D(200)-D(x)
    rows=[]
    for i,x in enumerate(values):
        vals=[mirror(v) for v in x];start=NOW-(7-i)*WIDTHS['5m']
        rows.append(Bar(snap.instrument.key,'5m',start,start+WIDTHS['5m'],start+WIDTHS['5m'],
                        vals[0],max(vals),min(vals),vals[-1],100,str(i)))
    pivots=confirmed_pivots(tuple(rows),1)
    state=State.MIXED if sweep else State.UP if side==Side.BUY else State.DOWN
    frames=dict(frames);frames['5m']=Frame('5m',tuple(rows),pivots,state)
    last=rows[-1]
    m1=replace(last,timeframe='1m',open_ns=NOW-MINUTE)
    frames['1m']=Frame('1m',(m1,),(),state)
    bid=D(104) if side==Side.BUY else D('95.9');ask=D('104.1') if side==Side.BUY else D(96)
    snap=replace(snap,bars=(m1,),quotes=(replace(snap.quotes[0],bid=bid,ask=ask),))
    found=observations(snap,policy,frames)
    active=[o for o in found if o.side==side and o.stage=='TRIGGERED']
    assert any(o.pathway=='A' for o in active)
    if sweep:
        assert any(o.pathway=='C' and 'SWEEP_REJECTION' in [e.kind for e in o.events] for o in active)
    else:
        assert any(o.pathway=='B' for o in active)
    store=Store(tmp_path/'derived.sqlite')
    result=DecisionService(store,policy,stream='derived').evaluate(snap,'derived',observation_override=found,frame_override=frames)
    assert result['trade_action']==side, (result['reason'],[(c['pathway'],c['reasons']) for c in result['candidate_audit']],result['final_revalidation_reasons'])
    assert len(store.pending_outbox())==1
    assert store.db.execute('SELECT COUNT(*) FROM selections').fetchone()[0]==1
