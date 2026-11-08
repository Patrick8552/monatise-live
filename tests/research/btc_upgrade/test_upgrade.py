"""Engineering fixtures only. Genuine archive checks run separately."""
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
import hashlib,json
import pytest
from monatise.research.unified.models import *
from monatise.research.unified.evidence import Frame
from monatise.research.unified.policy import exploratory_policy
from monatise.research.unified.store import Store
from monatise.research.btc_upgrade import require_btc
from monatise.research.btc_upgrade.policy import BTCPolicy,RegimePolicy,RiskPolicy
from monatise.research.btc_upgrade.regime import classify,confirm,range_box
from monatise.research.btc_upgrade.risk import combine_actions,gates,ledger_state
from monatise.research.btc_upgrade.news import NewsReview,CalendarSource,REQUIRED,DOMAINS
from monatise.research.btc_upgrade.setups import deadline,trend_observations,range_observations,range_plan,inspect
from monatise.research.btc_upgrade.analysis import reference_analysis
from monatise.research.btc_upgrade.service import BTCService
NOW=1793890800000000000//WIDTHS['5m']*WIDTHS['5m']

def fixture(side=Side.BUY):
    inst=Instrument('GLBX.MDP3','XCME',1,42316233,'BTCX6','BTC',1795795200000000000,D(5),D(5),'a'*64)
    mirror=lambda x:D(x) if side==Side.BUY else D(101000)-D(x)
    def bar(tf,opened,values,volume=100):
        vals=[mirror(x) for x in values]
        return Bar(inst.key,tf,opened,opened+WIDTHS[tf],opened+WIDTHS[tf],vals[0],max(vals),min(vals),vals[-1],volume,identity('fixture',tf,opened))
    m5=tuple(bar('5m',NOW-(14-i)*WIDTHS['5m'],[50000,50050,49980,50020],50) for i in range(13))+(bar('5m',NOW-WIDTHS['5m'],[50025,50150,50005,50100]),)
    m1=bar('1m',NOW-MINUTE,[50100,50120,50095,50105])
    side_state=State.UP if side==Side.BUY else State.DOWN
    frames={tf:Frame(tf,(bar(tf,NOW-WIDTHS[tf],[50000,50200,49900,50100]),),(),side_state) for tf in WIDTHS}
    frames['5m']=Frame('5m',m5,(),side_state);frames['1m']=Frame('1m',(m1,),(),side_state)
    target=Pivot(inst.key,'15m','HIGH' if side==Side.BUY else 'LOW',mirror(51000),NOW-8*WIDTHS['15m'],NOW-6*WIDTHS['15m'],NOW-6*WIDTHS['15m'],('fixture-source',))
    frames['15m']=replace(frames['15m'],pivots=(target,))
    q=Quote(inst.key,NOW,NOW,D(50100) if side==Side.BUY else D(50895),D(50105) if side==Side.BUY else D(50900),'ENGINEERING_QUOTE')
    schedule=Schedule(((NOW-40*WIDTHS['4h'],NOW+WIDTHS['4h']),),'ENGINEERING_ONLY','b'*64)
    snap=Snapshot(inst,NOW,(m1,),(),(q,),(),schedule,'ENGINEERING_FIXTURE','c'*64,news_coverage=False,evidence_kind='ENGINEERING_SYNTHETIC')
    native=replace(exploratory_policy(rationale_hash='e'*64,volume_mode='EXECUTED_BAR_PARTICIPATION'),outcome_mode='NATIVE_L1')
    policy=BTCPolicy(native,regime=RegimePolicy(confirmation_closes=1),range_enabled=True)
    origin=Event('BREAK',inst.key,side,NOW-3*WIDTHS['5m'],NOW-3*WIDTHS['5m'],'p',mirror(50000),'origin')
    trigger=Event('RETEST',inst.key,side,NOW,NOW,'p',mirror(50000),m5[-1].key,(origin.key,))
    obs=Observation('A',side,origin,'TRIGGERED',origin.available_ns,NOW-2*WIDTHS['5m'],trigger,mirror(49900),mirror(50000),(origin,trigger))
    return snap,policy,frames,obs

