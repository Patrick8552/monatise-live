from dataclasses import replace
from decimal import Decimal as D
from monatise.research.unified.models import *
from monatise.research.unified.service import DecisionService
from monatise.research.unified.store import Store
from monatise.research.unified.outcomes import ShadowOutcomes,performance
from .helpers import fixture,NOW,expected_ratio


def selected(tmp_path,*,outcome_mode='MINUTE_BAR'):
    snap,policy,frames,o=fixture();store=Store(tmp_path/'outcomes.sqlite')
    policy=replace(policy,outcome_mode=outcome_mode)
    decision=DecisionService(store,policy,stream='experiment').evaluate(snap,'selected',observation_override=(o,),frame_override=frames)
    assert decision['trade_action']=='BUY'
    return snap,policy,store,decision


def future_bar(snap,*,high='111',low='100'):
    return Bar(snap.instrument.key,'1m',NOW+MINUTE,NOW+2*MINUTE,NOW+2*MINUTE+1,
               D('101.1'),D(high),D(low),D('101.2'),10,'genuine-shape-engineering-fixture')


def test_next_bar_fill_is_after_selection_and_costs_are_counted_once(tmp_path):
    snap,p,store,d=selected(tmp_path);b=future_bar(snap)
    later=replace(snap,cutoff_ns=b.available_ns,bars=snap.bars+(b,),replay_mode='HISTORICAL_EVENT_TIME')
    evaluator=ShadowOutcomes(store,'experiment',p);evaluator.advance(later);evaluator.advance(later)
    events=store.db.execute('SELECT kind,at_ns,payload FROM position_events ORDER BY at_ns').fetchall()
    assert [e['kind'] for e in events]==['FILL','OUTCOME']
    assert events[0]['at_ns']>d['cutoff_ns']
    m=performance(store,'experiment')
    assert m['fills']==m['resolved_outcomes']==1 and D(m['resolved_net_r'])==expected_ratio(840,370)


def test_both_stop_and_target_in_one_bar_is_not_a_winning_assumption(tmp_path):
    snap,p,store,d=selected(tmp_path);b=future_bar(snap,low='97')
    later=replace(snap,cutoff_ns=b.available_ns,bars=snap.bars+(b,),replay_mode='HISTORICAL_EVENT_TIME')
    ShadowOutcomes(store,'experiment',p).advance(later)
    m=performance(store,'experiment')
    assert m['unresolved_outcomes']==1 and m['resolved_outcomes']==0
    assert m['win_rate_resolved_only'] is m['net_expectancy_r_resolved_only'] is None


def test_as_recorded_never_substitutes_a_retrospective_bar_fill(tmp_path):
    snap,p,store,d=selected(tmp_path);b=future_bar(snap)
    later=replace(snap,cutoff_ns=b.available_ns,bars=snap.bars+(b,),replay_mode='AS_RECORDED')
    ShadowOutcomes(store,'experiment',p).advance(later)
    assert performance(store,'experiment')['fills']==0


def native_snapshot(snap,quotes,invalidations=(),*,coverage=True):
    end=NOW+10*NS
    return replace(snap,cutoff_ns=end,quotes=quotes,quote_invalidations=invalidations,
        coverage=(Coverage('mbp-1',NOW,end+1,end,'reviewed-native-source'),) if coverage else (),
        replay_mode='HISTORICAL_EVENT_TIME')


def test_native_quotes_resolve_sequence_without_ohlc_guess_and_retry_is_idempotent(tmp_path):
    snap,p,store,d=selected(tmp_path,outcome_mode='NATIVE_L1')
    q=replace(snap.quotes[0],receive_ns=NOW+NS,available_ns=NOW+NS)
    target=replace(q,receive_ns=NOW+2*NS,available_ns=NOW+2*NS,bid=D('110.1'),ask=D('110.2'))
    # Later stop cannot overwrite an already completed first-target outcome.
    stop=replace(q,receive_ns=NOW+3*NS,available_ns=NOW+3*NS,bid=D(97),ask=D('97.1'))
    future=native_snapshot(snap,(stop,target,q))
    e=ShadowOutcomes(store,'experiment',p);e.advance(future);e.advance(future)
    events=store.db.execute('SELECT kind,payload FROM position_events ORDER BY at_ns').fetchall()
    assert [v['kind'] for v in events]==['FILL','OUTCOME']
    import json
    assert json.loads(events[-1]['payload'])['exit_reason']=='FIRST_TARGET_TRADE_THROUGH'


def test_native_l1_requires_coverage_and_does_not_fall_back_to_candle_fills(tmp_path):
    snap,p,store,d=selected(tmp_path,outcome_mode='NATIVE_L1')
    q=replace(snap.quotes[0],receive_ns=NOW+NS,available_ns=NOW+NS)
    ShadowOutcomes(store,'experiment',p).advance(native_snapshot(snap,(q,),coverage=False))
    assert performance(store,'experiment')['fills']==0


def test_native_book_loss_after_fill_makes_outcome_unresolved(tmp_path):
    snap,p,store,d=selected(tmp_path,outcome_mode='NATIVE_L1')
    q=replace(snap.quotes[0],receive_ns=NOW+NS,available_ns=NOW+NS)
    missing=QuoteUnavailable(q.contract,NOW+2*NS,NOW+2*NS,'native-book-removed')
    ShadowOutcomes(store,'experiment',p).advance(native_snapshot(snap,(q,),(missing,)))
    m=performance(store,'experiment')
    assert m['fills']==m['unresolved_outcomes']==1 and m['resolved_outcomes']==0


def test_outcome_costs_and_management_must_match_frozen_selected_policy(tmp_path):
    import pytest
    from monatise.research.unified.store import Conflict
    snap,p,store,d=selected(tmp_path)
    assert d['selected_plan']['frozen_policy_hash']==p.hash
    altered=replace(p,fee_ticks_per_side=D(0))
    with pytest.raises(Conflict,match='OUTCOME_POLICY_DIFFERS'):
        ShadowOutcomes(store,'experiment',altered).advance(snap)
    assert performance(store,'experiment')['fills']==0


def test_another_contract_snapshot_cannot_fill_existing_selected_trade(tmp_path):
    snap,p,store,d=selected(tmp_path)
    other=replace(snap.instrument,instrument_id=snap.instrument.instrument_id+1)
    wrong=replace(snap,instrument=other,bars=tuple(replace(b,contract=other.key) for b in snap.bars),
        quotes=tuple(replace(q,contract=other.key) for q in snap.quotes))
    ShadowOutcomes(store,'experiment',p).advance(wrong)
    assert performance(store,'experiment')['fills']==0
