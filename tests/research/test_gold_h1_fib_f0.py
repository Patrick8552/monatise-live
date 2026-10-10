from __future__ import annotations

import ast
import copy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from monatise.application.gold_analysis import GoldLayerEvaluator, GoldPolicy
from monatise.application.hierarchy.coordinator import HierarchyConfiguration
from monatise.application.hierarchy.models import StrategicState
from monatise.application.take_profit import MultiTPConfiguration, build_plan
from monatise.application.target_evidence import candidate, crypto_layer_candidates
from monatise.engines.fibonacci_liquidity import FibonacciAnchorConstraint, FibonacciDirection, FibonacciLiquidityEngine, FibonacciRequest
from monatise.research.gold_fib.capture import CaptureGoldLayerEvaluator
from monatise.research.gold_fib.diagnostics import diagnostics
from monatise.research.gold_fib.episode import GoldH1StructuralLegSelector, H1StructuralEpisodeAdapter
from monatise.research.gold_fib.f0 import H1FibF0, ISOLATION, target_rejection
from monatise.research.gold_fib.models import FrozenRecord, GoldSetupSeed, H1ParentSnapshot, digest, encode
from monatise.research.gold_fib.replay import OfflineReplay, write_immutable
from tests.research.gold_fib_fixtures import NOW, archive


@pytest.fixture(scope='module',params=[False,True],ids=['long','short'])
def replayed(request):
    runner=OfflineReplay()
    record=runner.run(archive(short=request.param))
    assert len(runner.seeds)==1
    return runner,record


@pytest.fixture(scope='module')
def long_replay():
    runner=OfflineReplay(); record=runner.run(archive())
    return runner,record


def derive(seed, *, layer_change=None, prepared_change=None):
    contexts,prepared,layers=seed.objects()
    context,snapshot,layer=seed.parent.objects()
    if layer_change:
        layer=layer_change(layer)
    parent=H1ParentSnapshot.capture(context,snapshot,layer)
    layers=dict(layers); layers['1h']=layer
    return GoldSetupSeed.create(contexts=contexts,parent=parent,
        prepared=prepared_change(prepared) if prepared_change else prepared,
        layers=tuple(sorted(layers.items())),observed_at=seed.observed_at,
        session_close=seed.record.data['session_close'],calendar_hash=seed.record.data['calendar_hash'],
        broker_identity=seed.record.data['broker_identity'],broker_units=seed.record.data['broker_units'],
        timestamp_policy='reviewed_manifest')


def test_actual_engine_seed_then_leg_and_canonical_nearest_gate(replayed):
    runner,record=replayed
    r=record.data['records'][0]
    assert r['canonical']['setup_15m']['state']=='setup_confirmed'
    assert r['canonical']['trigger_5m']['state']=='trigger_confirmed'
    assert r['canonical']['reasons']==['risk_proposal_rejected:tp1_reward_risk_below_minimum']
    assert r['reason']=='NEAREST_OBJECTIVE_RR_REJECTED'
    assert r['valid_constrained_fib'] and r['candidate_admitted_count']==3 and r['eligible_target_count']==0
    assert r['final_target_count']==0 and r['targets']==[]
    assert r['anchor']['A']['index']==52 and r['anchor']['B']['index']==58
    assert r['anchor']['range_usd']==80
    assert r['anchor']['range_atr_multiple']>=2
    assert [s['ratio'] for s in r['raw_slots']]==[1.272,1.414,1.618]
    sign=1 if runner.seeds[0].objects()[1].direction=='long' else -1
    a=r['anchor']['A']['price']
    assert [float(s['raw_price']) for s in r['raw_slots']]==pytest.approx([a+sign*80*x for x in (1.272,1.414,1.618)])
    assert all(r[k] is False for k in ISOLATION)