def review(tmp_path,cutoff=NOW,complete=True):
    rows=[]
    for name in REQUIRED:
        p=tmp_path/(name+'.html');p.write_text('ENGINEERING_CALENDAR_FIXTURE '+name)
        rows.append(CalendarSource(name,'https://www.'+DOMAINS[name][0]+'/calendar',str(p),hashlib.sha256(p.read_bytes()).hexdigest(),cutoff-1,cutoff-MINUTE,cutoff+MINUTE,complete))
    return NewsReview(tuple(rows))

def test_scope_and_explicit_policy():
    with pytest.raises(ValueError,match='BTC_NATIVE'):require_btc(SimpleNamespace(instrument=SimpleNamespace(product='OTHER',dataset='GLBX.MDP3',venue='XCME')))
    s,p,_,_=fixture()
    with pytest.raises(ValueError,match='REVIEWED_NEWS'):replace(p,trend=replace(p.trend,news_required=False))
    with pytest.raises(ValueError,match='L1'):replace(p,trend=replace(p.trend,outcome_mode='MINUTE_BAR'))

@pytest.mark.parametrize('a',['NORMAL','WIDEN','REDUCE','PAUSE'])
def test_pause_always_dominates(a):
    assert combine_actions([a,'PAUSE'])==combine_actions(['PAUSE',a])=='PAUSE'

def test_news_is_explicit_bounded_hash_verified(tmp_path):
    assert NewsReview().status(NOW)['missing_publishers']==list(REQUIRED)
    r=review(tmp_path);assert r.status(NOW)['available']
    Path(r.sources[0].evidence_path).write_text('changed')
    assert not r.status(NOW)['available'];assert r.status(NOW)['source_errors']
    with pytest.raises(ValueError,match='SCOPE'):NewsReview(required_publishers=('BLS',))

def test_source_capture_does_not_prove_calendar_completeness(tmp_path):
    assert not review(tmp_path,complete=False).status(NOW)['available']
    r=review(tmp_path)
    assert not r.status(NOW+2*MINUTE)['available']
    assert not replace(r,sources=(replace(r.sources[0],retrieved_ns=NOW+1),)+r.sources[1:]).status(NOW)['available']

def test_replay_does_not_renew_expired_market_trigger(monkeypatch):
    s,p,f,o=fixture();old=replace(o.trigger,at_ns=NOW-60*MINUTE,available_ns=NOW)
    o=replace(o,trigger=old)
    monkeypatch.setattr('monatise.research.btc_upgrade.setups.observations',lambda *a:(o,))
    fixed=trend_observations(s,p.trend,f)[0]
    assert fixed.stage=='EXPIRED' and fixed.trigger.available_ns==NOW
    assert deadline(fixed,s,p.trend)==NOW-55*MINUTE
    row=inspect(fixed,s,p,f,{'regime':'TREND','side':'BUY'})
    assert 'MARKET_TRIGGER_EXPIRED' in row['gates']['trigger'] and row['plan'] is None

@pytest.mark.parametrize('side',[Side.BUY,Side.SELL])
def test_trend_plan_supports_both_sides_and_reports_all_gates(side):
    s,p,f,o=fixture(side)
    row=inspect(o,s,p,f,{'regime':'TREND','side':side})
    assert row['plan'] is not None
    assert row['plan'].expires_ns==NOW+WIDTHS['5m']
    assert row['plan'].trigger_ns==o.trigger.at_ns
    assert 'trigger' in row['gates'] and 'context' in row['gates']

