import asyncio,json
from dataclasses import replace
import pytest
import databento_dbn as dn
from monatise.research.databento.live_state import Cursor,FeedState
from monatise.research.native_futures.recovery import RecoveryPolicy,recoverable,VERSION
from monatise.research.native_futures.information_gate import NativeInformationGate,MODE
from monatise.research.phase9.service import PersistentResearchService,CaptureStep
from monatise.research.phase9.rotation import RotatingSpool,RotationPolicy
from monatise.research.phase9.pipeline import ResearchPipeline
from monatise.research.institutional.models import encode,digest
from tests.research.test_databento_live_preparation import scope,permit,trade,native,system,FakeClient,NOW_NS
from tests.research.phase9.test_pipeline import calendar
from tests.research.phase9.test_options_service import make_plan


def test_documented_count_cursor_preserves_tied_multiplicity_without_capture_clock_equality():
    c=Cursor();h=digest('original')
    for _ in range(2):assert c.accept(NOW_NS,h,index_ns=NOW_NS+1)
    r=Cursor.recover_count(c.snapshot())
    assert not r.accept(NOW_NS-1,digest('older'),index_ns=NOW_NS-1)
    for _ in range(2):assert not r.accept(NOW_NS,digest('other native capture clock'),index_ns=NOW_NS+2)
    assert r.accept(NOW_NS,digest('new legitimate identical event'),index_ns=NOW_NS+2)
    assert len(r.hashes_at_event)==3
    incomplete=Cursor.recover_count(c.snapshot())
    incomplete.accept(NOW_NS,h)
    with pytest.raises(ValueError,match='missing_tied'):incomplete.accept(NOW_NS+1,h)
    with pytest.raises(ValueError,match='prefix_incomplete'):incomplete.finish_recovery()
    with pytest.raises(ValueError,match='overlap_review'):Cursor.recover_count(dict(c.snapshot(),event_order_regressed=True))


@pytest.mark.parametrize('reason,expected',[
 ('connection_stalled_definition',True),('provider_disconnected_trades',True),
 ('provider_disconnect_or_error_mbp-1',True),('provider_error_code_1',False),
 ('provider_error_code_8',False),('local_callback_or_queue_backpressure',False),
 ('independent_clock_review_expired_or_invalid',False),('capture_transport_or_storage_failure',False)])
def test_only_transport_faults_can_reconnect(reason,expected):
    q=dict(reasons=[reason],component_rejections={})
    assert recoverable(dict(quality=q)) is expected
    q['component_rejections']={'trades:41271':['invalid']}
    assert not recoverable(dict(quality=q))


def build(tmp_path,*,fault=None,max_attempts=3):
    s=scope(duration_seconds=5);plan=make_plan(s)
    gates={c.metadata.instrument_id:NativeInformationGate(c) for c in s.contracts}
    calendars={i:calendar(g.contract) for i,g in gates.items()}
    pipeline=ResearchPipeline(gates,calendars,enabled_schemas=s.schemas)
    root=tmp_path/'trial';root.mkdir();clients=[];preparations=[]
    spool=RotatingSpool(root/'spool',policy=RotationPolicy())
    class Client(FakeClient):
        def start(self):
            schema=self.subscription['schema'];cb=self.callbacks[0]
            cb(system(dn.SystemCode.SUBSCRIPTION_ACK))
            if fault=='provider':
                cb(dn.ErrorMsg(ts_event=NOW_NS,err='ENGINEERING',code=dn.ErrorCode.AUTH_FAILED));return
            if fault=='disconnect':self.closed.set();return
            retry=len(clients)>3
            for iid in self.subscription['symbols']:
                product={41271:'GC',10252:'ES',261401:'NQ'}[iid]
                row=native(product) if schema=='definition' else trade(iid) if schema=='trades' else __import__('tests.research.test_databento_live_preparation',fromlist=['book']).book(iid)
                cb(row)
                if schema=='trades':cb(row)  # two legitimate indistinguishable executions
                if retry and schema=='trades':cb(trade(iid,t=NOW_NS-500000000,sequence=2))
            cb(system(dn.SystemCode.REPLAY_COMPLETED))
            if not retry:asyncio.get_running_loop().call_later(.05,self.closed.set)
    def factory(*args):
        assert all(c.terminated for c in clients[:-len(clients)%3 or None]) if len(clients)%3==0 and clients else True
        c=Client();clients.append(c);return c
    def prepare(index,remaining):
        preparations.append(index)
        retry=replace(s,duration_seconds=1)
        return CaptureStep(retry,permit(retry,permit_id='retry-'+str(index)),'RECOVER','ENGINEERING same-scope metadata/clock receipt')
    policy=RecoveryPolicy(maximum_attempts=max_attempts,total_seconds=5)
    service=PersistentResearchService(plan,spool,pipeline,client_factory=factory,clock_ns=lambda:NOW_NS,
        recovery_policy=policy,recovery_prepare=prepare)
    auth=dict(normalization_semantics='native-futures-normalization-v2',quality_mode=MODE,
        capture_clock_semantics='ORIGINAL_UTC_WALL_AND_MONOTONIC_ARRIVAL_V2',plan=encode(plan),recovery_policy=encode(policy))
    (root/'authorization.json').write_text(json.dumps(auth))
    (root/'analysis-inputs.json').write_text(json.dumps(dict(version='phase10-analysis-inputs-v1',
        normalization_semantics=auth['normalization_semantics'],authorization_sha256=digest(auth),
        calendars={str(i):encode(c) for i,c in calendars.items()})))
    result=asyncio.run(service.run(api_key='ENGINEERING',output=root/'capture',permit_ledger=root/'permits.sqlite',evidence_kind='ENGINEERING_SYNTHETIC'))
    (root/'progress.json').write_text(json.dumps(dict(status='COMPLETED_FINITE_NATIVE_INFORMATION_TRIAL',
        health=result['reports'][-1]['quality'],observed_at_ns=NOW_NS,spool_records=spool.count)))
    return root,pipeline,spool,result,clients,preparations


