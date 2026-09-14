import asyncio
from datetime import timedelta
import pytest
from monatise.adapters.flashalpha import FlashAlphaAdapterError
from monatise.application.market_intelligence import validate_flashalpha_context, StockMarketIntelligenceCoordinator
from monatise.application.provider_evidence import EvidenceValidationError, flashalpha_diagnostics
from monatise.application.ftmo_registry import FTMO_REGISTRY
from monatise.application.scan_audit import analysis_trace
from monatise.application.ftmo_scanner import publication_allowed
from tests.test_market_intelligence import NOW, FlashAlpha, Alpaca, Quiver, Finnhub


def context():
    value=FlashAlpha().context('SNOW')
    value['gamma_flip_status']='available'
    value['provider_evidence']={name:{'symbol':'SNOW','as_of':value['as_of'],
        'gamma_flip_status':'available','http_status':200,'attempts':1,'http_statuses':[200],
        'data_as_of':{'equity_feed':value['as_of'],'equity_options_feed':value['as_of']}}
        for name in ('gex','levels')}
    return value


@pytest.mark.parametrize('status',['no_boundary','sensitive_root','uncertain_root_path',
    'insufficient_quote_quality','quality_budget','unrecognized PRIVATE',None])
def test_uncertified_numeric_or_null_gamma_is_never_accepted(status):
    value=context();value['gamma_flip_status']=status
    with pytest.raises(EvidenceValidationError) as caught:
        validate_flashalpha_context(value,provider_symbol='SNOW',now=NOW,maximum_age=timedelta(hours=1))
    diag=flashalpha_diagnostics(value,caught.value)
    assert diag['failure']['field']=='gamma_flip'
    assert diag['failure']['endpoint']=='levels'
    assert 'PRIVATE' not in str(diag) and 'PRIVATE' not in str(caught.value)


@pytest.mark.parametrize('mutation,field,issue',[
    ('identity','symbol','identity_mismatch'),('stale_response','as_of','stale'),
    ('stale_feed','data_as_of.equity_options_feed','stale'),
    ('future_feed','data_as_of.equity_options_feed','future'),
    ('malformed_feed','data_as_of.equity_options_feed','missing_or_malformed')])
def test_fresh_levels_cannot_hide_invalid_gex_source(mutation,field,issue):
    value=context();raw=value['provider_evidence']['gex']
    if mutation=='identity':raw['symbol']='MSFT'
    if mutation=='stale_response':raw['as_of']=(NOW-timedelta(hours=2)).isoformat()
    if mutation=='stale_feed':raw['data_as_of']['equity_options_feed']=(NOW-timedelta(hours=2)).isoformat()
    if mutation=='future_feed':raw['data_as_of']['equity_options_feed']=(NOW+timedelta(seconds=1)).isoformat()
    if mutation=='malformed_feed':raw['data_as_of']['equity_options_feed']='PRIVATE'
    with pytest.raises(EvidenceValidationError) as caught:
        validate_flashalpha_context(value,provider_symbol='SNOW',now=NOW,maximum_age=timedelta(hours=1))
    diag=flashalpha_diagnostics(value,caught.value)
    assert diag['failure']=={'field':field,'issue':issue,'endpoint':'gex'}
    assert 'PRIVATE' not in str(diag)


def test_snow_rejection_has_durable_provider_field_and_no_candle_or_order_fallback():
    class Provider:
        def context(self,symbol):
            result=context();result.update(gamma_flip=None,gamma_flip_status='no_boundary');return result
    alpaca=Alpaca()
    result=asyncio.run(StockMarketIntelligenceCoordinator(alpaca,Quiver(),Finnhub(),Provider(),environment={})
        .analyse('SNOW',instrument=FTMO_REGISTRY.resolve('SNOW'),now=NOW))
    assert result['decision']=='INSUFFICIENT_MARKET_DATA' and not publication_allowed(result)
    assert result['reason_detail']=='provider_incomplete: flashalpha gamma_flip unavailable (no_boundary)'
    assert result['ftmo_execution_quote']['status']=='not_requested'
    assert alpaca.calls==[]
    trace=analysis_trace(result)
    assert trace['provider_diagnostics']['failure']['issue']=='no_boundary'


def test_transport_failure_preserves_provider_http_and_attempts_without_message():
    error=FlashAlphaAdapterError('PRIVATE URL TOKEN',status_code=429,code='rate_limited')
    error.attempts=3;error.endpoint='levels'
    result=asyncio.run(StockMarketIntelligenceCoordinator(Alpaca(),Quiver(),Finnhub(),
        FlashAlpha(failure=error),environment={}).analyse('SNOW',instrument=FTMO_REGISTRY.resolve('SNOW'),now=NOW))
    assert result['provider_diagnostics']['failure']=={
        'issue':'provider_request_failed','http_status':429,'attempts':3,'endpoint':'levels'}
    assert 'PRIVATE' not in str(analysis_trace(result))


def test_valid_certified_context_passes_unchanged():
    value=context()
    assert validate_flashalpha_context(value,provider_symbol='SNOW',now=NOW,maximum_age=timedelta(hours=1))
