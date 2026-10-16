from dataclasses import replace
from decimal import Decimal
import asyncio,hashlib
import pytest
import databento_dbn as dn
from monatise.research.native_futures.bootstrap import review_bootstrap
from monatise.research.databento.live_journal import NativeJournal
from monatise.research.databento.live_state import FeedState
from monatise.research.phase9.quality import PriceGuard
from monatise.research.institutional.models import digest
from tests.research.phase9.test_pipeline import pipeline,trade,add,NOW_NS,NS
from tests.research.test_databento_live_preparation import scope,system,permit,native


@pytest.fixture
def setup(tmp_path):
    p,c=pipeline('ES');g=p.gates[c.metadata.instrument_id];at=NOW_NS-54*NS
    rows=[trade(c,t=at,size=1),trade(c,t=at,size=2)]
    policy=replace(g.policy,floor_ticks=3);g.schema_policies['trades']=policy
    g.guards['trades']=PriceGuard(c,policy,anchor='2500',anchor_ns=rows[-1].ts_recv,anchor_sha256=hashlib.sha256(bytes(rows[-1])).hexdigest())
    s=scope(contracts=(c,),schemas=('definition','trades'),start_ns=NOW_NS-60*NS,duration_seconds=1)
    j=NativeJournal(tmp_path/'trades',schema='trades',scope=s,evidence_kind='ENGINEERING_SYNTHETIC')
    for row in rows:j.append(row,capture_ns=NOW_NS-50*NS)
    j.close(quality=dict(quarantined=False,reasons=[]),checkpoint={})
    return p,c,s,rows,tmp_path


def test_startup_replays_bridge_and_same_time_multiplicity_once_without_relaxing_guard(setup):
    p,c,s,rows,root=setup;r=review_bootstrap(p,s,root,review_reference='ENGINEERING_NATIVE_SOURCE_REVIEW')
    checkpoints=r.checkpoints(p,s);key='trades:'+str(c.metadata.instrument_id)
    assert len(checkpoints[key]['hashes_at_event'])==2
    st=FeedState(s,checkpoints=checkpoints,recovery_review_reference=r.sha256)
    assert st.replay_start('trades')==rows[0].ts_event
    st.ingest('trades',system(dn.SystemCode.SUBSCRIPTION_ACK),capture_ns=NOW_NS,ordinal=0)
    for i,row in enumerate(rows):assert st.ingest('trades',row,capture_ns=NOW_NS,ordinal=i+1) is None
    for i in range(1,7):
        row=trade(c,t=rows[0].ts_event+i*NS,price=str(Decimal('2500')+c.tick_size*i))
        assert st.ingest('trades',row,capture_ns=NOW_NS,ordinal=i+3) is not None
        assert add(p,row,ordinal=i+3)['accepted']
    assert len(p.gates[c.metadata.instrument_id].accepted)==6
    assert p.gates[c.metadata.instrument_id].guards['trades'].policy.floor_ticks==3
    assert st.counts['replay_duplicates_skipped']==2
    assert not p.gates[c.metadata.instrument_id].faults


def test_skipping_bridge_still_rejects_actual_jump(setup):
    p,c,s,rows,root=setup
    assert not add(p,trade(c,price='2501.5'),ordinal=5)['accepted']
    with pytest.raises(ValueError,match='pristine'):review_bootstrap(p,s,root,review_reference='review')


def test_later_scope_start_and_wrong_anchor_do_not_get_approved(setup):
    p,c,s,rows,root=setup
    with pytest.raises(ValueError,match='replay_start'):review_bootstrap(p,replace(s,start_ns=NOW_NS-NS),root,review_reference='review')
    p.gates[c.metadata.instrument_id].guards['trades'].anchor_sha256=digest('wrong')
    with pytest.raises(ValueError,match='anchor'):review_bootstrap(p,s,root,review_reference='review')


