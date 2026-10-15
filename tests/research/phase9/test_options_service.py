import asyncio
from dataclasses import replace
from decimal import Decimal

import databento_dbn as dbn
import pytest

from monatise.application.gold_options import black76
from monatise.research.institutional.fixtures import contract as option_contract, NOW_NS
from monatise.research.institutional.models import digest
from monatise.research.phase9.options import option_inputs
from monatise.research.phase9.service import CapturePlan, CaptureStep, PersistentResearchService
from monatise.research.phase9.storage import DurableSpool
from monatise.research.phase9.pipeline import ResearchPipeline
from tests.research.phase9.test_pipeline import gate, calendar, pipeline, trade, add
from tests.research.test_databento_live_preparation import scope, permit, FakeClient

NS=10**9


def quote(c,mid, *, event=NOW_NS-100):
    tick=c.tick_size
    b=(Decimal(str(mid))/tick).to_integral_value()*tick
    return dbn.MBP1Msg(publisher_id=c.metadata.publisher_id,instrument_id=c.metadata.instrument_id,
        ts_event=event,ts_recv=event+1,price=int(b*NS),size=1,action=dbn.Action.MODIFY,side=dbn.Side.BID,
        depth=0,sequence=1,flags=0,levels=dbn.BidAskPair(bid_px=int((b-tick)*NS),ask_px=int((b+tick)*NS),
            bid_sz=10,ask_sz=12,bid_ct=2,ask_ct=3))


def options(**changes):
    o,f=option_contract(option=True),option_contract()
    premium=black76(2500,2500,30/365,.04,.2,'C')
    args=dict(option=o,underlying=f,option_quote=quote(o,premium),future_quote=quote(f,2500),
        option_available_ns=NOW_NS-1,future_available_ns=NOW_NS-1,market_cutoff_ns=NOW_NS,local_cutoff_ns=NOW_NS,
        rate=.04,rate_as_of_ns=NOW_NS-NS,rate_source_sha256=digest('rate'),
        convention_reference='ENGINEERING_EUROPEAN_BENCHMARK',style='European',evidence_kind='ENGINEERING_SYNTHETIC')
    args.update(changes)
    return option_inputs(**args)


def oi(days, quantity=25):
    return dbn.StatMsg(publisher_id=1,instrument_id=900003,ts_event=NOW_NS-100,ts_recv=NOW_NS-90,
        ts_ref=NOW_NS-days*86400*NS,quantity=quantity,price=0,stat_type=dbn.StatType.OPEN_INTEREST,update_action=dbn.StatUpdateAction.NEW)


def test_stale_OI_does_not_invalidate_IV_but_exposure_remains_unknown():
    missing=options();stale=options(oi_record=oi(5),oi_available_ns=NOW_NS-1,oi_captured=True,oi_entitled=True)
    assert stale['pricing_and_model_greeks']['status']=='VALIDATED_MODEL_SENSITIVITIES'
    assert stale['pricing_and_model_greeks']==missing['pricing_and_model_greeks']
    assert stale['pricing_and_model_greeks']['iv']==pytest.approx(.2,abs=.001)
    assert stale['open_interest']['status']=='STALE'
    assert stale['unsigned_gamma_times_OI_multiplier'] is None and stale['signed_dealer_GEX'] is None
    assert not stale['production_GIL_compatible'] and not stale['gil_enabled']


@pytest.mark.parametrize('quantity',[0,25])
def test_published_qualifying_OI_allows_only_unsigned_leg_exposure(quantity):
    r=options(oi_record=oi(1,quantity),oi_available_ns=NOW_NS-1,oi_captured=True,oi_entitled=True)
    assert r['open_interest']['value']==quantity
    assert Decimal(r['unsigned_gamma_times_OI_multiplier'])>=0
    assert r['gamma_flip'] is None and r['options_derived_levels'] is None and r['decision']=='NO_TRADE'


@pytest.mark.parametrize('fault',['no_future_quote','no_option_quote','pair_skew','future_quote','off_tick','rate'])
def test_mandatory_pricing_dependencies_stay_mandatory(fault):
    changes={}
    if fault=='no_future_quote': changes['future_quote']=None
    if fault=='no_option_quote': changes['option_quote']=None
    if fault=='pair_skew':changes['future_quote']=quote(option_contract(),2500,event=NOW_NS-2*NS)
    if fault=='future_quote':changes['future_quote']=quote(option_contract(),2500,event=NOW_NS+NS)
    if fault=='off_tick':
        q=quote(option_contract(),2500);top=q.levels[0]
        changes['future_quote']=dbn.MBP1Msg(publisher_id=1,instrument_id=q.instrument_id,ts_event=q.ts_event,
            ts_recv=q.ts_recv,price=q.price,size=1,action=dbn.Action.MODIFY,side=dbn.Side.BID,depth=0,sequence=1,flags=0,
            levels=dbn.BidAskPair(bid_px=top.bid_px+1,ask_px=top.ask_px,bid_sz=1,ask_sz=1,bid_ct=1,ask_ct=1))
    if fault=='rate':changes['rate']=None
    r=options(**changes)
    assert r['pricing_and_model_greeks']['iv'] is None
    assert r['unsigned_gamma_times_OI_multiplier'] is None


