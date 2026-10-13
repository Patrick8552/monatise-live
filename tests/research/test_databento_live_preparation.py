"""Native-shaped offline live-feed preparation; no credentials or provider calls."""
import asyncio
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import databento_dbn as dbn
import pytest

from monatise.adapters.databento_gold import DatabentoGoldAdapter
from monatise.research.databento.datasets import DatasetCapability
from monatise.research.databento.live_models import ClockReview,LiveScope,LivePermit,native_definition,consume_permit,SCHEMAS
from monatise.research.databento.live_state import Cursor,FeedState
from monatise.research.databento.live_journal import NativeJournal,verify
from monatise.research.databento.live_feed import CMELiveCapture
from monatise.research.institutional.models import digest
from monatise.research.institutional.fixtures import NOW_NS
from tests.test_databento_gold import replay


def native(product='GC',**changes):
    iid,tick,size,unit,venue={'GC':(41271,'.1',100,'TRYOZ','XCEC'),
        'ES':(10252,'.25',50,'IPNT','XCME'),'NQ':(261401,'.25',20,'IPNT','XCME')}[product]
    display=Decimal('.1') if product=='GC' else Decimal('.01')
    values=dict(publisher_id=1,instrument_id=iid,ts_event=NOW_NS-86400*10**9,ts_recv=NOW_NS-86400*10**9+1,
        raw_symbol=product+'Z6',asset=product,exchange=venue,currency='USD',instrument_class=dbn.InstrumentClass.FUTURE,
        security_type='FUT',leg_count=0,user_defined_instrument=dbn.UserDefinedInstrument.NO,
        security_update_action=dbn.SecurityUpdateAction.ADD,expiration=NOW_NS+60*86400*10**9,
        maturity_year=2026,maturity_month=12,unit_of_measure=unit,unit_of_measure_qty=size*10**9,
        display_factor=int(display*10**9),min_price_increment=int(Decimal(tick)*10**9),
        min_price_increment_amount=int(Decimal(tick)*size*display*10**9))
    values.update(changes);return dbn.InstrumentDefMsg(**values)


def capability():return DatasetCapability('GLBX.MDP3',SCHEMAS,NOW_NS-10**9,digest('ENGINEERING_PUBLISHER_METADATA'))


def contract(product='GC'):
    return native_definition(native(product),capability=capability(),publishers={1:('GLBX.MDP3','GLBX')},as_of_ns=NOW_NS)


def scope(**changes):
    v=dict(contracts=(contract(),contract('ES'),contract('NQ')),start_ns=NOW_NS-2*10**9,
        session_end_ns=NOW_NS+3600*10**9,session_review_reference='ENGINEERING_REVIEWED_SESSIONS',
        capability=capability(),publishers=((1,'GLBX.MDP3','GLBX'),))
    v.update(changes);return LiveScope(**v)


def permit(s,**changes):
    v=dict(permit_id='ENGINEERING_ONE_USE',scope_sha256=s.sha256,approved_at_ns=NOW_NS-1,expires_ns=NOW_NS+100*10**9,
        human_approval_reference='MOCK_HUMAN_RESEARCH_APPROVAL',live_entitlement_reference='MOCK_ACTIVE_PERSONAL_STANDARD',
        native_lineage_review_reference='ENGINEERING_NATIVE_TERMS',subscription_cost_reference='MOCK_RECURRING_PRICE',
        total_monthly_cost_usd='199',approved_monthly_budget_usd='199',licensing_use_reference='MOCK_PERSONAL_LICENSE',
        confirmed_available_sessions=10)
    v.update(changes);return LivePermit(**v)


def trade(iid=41271, *, t=NOW_NS-10**9,side=dbn.Side.BID,size=2,sequence=1):
    return dbn.TradeMsg(publisher_id=1,instrument_id=iid,ts_event=t,ts_recv=t+1,price=2500*10**9,
        size=size,action=dbn.Action.TRADE,side=side,depth=0,sequence=sequence,flags=0)


