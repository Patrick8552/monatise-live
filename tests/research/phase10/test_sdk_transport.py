import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest

from monatise.research.databento.sdk_transport import OwnedSDKClient


class SDK:
    def __init__(self, **kwargs):
        self.owner = threading.get_ident()
        self.loop = kwargs['loop']
        assert asyncio.get_running_loop() is self.loop
        assert kwargs['reconnect_policy'] == 'none'
        self.calls = []
        self.callback = None
        self.closed = self.loop.create_future()
        queue = SimpleNamespace(is_enabled=lambda: False, qsize=lambda: 0)
        self._session = SimpleNamespace(_protocol=None, _transport=None, _dbn_queue=queue)

    def add_callback(self, fn, **kwargs):
        assert threading.get_ident() == self.owner
        self.callback = fn

    def subscribe(self, **kwargs):
        assert threading.get_ident() != self.owner
        # Mirrors the real SDK synchronous wait on its network event loop.
        async def connected():
            self.calls.append('subscribe')
        asyncio.run_coroutine_threadsafe(connected(), self.loop).result(timeout=1)

    def start(self):
        assert threading.get_ident() == self.owner
        self.calls.append('start')
        self.callback('ENGINEERING_RECORD')

    def terminate(self):
        assert threading.get_ident() == self.owner
        self.calls.append('terminate')
        if not self.closed.done():
            self.closed.set_result(None)

    async def wait_for_close(self):
        async def wait():
            await self.closed
        await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(wait(), self.loop))


def test_lifecycle_ownership_subscription_and_full_owned_cleanup():
    client = OwnedSDKClient('ENGINEERING_ONLY', 5, builder=SDK)
    rows = []
    try:
        client.add_callback(rows.append)
        client.subscribe(schema='trades')
        client.start()
        assert rows == ['ENGINEERING_RECORD']
        assert client.diagnostics()['network_loop_responsive']
        client.terminate()
        asyncio.run(client.wait_for_close())
    finally:
        client.close()
    assert not client._thread.is_alive()
    with pytest.raises(ValueError, match='closed_owned'):
        client.start()


def test_one_stuck_network_loop_does_not_stop_another_and_probe_is_bounded():
    first = OwnedSDKClient('ENGINEERING_ONLY', 5, builder=SDK)
    second = OwnedSDKClient('ENGINEERING_ONLY', 5, builder=SDK)
    entered, release = threading.Event(), threading.Event()
    def block():
        entered.set()
        release.wait(2)
    first._loop.call_soon_threadsafe(block)
    assert entered.wait(1)
    try:
        begin = time.monotonic()
        assert first.diagnostics()['network_loop_responsive'] is False
        assert time.monotonic()-begin < 1
        rows = []
        second.add_callback(rows.append)
        second.subscribe(schema='definition')
        second.start()
        assert rows == ['ENGINEERING_RECORD']
        assert first._loop is not second._loop
        assert first._thread is not second._thread
    finally:
        release.set()
        first.close()
        second.close()


def test_exception_context_never_exposes_credentials_or_licensed_payload():
    client = OwnedSDKClient('ENGINEERING_SECRET', 5, builder=SDK)
    try:
        client._call(lambda: client._loop.call_exception_handler({
            'exception': RuntimeError('ENGINEERING_SECRET LICENSED_PRICE'),
            'message': 'ENGINEERING_SECRET', 'task': 'LICENSED_PRICE'}))
        diag = client.diagnostics()
        assert diag['loop_errors'][0]['error_type'] == 'RuntimeError'
        assert 'ENGINEERING_SECRET' not in json.dumps(diag)
        assert 'LICENSED_PRICE' not in json.dumps(diag)
    finally:
        client.close()


def test_builder_failure_does_not_leave_an_owned_network_thread():
    before = set(threading.enumerate())
    def fail(**kwargs):
        raise RuntimeError('ENGINEERING_FAILURE')
    with pytest.raises(RuntimeError, match='ENGINEERING_FAILURE'):
        OwnedSDKClient('ENGINEERING_ONLY', 5, builder=fail)
    assert not [t for t in set(threading.enumerate())-before if t.name == 'monatise-databento-network']


def test_SDK_timeout_cleanup_cannot_orphan_owned_transport():
    class Transport:
        aborted = False
        def abort(self):
            self.aborted = True
    class TimeoutSDK(SDK):
        def subscribe(self, **kwargs):
            super().subscribe(**kwargs)
            self._session._transport = Transport()
        async def wait_for_close(self):
            # Real pinned LiveSession.wait_for_close finally clears this reference.
            self._session._transport = None
            raise RuntimeError('ENGINEERING_PRIVATE_ERROR')
    client = OwnedSDKClient('ENGINEERING_ONLY', 5, builder=TimeoutSDK)
    client.subscribe(schema='trades')
    transport = client._transport
    with pytest.raises(RuntimeError, match='ENGINEERING_PRIVATE_ERROR'):
        asyncio.run(client.wait_for_close())
    client.close()
    assert transport.aborted
    assert not client._thread.is_alive()


