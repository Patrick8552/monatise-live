"""Phase 6 offline evidence gates and numerical experiments, all inputs mocked."""
import asyncio
from dataclasses import replace
from decimal import Decimal
import json

import pytest

from monatise.research.institutional.fixtures import contract,quote,candle_evidence,NOW_NS
from monatise.research.institutional.models import MarketObservation,Source,digest
from monatise.research.institutional.phase6 import SAFETY,POLICY
from monatise.research.institutional.phase6.cvd import evaluate as cvd,observation_from
from monatise.research.institutional.phase6.basis import evaluate,held_out,BasisPolicy
from monatise.research.institutional.phase6.examples import basis_pairs,basis_example,options_example
from monatise.research.institutional.phase6.options import (
    inputs,OptionInputReview,BenchmarkLeg,benchmark_scenarios,map_level,american_diagnostics)
from monatise.research.institutional.phase6.billing import reconcile,release_bundle
from monatise.research.institutional.phase6.signals import evaluate_broker,evaluate_crypto
from monatise.research.institutional.phase6.runner import run,isolated
from monatise.research.databento.acquisition import HistoricalRequest
from monatise.research.institutional.options import OptionConvention,RateAssumption
from monatise.research.institutional.models import encode


def trade(side=None,size=3,at=NOW_NS-10**9,ordinal=1,sequence=100):
    return MarketObservation(contract(),'trades',at-1,at,
        Source(digest('ENGINEERING_TRADE_ARCHIVE'),digest((at,ordinal)),ordinal,at+1,at+1,'ENGINEERING_SYNTHETIC'),
        ('2519.2',size,side),sequence=sequence)


def preceding(**changes):
    values=dict(receive_ns=NOW_NS-10**9-1000,ordinal=99)
    values.update(changes);return quote(contract(),**values)


def test_cvd_unknown_volume_bounds_path_and_inference_remain_distinct():
    t=[trade('BUY',2,at=NOW_NS-3*10**9,ordinal=0),trade('SELL',1,at=NOW_NS-2*10**9,ordinal=1),trade(ordinal=2)]
    r=cvd(t,quotes=[preceding()],start_ns=NOW_NS-4*10**9,end_ns=NOW_NS,session_reference='ENGINEERING_SESSION')
    assert (r['cvd_known'],r['cvd_lower'],r['cvd_upper'])==(1,-2,4)
    assert r['unknown_volume']==3 and r['full_exchange_side_cvd'] is None
    assert r['quote_inference']['buy_volume']==3 and r['quote_inference']['combined_delta']==4
    assert r['status']=='INCOMPLETE_CVD' and not r['quote_inference']['certified']
    assert r['bounds_path'][-1]['lower']==-2 and not r['complete_window_certified']
    assert Decimal(r['classified_volume_coverage'])==Decimal(3)/6


@pytest.mark.parametrize('fault',['future_receive','equal_receive','future_event','equal_sequence','missing_sequence',
                                  'stale','locked','inside','outside','missing'])
def test_cvd_never_recovers_exchange_side_from_bad_or_ambiguous_quote(fault):
    q=preceding();t=trade()
    if fault=='future_receive':q=preceding(receive_ns=t.receive_ns+100)
    if fault=='equal_receive':q=preceding(receive_ns=t.receive_ns)
    if fault=='future_event':q=replace(preceding(receive_ns=t.receive_ns+2),event_ns=t.event_ns+1)
    if fault=='equal_sequence':q=replace(q,sequence=t.sequence)
    if fault=='missing_sequence':q=replace(q,sequence=None)
    if fault=='stale':q=preceding(receive_ns=t.receive_ns-10**9)
    if fault=='locked':q=preceding(bid='2519.2',ask='2519.2')
    if fault=='inside':t=replace(t,payload=('2519.1',3,None))
    if fault=='outside':t=replace(t,payload=('2519.3',3,None))
    r=cvd([t],quotes=[] if fault=='missing' else [q],start_ns=NOW_NS-3*10**9,end_ns=NOW_NS+1000,session_reference='FIXTURE')
    assert r['unknown_volume']==3 and r['quote_inference']['unresolved_volume']==3