def test_incomplete_equal_timestamp_replay_prefix_remains_a_failure(setup):
    p,c,s,rows,root=setup;r=review_bootstrap(p,s,root,review_reference='review')
    st=FeedState(s,checkpoints=r.checkpoints(p,s),recovery_review_reference=r.sha256)
    st.ingest('trades',rows[0],capture_ns=NOW_NS,ordinal=1)
    with pytest.raises(ValueError,match='missing_tied'):
        st.ingest('trades',trade(c,t=NOW_NS-NS),capture_ns=NOW_NS,ordinal=2)


def test_changed_source_or_policy_cannot_reuse_bootstrap_review(setup):
    p,c,s,rows,root=setup;r=review_bootstrap(p,s,root,review_reference='review')
    g=p.gates[c.metadata.instrument_id];g.guards['trades'].policy=replace(g.schema_policies['trades'],scale=Decimal(9))
    with pytest.raises(ValueError,match='changed'):r.checkpoints(p,s)


@pytest.mark.parametrize('clock_delta',[0,40])
def test_persistent_capture_wires_bootstrap_cursor_to_initial_sdk_attempt(setup,tmp_path,clock_delta):
    from monatise.research.phase9.service import CapturePlan,CaptureStep,PersistentResearchService
    from monatise.research.phase9.rotation import RotatingSpool,RotationPolicy
    p,c,s,rows,root=setup;r=review_bootstrap(p,s,root,review_reference='review',capture_clock_tolerance_ns=1000 if clock_delta else 0,clock_equivalence_review_reference='EXPLICIT_INITIAL_CLOCK_REVIEW');clients=[]
    class Client:
        def __init__(self,*args):self.done=asyncio.Event();clients.append(self)
        def add_callback(self,callback,exception_callback):self.callback=callback
        def subscribe(self,**kwargs):self.kw=kwargs
        def start(self):
            schema=self.kw['schema'];self.callback(system(dn.SystemCode.SUBSCRIPTION_ACK))
            if schema=='definition':self.callback(native('ES'))
            else:
                assert self.kw['start']==rows[0].ts_event
                for row in rows:self.callback(translated(row,delta=clock_delta) if clock_delta else row)
                self.callback(trade(c,t=NOW_NS-NS,price='2500.25'))
            self.callback(system(dn.SystemCode.REPLAY_COMPLETED))
        def terminate(self):self.done.set()
        async def wait_for_close(self):await self.done.wait()
    plan=CapturePlan((CaptureStep(s,permit(s),'INITIAL','review'),),digest('entitlement'),digest('cost'),True,'review')
    spool=RotatingSpool(tmp_path/'spool',policy=RotationPolicy())
    service=PersistentResearchService(plan,spool,p,client_factory=Client,clock_ns=lambda:NOW_NS,bootstrap_review=r)
    report=asyncio.run(service.run(api_key='ENGINEERING',output=tmp_path/'capture',permit_ledger=tmp_path/'permits',evidence_kind='ENGINEERING_SYNTHETIC'))
    assert not report['reports'][0]['quality']['quarantined']
    assert len(p.gates[c.metadata.instrument_id].accepted)==1
    assert spool.load('bootstrap')['review_sha256']==r.sha256


def translated(row,*,delta=40,price_change=0,sequence_change=0):
    return dn.TradeMsg(publisher_id=row.publisher_id,instrument_id=row.instrument_id,ts_event=row.ts_event,
        ts_recv=row.ts_recv+delta,ts_in_delta=row.ts_in_delta+delta,price=row.price+price_change,
        size=row.size,action=row.action,side=row.side,depth=row.depth,flags=int(row.flags),sequence=row.sequence+sequence_change)