def book(iid=41271,t=NOW_NS-10**9):
    return dbn.MBP1Msg(publisher_id=1,instrument_id=iid,ts_event=t,ts_recv=t+1,price=2500*10**9,
        size=1,action=dbn.Action.ADD,side=dbn.Side.BID,depth=0,sequence=1,flags=0,
        levels=dbn.BidAskPair(bid_px=2500*10**9,ask_px=2501*10**9,bid_sz=2,ask_sz=3,bid_ct=1,ask_ct=1))


def system(code):return dbn.SystemMsg(ts_event=NOW_NS,msg='ENGINEERING_CONTROL',code=code)


def populate(state):
    i=0
    for schema in state.scope.schemas:
        state.ingest(schema,system(dbn.SystemCode.SUBSCRIPTION_ACK),capture_ns=NOW_NS,ordinal=i);i+=1
        for c in state.scope.contracts:
            row=native(c.metadata.product) if schema=='definition' else trade(c.metadata.instrument_id) if schema=='trades' else book(c.metadata.instrument_id)
            state.ingest(schema,row,capture_ns=NOW_NS,ordinal=i);i+=1
        state.ingest(schema,system(dbn.SystemCode.REPLAY_COMPLETED),capture_ns=NOW_NS,ordinal=i);i+=1


@pytest.mark.parametrize('product,tick,multiplier',[('GC','.1','100'),('ES','.25','50'),('NQ','.25','20')])
def test_genuine_native_conventions_supported_without_rescaling_prices(product,tick,multiplier):
    c=contract(product)
    assert c.metadata.publisher_id==1 and c.tick_size==Decimal(tick) and c.multiplier==Decimal(multiplier)
    assert dict(c.metadata.native_terms)['unit_of_measure'] in {'TRYOZ','IPNT'}
    s=FeedState(scope());row=trade(c.metadata.instrument_id)
    result=s.ingest('trades',row,capture_ns=NOW_NS,ordinal=1)
    assert result['payload'][0]=='2500' and result['availability_basis']=='ACTUAL_LOCAL_LIVE_CAPTURE'
    assert not result['execution_eligible']


@pytest.mark.parametrize('changes',[{'currency':'EUR'},{'unit_of_measure':'oz'},{'unit_of_measure_qty':99*10**9},
                                  {'min_price_increment_amount':10**9+1},{'asset':'MGC'},{'exchange':'XCME'},
                                  {'raw_symbol':'GC.c.0'},{'leg_count':1}])
def test_native_GC_contradictions_rejected(changes):
    with pytest.raises(ValueError):native_definition(native(**changes),capability=capability(),
        publishers={1:('GLBX.MDP3','GLBX')},as_of_ns=NOW_NS)


@pytest.mark.parametrize('changes',[{'schemas':('trades','mbo')},{'schemas':('definition','mbp-10')},
    {'contracts':()},{'duration_seconds':True},{'duration_seconds':86401},{'maximum_records':0},
    {'maximum_bytes':0},{'publishers':((1,'WRONG','GLBX'),)},{'session_review_reference':''}])
def test_scope_expensive_broad_or_invalid_inputs_rejected(changes):
    with pytest.raises(ValueError):scope(**changes)


@pytest.mark.parametrize('fault',['expired','future','hash','cost','entitlement','lineage','sessions','metadata'])
def test_live_permit_gates_before_client_creation(tmp_path,fault):
    s=scope();p=permit(s)
    if fault=='expired':p=replace(p,expires_ns=NOW_NS)
    if fault=='future':p=replace(p,approved_at_ns=NOW_NS+1)
    if fault=='hash':p=replace(p,scope_sha256=digest('other'))
    if fault=='cost':p=replace(p,approved_monthly_budget_usd='125')
    if fault=='entitlement':p=replace(p,live_entitlement_reference='')
    if fault=='lineage':p=replace(p,native_lineage_review_reference='')
    if fault=='sessions':p=replace(p,confirmed_available_sessions=2)
    if fault=='metadata':s=replace(s,capability=replace(s.capability,observed_at_ns=NOW_NS-301*10**9))
    def never(*args):raise AssertionError('network_client_must_not_be_created')
    with pytest.raises(ValueError):asyncio.run(CMELiveCapture(s,client_factory=never,clock_ns=lambda:NOW_NS).run(
        api_key='ENGINEERING_DUMMY',permit=p,permit_ledger=tmp_path/'permit.sqlite',output=tmp_path/'run'))