def test_cvd_latest_ambiguous_quote_cannot_cherry_pick_older_useful_quote():
    a=preceding(receive_ns=NOW_NS-10**9-100000,ordinal=98)
    b=preceding(bid='2519.1',ask='2519.3')
    r=cvd([trade()],quotes=[a,b],start_ns=NOW_NS-2*10**9,end_ns=NOW_NS,session_reference='FIXTURE')
    assert r['quote_inference']['unresolved_volume']==3


def test_cvd_point_in_time_does_not_backdate_archive_admission_and_identity_is_exact():
    t=replace(trade(),source=replace(trade().source,admission_ns=NOW_NS+1))
    with pytest.raises(ValueError,match='availability'):cvd([t],start_ns=NOW_NS-2*10**9,end_ns=NOW_NS,
        session_reference='FIXTURE',cutoff_ns=NOW_NS,mode='POINT_IN_TIME')
    with pytest.raises(ValueError,match='mismatch'):cvd([trade()],quotes=[quote(contract('ES'))],
        start_ns=NOW_NS-2*10**9,end_ns=NOW_NS,session_reference='FIXTURE')
    assert observation_from(encode(trade()))==trade()


def basis(**changes):
    c,p,s,fs=basis_pairs()
    args=dict(contract=c,futures_quotes=[x[0] for x in p],broker_quotes=[x[1] for x in p],broker_sessions=s,
        futures_session=fs,policy=BasisPolicy('ENGINEERING_POLICY',timing_bound_review_reference='ENGINEERING_REVIEW'),
        cutoff_ns=NOW_NS,futures_level='2520')
    args.update(changes);return evaluate(**args)


def test_basis_candidates_reuse_baseline_and_conservative_interval():
    r=basis()
    assert r['status']=='RESEARCH_CONTEXT_ESTIMATE'
    assert r['basis']=='1.0' and r['mapped_spot_level']=='2519.0'
    assert set(r['candidates'])=={'rolling_median','recency_weighted_median','mad_filtered_median'}
    assert r['baseline']['methodology'].startswith('existing-median')
    assert Decimal(r['uncertainty'])>Decimal('.2')
    assert not r['production_replacement_approved'] and not r['execution_eligible']


@pytest.mark.parametrize('fault',['missing','stale','future_available','future_event','roll','wrong_contract',
                                  'provider','session','duplicate','receipt','skew','expiry','uncertainty','range'])
def test_basis_rejects_unavailable_identity_session_or_quality(fault):
    c,p,s,fs=basis_pairs();f=[x[0] for x in p];b=[x[1] for x in p];extra={}
    if fault=='missing':b=[]
    if fault=='stale':extra['cutoff_ns']=NOW_NS+31*10**9
    if fault=='future_available':b[0]=replace(b[0],available_ns=NOW_NS+1,admission_ns=NOW_NS+1)
    if fault=='future_event':f[-1]=quote(c,receive_ns=NOW_NS+1,ordinal=7)
    if fault in {'roll','wrong_contract'}:
        c2=replace(c,metadata=replace(c.metadata,instrument_id=c.metadata.instrument_id+1))
        f[-1]=quote(c2,receive_ns=p[-1][0].receive_ns,ordinal=7)
    if fault=='provider':b[-1]=replace(b[-1],specification=replace(b[-1].specification,server='OTHER'))
    if fault=='session':extra['broker_sessions']=replace(s,intervals=((NOW_NS-100*10**9,NOW_NS),))
    if fault=='duplicate':f[1]=f[0]
    if fault=='receipt':b[0]=replace(b[0],receive_ns=None)
    if fault=='skew':b[0]=replace(b[0],event_ns=b[0].event_ns-2*10**9)
    if fault=='expiry':extra['policy']=BasisPolicy('EXPIRY',timing_bound_review_reference='FIXTURE',minimum_time_to_expiry_ns=90*86400*10**9)
    if fault=='uncertainty':extra['policy']=BasisPolicy('UNCERTAINTY',timing_bound_review_reference='FIXTURE',maximum_uncertainty=Decimal('.1'))
    if fault=='range':b[-1]=replace(b[-1],bid=Decimal('2517'),ask=Decimal('2517.2'))
    r=basis(futures_quotes=f,broker_quotes=b,**extra)
    assert r['status']=='MAPPING_UNAVAILABLE' and r['basis'] is None and r['mapped_spot_level'] is None
    assert r['rejection_reasons']