def test_actual_pinned_SDK_start_violates_asyncio_ownership_on_legacy_thread():
    # Real pinned SDK + real debug asyncio loop, no network or credentials.
    from databento.live.session import LiveSession
    client = OwnedSDKClient('ENGINEERING_ONLY', 5, builder=SDK)
    session = object.__new__(LiveSession)
    session._lock = threading.RLock()
    session._loop = client._loop
    session._heartbeat_monitor_task = None
    def prepare():
        client._loop.set_debug(True)
        session._protocol = SimpleNamespace(start=lambda: None,
            disconnected=client._loop.create_future(), _last_msg_loop_time=client._loop.time())
    client._call(prepare)
    session._heartbeat_interval_s = 5
    try:
        with pytest.warns(RuntimeWarning, match='never awaited'):
            with pytest.raises(RuntimeError, match='Non-thread-safe operation'):
                session.start()
        # The same SDK method succeeds when marshalled to its network loop.
        client._call(session.start)
        assert session._heartbeat_monitor_task.get_loop() is client._loop
    finally:
        client.close()


def test_owned_transport_capture_end_to_end_seals_and_releases_all_loops(tmp_path):
    from monatise.research.databento.live_feed import CMELiveCapture
    from tests.research.test_databento_live_preparation import scope, permit, FakeClient, NOW_NS
    class WireSDK(SDK):
        def add_callback(self, fn, **kwargs):
            super().add_callback(fn, **kwargs)
            self.callbacks = [fn]
        def subscribe(self, **kwargs):
            super().subscribe(**kwargs)
            self.subscription = kwargs
        def start(self):
            assert threading.get_ident() == self.owner
            self.fault = None
            FakeClient.start(self)
    clients = []
    def factory(key, heartbeat):
        client = OwnedSDKClient(key, heartbeat, builder=WireSDK)
        clients.append(client)
        return client
    s = scope(duration_seconds=1)
    report = asyncio.run(CMELiveCapture(s, client_factory=factory, clock_ns=lambda: NOW_NS).run(
        api_key='ENGINEERING_ONLY', permit=permit(s), permit_ledger=tmp_path/'permits.sqlite',
        output=tmp_path/'capture', evidence_kind='ENGINEERING_SYNTHETIC'))
    assert not report['quality']['quarantined']
    assert report['automatic_retries'] == 0
    assert all(not c._thread.is_alive() for c in clients)
    assert set(report['delivery_diagnostics']['client_transports']) == set(s.schemas)
    assert all(d['isolated_network_loop'] for d in report['delivery_diagnostics']['client_transports'].values())


def test_replay_burst_within_handoff_capacity_is_lossless_and_all_subscribe_first(tmp_path):
    import databento_dbn as dn
    from monatise.research.databento.live_feed import CMELiveCapture
    from tests.research.test_databento_live_preparation import scope, permit, FakeClient, NOW_NS, system
    order=[]
    class ReplaySDK(SDK):
        def add_callback(self, fn, **kwargs):
            super().add_callback(fn, **kwargs)
            self.callbacks=[fn]
        def subscribe(self, **kwargs):
            super().subscribe(**kwargs)
            self.subscription=kwargs;order.append('subscribe')
        def start(self):
            assert order.count('subscribe')==3
            order.append('start')
            def produce():
                self.fault=None;FakeClient.start(self)
                if self.subscription['schema']=='trades':
                    for _ in range(512):self.callback(system(dn.SystemCode.HEARTBEAT))
            # Actual SDK start schedules streaming; data arrives independently.
            self.loop.call_soon(produce)
    clients=[]
    def factory(key, heartbeat):
        client=OwnedSDKClient(key,heartbeat,builder=ReplaySDK);clients.append(client);return client
    s=scope(duration_seconds=1)
    report=asyncio.run(CMELiveCapture(s,client_factory=factory,clock_ns=lambda:NOW_NS,queue_capacity=1024).run(
        api_key='ENGINEERING_ONLY',permit=permit(s),permit_ledger=tmp_path/'permits.sqlite',
        output=tmp_path/'capture',evidence_kind='ENGINEERING_SYNTHETIC'))
    assert not report['quality']['quarantined']
    assert report['journals']['trades']['record_count']==517
    assert report['delivery_diagnostics']['max_queue_depth']<=1024
    assert all(not c._thread.is_alive() for c in clients)
