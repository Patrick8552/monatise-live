from dataclasses import replace
from decimal import Decimal as D
import json
import sqlite3
import pytest
from monatise.research.unified.models import *
from monatise.research.unified.policy import Policy
from monatise.research.unified.eligibility import validate, final_revalidate
from monatise.research.unified.pathways import model_a, model_b, model_c
from monatise.research.unified.service import DecisionService
from monatise.research.unified.store import Store, Conflict
from .helpers import fixture, later, NOW, expected_ratio


def service(tmp_path, policy, name='unified', **kwargs):
    store = Store(tmp_path/'state.sqlite')
    return DecisionService(store, policy, stream=name, **kwargs)


@pytest.mark.parametrize('side', [Side.BUY, Side.SELL])
def test_real_economic_buy_and_sell_paths_are_symmetric(tmp_path, side):
    snap, policy, frames, obs = fixture(side)
    s = service(tmp_path, policy)
    result = s.evaluate(snap, 'cycle-1', observation_override=(obs,), frame_override=frames)
    assert result['trade_action'] == side
    assert result['is_new_selection'] and result['market_trigger_event_id'] != result['selection_event_id']
    assert D(result['selected_plan']['initial_risk']) == D(370)
    assert D(result['net_rr'][0]) == expected_ratio(840,370)
    assert result['mode'] == 'SHADOW' and not result['execution_eligible']
    assert len(s.store.pending_outbox()) == 1


def test_model_a_can_qualify_without_b_and_neutral_is_not_missing(tmp_path):
    snap, policy, frames, a = fixture(neutral_m15=True)
    b = replace(a, pathway='B')
    assert not model_a(a, frames, policy, snap.instrument.tick)[0]
    assert 'B_M15_NOT_ALIGNED' in model_b(b, frames, policy, snap.instrument.tick)[0]
    r = service(tmp_path, policy).evaluate(snap, 'a', observation_override=(a, b), frame_override=frames)
    assert r['trade_action'] == 'BUY' and r['supporting_classifications'] == ['A']
    bad = dict(frames); bad['15m'] = replace(frames['15m'], state=State.UNAVAILABLE)
    assert 'M15_UNAVAILABLE' in model_a(a, bad, policy, snap.instrument.tick)[0]


def test_same_episode_labels_and_retries_do_not_create_extra_trade(tmp_path):
    snap, policy, frames, a = fixture()
    b = replace(a, pathway='B')
    s = service(tmp_path, policy)
    one = s.evaluate(snap, 'first', observation_override=(a, b), frame_override=frames)
    two = s.evaluate(snap, 'first', observation_override=(a, b), frame_override=frames)
    assert one == two and one['supporting_classifications'] == ['A', 'B']
    three = s.evaluate(later(snap, NOW+MINUTE), 'second', observation_override=(a, b), frame_override=frames)
    assert three['selection_event_id'] == one['selection_event_id']
    assert not three['is_new_selection'] and three['trade_action'] == 'BUY'
    assert len(s.store.pending_outbox()) == 1
    frozen = json.loads(s.store.selected('unified', a.opportunity_id)['plan'])
    assert frozen == one['selected_plan']


def test_ab_upgrade_after_trigger_preserves_first_plan(tmp_path):
    snap, policy, frames, a = fixture(neutral_m15=True)
    s = service(tmp_path, policy)
    first = s.evaluate(snap, 'early', observation_override=(a,), frame_override=frames)
    assert first['supporting_classifications'] == ['A']
    confirmed_frames = dict(frames); confirmed_frames['15m'] = replace(frames['15m'], state=State.UP)
    b = replace(a, pathway='B', stop_level=D(99))  # Later revision must not rewrite original risk.
    second = s.evaluate(later(snap, NOW+MINUTE), 'confirm', observation_override=(a, b), frame_override=confirmed_frames)
    assert second['supporting_classifications'] == ['A', 'B']
    assert second['selected_plan'] == first['selected_plan']
    assert second['selected_pathway'] == 'A' and not second['is_new_selection']
    with pytest.raises(sqlite3.IntegrityError, match='immutable_selected_plan'):
        s.store.db.execute("UPDATE selections SET plan='{}'")


