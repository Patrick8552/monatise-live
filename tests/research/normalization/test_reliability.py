"""Offline deterministic bursts, overload accounting and actual SDK probes."""
import asyncio,json,threading,time
from types import SimpleNamespace
import databento_dbn as dbn
import pytest
from monatise.research.databento.sdk_transport import OwnedSDKClient
from monatise.research.databento.live_feed import CMELiveCapture
from monatise.research.databento.live_journal import verify
from monatise.research.phase9.storage import DurableSpool
from tests.research.phase10.test_sdk_transport import SDK
from tests.research.test_databento_live_preparation import FakeClient,scope,permit,system,NOW_NS


def test_public_wrapper_does_not_rewrite_actual_sdk_protocol_buffers():
    from databento.live.protocol import DatabentoLiveProtocol
    client=OwnedSDKClient('ENGINEERING_ONLY',5,builder=SDK)
    try:
        def prepare():
            protocol=DatabentoLiveProtocol(api_key='ENGINEERING_ONLY',dataset='GLBX.MDP3')
            protocol._authenticated.set_result('ENGINEERING_ONLY')
            received=[];protocol._process_dbn=received.append
            return protocol,received
        protocol,received=client._call(prepare)
        original=protocol.get_buffer.__func__
        client.subscribe(schema='trades')
        def feed():
            assert protocol.get_buffer.__func__ is original
            view=protocol.get_buffer(65536);assert len(view)==65536
            view[:3]=b'abc';protocol.buffer_updated(3)
            assert received==[b'abc']
        client._call(feed)
        assert client.diagnostics()['sdk_private_instrumentation'] is False
    finally:client.close()


def test_nonblocking_callback_overload_is_counted_quarantined_and_never_retried(tmp_path):
    class Overload(FakeClient):
        def start(self):
            for _ in range(100):self.callbacks[0](system(dbn.SystemCode.HEARTBEAT))
    s=scope(schemas=('definition','trades'),duration_seconds=1)
    report=asyncio.run(CMELiveCapture(s,client_factory=lambda *a:Overload(),clock_ns=lambda:NOW_NS,queue_capacity=8).run(
        api_key='ENGINEERING_ONLY',permit=permit(s),permit_ledger=tmp_path/'permit',output=tmp_path/'capture',evidence_kind='ENGINEERING_SYNTHETIC'))
    diag=report['delivery_diagnostics']
    assert diag['unretained_overflow_records']==192 and sum(j['record_count'] for j in report['journals'].values())==8
    assert sum(diag['callback_counts'].values())==200
    assert report['quality']['quarantined'] and 'local_callback_or_queue_backpressure' in report['quality']['reasons']
    assert report['automatic_retries']==0 and not diag['callback_queue_waiting']
    assert diag['latency_distributions']['callback_execution']['count']==200
    assert diag['unretained_overflow_hash_chain']


def test_controlled_peak_burst_uses_public_iteration_and_durably_preserves_every_record(tmp_path):
    from tests.research.test_databento_live_preparation import trade
    from tests.research.phase9.test_pipeline import gate,calendar
    from monatise.research.phase9.pipeline import ResearchPipeline
    order=[];clients=[]
    class BurstSDK(SDK):
        def subscribe(self,**kwargs):
            super().subscribe(**kwargs);order.append('subscribe')
        def __aiter__(self):
            assert order.count('subscribe')==3
            wire=FakeClient();wire.subscription=self.subscription;wire.callbacks=[self.rows.append];wire.start()
            if self.subscription['schema']=='trades':
                self.rows.extend(trade(s.contracts[n%3].metadata.instrument_id,t=NOW_NS-10**9+n*1000,sequence=n+10) for n in range(1000))
            return super().__aiter__()
    def factory(key,heartbeat):
        client=OwnedSDKClient(key,heartbeat,builder=BurstSDK);clients.append(client);return client
    s=scope(duration_seconds=3);spool=DurableSpool(tmp_path/'spool.sqlite')
    pipeline=ResearchPipeline({c.metadata.instrument_id:gate(c) for c in s.contracts},
        {c.metadata.instrument_id:calendar(c) for c in s.contracts},enabled_schemas=s.schemas)
    begun=time.monotonic()
    def sink(schema,row,captured,ordinal,normalized):
        admitted=normalized is not None and schema!='definition'
        position,sha,_=spool.append(schema,row,capture_ns=captured,delivery_id=schema+':'+str(ordinal),evidence_kind='ENGINEERING_SYNTHETIC',admitted=admitted)
        if admitted:
            result=pipeline.ingest(row,schema=schema,archive_sha256=sha,ordinal=position,capture_ns=captured,admission_ns=captured,evidence_kind='ENGINEERING_SYNTHETIC')
            assert result['accepted']
    report=asyncio.run(CMELiveCapture(s,client_factory=factory,clock_ns=lambda:NOW_NS,queue_capacity=64).run(
        api_key='ENGINEERING_ONLY',permit=permit(s),permit_ledger=tmp_path/'permit',output=tmp_path/'capture',evidence_kind='ENGINEERING_SYNTHETIC',record_sink=sink,
        checkpoint_sink=lambda c:spool.checkpoint('cursor',dict(cursors=c,records=spool.count))))
    assert not report['quality']['quarantined']
    assert report['journals']['trades']['record_count']==1005
    assert report['delivery_diagnostics']['unretained_overflow_records']==0
    actual=sum(v['record_count'] for v in report['journals'].values())
    assert actual==spool.count==sum(report['delivery_diagnostics']['callback_counts'].values())
    assert sum(len([v for v in g.accepted if v.schema=='trades']) for g in pipeline.gates.values())==1003
    assert all(not g.faults for g in pipeline.gates.values())
    assert spool.load('cursor')['records']==actual
    for schema in s.schemas:assert len(verify(tmp_path/'capture'/schema)[1])==report['journals'][schema]['record_count']
    metrics=report['delivery_diagnostics']['latency_distributions']
    assert all(k in metrics for k in ('callback_execution','queue_insertion','queue_residence','consumer_processing','journal_write','journal_synchronization','record_sink','checkpoint','end_to_end_ingestion'))
    assert report['delivery_diagnostics']['max_queue_depth']<=64 and all(not c._thread.is_alive() for c in clients)
    (tmp_path/'benchmark.json').write_text(json.dumps(dict(seconds=time.monotonic()-begun,records=actual,metrics=metrics,queue=report['delivery_diagnostics']['max_queue_depth'])))
    spool.close();again=DurableSpool(tmp_path/'spool.sqlite');assert again.count==actual and again.load('cursor')['records']==actual;again.close()


def test_journal_failure_cannot_advance_durable_cursor(tmp_path):
    class FailedJournal:
        def __init__(self,*a,**kw):pass
        def append(self,*a,**kw):raise OSError('ENGINEERING_DISK_FAILURE')
        def close(self,**kw):return {'record_count':0}
    advanced=[];s=scope(duration_seconds=1)
    report=asyncio.run(CMELiveCapture(s,client_factory=lambda *a:FakeClient(),clock_ns=lambda:NOW_NS,journal_factory=FailedJournal).run(
        api_key='ENGINEERING_ONLY',permit=permit(s),permit_ledger=tmp_path/'permit',output=tmp_path/'capture',evidence_kind='ENGINEERING_SYNTHETIC',checkpoint_sink=advanced.append))
    assert not advanced and report['quality']['quarantined'] and report['failure_type']=='OSError'