def test_basis_outliers_do_not_disappear_from_uncertainty():
    c,p,s,fs=basis_pairs();b=[x[1] for x in p];b[0]=replace(b[0],bid=Decimal('2517.6'),ask=Decimal('2517.8'))
    r=basis(broker_quotes=b)
    assert r['status']=='RESEARCH_CONTEXT_ESTIMATE' and r['outlier_retained']==7
    assert Decimal(r['candidates']['mad_filtered_median']['uncertainty'])>=Decimal('.6')


def test_basis_time_weighted_estimate_uses_declared_recency_weights():
    c,p,s,fs=basis_pairs();b=[x[1] for x in p]
    b[-1]=replace(b[-1],bid=Decimal('2517.8'),ask=Decimal('2518'))
    b[-2]=replace(b[-2],bid=Decimal('2517.8'),ask=Decimal('2518'))
    r=basis(broker_quotes=b)
    assert r['status']=='RESEARCH_CONTEXT_ESTIMATE'
    assert Decimal(r['candidates']['recency_weighted_median']['basis'])>=Decimal(r['candidates']['rolling_median']['basis'])


def test_basis_walk_forward_held_out_spot_not_used_for_fit():
    c,p,s,fs=basis_pairs();args=dict(contract=c,futures_quotes=[x[0] for x in p],broker_quotes=[x[1] for x in p],
        broker_sessions=s,futures_session=fs,policy=BasisPolicy('FIXTURE',timing_bound_review_reference='FIXTURE'))
    a=held_out(**args);args['broker_quotes'][-1]=replace(args['broker_quotes'][-1],bid=Decimal('2517'),ask=Decimal('2517.2'))
    b=held_out(**args)
    assert a['status']=='EVALUATED' and len(a['rows'])==3
    assert a['rows'][-1]['training_input_sha256']==b['rows'][-1]['training_input_sha256']
    assert a['rows'][-1]['metrics']!=b['rows'][-1]['metrics']
    assert not a['held_out_broker_prices_used_for_fit']
    assert all(max(row['train_positions'])<row['test_position'] for row in a['rows'])


def billing_inputs():
    values=[];ledger=[];records=[];costs={'ES':[],'NQ':[]}
    hsource=digest('ENGINEERING_PROVIDER_STATEMENT')
    for name,iid in (('ESZ6',10252),('NQZ6',261401)):
        for schema in ('definition','trades','ohlcv-1m'):
            r=HistoricalRequest('GLBX.MDP3',schema,((1,iid,name),),NOW_NS-100*10**9,NOW_NS,100)
            h=r.sha256;archive=digest((name,schema));auth='MOCK_PERMIT_'+h[:12]
            m=dict(request=encode(r),request_sha256=h,archive_sha256=archive,manifest_sha256=digest(('manifest',h)),
                retrieval_ns=NOW_NS+1,ingestion_ns=NOW_NS+2,status='ARCHIVED',download_attempts=1,
                evidence_kind='AUTHENTIC_HISTORICAL_DOWNLOAD',coverage=dict(transport_complete=True),
                authorization=dict(approval_id=auth),preflight=dict(estimated_usd='.01'))
            values.append(m);ledger.append(dict(approval_id=auth,request_sha256=h,reserved_usd='1',
                actual_usage_usd=None,credit_used_usd=None,transport_started=1))
            costs[name[:-2]].append(dict(request_sha256=h,archive_sha256=archive))
            records.append(dict(request_sha256=h,provider_source_sha256=hsource,provider_request_id='MOCK_PROVIDER_'+h,
                source_kind='PROVIDER_REQUEST_JOURNAL',settled=True,dataset=r.dataset,schema=r.schema,
                contracts=r.contracts,start_ns=r.start_ns,end_ns=r.end_ns,acquired_at_ns=NOW_NS+1,
                actual_usage_usd='.01',credit_used_usd='.01',cash_usd='0'))
    diagnostics=dict(products={p:dict(costs=costs[p],missing_minute_opens_ns=[]) for p in costs})
    return values,dict(diagnostics=diagnostics,ledger_rows=ledger,provider_records=records,
        billing_review=dict(independent_review_reference='MOCK_PROVIDER_ORIGIN_REVIEW',verified_source_hashes=[hsource]),
        admission_review=dict(human_review_reference='MOCK_RESEARCH_ADMISSION',approved_request_hashes=[m['request_sha256'] for m in values]))