def test_one_use_gate_is_persistent_across_instances(tmp_path):
    s=scope();p=permit(s);path=tmp_path/'permits.sqlite'
    consume_permit(path,p,s,NOW_NS)
    with pytest.raises(ValueError,match='already_consumed'):consume_permit(path,p,s,NOW_NS)


def test_normal_controls_complete_each_schema_without_quarantining():
    state=FeedState(scope());populate(state)
    assert state.health(NOW_NS)['status']=='CAPTURED_CONTEXT_FRESH'
    state.ingest('trades',system(dbn.SystemCode.HEARTBEAT),capture_ns=NOW_NS,ordinal=100)
    assert not state.health(NOW_NS)['quarantined']
    assert state.health(NOW_NS)['counts']['trades']==3


@pytest.mark.parametrize('fault',['error','slow_reader','unknown','unacked_watermark','duplicate_watermark'])
def test_controls_quarantine_uncertain_transport(fault):
    state=FeedState(scope())
    if fault=='error':row=dbn.ErrorMsg(ts_event=NOW_NS,err='ENGINEERING_ERROR',code=dbn.ErrorCode.AUTH_FAILED)
    elif fault=='slow_reader':row=system(dbn.SystemCode.SLOW_READER_WARNING)
    elif fault=='unknown':row=system(dbn.SystemCode.END_OF_INTERVAL)
    else:row=system(dbn.SystemCode.REPLAY_COMPLETED)
    if fault=='duplicate_watermark':populate(state)
    state.ingest('trades',row,capture_ns=NOW_NS,ordinal=100)
    assert state.health(NOW_NS)['quarantined']


def test_heartbeats_do_not_make_old_market_observations_fresh():
    state=FeedState(scope());populate(state)
    future=NOW_NS+20*10**9
    for schema in state.scope.schemas:state.ingest(schema,system(dbn.SystemCode.HEARTBEAT),capture_ns=future,ordinal=99)
    h=state.health(future)
    assert h['status']=='UNAVAILABLE' and h['stale_market_inputs'] and not h['stalled_connections']


def test_definition_roll_or_economic_revision_rejected():
    s=FeedState(scope())
    with pytest.raises(ValueError):s.ingest('definition',native(expiration=NOW_NS+61*86400*10**9),capture_ns=NOW_NS,ordinal=1)


def test_cursor_counts_preserve_identical_legitimate_events_and_validate_replay_prefix():
    c=Cursor();h=digest('same_record')
    assert c.accept(NOW_NS,h) and c.accept(NOW_NS,h)
    recovered=Cursor.recover(c.snapshot())
    assert not recovered.accept(NOW_NS,h) and not recovered.accept(NOW_NS,h)
    assert recovered.accept(NOW_NS,h) and len(recovered.hashes_at_event)==3
    assert recovered.accept(NOW_NS+1,digest('next'))
    assert len(recovered.hashes_at_event)==1
    bad=Cursor.recover(c.snapshot())
    with pytest.raises(ValueError,match='prefix_mismatch'):bad.accept(NOW_NS,digest('different'))
    with pytest.raises(ValueError,match='missing_tied'):bad.accept(NOW_NS+1,h)