@pytest.mark.parametrize('side',[Side.BUY,Side.SELL])
def test_missing_news_and_h4_do_not_hide_valid_reference_plan(side):
    s,p,f,o=fixture(side);f['4h']=replace(f['4h'],state=State.UNAVAILABLE)
    row=inspect(o,s,p,f,{'regime':'UNKNOWN','side':None})
    result=reference_analysis(s,f,p,[row],{'reasons':['NEWS_CALENDAR_UNAVAILABLE']},{'reasons':['INVENTORY_CAP']},{'raw':{'raw_regime':'UNKNOWN'}})
    assert result['action']==side and result['execution_eligible'] is False
    assert 'NEWS_CALENDAR_UNAVAILABLE' in result['limitations'] and '4H_CONTEXT_UNAVAILABLE' in result['limitations']
    stale=replace(s,cutoff_ns=NOW+10*NS)
    old=reference_analysis(stale,f,p,[row],{'reasons':[]},{'reasons':[]},{'raw':{'raw_regime':'UNKNOWN'}})
    assert old['action']==side and 'FRESH_QUOTE_REQUIRED_BEFORE_ENTRY' in old['limitations']

def range_fixture(side=Side.BUY):
    s,p,f,o=fixture(side)
    f['5m']=replace(f['5m'],bars=tuple(replace(b,low=max(D(50000),b.low),high=min(D(51000),b.high)) for b in f['5m'].bars))
    box={'available':True,'lower':'50000','upper':'51000','formed_ns':NOW-10*MINUTE,'available_ns':NOW-10*MINUTE,'box_id':'box-fixture'}
    return s,p,f,box

@pytest.mark.parametrize('side',[Side.BUY,Side.SELL])
def test_bounded_range_rejection_has_structural_stop_and_midpoint(side):
    s,p,f,box=range_fixture(side);obs=range_observations(s,f,p,box)
    assert len(obs)==1 and obs[0].side==side
    plan,codes=range_plan(obs[0],s,p,f,box)
    assert not codes and plan.targets[0].price==D(50500)
    assert plan.stop==D(49990 if side==Side.BUY else 51010) and plan.net_rr[0]>=1
    assert plan.management=='FULL_EXIT_FIRST_TARGET_FIXED_STOP'

def test_range_boundaries_cannot_be_known_after_trigger_or_survive_break():
    s,p,f,b=range_fixture();b['available_ns']=NOW
    assert not range_observations(s,f,p,b)
    b['available_ns']=NOW-10*MINUTE
    bad=replace(f['5m'].bars[-1],low=D(49985))
    f['5m']=replace(f['5m'],bars=f['5m'].bars[:-1]+(bad,))
    assert not range_observations(s,f,p,b)

def test_risk_caps_include_pending_inventory_and_projected_loss():
    s,p,f,o=fixture();plan=inspect(o,s,p,f,{'regime':'TREND','side':'BUY'})['plan']
    state={'contracts':1,'open_risk_usd':D(500),'gross_realized_loss_usd':D(1900),'unresolved_selections':[]}
    r=gates(state,p.risk,plan)
    assert r['action']=='PAUSE' and 'INVENTORY_CAP' in r['reasons'] and 'PROJECTED_DAILY_LOSS_CAP' in r['reasons']
    state.update(contracts=0,open_risk_usd=D(0),gross_realized_loss_usd=D(0),unresolved_selections=['unresolved'])
    assert gates(state,p.risk)['reasons']==['UNRESOLVED_EXPOSURE_PAUSE']

def test_regime_requires_history_not_flat_missing_data():
    s,p,f,_=fixture();f['4h']=replace(f['4h'],state=State.UNAVAILABLE)
    raw=classify(s,f,p.regime);assert raw['raw_regime']=='UNKNOWN'
    assert '4H_CONTEXT_UNAVAILABLE' in raw['reasons']