def test_billing_request_accounting_and_explicit_admission_all_or_none():
    values,args=billing_inputs();r=reconcile(values,**args)
    assert r['status']=='RESEARCH_RELEASE_APPROVED' and r['research_admission_eligible']
    assert r['actual_usage_usd']=='0.06' and r['credit_used_usd']=='0.06' and r['cash_usd']=='0'
    assert r['reserved_usd']=='6' and not r['reservation_is_charge'] and not r['execution_eligible']


@pytest.mark.parametrize('fault',['missing_records','estimate_only','unsettled','scope','timestamp','origin','cash',
                                  'no_approval','partial_approval','quality','missing_candle'])
def test_billing_never_releases_unresolved_request_or_independent_quality(fault):
    values,args=billing_inputs()
    if fault=='missing_records':args['provider_records']=[]
    if fault=='estimate_only':args['provider_records'][0]['source_kind']='PROVIDER_COST_ESTIMATE'
    if fault=='unsettled':args['provider_records'][0]['settled']=False
    if fault=='scope':args['provider_records'][0]['schema']='mbp-1'
    if fault=='timestamp':args['provider_records'][0]['acquired_at_ns']+=1
    if fault=='origin':args['billing_review']['verified_source_hashes']=[]
    if fault=='cash':args['provider_records'][0].update(credit_used_usd='0',cash_usd='.01')
    if fault=='no_approval':args['admission_review']=None
    if fault=='partial_approval':args['admission_review']['approved_request_hashes'].pop()
    if fault=='quality':args['admission_review']['unresolved_quality_requests']=[values[0]['request_sha256']]
    if fault=='missing_candle':args['diagnostics']['products']['ES']['missing_minute_opens_ns']=[1]
    r=reconcile(values,**args)
    assert not r['research_admission_eligible'] and r['status'].endswith('QUARANTINE_RETAINED')
    with pytest.raises(ValueError,match='cannot_release'):release_bundle(r,root='unused',contracts={})


@pytest.mark.parametrize('fault',['accounting','negative','cache','request','ledger','duplicate','extra'])
def test_billing_rejects_integrity_and_accounting_mismatches(fault):
    values,args=billing_inputs()
    if fault=='accounting':args['provider_records'][0]['actual_usage_usd']='.02'
    if fault=='negative':args['provider_records'][0].update(actual_usage_usd='-.01',credit_used_usd='-.01')
    if fault=='cache':args['diagnostics']['products']['ES']['costs'][0]['archive_sha256']=digest('wrong')
    if fault=='request':values[0]['request_sha256']=digest('wrong')
    if fault=='ledger':args['ledger_rows'][0]['transport_started']=0
    if fault=='duplicate':args['provider_records'].append(args['provider_records'][0])
    if fault=='extra':args['provider_records'].append(dict(args['provider_records'][0],request_sha256=digest('extra')))
    with pytest.raises(ValueError):reconcile(values,**args)


def test_options_missing_genuine_inputs_are_blocked_with_research_policy():
    r=inputs(cutoff_ns=NOW_NS)
    assert r['status']=='BLOCKED_AUTHENTIC_INPUTS' and r['analytics'] is None
    assert POLICY['mandatory_providers']==() and POLICY['canonical_index_requirements_preserved']
    assert not r['gil_enabled']