def make_plan(s, **kwargs):
    values=dict(steps=(CaptureStep(s,permit(s),'INITIAL','ENGINEERING'),),
        entitlement_receipt_sha256=digest('ENGINEERING ENTITLEMENT'),cost_receipt_sha256=digest('ENGINEERING ZERO COST'),
        no_additional_charges_verified=True,review_reference='ENGINEERING MOCK PLAN',retry_delay_seconds=0)
    values.update(kwargs);return CapturePlan(**values)


def live_pipeline(s):
    gates={c.metadata.instrument_id:gate(c) for c in s.contracts}
    return ResearchPipeline(gates,{iid:calendar(g.contract) for iid,g in gates.items()},enabled_schemas=s.schemas)


def test_zero_cost_evidence_required_before_any_client_exists():
    with pytest.raises(ValueError):make_plan(scope(),no_additional_charges_verified=False)
    with pytest.raises(ValueError):make_plan(scope(),cost_receipt_sha256='missing')


def test_bounded_service_durable_restart_preserves_native_multiplicity(tmp_path):
    s=scope(duration_seconds=1);plan=make_plan(s);spool=DurableSpool(tmp_path/'private/native.sqlite')
    p=live_pipeline(s);clients=[]
    def factory(*args):
        c=FakeClient();clients.append(c);return c
    service=PersistentResearchService(plan,spool,p,client_factory=factory,clock_ns=lambda:NOW_NS)
    args=dict(api_key='ENGINEERING',output=tmp_path/'runs',permit_ledger=tmp_path/'permits.sqlite',evidence_kind='ENGINEERING_SYNTHETIC')
    result=asyncio.run(service.run(**args))
    assert result['attempts']==1 and all(c.terminated for c in clients)
    assert spool.load('feed_cursor') and spool.load('service')['next_step']==1
    assert not result['execution_eligible'] and not result['fresh_live_operation_verified']
    a=p.analyse(41271,now_ns=NOW_NS,mandatory=('trade_features',))
    fresh=live_pipeline(s)
    again=PersistentResearchService(plan,spool,fresh,client_factory=factory,clock_ns=lambda:NOW_NS)
    r=asyncio.run(again.run(**args))
    assert r['attempts']==0 and len(clients)==3
    assert fresh.analyse(41271,now_ns=NOW_NS,mandatory=('trade_features',))==a
    spool.close()


def test_provider_error_never_retries_and_expired_permit_never_connects(tmp_path):
    s=scope(duration_seconds=1)
    step2=CaptureStep(s,replace(permit(s),permit_id='second'),'RECOVER','ENGINEERING_RECOVERY')
    plan=make_plan(s,steps=(make_plan(s).steps[0],step2));spool=DurableSpool(tmp_path/'native.sqlite');clients=[]
    def factory(*a):
        c=FakeClient(fault='error');clients.append(c);return c
    r=asyncio.run(PersistentResearchService(plan,spool,live_pipeline(s),client_factory=factory,clock_ns=lambda:NOW_NS).run(
        api_key='ENGINEERING',output=tmp_path/'out',permit_ledger=tmp_path/'permits',evidence_kind='ENGINEERING_SYNTHETIC'))
    assert r['attempts']==1 and len(clients)==3
    spool.close()
    expired=replace(make_plan(s),steps=(CaptureStep(s,replace(permit(s),expires_ns=NOW_NS),'INITIAL','expired'),))
    spool=DurableSpool(tmp_path/'expired.sqlite')
    def never(*a):raise AssertionError('must not connect')
    with pytest.raises(ValueError):
        asyncio.run(PersistentResearchService(expired,spool,live_pipeline(s),client_factory=never,clock_ns=lambda:NOW_NS).run(
            api_key='ENGINEERING',output=tmp_path/'expired',permit_ledger=tmp_path/'expiredpermits',evidence_kind='ENGINEERING_SYNTHETIC'))
    spool.close()


def test_session_and_roll_plans_require_explicit_validated_boundaries():
    s=scope();first=make_plan(s).steps[0]
    changed=replace(s,start_ns=s.start_ns+NS)
    with pytest.raises(ValueError):make_plan(s,steps=(first,CaptureStep(changed,permit(changed,permit_id='other'),'RECOVER','review')))
    with pytest.raises(ValueError):make_plan(s,steps=(first,CaptureStep(s,permit(s,permit_id='other'),'NEW_SESSION','review')))
    with pytest.raises(ValueError):make_plan(s,steps=(first,CaptureStep(s,permit(s,permit_id='other'),'REVIEWED_ROLL','review')))