def test_range_metrics_and_closed_bar_hysteresis():
    s,p,f,_=fixture();rows=[]
    for i in range(20):
        center=D(50200 if i%2==0 else 50800);opened=NOW-(20-i)*WIDTHS['15m']
        rows.append(Bar(s.instrument.key,'15m',opened,opened+WIDTHS['15m'],opened+WIDTHS['15m'],center,center+200,center-200,center,100,'fixture:'+str(i)))
    box=range_box(rows,p.regime);assert box['available'] and box['low_touches']>=2 and box['high_touches']>=2
    raw={'raw_regime':'RANGE','side':None,'closed_bar_ns':NOW,'range_box':box}
    first=confirm(raw,None,2);assert first['regime']=='TRANSITION'
    same=confirm(raw,first,2);assert same['count']==1
    next=confirm({**raw,'closed_bar_ns':NOW+15*MINUTE},same,2);assert next['regime']=='RANGE'
    unknown=confirm({'raw_regime':'UNKNOWN','side':None,'closed_bar_ns':NOW+15*MINUTE},next,2);assert unknown['regime']=='UNKNOWN'

def test_service_keeps_analysis_separate_from_news_permission_and_is_idempotent(tmp_path,monkeypatch):
    s,p,f,o=fixture()
    monkeypatch.setattr('monatise.research.btc_upgrade.service.build_frames',lambda *a:f)
    monkeypatch.setattr('monatise.research.btc_upgrade.service.classify',lambda *a:{'raw_regime':'TREND','side':'BUY','closed_bar_ns':NOW,'reasons':[]})
    monkeypatch.setattr('monatise.research.btc_upgrade.service.trend_observations',lambda *a:(o,))
    store=Store(tmp_path/'ledger.sqlite');service=BTCService(store,p,stream='test',series_id='fixture')
    try:
        r=service.evaluate(s,'one');assert r['trade_action']=='NO_TRADE' and r['analysis']['action']=='BUY'
        assert r['reason']=='NEWS_PERMISSION_NOT_READY'
        assert 'news' in r['candidate_audit'][0]['gate_groups'] and r['candidate_audit'][0]['economic_status']=='PASSED'
        assert service.evaluate(s,'one')==r
        assert store.db.execute('select count(*) from selections').fetchone()[0]==0
    finally:store.close()

def test_service_selects_only_shadow_with_reviewed_calendar_and_never_duplicates(tmp_path,monkeypatch):
    s,p,f,o=fixture()
    monkeypatch.setattr('monatise.research.btc_upgrade.service.build_frames',lambda *a:f)
    monkeypatch.setattr('monatise.research.btc_upgrade.service.classify',lambda *a:{'raw_regime':'TREND','side':'BUY','closed_bar_ns':NOW,'reasons':[]})
    monkeypatch.setattr('monatise.research.btc_upgrade.service.trend_observations',lambda *a:(o,))
    store=Store(tmp_path/'ledger.sqlite');service=BTCService(store,p,stream='test',series_id='fixture')
    try:
        r=service.evaluate(s,'one',news_review=review(tmp_path));assert r['trade_action']=='BUY'
        assert not r['execution_eligible'] and r['orders_created']==0
        assert service.evaluate(s,'one',news_review=review(tmp_path))==r
        assert store.db.execute('select count(*) from selections').fetchone()[0]==1
    finally:store.close()

def test_analysis_can_describe_intraday_trend_with_unknown_h4():
    from monatise.research.btc_upgrade.analysis import intraday_regime
    s,p,f,_=fixture();rows=[]
    for i in range(20):
        opened=NOW-(20-i)*WIDTHS['15m'];base=D(48000+i*100)
        rows.append(Bar(s.instrument.key,'15m',opened,opened+WIDTHS['15m'],opened+WIDTHS['15m'],base,base+110,base-5,base+100,100,'trend-fixture:'+str(i)))
    f['15m']=replace(f['15m'],bars=tuple(rows));f['4h']=replace(f['4h'],state=State.UNAVAILABLE)
    assert classify(s,f,p.regime)['raw_regime']=='UNKNOWN'
    assert intraday_regime(f,p)['state']=='TREND' and intraday_regime(f,p)['side']=='BUY'