@pytest.mark.parametrize('stage', ['WATCHING', 'ARMED'])
def test_conditional_records_persist_without_action(tmp_path, stage):
    snap, policy, frames, o = fixture(stage=stage)
    s = service(tmp_path, policy)
    r = s.evaluate(snap, 'conditional', observation_override=(o,), frame_override=frames)
    assert r['trade_action'] == 'NO_TRADE'
    assert r['entry'] is r['stop_loss'] is r['targets'] is r['net_rr'] is None
    assert s.store.status('unified', o.opportunity_id) == stage
    assert not s.store.pending_outbox()


def test_provisional_sweep_needs_no_completed_economic_plan(tmp_path):
    snap, policy, frames, o = fixture(stage='WATCHING', pathway='C')
    o = replace(o, canonical=False)
    s = service(tmp_path, policy)
    r = s.evaluate(snap, 'provisional', observation_override=(o,), frame_override=frames)
    assert r['trade_action'] == 'NO_TRADE'
    assert s.store.db.execute('SELECT COUNT(*) FROM observations WHERE opportunity IS NULL').fetchone()[0] == 1
    assert s.store.db.execute('SELECT COUNT(*) FROM market_opportunities').fetchone()[0] == 0


def test_default_unresolved_policy_never_manufactures_a_plan(tmp_path):
    snap, _, frames, o = fixture()
    r = service(tmp_path, Policy()).evaluate(snap, 'default', observation_override=(o,), frame_override=frames)
    assert r['reason'] == 'POLICY_NOT_READY' and r['entry'] is None
    assert r['parameter_prerequisites']


def test_context_opposition_and_reversal_evidence_are_vetoes():
    snap, policy, frames, o = fixture(pathway='C')
    codes, _ = model_c(o, frames, policy, snap.instrument.tick)
    assert 'C_SWEEP_REVERSAL_EVIDENCE_MISSING' in codes
    bad = dict(frames); bad['4h'] = replace(frames['4h'], state=State.DOWN)
    assert 'H4_OPPOSED_OR_UNPERMITTED' in model_c(o, bad, policy, snap.instrument.tick)[0]


@pytest.mark.parametrize('change,expected', [
    ('stale', 'ENTRY_QUOTE_STALE'), ('missing', 'ENTRY_QUOTE_UNAVAILABLE'),
    ('news', 'SCHEDULED_NEWS_WINDOW'), ('quality', 'SOURCE_QUALITY_UNRESOLVED'),
    ('stop', 'STRUCTURAL_STOP_INVALIDATED'), ('target', 'NO_OBSERVED_TARGET_AHEAD')])
def test_hard_gates(change, expected):
    snap, policy, frames, o = fixture()
    if change == 'stale': snap = replace(snap, quotes=(replace(snap.quotes[0], receive_ns=NOW-6*10**9),))
    if change == 'missing': snap = replace(snap, quotes=())
    if change == 'news': snap = replace(snap, news=(News(NOW-MINUTE, NOW+MINUTE, NOW-MINUTE, 'FIXTURE_NEWS', 'fixture'),))
    if change == 'quality': snap = replace(snap, quality=('UNREVIEWED_RECORD',))
    if change == 'stop': o = replace(o, stop_level=D(105))
    if change == 'target': frames = {k:replace(v,pivots=()) for k,v in frames.items()}
    assert expected in validate(o, snap, policy, frames).reasons


def test_unknown_aggressors_cannot_be_silently_assigned_direction():
    snap, policy, frames, o = fixture()
    policy = replace(policy, volume_mode='AGGRESSOR_ROBUST')
    b = frames['5m'].bars[-1]
    def t(side, qty): return Trade(snap.instrument.key, b.open_ns+1, b.open_ns+1, b.close_ns, D(101), qty, side, str(side))
    snap = replace(snap, trades=(t('BUY',10),t('SELL',5),t(None,7)),
                   coverage=(Coverage('trades',b.open_ns,b.close_ns,b.close_ns,'proof'),))
    assert 'DIRECTIONAL_FLOW_NOT_ROBUST_TO_UNKNOWN' in validate(o,snap,policy,frames).reasons