def test_first_causal_origin_no_future_pivot_fallback(long_replay):
    seed=long_replay[0].seeds[0]
    # Delay A confirmation until E's open: v1 must take the older confirmed
    # origin, then reject its geometry; it must not retrospectively promote A.
    context,snapshot,layer=seed.parent.objects()
    rows=list(snapshot.candles)
    e=57
    rows[55]=replace(rows[55],received_at=rows[e].open_time)
    p=H1ParentSnapshot.capture(context,replace(snapshot,candles=tuple(rows),latest_finalized=rows[-1]),layer)
    selected=GoldH1StructuralLegSelector().select(p,H1StructuralEpisodeAdapter().assess(p))
    assert selected.record.data['reason']=='H1_LEG_GEOMETRY_REJECTED'
    assert selected.record.data['A']['index']==45
    assert selected.constraint is None


def test_no_late_download_invented_known_at(long_replay):
    seed=long_replay[0].seeds[0]
    context,snapshot,layer=seed.parent.objects()
    rows=tuple(replace(c,received_at=context.evaluated_at) for c in snapshot.candles)
    p=H1ParentSnapshot.capture(context,replace(snapshot,candles=rows,latest_finalized=rows[-1]),layer)
    result=GoldH1StructuralLegSelector().select(p,H1StructuralEpisodeAdapter().assess(p)).record.data
    assert result['reason'].startswith('H1_EPISODE_UNAVAILABLE:')
    assert not result['episode_identifiable'] and result['B'] is None


def test_parent_is_detached_and_tamper_evident(long_replay):
    parent=long_replay[0].seeds[0].parent
    context,snapshot,layer=parent.objects()
    layer.structure.metadata['tampered']=True
    assert 'tampered' not in parent.objects()[2].structure.metadata
    parent._layer.structure.metadata['tampered']=True
    try:
        with pytest.raises(ValueError,match='frozen capture changed'):
            parent.objects()
    finally:
        del parent._layer.structure.metadata['tampered']


def test_snapshot_rejects_future_or_wrong_timeframe(long_replay):
    seed=long_replay[0].seeds[0]; c,s,l=seed.parent.objects()
    with pytest.raises(ValueError,match='creation'):
        H1ParentSnapshot.capture(c,replace(s,observed_at=s.observed_at+timedelta(seconds=1)),l)
    with pytest.raises(ValueError,match='H1 parent'):
        H1ParentSnapshot.capture(c,replace(s,timeframe='15m'),l)
    rows=tuple(replace(x,received_at=c.evaluated_at+timedelta(seconds=1)) for x in s.candles)
    with pytest.raises(ValueError,match='future'):
        H1ParentSnapshot.capture(c,replace(s,candles=rows),l)


def test_parent_episode_identity_mismatch_fails_without_fallback(long_replay):
    seed=long_replay[0].seeds[0]
    episode=H1StructuralEpisodeAdapter().assess(seed.parent)
    data=episode.record.data; data['h1_snapshot_hash']='foreign'
    sel=GoldH1StructuralLegSelector().select(seed.parent,replace(episode,record=FrozenRecord.from_value(data)))
    assert sel.constraint is None and sel.record.data['reason']=='H1_EPISODE_PARENT_MISMATCH'


def test_optional_constraint_default_identical_and_exact_pair(replayed):
    seed=replayed[0].seeds[0]; layer=seed.parent.objects()[2]
    request=FibonacciRequest(layer.market,layer.structure,liquidity=layer.liquidity,zones=layer.zones,reclaim=layer.reclaim)
    engine=FibonacciLiquidityEngine()
    assert digest(engine.assess(request))==digest(engine.assess(replace(request,anchor_constraint=None)))
    selection=GoldH1StructuralLegSelector().select(seed.parent,H1StructuralEpisodeAdapter().assess(seed.parent))
    out=engine.assess(replace(request,anchor_constraint=selection.constraint))
    assert out.has_valid_anchor and out.primary_anchor.start_index==52 and out.primary_anchor.end_index==58
    assert out.alternate_anchors==()