def test_stale_frame_is_unknown_even_with_direction_label():
    s,p,f,_=fixture();old=tuple(replace(b,open_ns=b.open_ns-WIDTHS['4h']*2,close_ns=b.close_ns-WIDTHS['4h']*2,available_ns=b.available_ns-WIDTHS['4h']*2) for b in f['4h'].bars)
    f['4h']=replace(f['4h'],bars=old)
    assert '4H_FRAME_STALE' in classify(s,f,p.regime)['reasons']

def test_regime_requires_distinct_closes_after_direction_change():
    raw={'raw_regime':'TREND','side':'BUY','closed_bar_ns':NOW}
    prior=confirm(raw,None,1)
    changed=confirm({**raw,'side':'SELL'},prior,2)
    assert changed['regime']=='TRANSITION' and changed['count']==1
    with pytest.raises(ValueError,match='REGRESSION'):confirm({**raw,'closed_bar_ns':NOW-1},prior,2)

def test_range_disabled_only_blocks_permission_not_source_evidence():
    s,p,f,b=range_fixture();o=range_observations(s,f,p,b)[0]
    row=inspect(o,s,replace(p,range_enabled=False),f,{'regime':'RANGE','side':None},b)
    assert row['plan'] and 'RANGE_RESEARCH_NOT_ENABLED' in row['gates']['context']

def test_directional_aggressor_flow_is_required_when_selected():
    s,p,f,o=fixture();p=replace(p,trend=replace(p.trend,volume_mode='AGGRESSOR_ROBUST'))
    row=inspect(o,s,p,f,{'regime':'TREND','side':'BUY'})
    assert row['gates']['participation']==['EXECUTED_FLOW_WINDOW_NOT_COVERED']
    assert row['plan'] is not None  # Economic result remains independently visible.
    c=Coverage('trades',NOW-5*MINUTE,NOW,NOW,'fixture-coverage')
    ts=(Trade(s.instrument.key,NOW-MINUTE,NOW-MINUTE,NOW-MINUTE,D(50100),10,'BUY','fixture-buy'),
        Trade(s.instrument.key,NOW-MINUTE,NOW-MINUTE,NOW-MINUTE,D(50100),10,None,'fixture-unknown'))
    row=inspect(o,replace(s,trades=ts,coverage=(c,)),p,f,{'regime':'TREND','side':'BUY'})
    assert row['gates']['participation']==['DIRECTIONAL_FLOW_NOT_ROBUST_TO_UNKNOWN']

def test_unresolved_shadow_exposure_is_never_treated_as_flat(tmp_path):
    s,p,f,o=fixture();plan=inspect(o,s,p,f,{'regime':'TREND','side':'BUY'})['plan'];store=Store(tmp_path/'risk.sqlite')
    try:
        with store.transaction():
            store.record_observation('x',o,NOW,qualified=True)
            c=Candidate(o,plan,(),'BTC_TREND');sid,_,_=store.claim('x',c,NOW,'a'*64,'b'*64,'A',policy=p.trend)
            store.position_event('x',sid,'FILL',NOW+1,{'price':str(plan.entry)})
            store.position_event('x',sid,'UNRESOLVED',NOW+2,{'position_closed':True,'reason':'MISSING_NATIVE_QUOTES'})
        r=ledger_state(store,'x',s.instrument.key,NOW+10*MINUTE)
        assert r['contracts']==1 and r['unresolved_selections']==[sid]
        assert gates(r,p.risk)['action']=='PAUSE'
    finally:store.close()

def test_source_and_context_failures_are_attributed_even_when_news_missing(tmp_path,monkeypatch):
    s,p,f,o=fixture();s=replace(s,quality=('UNRECONCILED_GAP',));f['4h']=replace(f['4h'],state=State.UNAVAILABLE)
    monkeypatch.setattr('monatise.research.btc_upgrade.service.build_frames',lambda *a:f)
    monkeypatch.setattr('monatise.research.btc_upgrade.service.trend_observations',lambda *a:(o,))
    store=Store(tmp_path/'ledger.sqlite')
    try:
        r=BTCService(store,p,stream='bad-source',series_id='fixture').evaluate(s,'one')
        g=r['candidate_audit'][0]['gate_groups']
        assert 'SOURCE_QUALITY_UNRESOLVED' in g['source'] and 'NEWS_CALENDAR_UNAVAILABLE' in g['news'] and 'H4_UNAVAILABLE' in g['context']
        assert r['analysis']['action']=='NO_TRADE' and r['reason']=='SOURCE_NOT_READY'
    finally:store.close()

