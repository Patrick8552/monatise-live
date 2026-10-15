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
    g.guards['trades']=PriceGuard(c,policy,anchor='2500',anchor_ns=at,anchor_sha256=hashlib.sha256(bytes(rows[-1])).hexdigest())
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


def test_persistent_capture_wires_bootstrap_cursor_to_initial_sdk_attempt(setup,tmp_path):
    from monatise.research.phase9.service import CapturePlan,CaptureStep,PersistentResearchService
    from monatise.research.phase9.rotation import RotatingSpool,RotationPolicy
    p,c,s,rows,root=setup;r=review_bootstrap(p,s,root,review_reference='review');clients=[]
    class Client:
        def __init__(self,*args):self.done=asyncio.Event();clients.append(self)
        def add_callback(self,callback,exception_callback):self.callback=callback
        def subscribe(self,**kwargs):self.kw=kwargs
        def start(self):
            schema=self.kw['schema'];self.callback(system(dn.SystemCode.SUBSCRIPTION_ACK))
            if schema=='definition':self.callback(native('ES'))
            else:
                assert self.kw['start']==rows[0].ts_event
                for row in rows:self.callback(row)
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