@pytest.mark.parametrize('change',[{'timeframe':'15m'},{'symbol':'NQ'},{'start_index':45},{'end_price':9999},{'direction':FibonacciDirection.BEARISH}])
def test_constraint_cannot_fabricate_or_cross_timeframes(long_replay,change):
    seed=long_replay[0].seeds[0]; layer=seed.parent.objects()[2]
    constraint=GoldH1StructuralLegSelector().select(seed.parent,H1StructuralEpisodeAdapter().assess(seed.parent)).constraint
    out=FibonacciLiquidityEngine().assess(FibonacciRequest(layer.market,layer.structure,anchor_constraint=replace(constraint,**change)))
    # Index45 with unchanged 2450 is a fabricated pivot, not another valid leg.
    assert not out.has_valid_anchor and 'constrained_pair_not_authentic' in out.reasons


def test_seed_cannot_be_a_fake_passing_risk_proposal(long_replay):
    seed=long_replay[0].seeds[0]; contexts,prepared,layers=seed.objects()
    assert not hasattr(prepared,'calculated_reward_to_risk')
    kwargs=dict(contexts=contexts,parent=seed.parent,prepared=prepared,layers=layers,
        observed_at=seed.observed_at,session_close=seed.record.data['session_close'],
        calendar_hash='test',broker_identity={'account_id':'test'},broker_units=seed.record.data['broker_units'],timestamp_policy='reviewed_manifest')
    with pytest.raises(ValueError,match='invalid_parent_chain'):
        GoldSetupSeed.create(**{**kwargs,'contexts':contexts[:2]})
    with pytest.raises(ValueError,match='H1_direction_mismatch'):
        GoldSetupSeed.create(**{**kwargs,'contexts':(*contexts[:2],replace(contexts[2],state=StrategicState.NEUTRAL),*contexts[3:])})
    with pytest.raises(ValueError,match='invalid_stop_geometry'):
        GoldSetupSeed.create(**{**kwargs,'prepared':replace(prepared,final_stop=prepared.reference_entry+1)})


def test_confidence_range_and_age_are_not_loosened(long_replay):
    seed=long_replay[0].seeds[0]
    low=derive(seed,layer_change=lambda l:replace(l,structure=replace(l.structure,confidence=.44)))
    r=H1FibF0().assess(low,canonical={}).data
    assert r['reason']=='STRUCTURE_CONFIDENCE_REJECTED' and not r['valid_constrained_fib']
    # Range gate is also checked by the authentic engine, not a target adapter.
    layer=seed.parent.objects()[2]
    selection=GoldH1StructuralLegSelector().select(seed.parent,H1StructuralEpisodeAdapter().assess(seed.parent))
    request=FibonacciRequest(layer.market,layer.structure,anchor_constraint=selection.constraint,minimum_anchor_range_atr=100)
    assert not FibonacciLiquidityEngine().assess(request).has_valid_anchor
    assert not FibonacciLiquidityEngine().assess(replace(request,minimum_anchor_range_atr=2,maximum_anchor_age_candles=2)).has_valid_anchor


@pytest.mark.parametrize('expiry',[('H1_PARENT_EXPIRED',2),('M15_M5_EXPIRED',4)])
def test_original_expiries_cannot_be_extended(long_replay,expiry):
    seed=long_replay[0].seeds[0]; contexts=seed.objects()[0]
    reason,index=expiry
    r=H1FibF0().assess(seed,canonical={},at=contexts[index].expires_at).data
    assert r['reason']==reason and r['final_target_count']==0
    assert all(s['rejection_reason']==reason for s in r['raw_slots'])


def test_capture_instrumentation_does_not_change_default_canonical(replayed):
    runner,record=replayed
    state=runner.evaluator._state['XAU/USD']
    standard=GoldLayerEvaluator(configuration=HierarchyConfiguration(strategy_version=GoldPolicy().strategy),asset_route='gold')
    standard.broker_units=runner.evaluator.broker_units
    original=standard.evaluate('XAU/USD',state.snapshots,evaluated_at=NOW,macro_degraded=False)
    assert encode(original)==record.data['admissions'][-1]['canonical']


@pytest.mark.parametrize('price,at,confidence,relevance,expected',[
    ('100',0,'.6','.7','wrong_side'),('101',6,'.6','.7','stale_or_future'),
    ('101',-18001,'.6','.7','stale_or_future'),('101',0,'.34','.7','insufficient_evidence'),
    ('101',0,'.6','.39','insufficient_evidence'),('126',0,'.6','.7','outside_mapping_safety'),
    ('125',5,'.35','.4',None)])