def test_counterfactual_without_future_l1_is_not_a_profitable_rejection():
    from monatise.research.btc_upgrade.validation import observe_rejected_plan
    s,p,f,o=fixture();plan=encode(inspect(o,s,p,f,{'regime':'TREND','side':'BUY'})['plan'])
    r=observe_rejected_plan(plan,NOW,s,p.trend)
    assert r['status']=='NO_OBSERVED_FILL' and 'hypothetical_net_pnl' not in r

def test_history_merge_rejects_non_btc_before_writing(tmp_path,monkeypatch):
    from monatise.research.btc_upgrade.history import merge_manifests
    p=tmp_path/'manifest.json';p.write_text('{}')
    monkeypatch.setattr('monatise.research.btc_upgrade.history.load_archive',lambda p:SimpleNamespace(instrument=SimpleNamespace(product='OTHER')))
    with pytest.raises(ValueError,match='BTC_NATIVE'):merge_manifests([p],tmp_path/'out.json')
    assert not (tmp_path/'out.json').exists()

def test_no_provider_or_order_clients_in_upgrade_source():
    import ast
    root=Path(__file__).resolve().parents[3]/'monatise/research/btc_upgrade'
    assert root.exists()
    for p in root.glob('*.py'):
        tree=ast.parse(p.read_text())
        for n in ast.walk(tree):
            if isinstance(n,ast.Attribute):assert n.attr not in ('Live','Historical','submit_order','place_order','create_order')

def test_broker_cost_verification_cannot_be_claimed_without_calibration():
    s,p,f,o=fixture()
    with pytest.raises(ValueError,match='BROKER_COST_CLAIM'):replace(p,cost_basis='VERIFIED_BROKER_COSTS')

def test_modeled_spread_cannot_be_presented_as_observed_reference_quote():
    s,p,f,o=fixture();s=replace(s,quotes=(replace(s.quotes[0],source='MODELED_SPREAD_FROM_NATIVE_CLOSE:fixture'),))
    row=inspect(o,s,p,f,{'regime':'TREND','side':'BUY'})
    result=reference_analysis(s,f,p,[row],{'reasons':[]},{'reasons':[]},{'raw':{'raw_regime':'TREND'}})
    assert result['action']=='NO_TRADE' and 'OBSERVED_NATIVE_QUOTE_REQUIRED' in result['reason']

def test_source_failure_withholds_data_dependent_economic_plan():
    s,p,f,o=fixture();r=inspect(o,replace(s,quality=('GAP',)),p,f,{'regime':'TREND','side':'BUY'})
    assert r['plan'] is None and r['gates']['economics']==['ECONOMICS_NOT_EVALUATED_SOURCE_QUALITY']

def test_unknown_after_missing_frame_does_not_resurrect_old_regime():
    prior=confirm({'raw_regime':'TREND','side':'BUY','closed_bar_ns':NOW},None,1)
    r=confirm({'raw_regime':'UNKNOWN','side':None,'closed_bar_ns':0},prior,2)
    assert r['regime']=='UNKNOWN' and r['closed_bar_ns']==NOW and r['raw']['closed_bar_ns']==0

def test_forward_testing_requires_source_bound_freeze_receipt(tmp_path):
    from monatise.research.btc_upgrade.validation import replay
    s,p,f,o=fixture();a=SimpleNamespace(instrument=s.instrument)
    with pytest.raises(ValueError,match='FREEZE_RECEIPT'):
        replay(a,p,tmp_path/'r.sqlite',stream='x',series_id='fixture',cutoffs=(NOW,NOW+MINUTE),split_ns=NOW+MINUTE,freeze_ns=NOW-1,sample_status='PREREGISTERED_UNSEEN_FORWARD')
    assert not (tmp_path/'r.sqlite').exists()