def option_input():
    from monatise.application.gold_options import american_futures
    c=contract();o=contract(option=True)
    premium=Decimal(str(american_futures(2519.1,2500,30/365,.04,.2,'C'))).quantize(Decimal('.1'))
    r=RateAssumption(.04,NOW_NS-3600*10**9,digest('ENGINEERING_RATE'),'fixed annual fixture rate','ENGINEERING_SYNTHETIC')
    return dict(option=quote(o,bid=premium-Decimal('.1'),ask=premium+Decimal('.1')),underlying=quote(c),
        convention=OptionConvention('OG','American',o.metadata.definition_sha256,'ENGINEERING_SPECIFICATION'),rate=r,
        review=OptionInputReview(o.metadata.receive_ns,NOW_NS-3600*10**9,'exercise_into_underlying_future',
                                'ENGINEERING_SETTLEMENT','ENGINEERING_ORIGIN',r.source_sha256),cutoff_ns=NOW_NS)


def test_options_reviewed_american_IV_stays_separate_from_uncertified_Greeks_and_OI():
    r=inputs(**option_input())
    assert r['status']=='AMERICAN_IV_RESEARCH_ONLY' and abs(r['analytics']['iv']-.2)<.002
    assert r['gamma'] is None and r['open_interest'] is None and r['signed_dealer_gex'] is None
    assert not r['american_greeks_certified'] and r['missing']==['published_open_interest']


@pytest.mark.parametrize('fault',['rate_future','definition_future','rate_hash','wrong_underlying'])
def test_options_rejects_lookahead_or_wrong_lineage(fault):
    args=option_input()
    if fault=='rate_future':args['review']=replace(args['review'],rate_available_ns=NOW_NS+1)
    if fault=='definition_future':args['review']=replace(args['review'],definition_available_ns=NOW_NS+1)
    if fault=='rate_hash':args['review']=replace(args['review'],rate_source_sha256=digest('wrong'))
    if fault=='wrong_underlying':args['underlying']=quote(replace(contract(),metadata=replace(contract().metadata,instrument_id=777)))
    with pytest.raises(ValueError):inputs(**args)


def benchmark(oi=100):
    legs=(BenchmarkLeg('C','C',2500,30/365,.04,.2,oi,100,digest('C')),
          BenchmarkLeg('P','P',2600,30/365,.04,.2,100,100,digest('P')))
    return dict(legs=legs,price_grid=(2400,2500,2600,2700),
                scenarios=[dict(name='ASSUMED',signs={'C':1,'P':-1},assumption_reference='ENGINEERING_INVENTORY')])


def test_european_benchmark_scenarios_roots_theta_and_no_dealer_claim():
    r=benchmark_scenarios(**benchmark())
    assert r['status'].startswith('ENGINEERING') and r['signed_dealer_gex'] is None and not r['complete_chain']
    assert len(r['scenarios'][0]['candidate_grid_crossings'])==1
    assert 2500<r['scenarios'][0]['candidate_grid_crossings'][0]<2600
    assert r['scenarios'][0]['curve'][0]['legs'][0]['greeks']['theta_per_day'] is not None
    assert r['selected_call_put_OI']=={'C':100,'P':100}


def test_missing_OI_preserves_null_exposure_and_concentration_subtotals():
    r=benchmark_scenarios(**benchmark(None))
    assert r['missing_OI']==['C'] and r['selected_call_put_OI']['C'] is None
    assert all(x['scenario_signed_gamma_1pct'] is None for x in r['scenarios'][0]['curve'])
    assert not r['scenarios'][0]['candidate_grid_crossings']


@pytest.mark.parametrize('fault',['missing_sign','bool_sign','fraction','no_reference','grid_duplicate','empty','unknown_OI'])
def test_options_scenario_assumptions_and_bounds_required(fault):
    args=benchmark()
    if fault=='missing_sign':args['scenarios'][0]['signs'].pop('P')
    if fault=='bool_sign':args['scenarios'][0]['signs']['P']=True
    if fault=='fraction':args['scenarios'][0]['signs']['P']=.5
    if fault=='no_reference':args['scenarios'][0]['assumption_reference']=''
    if fault=='grid_duplicate':args['price_grid']=(2500,2500)
    if fault=='empty':args['legs']=()
    if fault=='unknown_OI':
        with pytest.raises(ValueError):replace(args['legs'][0],open_interest=-1)
        return
    with pytest.raises(ValueError):benchmark_scenarios(**args)


