import asyncio
from types import SimpleNamespace
from monatise.application.scan_audit import RUNS, audited_scan, stamp_analysis
from tests.test_ftmo_master import Store


def test_failed_market_data_is_durable_degraded_run_with_correlation_and_no_secrets():
    class Runtime:
        document_store=Store()
        @audited_scan('stocks')
        async def scan(self):
            row=stamp_analysis({'ftmo_symbol':'AAPL','decision':'INSUFFICIENT_MARKET_DATA',
                'pipeline_stage':'DATA_REJECTED','reasons':['provider_incomplete'],
                'ftmo_execution_quote':{'status':'not_requested','account_id':'PRIVATE'}},'AAPL')
            return {'analysis_completed_count':0,'analysis_failure_count':1,'results':[row]}
    async def run():
        runtime=Runtime(); result=await runtime.scan()
        record=(await runtime.document_store.list_namespace(RUNS))[0].value
        assert result['pipeline_status']=='degraded' and record['status']=='degraded'
        assert record['instruments'][0]['scanner_run_id']==record['run_id']
        assert record['instruments'][0]['analysis_id']
        assert 'PRIVATE' not in str(record)
        assert record['summary']['analysis_completed_count']==0
    asyncio.run(run())


def test_valid_no_trade_and_failed_run_are_distinguished():
    class Runtime:
        def __init__(self): self.document_store=Store()
        @audited_scan('futures_indices')
        async def scan(self,failed=False):
            if failed: raise TimeoutError('secret must not be logged')
            return {'analysis_completed_count':2,'qualified_count':0,'results':[
                stamp_analysis({'ftmo_symbol':s,'decision':'NO_TRADE','pipeline_stage':'REJECTED',
                                'reasons':['awaiting_confirmation']},s) for s in ['US100.cash','US500.cash']]}
    async def run():
        runtime=Runtime(); result=await runtime.scan()
        assert result['pipeline_status']=='healthy'
        try: await runtime.scan(True)
        except TimeoutError: pass
        records=await runtime.document_store.list_namespace(RUNS)
        assert {r.value['status'] for r in records}=={'healthy','failed'}
        assert 'secret' not in str(records)
    asyncio.run(run())


def test_crypto_publication_failure_keeps_trigger_identity_and_is_degraded():
    class Runtime:
        document_store=Store()
        @audited_scan('crypto')
        async def scan(self):
            return {'results':[stamp_analysis({'symbol':'BTC','publication_id':'trigger-1',
                'trigger_state':'confirmed','telegram_publication_failed':True},'BTCUSD')]}
    async def run():
        runtime=Runtime();result=await runtime.scan()
        assert result['pipeline_status']=='degraded'
        trace=(await runtime.document_store.list_namespace(RUNS))[0].value['instruments'][0]
        assert trace['symbol']=='BTC' and trace['publication_id']=='trigger-1'
        assert trace['trigger_state']=='confirmed'
    asyncio.run(run())


def test_risk_rejection_diagnostics_are_specific_without_arbitrary_exception_text():
    from monatise.application.hierarchy.evaluator import risk_rejection_code
    assert risk_rejection_code(ValueError('insufficient target evidence')) == 'insufficient_target_evidence'
    assert risk_rejection_code(ValueError('stop and target are inconsistent with direction')) == 'invalid_stop_target_geometry'
    assert risk_rejection_code(ValueError('insufficient TP1 reward/risk; cannot skip first objective')) == 'tp1_reward_risk_below_minimum'
    assert risk_rejection_code(ValueError('PRIVATE SECRET')) == 'ValueError'