def test_freeze_receipt_is_immutable_and_cannot_target_past(tmp_path):
    from monatise.research.btc_upgrade.validation import freeze_policy
    import time
    s,p,f,o=fixture();target=tmp_path/'freeze.json'
    with pytest.raises(ValueError,match='FUTURE'):freeze_policy(p,target,forward_start_ns=1)
    x=freeze_policy(p,target,forward_start_ns=time.time_ns()+MINUTE)
    assert x['policy_hash']==p.hash
    with pytest.raises(FileExistsError):freeze_policy(p,target,forward_start_ns=time.time_ns()+MINUTE)

def test_text_report_keeps_analysis_separate_from_execution():
    from monatise.research.btc_upgrade.formatting import text_report
    s,p,f,o=fixture();row=inspect(o,s,p,f,{'regime':'TREND','side':'BUY'})
    a=reference_analysis(s,f,p,[row],{'reasons':['NEWS_CALENDAR_UNAVAILABLE']},{'reasons':[]},{'raw':{'raw_regime':'TREND'}})
    r={'analysis':a,'cutoff_ns':NOW,'instrument':encode(s.instrument),'trade_action':'NO_TRADE','reason':'NEWS_PERMISSION_NOT_READY'}
    text=text_report(r)
    assert 'BTC BTCX6 — BUY' in text and 'Trading permission: NO_TRADE' in text and 'execution disabled' in text


def test_execution_quote_freshness_does_not_blanket_veto_inactive_analysis():
    s,p,f,o=fixture();s=replace(s,cutoff_ns=NOW+6*NS)
    row=inspect(o,s,p,f,{'regime':'TREND','side':'BUY'})
    assert row['plan'] is None and row['gates']['economics']==['ENTRY_QUOTE_STALE']
    r=reference_analysis(s,f,p,[row],{'reasons':['NEWS_CALENDAR_UNAVAILABLE']},{'reasons':[]},{'raw':{'raw_regime':'TREND'}})
    assert r['action']=='BUY' and r['observed_native_quote_age_seconds']=='6'
    assert r['execution_eligible'] is False and 'FRESH_QUOTE_REQUIRED_BEFORE_ENTRY' in r['limitations']

@pytest.mark.parametrize('age_ns',[5*NS,6*NS,59*NS,60*NS])
def test_analysis_accepts_quotes_up_to_and_including_sixty_seconds(age_ns):
    s,p,f,o=fixture();s=replace(s,cutoff_ns=NOW+age_ns)
    row=inspect(o,s,p,f,{'regime':'TREND','side':'BUY'})
    r=reference_analysis(s,f,p,[row],{'reasons':[]},{'reasons':[]},{'raw':{'raw_regime':'TREND'}})
    assert r['action']=='BUY' and r['observed_native_quote_timestamp_ns']==NOW
    assert D(r['observed_native_quote_age_seconds'])==D(age_ns)/NS
    assert not r['execution_eligible']

@pytest.mark.parametrize('age_ns',[60*NS+1,61*NS,120*NS])
def test_over_sixty_seconds_requires_refresh_and_hides_setup(age_ns):
    s,p,f,o=fixture();s=replace(s,cutoff_ns=NOW+age_ns)
    row=inspect(o,s,p,f,{'regime':'TREND','side':'BUY'})
    r=reference_analysis(s,f,p,[row],{'reasons':[]},{'reasons':[]},{'raw':{'raw_regime':'TREND'}})
    assert r['action']=='NO_TRADE' and r['status']=='STALE_DATA_REFRESH_REQUIRED' and r['plan'] is None
    assert 'ANALYSIS_QUOTE_STALE_REFRESH_REQUIRED' in r['reason']
    assert r['observed_native_quote_timestamp_ns']==NOW

