import asyncio,json
from monatise.research.databento.live_feed import CMELiveCapture
from tests.research.test_databento_live_preparation import FakeClient,scope,permit,NOW_NS


def test_transport_failure_records_type_without_leaking_exception_message_or_retrying(tmp_path):
    clients=[]
    class Failed(FakeClient):
        async def wait_for_close(self):
            if self.subscription['schema']=='trades':raise ConnectionResetError(54,'PRIVATE_KEY_AND_MARKET_PAYLOAD_MUST_NOT_APPEAR')
            await self.closed.wait()
    def factory(*args):
        client=Failed();clients.append(client);return client
    s=scope(duration_seconds=1)
    report=asyncio.run(CMELiveCapture(s,client_factory=factory,clock_ns=lambda:NOW_NS).run(api_key='ENGINEERING_ONLY',permit=permit(s),permit_ledger=tmp_path/'ledger',output=tmp_path/'capture',evidence_kind='ENGINEERING_SYNTHETIC'))
    assert report['quality']['quarantined'] and report['automatic_retries']==0
    assert report['transport_events']==[dict(schema='trades',stage='wait_for_close',observed_at_ns=NOW_NS,error_type='ConnectionResetError',errno=54)]
    assert 'PRIVATE_KEY' not in json.dumps(report)
    assert all(c.terminated for c in clients)
