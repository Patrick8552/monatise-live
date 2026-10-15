import asyncio
import databento_dbn as dn
from monatise.research.databento.live_feed import CMELiveCapture
from tests.research.test_databento_live_preparation import scope,permit,FakeClient,system,NOW_NS


def test_stall_reason_survives_fresh_queued_heartbeats_during_final_drain(tmp_path):
    s=scope(duration_seconds=3);clients=[];clock=[NOW_NS];triggered=[False]
    def factory(*args):
        client=FakeClient();clients.append(client);return client
    def tick(state,now):
        if state.completed==set(s.schemas) and not triggered[0]:
            triggered[0]=True;clock[0]+=16*10**9
            # Callbacks are fresh but their queued records have not been processed.
            # The unchanged liveness guard must stop, and draining cannot clear it.
            for client in clients:client.callbacks[0](system(dn.SystemCode.HEARTBEAT))
    report=asyncio.run(CMELiveCapture(s,client_factory=factory,clock_ns=lambda:clock[0]).run(
        api_key='ENGINEERING_ONLY',permit=permit(s),permit_ledger=tmp_path/'permit.sqlite',
        output=tmp_path/'capture',evidence_kind='ENGINEERING_SYNTHETIC',tick_sink=tick))
    assert triggered[0] and all(c.terminated for c in clients)
    assert report['quality']['quarantined']
    assert any(r.startswith('connection_stalled_') for r in report['quality']['reasons'])
    diag=report['delivery_diagnostics'];assert diag['stop_evidence']['stalled_connections']
    assert diag['thresholds_unchanged'] and report['automatic_retries']==0
    assert set(diag['last_callback_capture_ns'])==set(s.schemas)
    assert not report['execution_eligible']