def test_final_revalidation_does_not_promote_a_runner_up(tmp_path):
    snap, policy, frames, o = fixture()
    s = service(tmp_path, policy, final_snapshot=lambda x: later(x,NOW+MINUTE,bid=95,ask='95.1'))
    r = s.evaluate(snap, 'fail-final', observation_override=(o,), frame_override=frames)
    assert r['reason'] == 'FINAL_REVALIDATION_FAILED'
    assert r['trade_action'] == 'NO_TRADE' and not s.store.pending_outbox()


def test_cycle_conflict_stale_cycle_and_terminal_non_resurrection(tmp_path):
    snap, policy, frames, o = fixture()
    s = service(tmp_path, policy)
    s.evaluate(snap,'one',observation_override=(o,),frame_override=frames)
    with pytest.raises(Conflict,match='CYCLE_INPUT_CONFLICT'):
        s.evaluate(replace(snap,quality=('changed',)),'one',observation_override=(o,),frame_override=frames)
    with pytest.raises(Conflict,match='STALE_OR_DUPLICATE'):
        s.evaluate(snap,'same-cutoff-new-cycle',observation_override=(o,),frame_override=frames)
    s.store.transition('unified',o.opportunity_id,'INVALIDATED',NOW+1)
    r=s.evaluate(later(snap,NOW+MINUTE),'new',observation_override=(o,),frame_override=frames)
    assert r['trade_action']=='NO_TRADE' and s.store.status('unified',o.opportunity_id)=='INVALIDATED'
    with pytest.raises(Conflict,match='TERMINAL'):
        s.store.transition('unified',o.opportunity_id,'ARMED',NOW+MINUTE)


def test_atomic_failure_rolls_back_selection_decision_and_outbox(tmp_path):
    snap, policy, frames, o = fixture()
    s = service(tmp_path,policy)
    def crash(): raise RuntimeError('SIMULATED_CRASH')
    with pytest.raises(RuntimeError):
        s.evaluate(snap,'crash',observation_override=(o,),frame_override=frames,failpoint=crash)
    for table in ('decisions','selections','outbox','opportunities'):
        assert s.store.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0
    r=s.evaluate(snap,'crash',observation_override=(o,),frame_override=frames)
    assert r['is_new_selection']


def test_experiment_state_isolation_and_frozen_configuration(tmp_path):
    snap,policy,frames,o=fixture()
    one=service(tmp_path,policy,'A-only',pathways=('A',))
    two=service(tmp_path,policy,'B-only',pathways=('B',))
    a=one.evaluate(snap,'same-cycle',observation_override=(o,),frame_override=frames)
    b=two.evaluate(snap,'same-cycle',observation_override=(replace(o,pathway='B'),),frame_override=frames)
    assert a['selected_opportunity_id']==b['selected_opportunity_id']
    assert a['selection_event_id']!=b['selection_event_id']
    assert len(one.store.pending_outbox())==2
    changed=DecisionService(one.store,replace(policy,min_net_rr=D(2)),stream='A-only',pathways=('A',))
    with pytest.raises(Conflict,match='FROZEN_EXPERIMENT'):
        changed.evaluate(later(snap,NOW+MINUTE),'change',observation_override=(o,),frame_override=frames)


def test_no_position_event_can_precede_selection_and_fill_is_immutable(tmp_path):
    snap,policy,frames,o=fixture();s=service(tmp_path,policy)
    r=s.evaluate(snap,'first',observation_override=(o,),frame_override=frames)
    sid=r['selection_event_id']
    with pytest.raises(Conflict,match='PRECEDES'):
        s.store.position_event('unified',sid,'FILL',NOW-1,{'price':'100'})
    s.store.position_event('unified',sid,'FILL',NOW+1,{'price':'101.2'})
    with pytest.raises(Conflict,match='IMMUTABLE'):
        s.store.position_event('unified',sid,'FILL',NOW+1,{'price':'100'})
    item=s.store.pending_outbox()[0];s.store.acknowledge(item['event']);s.store.acknowledge(item['event'])
    assert not s.store.pending_outbox()
