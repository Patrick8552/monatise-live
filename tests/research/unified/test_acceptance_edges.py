from dataclasses import replace
from decimal import Decimal as D
import pytest
from monatise.research.unified.models import *
from monatise.research.unified.service import DecisionService
from monatise.research.unified.store import Store,Conflict
from monatise.research.unified.eligibility import validate,final_revalidate
from monatise.research.unified.arbitration import arbitrate,earliest_baseline
from monatise.research.unified.evidence import EvidenceCache
from monatise.research.unified.diagnostics import executed_window
from .helpers import fixture,later,NOW
from .test_evidence_and_arbitration import candidate


def test_final_selection_time_and_cursor_follow_final_observation(tmp_path):
    snap,p,frames,o=fixture();s=Store(tmp_path/'final.sqlite')
    result=DecisionService(s,p,stream='final',final_snapshot=lambda x:later(x,NOW+MINUTE)).evaluate(snap,'first',observation_override=(o,),frame_override=frames)
    assert result['trade_action']=='BUY'
    assert result['selected_plan']['selected_at_ns']==NOW+MINUTE
    with pytest.raises(Conflict,match='PRECEDES_SELECTION'):
        s.position_event('final',result['selection_event_id'],'FILL',NOW+1,{'price':'101.2'})
    with pytest.raises(Conflict,match='STALE'):
        DecisionService(s,p,stream='final').evaluate(later(snap,NOW+MINUTE//2),'old',observation_override=(o,),frame_override=frames)


def test_final_price_recovery_cannot_hide_a_stop_breach():
    snap,p,f,o=fixture();plan=validate(o,snap,p,f).plan
    t=Trade(snap.instrument.key,NOW+1,NOW+1,NOW+2,D(97),1,'SELL','late-native-execution')
    new=replace(later(snap,NOW+MINUTE),trades=(t,))
    assert 'FINAL_STOP_BREACHED_IN_WINDOW' in final_revalidate(plan,new,p)


def test_final_spread_change_is_checked_even_if_ask_still_matches_entry():
    snap,p,f,o=fixture();plan=validate(o,snap,p,f).plan
    assert 'FINAL_SPREAD_WIDENED' in final_revalidate(plan,later(snap,NOW+1,bid='100.9'),p)


def test_completed_shadow_trade_cannot_be_selected_again(tmp_path):
    snap,p,f,o=fixture();store=Store(tmp_path/'done.sqlite');service=DecisionService(store,p,stream='done')
    r=service.evaluate(snap,'first',observation_override=(o,),frame_override=f)
    sid=r['selection_event_id']
    store.position_event('done',sid,'FILL',NOW+1,{'price':'101.2','initial_risk':'360'})
    store.position_event('done',sid,'OUTCOME',NOW+2,{'realized_r':'1','hypothetical':True})
    again=service.evaluate(later(snap,NOW+MINUTE),'again',observation_override=(o,),frame_override=f)
    assert again['trade_action']=='NO_TRADE'
    assert 'SELECTED_OPPORTUNITY_ALREADY_COMPLETED' in again['candidate_audit'][0]['reasons']
    assert len(store.pending_outbox())==1


def test_explicit_roll_supersedes_old_signal_not_old_position(tmp_path):
    snap,p,f,o=fixture();store=Store(tmp_path/'roll.sqlite')
    DecisionService(store,p,stream='roll').evaluate(snap,'first',observation_override=(o,),frame_override=f)
    store.roll_contract('roll',snap.instrument.key,'different-exact-contract',NOW+1)
    assert store.status('roll',o.opportunity_id)=='SUPERSEDED'
    with pytest.raises(Conflict,match='TERMINAL'):
        store.transition('roll',o.opportunity_id,'TRIGGERED',NOW+2)
    assert store.db.execute('SELECT COUNT(*) FROM position_events').fetchone()[0]==0


def test_ambiguous_same_episode_plans_do_not_create_a_runner_up_selection():
    a=candidate();worse_cost_better_reward=replace(a,plan=replace(a.plan,net_rr=(D(10),),cost_risk_ratio=D(1)))
    other_o=replace(a.observation,origin=replace(a.observation.origin,bar_id='other-root'))
    other=replace(a,observation=other_o,plan=replace(a.plan,opportunity_id=other_o.opportunity_id))
    winner,reason,_=arbitrate([a,worse_cost_better_reward,other])
    assert winner is None and reason=='INCOMPARABLE_SAME_EPISODE_PLANS'


def test_registered_baseline_uses_time_but_does_not_break_a_tie_with_ids():
    a=candidate();o=replace(a.observation,origin=replace(a.observation.origin,bar_id='distinct'))
    b=replace(a,observation=o,plan=replace(a.plan,opportunity_id=o.opportunity_id))
    assert earliest_baseline([a,b])[1]=='BASELINE_TRIGGER_TIME_TIE'
    b=replace(b,plan=replace(b.plan,trigger_ns=b.plan.trigger_ns+1))
    assert earliest_baseline([a,b])[0]==a


def test_cache_shares_only_immutable_evidence_not_experiment_state():
    snap,p,_,_=fixture();cache=EvidenceCache()
    first=cache.get(snap,p);second=cache.get(snap,p)
    assert first is not second and first[0] is second[0]
    third=cache.get(snap,replace(p,pivot_radius=1))
    assert first[0] is not third[0]


def test_exact_executed_vwap_unknown_sides_and_profile_are_not_session_cvd():
    snap,_,_,_=fixture()
    trades=tuple(Trade(snap.instrument.key,NOW-10+i,NOW-10+i,NOW-10+i,D(price),qty,side,str(i))
                 for i,(price,qty,side) in enumerate([(100,2,'BUY'),(102,1,'SELL'),(101,1,None)]))
    result=executed_window(replace(snap,trades=trades),5)
    assert D(result['vwap'])==D('100.75') and result['point_of_control']=='100'
    assert result['known_side_delta']==1 and result['unknown_side_contracts']==1
    assert result['scope']=='EXACT_RETAINED_WINDOW_NOT_FULL_SESSION'
    assert not result['complete_exchange_continuity_certified']


def test_unsafe_context_or_observation_data_cannot_be_supplied_as_market_evidence(tmp_path):
    snap,p,frames,o=fixture();s=DecisionService(Store(tmp_path/'x.sqlite'),p,stream='x')
    with pytest.raises(ValueError,match='engineering_override_forbidden'):
        s.evaluate(replace(snap,evidence_kind='GENUINE_NATIVE_ARCHIVE'),'market',observation_override=(o,),frame_override=frames)
    future=replace(o,detected_ns=NOW+1)
    with pytest.raises(ValueError,match='NONCAUSAL'):
        s.evaluate(snap,'future',observation_override=(future,),frame_override=frames)


def test_policy_booleans_cannot_be_truthy_strings():
    from monatise.research.unified.policy import Policy
    with pytest.raises(ValueError,match='boolean_policy'):
        Policy(behavior_checked='false')
    snap,_,_,_=fixture()
    with pytest.raises(ValueError,match='news_coverage_boolean'):
        replace(snap,news_coverage='false')


def test_replay_cutoffs_use_registered_publication_availability():
    from types import SimpleNamespace
    from monatise.research.unified.replay import cutoffs
    snap,_,f,_=fixture()
    bar=replace(f['5m'].bars[-1],available_ns=NOW+1000000)
    assert cutoffs(SimpleNamespace(mode='HISTORICAL_EVENT_TIME',bars=(bar,)))==[NOW+1000000]


def test_identical_decisions_do_not_depend_on_ambient_decimal_context(tmp_path):
    from decimal import localcontext
    snap,p,f,o=fixture()
    with localcontext() as ctx:
        ctx.prec=7
        one=DecisionService(Store(tmp_path/'low.sqlite'),p,stream='same').evaluate(snap,'same',observation_override=(o,),frame_override=f)
    with localcontext() as ctx:
        ctx.prec=60
        two=DecisionService(Store(tmp_path/'high.sqlite'),p,stream='same').evaluate(snap,'same',observation_override=(o,),frame_override=f)
    assert one==two and one['numeric_decimal_precision']==40


def test_manual_lifecycle_event_advances_monotonic_stream_guard(tmp_path):
    snap,p,f,o=fixture();store=Store(tmp_path/'manual-clock.sqlite');service=DecisionService(store,p,stream='clock')
    service.evaluate(snap,'initial',observation_override=(o,),frame_override=f)
    store.transition('clock',o.opportunity_id,'INVALIDATED',NOW+2*MINUTE)
    with pytest.raises(Conflict,match='STALE'):
        service.evaluate(later(snap,NOW+MINUTE),'late-cycle',observation_override=(o,),frame_override=f)


def test_standalone_lifecycle_failure_rolls_back_state_and_cursor(tmp_path):
    import sqlite3
    snap,p,f,o=fixture();store=Store(tmp_path/'lifecycle-atomic.sqlite')
    DecisionService(store,p,stream='atomic').evaluate(snap,'initial',observation_override=(o,),frame_override=f)
    store.db.execute("""CREATE TRIGGER inject_lifecycle_failure BEFORE INSERT ON events
                        WHEN NEW.kind='LIFECYCLE' BEGIN SELECT RAISE(ABORT,'INJECTED_FAILURE'); END""")
    with pytest.raises(sqlite3.IntegrityError,match='INJECTED_FAILURE'):
        store.transition('atomic',o.opportunity_id,'INVALIDATED',NOW+MINUTE)
    assert store.status('atomic',o.opportunity_id)=='TRIGGERED'
    assert store.db.execute('SELECT cutoff FROM cursors WHERE stream=?',('atomic',)).fetchone()[0]==NOW


def test_cached_identity_is_immutable_and_replace_creates_a_fresh_value():
    snap,_,_,o=fixture()
    old=snap.hash;root=o.origin.key;oid=o.opportunity_id;observation=o.key
    assert snap.hash==old and o.origin.key==root
    assert replace(snap,quality=('new-fact',)).hash!=old
    assert replace(o,pathway='B').opportunity_id==oid
    assert replace(o,pathway='B').key!=observation
    assert replace(o,origin=replace(o.origin,at_ns=o.origin.at_ns+1)).opportunity_id!=oid


def test_latest_native_quote_resolves_packet_timestamp_ties_by_source_order():
    snap,_,_,_=fixture();first=snap.quotes[0]
    earlier=replace(first,bid=D(100),ask=D('100.1'),sequence=10,native_ordinal=2)
    later_native=replace(first,bid=D(101),ask=D('101.1'),sequence=10,native_ordinal=10)
    assert latest_quote((earlier,later_native))==later_native
    assert latest_quote((later_native,earlier))==later_native