@pytest.mark.parametrize('stage',['EXPIRED','INVALIDATED'])
def test_fresh_quote_never_revives_expired_or_invalidated_market_signal(stage):
    s,p,f,o=fixture();o=replace(o,stage=stage)
    row=inspect(o,s,p,f,{'regime':'TREND','side':'BUY'})
    assert row['plan'] is None and 'LIFECYCLE_'+stage in row['gates']['trigger']
    r=reference_analysis(s,f,p,[row],{'reasons':[]},{'reasons':[]},{'raw':{'raw_regime':'TREND'}})
    assert r['plan'] is None

def test_analysis_and_entry_quote_thresholds_are_separately_configurable():
    s,p,f,o=fixture();p=replace(p,analysis_quote_age_ns=60*NS,trend=replace(p.trend,quote_age_ns=2*NS))
    s=replace(s,cutoff_ns=NOW+3*NS);row=inspect(o,s,p,f,{'regime':'TREND','side':'BUY'})
    assert row['gates']['economics']==['ENTRY_QUOTE_STALE']
    assert reference_analysis(s,f,p,[row],{'reasons':[]},{'reasons':[]},{'raw':{'raw_regime':'TREND'}})['action']=='BUY'
    with pytest.raises(ValueError,match='ANALYSIS_QUOTE_AGE'):replace(p,analysis_quote_age_ns=0)


def current_research_policy():
    from monatise.research.btc_upgrade.__main__ import load_policy
    return load_policy(Path(__file__).resolve().parents[3]/'docs/btc-upgrade/research-policy.json')


@pytest.mark.parametrize('side',[Side.BUY,Side.SELL])
@pytest.mark.parametrize('pathway',['TREND','RANGE'])
@pytest.mark.parametrize('age_ns',[6*NS,59*NS,60*NS,60*NS+1])
def test_current_policy_entry_freshness_boundary(side,pathway,age_ns):
    configured=current_research_policy()
    assert configured.trend.quote_age_ns==60*NS
    assert configured.analysis_quote_age_ns==60*NS
    if pathway=='RANGE':
        s,p,f,box=range_fixture(side)
        o=range_observations(s,f,p,box)[0]
    else:
        s,p,f,o=fixture(side);box=None
    p=replace(p,trend=configured.trend)
    s=replace(s,cutoff_ns=NOW+age_ns)
    row=inspect(o,s,p,f,{'regime':pathway,'side':side},box)
    if age_ns<=60*NS:
        assert row['plan'] is not None and not row['gates']['economics']
    else:
        assert row['plan'] is None and row['gates']['economics']==['ENTRY_QUOTE_STALE']


@pytest.mark.parametrize('age_ns',[60*NS,60*NS+1])
def test_service_uses_and_reports_current_entry_freshness(tmp_path,monkeypatch,age_ns):
    s,p,f,o=fixture();p=replace(p,trend=current_research_policy().trend)
    s=replace(s,cutoff_ns=NOW+age_ns)
    monkeypatch.setattr('monatise.research.btc_upgrade.service.build_frames',lambda *a:f)
    monkeypatch.setattr('monatise.research.btc_upgrade.service.classify',lambda *a:{'raw_regime':'TREND','side':'BUY','closed_bar_ns':NOW,'reasons':[]})
    monkeypatch.setattr('monatise.research.btc_upgrade.service.trend_observations',lambda *a:(o,))
    store=Store(tmp_path/'ledger.sqlite')
    try:
        r=BTCService(store,p,stream='entry-60s',series_id='fixture').evaluate(s,'one')
        assert r['analysis']['quote_freshness_policy']=={'conditional_analysis_limit_seconds':'60','entry_limit_seconds':'60'}
        assert ('ENTRY_QUOTE_STALE' in r['readiness']['source']['reasons'])==(age_ns>60*NS)
        assert r['execution_eligible'] is False and r['orders_created']==0
    finally:store.close()