def test_recovery_needs_independent_review_and_missing_instrument_starts_at_original_scope():
    s=scope();state=FeedState(s);populate(state);checkpoints=state.checkpoint()
    with pytest.raises(ValueError,match='review'):FeedState(s,checkpoints=checkpoints)
    del checkpoints['trades:261401']
    recovered=FeedState(s,checkpoints=checkpoints,recovery_review_reference='ENGINEERING_REVIEW')
    assert recovered.replay_start('trades')==s.start_ns and recovered.replay_start('definition')<s.start_ns


def test_native_journal_hash_exact_bytes_capture_clock_and_tamper(tmp_path):
    s=scope();j=NativeJournal(tmp_path/'journal',schema='trades',scope=s,evidence_kind='ENGINEERING_SYNTHETIC')
    row=trade();ordinal,h=j.append(row,capture_ns=NOW_NS)
    assert ordinal==0 and h==hashlib.sha256(bytes(row)).hexdigest()
    j.close(quality={'quarantined':False},checkpoint={})
    manifest,rows=verify(tmp_path/'journal')
    assert rows==((NOW_NS,bytes(row)),) and manifest['record_count']==1
    p=tmp_path/'journal/records.sealed';p.chmod(0o600);p.write_bytes(p.read_bytes()[:-1]+b'X')
    with pytest.raises(ValueError,match='hash_mismatch'):verify(tmp_path/'journal')


@pytest.mark.parametrize('fault',['limit','clock','quarantine','unsealed'])
def test_native_journal_incomplete_or_uncertain_capture_not_admitted(tmp_path,fault):
    s=scope(maximum_records=1);j=NativeJournal(tmp_path/'journal',schema='trades',scope=s,evidence_kind='ENGINEERING_SYNTHETIC')
    j.append(trade(),capture_ns=NOW_NS)
    if fault=='limit':
        with pytest.raises(ValueError):j.append(trade(),capture_ns=NOW_NS)
    if fault=='clock':
        with pytest.raises(ValueError):j.append(trade(),capture_ns=NOW_NS-1)
    if fault=='unsealed':
        j.file.close()
        with pytest.raises(FileNotFoundError):verify(tmp_path/'journal')
        return
    j.close(quality={'quarantined':True},checkpoint={})
    with pytest.raises(ValueError,match='quarantined'):verify(tmp_path/'journal')


class FakeClient:
    def __init__(self,*,fault=None):self.fault=fault;self.callbacks=[];self.subscription=None;self.closed=asyncio.Event();self.terminated=False
    def add_callback(self,callback,exception_callback=None):self.callbacks.append(callback)
    def subscribe(self,**kwargs):self.subscription=kwargs
    def start(self):
        schema=self.subscription['schema'];cb=self.callbacks[0]
        cb(system(dbn.SystemCode.SUBSCRIPTION_ACK))
        if self.fault=='disconnect':self.closed.set();return
        if self.fault=='error':cb(dbn.ErrorMsg(ts_event=NOW_NS,err='ENGINEERING_ERROR',code=dbn.ErrorCode.AUTH_FAILED));return
        if self.fault=='overflow':
            for i in range(100):cb(system(dbn.SystemCode.HEARTBEAT))
            return
        for iid in self.subscription['symbols']:
            product={41271:'GC',10252:'ES',261401:'NQ'}[iid]
            row=native(product) if schema=='definition' else trade(iid) if schema=='trades' else book(iid)
            cb(row)
        cb(system(dbn.SystemCode.REPLAY_COMPLETED))
    async def wait_for_close(self):await self.closed.wait()
    def terminate(self):self.terminated=True;self.closed.set()