def test_american_tree_diagnostic_is_not_greek_certification():
    r=american_diagnostics(future=2519,strike=2500,years=30/365,rate=.04,volatility=.2,kind='C')
    assert len(r['rows'])==6 and r['certified_greeks'] is None and not r['american_greeks_certified']
    assert r['gamma_range']>=0 and not r['execution_eligible']


def mapped(**changes):
    c=contract();o=contract(option=True)
    args=dict(level_kind='ACTUAL_OPTION_STRIKE',level='2500',underlying_contract=c,basis_report=basis(),
        observation_ns=NOW_NS-10**9,available_ns=NOW_NS-10**9+1,cutoff_ns=NOW_NS,
        option_expiry_ns=o.metadata.expiration_ns,option_contract=o,
        level_source_sha256=o.metadata.definition_sha256,evidence_kind='ENGINEERING_SYNTHETIC')
    args.update(changes);return map_level(**args)


def test_option_strike_mapping_is_context_with_distinct_genuine_broker_reference():
    r=mapped()
    assert r['status']=='OPTIONS_CONTEXT_ESTIMATE' and r['actual_GC_option_strike']=='2500'
    assert r['contextual_XAUUSD_level']=='2499.0' and r['calculated_GC_gamma_level'] is None
    assert r['actual_broker_XAUUSD_price']=='2518.1' and not r['execution_eligible']


@pytest.mark.parametrize('fault',['expiry','expired_basis','contract','stale','lookahead','uncertainty',
                                  'fake_strike','missing_definition','kind','source','evidence','gamma_assumption'])
def test_options_mapping_rejects_incompatible_or_unavailable_levels(fault):
    kwargs={}
    if fault=='expiry':kwargs['option_expiry_ns']=contract().metadata.expiration_ns+1
    if fault=='expired_basis':kwargs['basis_report']=dict(basis(),expires_ns=NOW_NS)
    if fault=='contract':kwargs['basis_report']=dict(basis(),contract=contract('ES').identity)
    if fault=='stale':kwargs['observation_ns']=NOW_NS-31*10**9
    if fault=='lookahead':kwargs['available_ns']=NOW_NS+1
    if fault=='uncertainty':kwargs['basis_report']=dict(basis(),uncertainty='9999')
    if fault=='fake_strike':kwargs['level']='2501'
    if fault=='missing_definition':kwargs['option_contract']=None
    if fault=='kind':kwargs['level_kind']='GAMMA_FLIP_VERIFIED'
    if fault=='source':kwargs['level_source_sha256']=None
    if fault=='evidence':kwargs['evidence_kind']='AUTHENTIC_ARCHIVED_RECORD'
    if fault=='gamma_assumption':kwargs['level_kind']='CALCULATED_GAMMA_SCENARIO'
    r=mapped(**kwargs)
    assert r['status']=='MAPPING_UNAVAILABLE' and r['contextual_XAUUSD_level'] is None


@pytest.mark.parametrize('short,positive,expected',[(False,True,'LONG'),(True,True,'SHORT'),(False,False,'NO_TRADE')])
def test_former_canonical_futures_patterns_cannot_reactivate_retired_route(short,positive,expected):
    r=asyncio.run(evaluate_broker(asset='GC',instrument='XAU/USD',cutoff_ns=NOW_NS,
        evidence=candle_evidence(short=short,positive=positive),allow_engineering=True))
    assert r['status']=='REJECTED_QUALITY' and not r['canonical_evaluation_attempted']
    assert not r['execution_eligible'] and r['canonical'] is None
    assert r['entry'] is None and r['stop'] is None and r['targets'] is None
    assert 'canonical_futures_route_removed' in r['rejection_reasons'][0]


