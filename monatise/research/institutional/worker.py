"""Fixed-input offline acceptance examples and authentic captured-window processing."""
from dataclasses import asdict
from decimal import Decimal
import json

from . import VERSION, SAFETY
from .models import digest, encode
from .fixtures import NOW_NS, contract, quote, candle_evidence, positioning, ENABLED
from .signals import broker_preview, crypto_preview, preview
from .mapping import ContextMapper, MappingPolicy, BrokerQuote
from .options import OptionConvention, RateAssumption, analyze, unsigned_european_sensitivity
from .native import process_gc, START_NS, END_NS


def mapping_fixture():
    c=contract()
    mapper=ContextMapper(contract=c,broker_instrument='XAU/USD',policy=MappingPolicy('ENGINEERING_GOLD_POLICY'))
    for i in range(5):
        t=NOW_NS-(5-i)*10**9
        q=quote(c,receive_ns=t,ordinal=i)
        broker=BrokerQuote('XAU/USD','ENGINEERING_FIXTURE','USD',Decimal('2518'),Decimal('2518.2'),
            t,t,t+1,digest(dict(broker='ENGINEERING_SYNTHETIC',ordinal=i)), 'ENGINEERING_SYNTHETIC',c.price_unit)
        mapper.add(q,broker,now_ns=NOW_NS,session_start_ns=NOW_NS-3600*10**9,
                   session_end_ns=NOW_NS+3600*10**9,session_reference='ENGINEERING_SYNTHETIC_SESSION')
    return mapper.estimate(now_ns=NOW_NS,futures_level='2520')


def options_fixture():
    from monatise.application.gold_options import american_futures
    from monatise.research.databento.options import OpenInterest
    parent, option=contract(),contract(option=True)
    premium=Decimal(str(american_futures(2519.1,2500,30/365,.04,.2,'C'))).quantize(Decimal('.1'))
    q=quote(option,bid=premium-Decimal('.1'),ask=premium+Decimal('.1'))
    u=quote(parent)
    oi=OpenInterest(1,option.metadata.instrument_id,123,NOW_NS-86400*10**9,
                    NOW_NS-3600*10**9,NOW_NS-3600*10**9,digest('ENGINEERING_OI'))
    return analyze(option=q,underlying=u,
        convention=OptionConvention('OG','American',option.metadata.definition_sha256,'ENGINEERING_STANDARD_OG_REVIEW'),
        rate=RateAssumption(.04,NOW_NS-3600*10**9,digest('ENGINEERING_RATE'),'constant annual rate fixture','ENGINEERING_SYNTHETIC'),
        cutoff_ns=NOW_NS,open_interest=oi)


def acquisition_proposals():
    """Candidates are unverified symbols, not exact ID claims or submitted requests."""
    return dict(acquisition_enabled=False,numeric_credit_only_ceiling=None,cash_authorized=False,
        provider_estimates=None,credit_balance=None,current_entitlement='UNVERIFIED',
        requests=[dict(dataset='GLBX.MDP3',schema='definition',candidate_raw_symbol=p+'Z6',
            publisher_id=None,instrument_id=None,start_ns=1791158400*10**9,end_ns=1791158460*10**9,
            identity_status='UNVERIFIED_CANDIDATE_NEVER_SUBMITTED',maximum_records=1000,maximum_wire_bytes=2*1024**2,
            cache_status='NO_ACCEPTED_LOCAL_EXACT_DEFINITION',
            subsequent_sample=dict(schemas=['ohlcv-1m','trades','mbp-1','status'],start_ns=START_NS,end_ns=END_NS,
                contract_identity='ONLY_AFTER_NATIVE_DEFINITION_AND_METADATA_REVIEW',
                cache_overlap_plan='REQUIRED_ON_RESOLVED_HistoricalRequest',
                quote_and_receipt='REQUIRED_BEFORE_EACH_NEW_ACQUISITION')) for p in ('ES','NQ')],
        approval_required=['separately_confirmed_numeric_credit_only_ceiling','fresh_account_credit_and_entitlement_review',
            'reliable_exact_scope_provider_quote','reviewed_request_specific_one_use_receipt','residual_uncapped_exposure_review'],
        limitations=['Definition discovery precedes exact-ID sample requests; no root or guessed ID is submitted.',
                     'No options, depth, secondary asset or live subscription requested.'],**SAFETY)


def main(request, output_file, *, repository, loop):
    if request.get('schema') != VERSION or digest({k:v for k,v in request.items() if k!='input_sha256'}) != request.get('input_sha256'):
        raise ValueError('source_bound_input_hash_required')
    from .runner import source_hashes
    if request.get('source_hashes') != source_hashes(repository):
        raise ValueError('institutional_worker_source_hash_mismatch')
    native=process_gc(data_root=request['data_root'],prepared_file=request['prepared_file'],repository=repository) if request.get('data_root') else None
    genuine={}
    for asset,instrument in (('GC','XAU/USD'),('ES','US500.cash'),('NQ','US100.cash')):
        genuine[asset]=encode(loop.run_until_complete(broker_preview(asset=asset,instrument=instrument,now_ns=END_NS,
            institutional_instrument='GCZ6' if asset=='GC' and native else None)))
        genuine[asset]['authentic_institutional_data_status']='CAPTURED_NATIVE' if asset=='GC' and native else 'UNAVAILABLE'
        genuine[asset]['institutional_evidence_provenance']=[native['normalized_sha256']] if asset=='GC' and native else []
        genuine[asset]['institutional_context_used_for_scoring']=False
    genuine['BTC']=encode(crypto_preview(asset='BTC',now_ns=END_NS))
    engineering={}
    for asset in ('GC','ES','NQ'):
        evidence=candle_evidence(asset)
        engineering[asset]=encode(loop.run_until_complete(broker_preview(asset=asset,instrument=evidence.instrument,
            now_ns=NOW_NS,evidence=evidence,positioning=positioning(asset) if asset!='GC' else None)))
    engineering['BTC']=encode(crypto_preview(asset='BTC',now_ns=NOW_NS,evidence=candle_evidence('BTC'),
        derivatives=dict(open_interest=1e9,open_interest_change_pct=2.,cvd_delta=100.,
            liquidation_short_usd=1000.,liquidation_long_usd=500.,order_book_imbalance=.2,funding_rate=.0001)))
    result=dict(schema=VERSION,input_sha256=request['input_sha256'],native_gc=native,
        authentic_examples=genuine,engineering_examples=engineering,engineering_mapping=mapping_fixture(),
        authentic_options=dict(status='UNAVAILABLE',missing=['exact_chain_definitions','synchronized_option_and_underlying_quotes',
            'published_open_interest','dated_rate_assumption','reviewed_exercise_family'],signed_dealer_gex=None,gamma_flip=None,**SAFETY),
        engineering_options=options_fixture(),
        engineering_european_gamma=unsigned_european_sensitivity(future=5000,strike=5000,years=30/365,
            rate=.04,volatility=.2,kind='C',open_interest=100,multiplier=50,
            convention_reference='ENGINEERING_EUROPEAN_BENCHMARK_ONLY',input_sha256=digest('ENGINEERING_EUROPEAN_INPUTS')),
        acquisition_proposals=acquisition_proposals(),incremental_provider_usage_usd='0',credit_used_usd='0',
        actual_downloads=0,production_registration=False,**SAFETY)
    with output_file.open('x') as out:
        json.dump(encode(result),out,sort_keys=True,separators=(',',':'),allow_nan=False)