def test_bounded_real_service_reconnect_replay_and_read_only_audit(tmp_path):
    from monatise.research.phase10.source import load_capture
    root,p,spool,result,clients,preparations=build(tmp_path)
    assert result['attempts']==2 and preparations==[1] and len(clients)==6
    assert all(c.terminated for c in clients)
    assert result['reports'][0]['quality']['quarantined']
    assert not result['reports'][1]['quality']['quarantined']
    assert result['reports'][1]['quality']['counts']['replay_duplicates_skipped']==12
    assert len(p.trade_candles[41271].rows)==3  # two originals + one gap execution
    for c in clients[3:]:
        assert c.subscription['start']<NOW_NS
    spool.close()
    reader=load_capture(root,cutoff_ns=NOW_NS)
    assert len(reader.pipeline.trade_candles[41271].rows)==3
    health=reader.source_health(NOW_NS)
    assert health['recovery']['replay_overlap_records_verified']==9
    assert not health['quarantined']


def test_provider_error_no_retry_and_attempt_exhaustion(tmp_path):
    (tmp_path/'provider').mkdir()
    root,p,spool,result,clients,preparations=build(tmp_path/'provider',fault='provider')
    assert result['attempts']==1 and preparations==[]
    spool.close()
    (tmp_path/'exhausted').mkdir()
    root,p,spool,result,clients,preparations=build(tmp_path/'exhausted',fault='disconnect',max_attempts=2)
    assert result['attempts']==2 and preparations==[1] and result['reports'][-1]['quality']['quarantined']
    spool.close()


def test_reader_rejects_forged_overlap_admission(tmp_path):
    import sqlite3,hashlib
    from monatise.research.phase10.source import load_capture
    from monatise.research.phase9.storage import record_metadata_hash
    root,p,spool,result,_,_=build(tmp_path);spool.close()
    path=root/'spool/raw-00000.sqlite';path.chmod(0o600);db=sqlite3.connect(path)
    row=db.execute("SELECT id,delivery,schema,captured,hash,kind,rejection,clock_review,arrival_ns FROM raw WHERE delivery LIKE '%:1:trades:%' AND admitted=0 LIMIT 1").fetchone()
    n,d,s,a,h,k,reject,clock,arrival=row
    with db:db.execute('UPDATE raw SET admitted=1,metadata_hash=? WHERE id=?',(record_metadata_hash(d,s,a,h,k,True,reject,clock,arrival),n))
    db.close()
    index=root/'spool/state.sqlite';index.chmod(0o600);db=sqlite3.connect(index)
    value=json.loads(db.execute("SELECT value FROM states WHERE name='segments'").fetchone()[0]);value[0]['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    with db:db.execute("UPDATE states SET value=?,hash=? WHERE name='segments'",(json.dumps(value),digest(value)))
    db.close()
    with pytest.raises(ValueError,match='admission_mismatch'):load_capture(root,cutoff_ns=NOW_NS)