def test_filter_boundaries_match_existing_builder(price,at,confidence,relevance,expected):
    c=candidate(price,provider='fixture',kind='FIB_TP1',timeframe='1h',observed=NOW+timedelta(seconds=at),confidence=confidence,relevance=relevance)
    config=MultiTPConfiguration()
    assert target_rejection(c,entry=Decimal(100),sign=Decimal(1),now=NOW,config=config)==expected
    if expected:
        with pytest.raises(ValueError,match='insufficient target evidence'):
            build_plan(candidates=[c],direction='long',entry=100,stop=99,now=NOW,expires_at=NOW+timedelta(minutes=1),config=config)
    else:
        assert len(build_plan(candidates=[c],direction='long',entry=100,stop=99,now=NOW,expires_at=NOW+timedelta(minutes=1),config=config).targets)==1


@pytest.mark.parametrize('retain',[0,1,2,3])
def test_truthful_target_cardinality_and_renumbering(long_replay,monkeypatch,retain):
    # Component exercise: remove obstacle feed, and selectively fail confluence.
    # This is not a canonical qualified trade or a historical pilot event.
    import monatise.research.gold_fib.f0 as module
    engine=module.FibonacciLiquidityEngine.assess
    def assess(self,request):
        f=engine(self,request)
        levels=tuple(replace(l,liquidity_confluence=l.ratio in (1.272,1.414,1.618)[3-retain:] if retain else False,
            zone_confluence=False,structure_confluence=False) for l in f.extension_levels)
        return replace(f,extension_levels=levels)
    monkeypatch.setattr(module.FibonacciLiquidityEngine,'assess',assess)
    monkeypatch.setattr(module,'crypto_layer_candidates',lambda *a,**kw:[])
    r=module.H1FibF0().assess(long_replay[0].seeds[0],canonical={}).data
    assert r['final_target_count']==retain
    assert len(r['targets'])==retain
    if retain:
        assert r['status']=='SHADOW_VALID'
        assert r['targets'][0]['final_name']=='tp1'
        assert r['targets'][0]['raw_sources']==[f'FIB_TP{4-retain}']
        assert sum(Decimal(t['allocation_pct']) for t in r['targets'])==100
    else:
        assert r['reason']=='NO_ELIGIBLE_FIB_TARGETS'
    assert len(r['raw_slots'])==3


def test_no_options_evidence_or_environment_can_enable_actions(long_replay,monkeypatch):
    for key in ('MONATISE_AUTO_EXECUTE','MONATISE_HIERARCHICAL_TELEGRAM_PUBLISH_ENABLED','MULTI_TP_AUTO_PARTIAL_CLOSE','MULTI_TP_AUTO_TRAILING'):
        monkeypatch.setenv(key,'true')
    r=H1FibF0().assess(long_replay[0].seeds[0],canonical={'approval_eligible':True,'execution_enabled':True}).data
    assert all(r[k] is False for k in ISOLATION)
    assert r['gil']['status']=='DISABLED_F0'
    assert all(s['gc_contract'] is None and s['gil_evidence'] is None for s in r['raw_slots'])
    for path in Path('monatise/research/gold_fib').glob('*.py'):
        tree=ast.parse(path.read_text())
        imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        assert not any(x.startswith(('monatise.integrations','monatise.application.deployment','monatise.application.approval','monatise.application.execution')) for x in imports)
    # Production does not import or register any research entry point.
    for path in Path('monatise').rglob('*.py'):
        if 'research' not in path.parts:
            assert 'monatise.research.gold_fib' not in path.read_text()