def test_explicit_initial_clock_identity_review_preserves_multiplicity_and_raw_bytes(setup):
    p,c,s,rows,root=setup;r=review_bootstrap(p,s,root,review_reference='review',capture_clock_tolerance_ns=1000,clock_equivalence_review_reference='SOURCE_BOUND_30_TO_41_NS_CAPTURE_PAIR_REVIEW')
    st=FeedState(s,checkpoints=r.checkpoints(p,s),recovery_review_reference=r.sha256,bootstrap_prefixes=r.prefix_reviews())
    for i,row in enumerate(rows):
        new=translated(row);raw=bytes(new)
        assert st.ingest('trades',new,capture_ns=NOW_NS,ordinal=i) is None
        assert bytes(new)==raw
    assert st.counts['replay_duplicates_skipped']==2 and len(st.bootstrap_clock_translations)==2
    assert all(x['receive_time_difference_ns']==40 for x in st.bootstrap_clock_translations)
    assert st.ingest('trades',trade(c,t=NOW_NS-NS),capture_ns=NOW_NS,ordinal=3) is not None


@pytest.mark.parametrize('changes',[dict(price_change=250000000),dict(sequence_change=1),dict(delta=1001)])
def test_changed_exchange_identity_or_excess_clock_variation_remains_rejected(setup,changes):
    p,c,s,rows,root=setup;r=review_bootstrap(p,s,root,review_reference='review',capture_clock_tolerance_ns=1000,clock_equivalence_review_reference='review')
    st=FeedState(s,checkpoints=r.checkpoints(p,s),recovery_review_reference=r.sha256,bootstrap_prefixes=r.prefix_reviews())
    with pytest.raises(ValueError,match='event_identity_or_clock'):
        st.ingest('trades',translated(rows[0],**changes),capture_ns=NOW_NS,ordinal=1)


def test_same_receive_time_difference_cannot_hide_changed_publisher_send_time(setup):
    from monatise.research.native_futures.replay_identity import verified_prefix_hash,trade_identity
    p,c,s,rows,root=setup;x=rows[0]
    bad=dn.TradeMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,ts_event=x.ts_event,ts_recv=x.ts_recv+40,
        ts_in_delta=x.ts_in_delta,price=x.price,size=x.size,action=x.action,side=x.side,depth=x.depth,flags=int(x.flags),sequence=x.sequence)
    expected=dict(record_sha256=hashlib.sha256(bytes(x)).hexdigest(),identity_sha256=trade_identity(x),ts_recv=x.ts_recv)
    with pytest.raises(ValueError,match='event_identity_or_clock'):
        verified_prefix_hash(bad,expected=expected,maximum_translation_ns=1000)


def test_generic_recovery_keeps_byte_exact_prefix_matching(setup):
    p,c,s,rows,root=setup;r=review_bootstrap(p,s,root,review_reference='review')
    st=FeedState(s,checkpoints=r.checkpoints(p,s),recovery_review_reference=r.sha256)
    with pytest.raises(ValueError,match='prefix_mismatch'):st.ingest('trades',translated(rows[0]),capture_ns=NOW_NS,ordinal=1)


def test_initial_clock_equivalence_cannot_cross_native_second_bucket(setup):
    from monatise.research.native_futures.replay_identity import verified_prefix_hash,trade_identity
    p,c,s,rows,root=setup;x=rows[0];at=x.ts_event//NS*NS
    old=dn.TradeMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,ts_event=at,ts_recv=at+NS-10,ts_in_delta=NS-10,price=x.price,size=x.size,action=x.action,side=x.side,depth=x.depth,flags=int(x.flags),sequence=x.sequence)
    expected=dict(record_sha256=hashlib.sha256(bytes(old)).hexdigest(),identity_sha256=trade_identity(old),ts_recv=old.ts_recv)
    with pytest.raises(ValueError,match='event_identity_or_clock'):
        verified_prefix_hash(translated(old,delta=40),expected=expected,maximum_translation_ns=1000)