def test_recovery_replays_tied_prefix_without_double_volume(tmp_path):
    s=scope(duration_seconds=1);first=make_plan(s).steps[0]
    second=CaptureStep(s,replace(permit(s),permit_id='bounded-retry'),'RECOVER','ENGINEERING RECOVERY')
    plan=make_plan(s,steps=(first,second));spool=DurableSpool(tmp_path/'recovery.sqlite');p=live_pipeline(s);clients=[]
    class DisconnectAfterData(FakeClient):
        def start(self):
            super().start()
            asyncio.get_running_loop().call_later(.1,self.closed.set)
    def factory(*args):
        c=DisconnectAfterData() if len(clients)<3 else FakeClient()
        clients.append(c);return c
    r=asyncio.run(PersistentResearchService(plan,spool,p,client_factory=factory,clock_ns=lambda:NOW_NS).run(
        api_key='ENGINEERING',output=tmp_path/'out',permit_ledger=tmp_path/'permits',evidence_kind='ENGINEERING_SYNTHETIC'))
    assert r['attempts']==2 and len(clients)==6 and all(c.terminated for c in clients)
    assert r['reports'][1]['quality']['counts']['replay_duplicates_skipped']==9
    current=p.analyse(41271,now_ns=NOW_NS,mandatory=('trade_features',))
    assert current['components']['trade_features']['result']['executed_contracts']==2
    fresh=live_pipeline(s);spool.replay(fresh)
    assert fresh.analyse(41271,now_ns=NOW_NS,mandatory=('trade_features',))==current
    spool.close()


def test_spool_rejected_component_remains_quarantined_after_restart(tmp_path):
    p,c=pipeline();spool=DurableSpool(tmp_path/'fault.sqlite');r=trade(c)
    spool.append('trades',r,capture_ns=NOW_NS,delivery_id='good',evidence_kind='ENGINEERING_SYNTHETIC')
    spool.append('trades',r,capture_ns=NOW_NS,delivery_id='bad',evidence_kind='ENGINEERING_SYNTHETIC',
        admitted=False,rejection_reason='invalid_source')
    spool.replay(p)
    assert not p.analyse(c.metadata.instrument_id,now_ns=NOW_NS,mandatory=('trade_features',))['components']['trade_features']['available']
    spool.close()


def test_extended_live_schemas_are_opt_in_and_typed():
    from tests.research.test_databento_live_preparation import populate
    from monatise.research.databento.live_state import FeedState
    from monatise.research.databento.live_models import SUPPORTED_SCHEMAS
    assert 'ohlcv-1s' in SUPPORTED_SCHEMAS and 'mbp-10' in SUPPORTED_SCHEMAS
    s=scope(schemas=('definition','ohlcv-1s'))
    state=FeedState(s)
    c=s.contracts[0]
    row=dbn.OHLCVMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,ts_event=NOW_NS-2*NS,
        rtype=dbn.RType.OHLCV_1S,open=2500*NS,high=2501*NS,low=2499*NS,close=2500*NS,volume=4)
    r=state.ingest('ohlcv-1s',row,capture_ns=NOW_NS,ordinal=0)
    assert r['payload'][-1]==4 and r['capture_ns']==NOW_NS and not r['execution_eligible']


def test_transport_component_rejection_preserves_other_instruments():
    from tests.research.test_databento_live_preparation import populate
    from monatise.research.databento.live_state import FeedState
    state=FeedState(scope());populate(state)
    c=state.contracts[41271]
    state.reject_component('trades',trade(c),'invalid_price')
    h=state.health(NOW_NS)
    assert h['quarantined'] and h['status']=='UNAVAILABLE'
    assert h['component_health']['GCZ6']['trades']['status']=='UNAVAILABLE'
    assert h['component_health']['NQZ6']['trades']['status']=='CAPTURED_CONTEXT_FRESH'


def test_bad_reader_backpressure_never_reconnects_automatically(tmp_path):
    s=scope(duration_seconds=1);spool=DurableSpool(tmp_path/'overflow.sqlite');clients=[]
    class LargeBurst(FakeClient):
        def start(self):
            from tests.research.test_databento_live_preparation import system
            for _ in range(4000):self.callbacks[0](system(dbn.SystemCode.HEARTBEAT))
    def factory(*a):
        c=LargeBurst();clients.append(c);return c
    r=asyncio.run(PersistentResearchService(make_plan(s),spool,live_pipeline(s),client_factory=factory,clock_ns=lambda:NOW_NS).run(
        api_key='ENGINEERING',output=tmp_path/'out',permit_ledger=tmp_path/'permits',evidence_kind='ENGINEERING_SYNTHETIC'))
    assert r['attempts']==1 and r['reports'][0]['quality']['quarantined'] and all(c.terminated for c in clients)
    assert 'local_callback_or_queue_backpressure' in r['reports'][0]['quality']['reasons']
    assert not r['execution_eligible'];spool.close()