def test_replay_determinism_duplicate_prevention_and_immutable_audit(long_replay,tmp_path):
    runner,first=long_replay
    second=OfflineReplay().run(archive())
    assert first.payload==second.payload and first.sha256==second.sha256
    path=tmp_path/'record.json'
    write_immutable(path,first.payload)
    write_immutable(path,first.payload)
    with pytest.raises(ValueError,match='immutable artifact conflict'):
        write_immutable(path,'different')
    detached=first.data; detached['records'][0]['entry']='altered'
    assert first.data['records'][0]['entry']!='altered'
    malformed=archive(); malformed['observations'][1]['at']=malformed['observations'][0]['at']
    with pytest.raises(ValueError,match='strictly increase'):
        OfflineReplay().run(malformed)


def test_clustered_counts_do_not_claim_independence(long_replay):
    rows=long_replay[1].data['records']; r=copy.deepcopy(rows[0]);r['setup_identifier']='second-m15'; rows.append(r)
    report=diagnostics(rows)
    assert report['seed_level']['total_GoldSetupSeed_events']==2
    assert report['episode_cluster_count']==1
    assert len(report['clusters'])==1
    assert next(iter(report['episode_weighted'].values()))['seed_events']==2
    with pytest.raises(ValueError,match='duplicate seed'):
        diagnostics([r,r])


def test_seed_snapshot_does_not_move_with_later_entry(long_replay):
    seed=long_replay[0].seeds[0]; runner=H1FibF0()
    first=runner.assess(seed,canonical={}).data
    second=runner.assess(seed,canonical={},at=seed.observed_at+timedelta(seconds=1)).data
    assert first['anchor_hash']==second['anchor_hash']
    assert first['raw_slots']==second['raw_slots']
    assert first['observed_price']==second['observed_price']


@pytest.mark.parametrize('kwargs,reason',[
    ({'forming_b':True},'B_UNCONFIRMED_AT_PARENT_CUTOFF'),
    ({'origin_latency':True},'H1_LEG_GEOMETRY_REJECTED'),
    ({'late_history':True},'H1_EPISODE_UNAVAILABLE:latest_event_unresolvable'),
])
def test_real_engine_replay_rejections_are_truthful(kwargs,reason):
    result=OfflineReplay().run(archive(**kwargs)).data
    assert len(result['records'])==1
    r=result['records'][0]
    assert r['reason']==reason
    assert r['final_target_count']==0 and all(s['raw_price'] is None for s in r['raw_slots'])


def test_real_two_m15_setups_share_one_h1_episode_and_freeze():
    from tests.research.gold_fib_fixtures import repeated_setup_archive
    result=OfflineReplay().run(repeated_setup_archive()).data
    rows=result['records']
    assert len(rows)==2
    assert rows[0]['h1_episode_id']==rows[1]['h1_episode_id']
    assert rows[0]['m15_setup_id']!=rows[1]['m15_setup_id']
    assert rows[0]['m5_trigger_id']!=rows[1]['m5_trigger_id']
    assert rows[0]['anchor']['A']==rows[1]['anchor']['A']
    assert rows[0]['anchor']['B']==rows[1]['anchor']['B']
    assert diagnostics(rows)['episode_cluster_count']==1


def test_no_network_even_with_live_flags(monkeypatch):
    import socket
    def denied(*args,**kwargs):
        raise AssertionError('offline research attempted network access')
    monkeypatch.setattr(socket.socket,'connect',denied)
    monkeypatch.setattr(socket,'create_connection',denied)
    monkeypatch.setenv('MONATISE_LIVE_EXECUTION_ENABLED','true')
    monkeypatch.setenv('MONATISE_GOLD_TELEGRAM_ENABLED','true')
    result=OfflineReplay().run(archive()).data
    assert len(result['records'])==1
    assert all(result['records'][0][key] is False for key in ISOLATION)


def test_seed_refuses_forged_narrower_stop(long_replay):
    with pytest.raises(ValueError,match='entry_stop_not_canonical'):
        derive(long_replay[0].seeds[0],prepared_change=lambda p:replace(p,final_stop=p.reference_entry-.01))


def test_research_anchors_cannot_be_recomputed_after_freeze(long_replay):
    seed=long_replay[0].seeds[0]
    engine=H1FibF0();engine.assess(seed,canonical={})
    changed=derive(seed,layer_change=lambda l:replace(l,structure=replace(l.structure,confidence=.46)))
    with pytest.raises(ValueError,match='CHANGED_AFTER_FREEZE'):
        engine.assess(changed,canonical={})