def test_bootstrap_separates_event_replay_seek_from_receive_time_guard_anchor(setup,tmp_path):
    p,c,s,rows,_=setup;old=rows[-1];root=tmp_path/'clock-domain-anchors'
    anchor=dn.TradeMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,
        ts_event=old.ts_event,ts_recv=old.ts_event-1000,ts_in_delta=0,
        price=old.price,size=old.size,action=old.action,side=old.side,depth=0,flags=0,sequence=1)
    j=NativeJournal(root/'trades',schema='trades',scope=s,evidence_kind='ENGINEERING_SYNTHETIC')
    j.append(anchor,capture_ns=NOW_NS-50*NS);j.close(quality=dict(quarantined=False),checkpoint={})
    g=p.gates[c.metadata.instrument_id]
    g.guards['trades']=PriceGuard(c,g.schema_policies['trades'],anchor='2500',
        anchor_ns=anchor.ts_recv,anchor_sha256=hashlib.sha256(bytes(anchor)).hexdigest())
    review=review_bootstrap(p,s,root,review_reference='EXPLICIT_INDEPENDENT_NATIVE_CLOCK_DOMAINS')
    key='trades:'+str(c.metadata.instrument_id)
    assert review.checkpoints(p,s)[key]['event_ns']==anchor.ts_event
    st=FeedState(s,checkpoints=review.checkpoints(p,s),recovery_review_reference=review.sha256)
    assert st.replay_start('trades')==anchor.ts_event
    assert st.ingest('trades',anchor,capture_ns=NOW_NS,ordinal=0) is None
    next_row=dn.TradeMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,
        ts_event=anchor.ts_event+1,ts_recv=anchor.ts_recv+500,ts_in_delta=0,
        price=old.price,size=old.size,action=old.action,side=old.side,depth=0,flags=0,sequence=2)
    raw=bytes(next_row)
    assert st.ingest('trades',next_row,capture_ns=NOW_NS,ordinal=1) is not None
    assert add(p,next_row,ordinal=1)['accepted']
    assert bytes(next_row)==raw and g.guards['trades'].anchor_ns==anchor.ts_recv


def test_bootstrap_rejects_event_time_substitution_for_trade_receive_anchor(setup):
    p,c,s,rows,root=setup
    p.gates[c.metadata.instrument_id].guards['trades'].anchor_ns=rows[-1].ts_event
    with pytest.raises(ValueError,match='anchor_provider_index'):
        review_bootstrap(p,s,root,review_reference='WRONG_CLOCK_MUST_NOT_PASS')


def test_book_bootstrap_uses_exact_native_prefix_and_receive_anchor(setup,tmp_path):
    from tests.research.phase9.test_options_service import quote
    p,c,s,_,_=setup;root=tmp_path/'book';s=replace(s,schemas=('definition','mbp-1'))
    row=quote(c,2500);g=p.gates[c.metadata.instrument_id]
    g.guards['mbp-1']=PriceGuard(c,g.policy,anchor=Decimal(row.levels[0].ask_px)/NS,
        anchor_ns=row.ts_recv,anchor_sha256=hashlib.sha256(bytes(row)).hexdigest())
    j=NativeJournal(root/'mbp-1',schema='mbp-1',scope=s,evidence_kind='ENGINEERING_SYNTHETIC')
    j.append(row,capture_ns=NOW_NS);j.close(quality=dict(quarantined=False),checkpoint={})
    review=review_bootstrap(p,s,root,review_reference='EXACT_BOOK_PREFIX')
    st=FeedState(s,checkpoints=review.checkpoints(p,s),recovery_review_reference=review.sha256)
    assert st.ingest('mbp-1',row,capture_ns=NOW_NS,ordinal=1) is None
    assert not review.trade_prefixes
    bad=dn.MBP1Msg(publisher_id=row.publisher_id,instrument_id=row.instrument_id,ts_event=row.ts_event,
        ts_recv=row.ts_recv+1,price=row.price,size=row.size,action=row.action,side=row.side,
        depth=row.depth,flags=int(row.flags),sequence=row.sequence,levels=row.levels[0])
    st=FeedState(s,checkpoints=review.checkpoints(p,s),recovery_review_reference=review.sha256)
    with pytest.raises(ValueError,match='prefix_mismatch'):
        st.ingest('mbp-1',bad,capture_ns=NOW_NS,ordinal=1)