def test_live_capture_mocked_end_to_end_separate_schema_clients_and_persistent_gate(tmp_path):
    s=scope(duration_seconds=1);clients=[]
    def factory(key,heartbeat):
        assert key=='ENGINEERING_ONLY' and heartbeat==5
        c=FakeClient();clients.append(c);return c
    capture=CMELiveCapture(s,client_factory=factory,clock_ns=lambda:NOW_NS)
    args=dict(api_key='ENGINEERING_ONLY',permit=permit(s),permit_ledger=tmp_path/'ledger.sqlite',
              output=tmp_path/'capture',evidence_kind='ENGINEERING_SYNTHETIC')
    report=asyncio.run(capture.run(**args))
    assert report['quality']['status']=='CAPTURED_CONTEXT_FRESH' and report['connection_count']==3
    assert all(c.terminated for c in clients) and report['automatic_retries']==0
    assert {c.subscription['schema'] for c in clients}==set(SCHEMAS)
    assert all(c.subscription['symbols']==[41271,10252,261401] for c in clients)
    assert clients[0].subscription['start']==0
    assert report['normalization_tail'][0]['context_only'] and not report['execution_eligible']
    for schema in SCHEMAS:assert verify(tmp_path/'capture'/schema)[0]['record_count']==5
    args['output']=tmp_path/'second'
    with pytest.raises(ValueError,match='already_consumed'):asyncio.run(capture.run(**args))
    assert len(clients)==3


@pytest.mark.parametrize('fault',['disconnect','error','overflow'])
def test_live_transport_failures_quarantine_and_close_every_client(tmp_path,fault):
    s=scope(duration_seconds=1);clients=[]
    def factory(*args):
        c=FakeClient(fault=fault);clients.append(c);return c
    r=asyncio.run(CMELiveCapture(s,client_factory=factory,clock_ns=lambda:NOW_NS,queue_capacity=8).run(
        api_key='ENGINEERING',permit=permit(s),permit_ledger=tmp_path/'permits.sqlite',output=tmp_path/'capture',
        evidence_kind='ENGINEERING_SYNTHETIC'))
    assert r['quality']['quarantined'] and all(c.terminated for c in clients)
    assert not r['automatic_retries']
    with pytest.raises(ValueError):verify(tmp_path/'capture/trades')


def test_legacy_boolean_cannot_open_paid_live_transport():
    def never(*args):raise AssertionError('legacy_live_client_creation_forbidden')
    adapter=DatabentoGoldAdapter(replay(),client_factory=never)
    with pytest.raises(ValueError,match='prepared_native_live'):asyncio.run(adapter.stream(api_key='ENGINEERING',authorized=True))


def test_rejected_record_does_not_advance_durable_recovery_cursor():
    state=FeedState(scope());before=state.checkpoint()
    row=trade();row.price=2500000000001
    with pytest.raises(ValueError):state.ingest('trades',row,capture_ns=NOW_NS,ordinal=1)
    assert state.checkpoint()==before


def test_watermark_ends_recovery_and_later_regression_is_not_silently_skipped():
    state=FeedState(scope());populate(state);restored=FeedState(scope(),checkpoints=state.checkpoint(),recovery_review_reference='ENGINEERING_REVIEW')
    populate(restored)
    with pytest.raises(ValueError,match='regressed'):restored.ingest('trades',trade(t=NOW_NS-2*10**9),capture_ns=NOW_NS,ordinal=99)


def test_locked_or_one_sided_book_cannot_report_usable_live_context():
    state=FeedState(scope());populate(state)
    row=book(t=NOW_NS);row.levels[0].ask_px=row.levels[0].bid_px
    # Native SDK level values may be copy properties, so construct an explicit lock.
    row=dbn.MBP1Msg(publisher_id=1,instrument_id=41271,ts_event=NOW_NS-1,ts_recv=NOW_NS,
        price=2500*10**9,size=1,action=dbn.Action.MODIFY,side=dbn.Side.BID,depth=0,sequence=2,flags=0,
        levels=dbn.BidAskPair(bid_px=2500*10**9,ask_px=2500*10**9,bid_sz=1,ask_sz=1,bid_ct=1,ask_ct=1))
    state.ingest('mbp-1',row,capture_ns=NOW_NS,ordinal=99)
    assert state.health(NOW_NS)['status']=='UNAVAILABLE'
    assert 41271 in state.health(NOW_NS)['unusable_quote_instruments']