def test_successor_leg_does_not_fall_back_to_prior_confirmed_b():
    a=archive()
    for observation in a['observations']:
        for row in observation['candles'].get('1h',[]):
            if row['timestamp']=='2026-10-05T14:00:00+00:00':
                row.update(open=2520,high=2540,low=2519,close=2538)
    result=OfflineReplay().run(a).data
    assert len(result['records'])==1
    r=result['records'][0]
    active=r['anchor']['episode_provenance']['active']
    assert active['event_index']==64 and active['broken_pivot'][0]==58
    assert r['reason']=='B_UNCONFIRMED_AT_PARENT_CUTOFF'
    assert r['anchor']['B'] is None and all(s['raw_price'] is None for s in r['raw_slots'])


def test_spacing_merge_retains_raw_identity_and_only_nearer_price():
    cs=[candidate(p,provider='fixture',kind=k,timeframe='1h',observed=NOW)
        for p,k in ((103,'FIB_TP1'),(103.05,'FIB_TP2'),(104,'FIB_TP3'))]
    plan=build_plan(candidates=cs,direction='long',entry=100,stop=99,
        now=NOW,expires_at=NOW+timedelta(minutes=1),config=MultiTPConfiguration(),tick_size='.01')
    assert len(plan.targets)==2 and plan.targets[0].price==Decimal('103')
    assert 'FIB_TP2:merged_nearby' in plan.rejection_log
    assert 'FIB_TP2@103.05' in plan.targets[0].source


@pytest.mark.parametrize('short',[False,True])
@pytest.mark.parametrize('case,reason,count',[('two-atr','TWO_ATR_REJECTED',0),('distance-one','NEAREST_OBJECTIVE_RR_REJECTED',1),('distance-two','NEAREST_OBJECTIVE_RR_REJECTED',2)])
def test_real_engine_fixed_range_and_distance_ceiling_cases(short,case,reason,count):
    from tests.research.gold_fib_fixtures import range_gate_archive
    result=OfflineReplay().run(range_gate_archive(short=short,case=case)).data
    assert len(result['records'])==1
    r=result['records'][0]
    assert r['reason']==reason and r['candidate_admitted_count']==count and r['eligible_target_count']==0
    assert r['final_target_count']==0
    if case!='two-atr':
        assert sum(s['rejection_reason']=='outside_mapping_safety' for s in r['raw_slots'])==3-count


def test_default_160_candle_age_rule_on_authentic_old_pair():
    runner=OfflineReplay(); result=runner.run(archive(aged=True)).data
    assert len(result['records'])==1
    r=result['records'][0]
    assert r['reason']=='ANCHOR_AGE_REJECTED'
    assert r['anchor']['valid_a'] and r['anchor']['valid_b']
    assert len(runner.seeds[0].parent.objects()[2].market.candles)==200
    assert r['anchor']['A']['index']<40 and r['anchor']['B']['index']<40


def test_observed_price_outside_zone_is_never_replaced_by_planned_entry():
    data=archive()
    for observation in data['observations']:
        for row in observation['candles'].get('1m',[]):
            if row['timestamp']=='2026-10-05T15:03:00+00:00':
                row.update(open=2505,high=2506.2,low=2504.8,close=2506)
    runner=OfflineReplay();result=runner.run(data).data
    assert len(result['records'])==1
    seed=runner.seeds[0]; r=result['records'][0]
    prepared=seed.objects()[1]
    assert r['observed_price']==2506
    assert float(r['entry'])==prepared.entry_zone_high
    assert r['observed_price']>float(r['entry'])
    assert all(r[key] is False for key in ISOLATION)


def test_distribution_uses_standard_even_sample_median_and_unknown_empty():
    from monatise.research.gold_fib.diagnostics import distribution
    assert distribution([1,2,3,4])=={'n':4,'min':1.0,'median':2.5,'p90':4.0,'max':4.0}
    assert distribution([None])=={'n':0,'min':None,'median':None,'p90':None,'max':None}