@pytest.mark.parametrize('fault',['missing','fixture','future','incomplete'])
def test_canonical_inputs_block_or_reject_without_replacement_strategy(fault):
    e=candle_evidence();allow=True
    if fault=='missing':e=None
    if fault=='fixture':allow=False
    if fault=='future':e=replace(e,confirmation_ns=NOW_NS+1)
    if fault=='incomplete':
        rows=json.loads(e.timeframes_json);rows.pop('4h');e=replace(e,timeframes_json=json.dumps(rows))
    r=asyncio.run(evaluate_broker(asset='GC',instrument='XAU/USD',cutoff_ns=NOW_NS,evidence=e,allow_engineering=allow))
    assert r['status']==('BLOCKED_AUTHENTIC_INPUTS' if fault=='missing' else 'REJECTED_QUALITY')
    assert r['canonical'] is None and not r['canonical_evaluation_attempted']


def test_canonical_index_positioning_survives_isolated_research_policy_change():
    r=asyncio.run(evaluate_broker(asset='ES',instrument='US500.cash',cutoff_ns=NOW_NS,
        evidence=candle_evidence('ES'),allow_engineering=True))
    assert r['status']=='BLOCKED_AUTHENTIC_INPUTS' and 'canonical_primary_index_positioning_missing' in r['rejection_reasons']
    assert evaluate_crypto(asset='BTC',cutoff_ns=NOW_NS)['status']=='BLOCKED_AUTHENTIC_INPUTS'


def test_phase6_isolated_replay_deterministic_and_credentials_removed(tmp_path,monkeypatch):
    monkeypatch.setenv('DATABENTO_API_KEY','DO_NOT_INHERIT_TEST_CREDENTIAL')
    result=run(output=tmp_path/'phase6')
    a=(tmp_path/'phase6/replay-01.json').read_bytes();b=(tmp_path/'phase6/replay-02.json').read_bytes()
    assert a==b and result['repeat_equal'] and result['new_acquisitions']==0
    assert 'DO_NOT_INHERIT' not in a.decode() and result['authentic_canonical']['GC']=='BLOCKED_AUTHENTIC_INPUTS'
    assert result['engineering_canonical']['GC']=='REJECTED_QUALITY' and result['engineering_canonical']['GC_SHORT']=='REJECTED_QUALITY'
    assert not result['research_admission_eligible']
    with pytest.raises(FileExistsError):run(output=tmp_path/'phase6')


def test_billing_release_reuses_admission_seam_and_detects_manifest_change(monkeypatch):
    from monatise.research.institutional.phase6 import billing as module
    values,args=billing_inputs();result=reconcile(values,**args);calls=[]
    monkeypatch.setattr(module,'manifests',lambda root:values)
    def fake_admit(path,**kwargs):
        assert kwargs['review']['billing_status']=='RECONCILED'
        assert kwargs['request'].contracts==(kwargs['contract'].identity[1:4],)
        calls.append(kwargs);return {'execution_eligible':False}
    monkeypatch.setattr(module,'admit',fake_admit)
    contracts={name:replace(contract(name[:-2]),metadata=replace(contract(name[:-2]).metadata,instrument_id=iid))
               for name,iid in (('ESZ6',10252),('NQZ6',261401))}
    assert len(release_bundle(result,root='MOCK_ARCHIVE',contracts=contracts))==6 and len(calls)==6
    values[0]['manifest_sha256']=digest('changed')
    with pytest.raises(ValueError,match='changed_after'):release_bundle(result,root='MOCK_ARCHIVE',contracts=contracts)


def test_crypto_incomplete_derivative_provenance_rejected():
    r=evaluate_crypto(asset='BTC',cutoff_ns=NOW_NS,evidence=candle_evidence('BTC'),derivatives={},allow_engineering=True)
    assert r['status']=='REJECTED_QUALITY' and r['canonical'] is None


def option_requests():
    from monatise.research.institutional.phase6.acquisition_plan import requests
    o=contract(option=True)
    return requests([o],underlying=contract(),expiration_ns=o.metadata.expiration_ns,
                    strikes_fixed=(o.metadata.strike_fixed,),schema='mbp-1',start_ns=NOW_NS,end_ns=NOW_NS+60*10**9)