def test_reviewed_recovery_can_restore_fresh_quote_context_without_double_counting():
    state=FeedState(scope());populate(state)
    restored=FeedState(scope(),checkpoints=state.checkpoint(),recovery_review_reference='ENGINEERING_REVIEW')
    populate(restored)
    assert restored.health(NOW_NS)['status']=='CAPTURED_CONTEXT_FRESH'
    assert restored.counts['trades']==0 and restored.counts['replay_duplicates_skipped']==9


@pytest.mark.parametrize('fault',[None,'instrument','symbol','stype','expired'])
def test_live_symbol_mapping_binds_exact_numeric_selection(fault):
    state=FeedState(scope());populate(state)
    row=dbn.SymbolMappingMsg(publisher_id=0,instrument_id=999 if fault=='instrument' else 41271,ts_event=NOW_NS,
        stype_in=dbn.SType.RAW_SYMBOL if fault=='stype' else dbn.SType.INSTRUMENT_ID,
        stype_out=dbn.SType.INSTRUMENT_ID,stype_in_symbol='GCZ6' if fault=='symbol' else '41271',
        stype_out_symbol='41271',start_ts=NOW_NS-10**9,end_ts=NOW_NS if fault=='expired' else NOW_NS+10**9)
    state.ingest('trades',row,capture_ns=NOW_NS,ordinal=99)
    assert state.health(NOW_NS)['quarantined']==(fault is not None)


@pytest.mark.parametrize('product',['GC','ES','NQ'])
def test_live_gateway_numeric_to_raw_mapping_matches_reviewed_contract(product):
    state=FeedState(scope());populate(state)
    c=contract(product)
    row=dbn.SymbolMappingMsg(publisher_id=0,instrument_id=c.metadata.instrument_id,ts_event=NOW_NS,
        stype_in=dbn.SType.INSTRUMENT_ID,stype_out=dbn.SType.RAW_SYMBOL,
        stype_in_symbol=str(c.metadata.instrument_id),stype_out_symbol=c.metadata.raw_symbol,
        start_ts=NOW_NS-10**9,end_ts=2**64-1)
    state.ingest('definition',row,capture_ns=NOW_NS,ordinal=100)
    assert state.health(NOW_NS)['status']=='CAPTURED_CONTEXT_FRESH'


@pytest.mark.parametrize('output',['GCG7','GC.FUT','GC.c.0','41271','ESZ6'])
def test_live_gateway_raw_mapping_cannot_change_exact_contract(output):
    state=FeedState(scope());populate(state)
    row=dbn.SymbolMappingMsg(publisher_id=0,instrument_id=41271,ts_event=NOW_NS,
        stype_in=dbn.SType.INSTRUMENT_ID,stype_out=dbn.SType.RAW_SYMBOL,
        stype_in_symbol='41271',stype_out_symbol=output,start_ts=NOW_NS-10**9,end_ts=2**64-1)
    state.ingest('trades',row,capture_ns=NOW_NS,ordinal=100)
    assert state.health(NOW_NS)['quarantined']


def test_provider_clock_ahead_of_actual_local_capture_is_rejected():
    state=FeedState(scope());populate(state)
    with pytest.raises(ValueError,match='clocks'):
        state.ingest('trades',trade(t=NOW_NS+100*10**6),capture_ns=NOW_NS,ordinal=100)
    assert state.cursors['trades:41271'].event_ns==NOW_NS-10**9


def clock_review(**changes):
    values=dict(observed_at_ns=NOW_NS-10**9,expires_ns=NOW_NS+60*10**9,
        offset_lower_ns=100*10**6,offset_upper_ns=250*10**6,
        source_sha256=digest('ENGINEERING_INDEPENDENT_CLOCK_SAMPLES'),
        review_reference='ENGINEERING_TWO_SOURCE_CLOCK_INTERVAL',drift_bound_ppm=100)
    values.update(changes);return ClockReview(**values)


