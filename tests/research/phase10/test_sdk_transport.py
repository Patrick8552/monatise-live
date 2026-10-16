import asyncio,ast,inspect,json,threading,time
import pytest
from monatise.research.databento.sdk_transport import OwnedSDKClient

class SDK:
    """Public SDK surface only; private session access cannot work here."""
    def __init__(self,**kwargs):
        self.owner=threading.get_ident();self.loop=kwargs['loop']
        assert asyncio.get_running_loop() is self.loop
        assert kwargs['reconnect_policy']=='none' and kwargs['slow_reader_behavior']=='warn'
        self.ready=asyncio.Event();self.rows=[];self.terminated=False
    def subscribe(self,**kwargs):
        assert threading.get_ident()!=self.owner
        self.subscription=kwargs
        asyncio.run_coroutine_threadsafe(asyncio.sleep(0),self.loop).result(1)
    def __aiter__(self):
        assert threading.get_ident()==self.owner
        return self
    async def __anext__(self):
        if self.rows:return self.rows.pop(0)
        await self.ready.wait()
        raise StopAsyncIteration
    def terminate(self):
        assert threading.get_ident()==self.owner
        self.terminated=True;self.ready.set()

def test_public_iterator_lifecycle_and_complete_owned_cleanup():
    client=OwnedSDKClient('ENGINEERING_ONLY',5,builder=SDK);rows=[]
    try:
        client.add_callback(rows.append);client.subscribe(schema='trades')
        client._call(lambda:client._client.rows.extend(['ENGINEERING_RECORD']));client.start()
        until=time.monotonic()+2
        while not rows and time.monotonic()<until:time.sleep(.01)
        assert rows==['ENGINEERING_RECORD']
        d=client.diagnostics();assert d['network_loop_responsive'] and d['streaming_method']=='Live.__aiter__'
        assert d['sdk_private_instrumentation'] is False
        client.terminate();asyncio.run(client.wait_for_close())
    finally:client.close()
    assert not client._thread.is_alive()
    with pytest.raises(ValueError,match='closed_owned'):client.start()

def test_backpressure_consumer_wait_never_blocks_sdk_network_loop():
    client=OwnedSDKClient('ENGINEERING_ONLY',5,builder=SDK);entered=threading.Event();release=threading.Event()
    def slow(record):entered.set();release.wait(2)
    try:
        client.add_callback(slow);client.subscribe(schema='trades')
        client._call(lambda:client._client.rows.extend(range(3000)));client.start();assert entered.wait(1)
        assert client.diagnostics()['network_loop_responsive']
        assert len(client._client.rows)==2999
    finally:release.set();client.close()

def test_one_stuck_loop_has_bounded_probe_and_does_not_stop_another():
    first=OwnedSDKClient('ENGINEERING_ONLY',5,builder=SDK);second=OwnedSDKClient('ENGINEERING_ONLY',5,builder=SDK)
    entered,release=threading.Event(),threading.Event()
    first._loop.call_soon_threadsafe(lambda:(entered.set(),release.wait(2)));assert entered.wait(1)
    try:
        begin=time.monotonic();assert not first.diagnostics()['network_loop_responsive']
        assert time.monotonic()-begin<1 and second.diagnostics()['network_loop_responsive']
    finally:release.set();first.close();second.close()

def test_iteration_fault_visible_without_secret_exception_text_or_retry():
    class Broken(SDK):
        async def __anext__(self):raise RuntimeError('ENGINEERING_SECRET LICENSED_PRICE')
    client=OwnedSDKClient('ENGINEERING_SECRET',5,builder=Broken)
    try:
        client.subscribe(schema='trades');client.start()
        with pytest.raises(RuntimeError):asyncio.run(client.wait_for_close())
        d=client.diagnostics();assert d['loop_errors'][0]['stage']=='public_async_iteration'
        assert 'ENGINEERING_SECRET' not in json.dumps(d) and 'LICENSED_PRICE' not in json.dumps(d)
    finally:client.close()

def test_builder_failure_leaves_no_network_thread():
    before=set(threading.enumerate())
    def fail(**kwargs):raise RuntimeError('ENGINEERING_FAILURE')
    with pytest.raises(RuntimeError):OwnedSDKClient('ENGINEERING_ONLY',5,builder=fail)
    assert not [t for t in set(threading.enumerate())-before if t.name=='monatise-databento-network']

def test_no_private_SDK_attributes_or_transport_hooks_in_implementation():
    tree=ast.parse(inspect.getsource(__import__('monatise.research.databento.sdk_transport',fromlist=['x'])))
    banned={'_session','_protocol','_transport','_dbn_queue','get_buffer','buffer_updated','pause_reading','resume_reading'}
    assert not {n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute)} & banned

def test_large_replay_uses_bounded_public_iterator_handoff_and_seals(tmp_path):
    import databento_dbn as dn
    from monatise.research.databento.live_feed import CMELiveCapture
    from tests.research.test_databento_live_preparation import scope,permit,FakeClient,NOW_NS,system
    order=[]
    class ReplaySDK(SDK):
        def subscribe(self,**kwargs):super().subscribe(**kwargs);order.append('subscribe')
        def __aiter__(self):
            assert order.count('subscribe')==3
            wire=FakeClient();wire.subscription=self.subscription;wire.callbacks=[self.rows.append];wire.start()
            if self.subscription['schema']=='trades':self.rows.extend(system(dn.SystemCode.HEARTBEAT) for _ in range(3000))
            return super().__aiter__()
    clients=[]
    def factory(key,heartbeat):
        c=OwnedSDKClient(key,heartbeat,builder=ReplaySDK);clients.append(c);return c
    s=scope(duration_seconds=2)
    r=asyncio.run(CMELiveCapture(s,client_factory=factory,clock_ns=lambda:NOW_NS,queue_capacity=32).run(
        api_key='ENGINEERING_ONLY',permit=permit(s),permit_ledger=tmp_path/'permits.sqlite',output=tmp_path/'capture',evidence_kind='ENGINEERING_SYNTHETIC'))
    assert not r['quality']['quarantined'],r['quality']['reasons']
    assert r['journals']['trades']['record_count']==3005
    assert r['delivery_diagnostics']['max_queue_depth']<=32 and r['delivery_diagnostics']['unretained_overflow_records']==0
    assert all(not c._thread.is_alive() for c in clients)