def test_options_exact_request_cost_review_reuses_cache_before_metadata():
    from monatise.research.institutional.phase6.acquisition_plan import review
    def must_not_quote(r):raise AssertionError('cached data never needs new acquisition')
    r=review(option_requests(),cache_plan=lambda req:dict(new_download_required=False,overlapping_request_hashes=[req.sha256],
        covering_manifests=[dict(request_sha256=req.sha256)],uncovered_ranges=[]),
             metadata_preflight=must_not_quote,now_ns=NOW_NS)
    assert r['total_known_estimated_usd']=='0' and not r['rejection_reasons'] and not r['acquisition_enabled']


@pytest.mark.parametrize('fault',['unknown_cost','entitlement','budget','overlap','no_cash_protection','stale_quote'])
def test_options_nonzero_proposal_never_creates_authorization(fault):
    from monatise.research.institutional.phase6.acquisition_plan import review
    from monatise.research.databento.acquisition import DownloadPreflight
    def preflight(r):
        if fault=='unknown_cost':raise RuntimeError('MOCK_ESTIMATE_UNAVAILABLE')
        return DownloadPreflight(r.sha256,NOW_NS-301*10**9 if fault=='stale_quote' else NOW_NS,
            NOW_NS-10**9,NOW_NS+100*10**9,'.1',True,True,digest('MOCK_METADATA'),
            'UNKNOWN' if fault=='entitlement' else 'VERIFIED_OPERATOR')
    r=review(option_requests(),cache_plan=lambda req:dict(new_download_required=True,
        overlapping_request_hashes=[digest('overlap')] if fault=='overlap' else []),metadata_preflight=preflight,
        now_ns=NOW_NS,approved_credit_ceiling_usd='0' if fault=='budget' else '1',verified_credit_usd='1',
        credit_checked_ns=NOW_NS,credit_review_reference='MOCK_CREDIT_REVIEW',
        credit_expires_ns=NOW_NS+100*10**9,zero_cash_protection_reference=None if fault=='no_cash_protection' else 'MOCK_CAP_REVIEW')
    assert not r['acquisition_enabled'] and not r['approval_created']
    assert r['rejection_reasons'] or r['rows'][0]['rejection_reasons']


def test_empty_CVD_sample_cannot_claim_classified_exchange_sides():
    r=cvd([],start_ns=NOW_NS-10**9,end_ns=NOW_NS,session_reference='ENGINEERING_SESSION')
    assert r['status']=='UNAVAILABLE' and r['classified_volume_coverage'] is None and r['full_exchange_side_cvd'] is None


def test_held_out_retains_original_staleness_rejection():
    c,p,s,fs=basis_pairs();p=[(replace(f,source=replace(f.source,admission_ns=NOW_NS+100*10**9)),
        replace(b,available_ns=NOW_NS+100*10**9,admission_ns=NOW_NS+100*10**9)) for f,b in p]
    r=held_out(contract=c,futures_quotes=[f for f,b in p],broker_quotes=[b for f,b in p],broker_sessions=s,
        futures_session=fs,policy=BasisPolicy('FIXTURE',timing_bound_review_reference='FIXTURE'))
    assert r['status']=='BLOCKED_AUTHENTIC_INPUTS'
    assert all('identity_roll_session_availability_or_causal_alignment_rejected' in row['rejection_reasons'] for row in r['rows'])


def test_billing_distinct_downloads_cannot_share_one_provider_request_ID():
    values,args=billing_inputs();args['provider_records'][1]['provider_request_id']=args['provider_records'][0]['provider_request_id']
    with pytest.raises(ValueError,match='duplicate_provider_request_ID'):reconcile(values,**args)


def test_billing_previously_settled_ledger_conflict_retains_quarantine():
    values,args=billing_inputs();args['ledger_rows'][0].update(actual_usage_usd='.02',credit_used_usd='.02')
    r=reconcile(values,**args)
    assert not r['research_admission_eligible'] and not r['rows'][0]['billing_reconciled']
    assert 'existing_ledger_settlement_conflict' in r['rows'][0]['rejection_reasons']