@pytest.mark.parametrize('changes',[{'source_sha256':'missing'},{'review_reference':''},
    {'offset_lower_ns':True},{'offset_upper_ns':10**9+1},{'offset_lower_ns':300*10**6},
    {'offset_lower_ns':-300*10**6},{'expires_ns':NOW_NS+300*10**9},
    {'drift_bound_ppm':1001},{'drift_bound_ppm':False}])
def test_clock_review_cannot_supply_unbounded_or_unproven_timestamp_tolerance(changes):
    with pytest.raises(ValueError):clock_review(**changes)


def test_reviewed_clock_preserves_original_record_and_local_capture_timestamps():
    state=FeedState(scope(clock_review=clock_review()));populate(state)
    row=trade(t=NOW_NS+150*10**6)
    value=state.ingest('trades',row,capture_ns=NOW_NS,ordinal=100)
    assert value['capture_ns']==NOW_NS and value['receive_ns']==row.ts_recv
    assert value['event_ns']==row.ts_event
    assert value['capture_utc_bounds_ns'][0]<value['receive_ns']<value['capture_utc_bounds_ns'][1]
    assert value['clock_review_sha256']==digest(state.scope.clock_review)
    assert not value['execution_eligible']


def test_future_record_beyond_independently_reviewed_uncertainty_still_rejects():
    state=FeedState(scope(clock_review=clock_review()));populate(state)
    with pytest.raises(ValueError,match='clocks'):
        state.ingest('trades',trade(t=NOW_NS+300*10**6),capture_ns=NOW_NS,ordinal=100)
    assert state.cursors['trades:41271'].event_ns==NOW_NS-10**9


def test_market_freshness_uses_worst_age_over_reviewed_clock_interval():
    state=FeedState(scope(clock_review=clock_review()));populate(state)
    # Raw subtraction is 9.9 seconds; upper UTC bound makes it over 10.
    result=state.health(NOW_NS+8900*10**6)
    assert result['stale_market_inputs'] and result['status']=='UNAVAILABLE'
    assert not result['authenticated_clock_certified']


def test_expired_clock_review_blocks_clients_and_invalidates_context(tmp_path):
    review=clock_review(expires_ns=NOW_NS)
    s=scope(clock_review=review)
    def never(*args):raise AssertionError('network_must_not_open')
    with pytest.raises(ValueError,match='clock_review'):
        asyncio.run(CMELiveCapture(s,client_factory=never,clock_ns=lambda:NOW_NS).run(
            api_key='ENGINEERING_DUMMY',permit=permit(s),permit_ledger=tmp_path/'permits.sqlite',output=tmp_path/'run'))
    assert FeedState(s).health(NOW_NS)['quarantined']


def test_clock_bounds_expand_only_by_explicit_bounded_drift_and_expire():
    review=clock_review()
    assert review.bounds(NOW_NS)==(99900000,250100000)
    with pytest.raises(ValueError,match='not_yet_available'):review.bounds(NOW_NS-2*10**9)
    with pytest.raises(ValueError,match='expired'):review.bounds(review.expires_ns)


def test_capture_duration_cannot_cross_session_end_under_reviewed_clock_uncertainty():
    s=scope(duration_seconds=30,session_end_ns=NOW_NS+30*10**9+200*10**6,clock_review=clock_review())
    with pytest.raises(ValueError,match='session'):s.validate_at(NOW_NS)


def test_uncertain_capture_at_session_boundary_cannot_report_fresh_context():
    state=FeedState(scope(session_end_ns=NOW_NS+200*10**6,clock_review=clock_review()))
    assert state.health(NOW_NS)['status']=='UNAVAILABLE'
    with pytest.raises(ValueError,match='session'):
        state.ingest('trades',trade(),capture_ns=NOW_NS,ordinal=0)
