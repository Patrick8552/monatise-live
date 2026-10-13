"""Offline Phase 6 workstreams using existing authenticated local evidence."""
import json
from pathlib import Path

from ..native import process_gc,END_NS
from ..native_window import diagnose
from ..models import digest,encode
from ..runner import source_hashes
from ..fixtures import candle_evidence,positioning,NOW_NS
from ..broker_import import BrokerSpecification,BrokerSessions,import_candles
from . import BASELINE,VERSION,SAFETY,POLICY
from .cvd import investigate_cached,contract_from
from .billing import manifests,reconcile,release_bundle
from .basis import evaluate as basis_evaluate,BasisPolicy
from .options import inputs as option_inputs
from .signals import evaluate_broker,evaluate_crypto
from .examples import basis_example,options_example


def _broker_input(value,cutoff_ns):
    spec=BrokerSpecification(**value['specification']);s=dict(value['sessions'])
    s['intervals']=tuple(tuple(t) for t in s['intervals']);sessions=BrokerSessions(**s)
    return import_candles(value['path'],specification=spec,sessions=sessions,review=value['review'],
        admission_ns=value['admission_ns'],cutoff_ns=cutoff_ns,spread_price=value['spread_price'],
        confirmation_sha256=value.get('confirmation_sha256'),confirmation_ns=value.get('confirmation_ns'))


def main(request,output_file,*,repository,loop):
    if (request.get('schema')!=VERSION or request.get('baseline')!=BASELINE
            or request.get('input_sha256')!=digest({k:v for k,v in request.items() if k!='input_sha256'})
            or request.get('source_hashes')!=source_hashes(repository)):
        raise ValueError('phase6_source_and_baseline_bound_input_required')
    native=process_gc(data_root=request['data_root'],prepared_file=request['prepared_file'],repository=repository) if request.get('data_root') else None
    cvd=investigate_cached(native,data_root=request['data_root'],prepared_file=request['prepared_file']) if native else None
    indices=diagnose(request['esnq_root']) if request.get('esnq_root') else None
    billing=reconcile(manifests(request['esnq_root']),diagnostics=indices,ledger_rows=request['ledger_rows'],
        provider_records=request.get('provider_records',()),billing_review=request.get('billing_review'),
        admission_review=request.get('admission_review')) if indices else None
    admitted=None
    if billing and billing['research_admission_eligible']:
        contracts={p['contract']['metadata']['raw_symbol']:contract_from(p['contract']) for p in indices['products'].values()}
        admitted=release_bundle(billing,root=request['esnq_root'],contracts=contracts)
    authentic={};engineering={}
    for asset,instrument in (('GC','XAU/USD'),('ES','US500.cash'),('NQ','US100.cash')):
        supplied=request.get('broker_inputs',{}).get(asset);cutoff=supplied['cutoff_ns'] if supplied else END_NS
        evidence=None
        if supplied:
            try:
                evidence=_broker_input(supplied,cutoff)
                if evidence.evidence_kind!='AUTHENTIC_ARCHIVED_RECORD':
                    raise ValueError('engineering_broker_input_not_authentic')
            except (ValueError,TypeError,KeyError,ArithmeticError) as exc:
                authentic[asset]=dict(status='REJECTED_QUALITY',canonical=None,rejection_reasons=[str(exc)],**SAFETY)
        context=dict(source_normalized_sha256=native['normalized_sha256'],cvd=cvd) if asset=='GC' and native else (
            dict(source_normalized_sha256=indices['products'][asset]['normalized_sha256'],billing=billing['status'],
                 research_admission_eligible=billing['research_admission_eligible']) if indices else None)
        if asset not in authentic:
            authentic[asset]=loop.run_until_complete(evaluate_broker(asset=asset,instrument=instrument,cutoff_ns=cutoff,
                evidence=evidence,positioning=supplied.get('positioning') if supplied else None,institutional_context=context))
        e=candle_evidence(asset)
        engineering[asset]=loop.run_until_complete(evaluate_broker(asset=asset,instrument=instrument,cutoff_ns=NOW_NS,
            evidence=e,positioning=positioning(asset) if asset!='GC' else None,allow_engineering=True))
    engineering['GC_SHORT']=loop.run_until_complete(evaluate_broker(asset='GC',instrument='XAU/USD',cutoff_ns=NOW_NS,
        evidence=candle_evidence(short=True),allow_engineering=True))
    engineering['GC_NO_TRADE']=loop.run_until_complete(evaluate_broker(asset='GC',instrument='XAU/USD',cutoff_ns=NOW_NS,
        evidence=candle_evidence(positive=False),allow_engineering=True))
    authentic['BTC']=evaluate_crypto(asset='BTC',cutoff_ns=END_NS)
    basis=(basis_evaluate(contract=contract_from(native['contract']),policy=BasisPolicy('PHASE6_NO_BROKER_INPUTS',
        timing_bound_review_reference='NOT_USED_NO_OBSERVATIONS'),cutoff_ns=END_NS) if native else
        dict(status='BLOCKED_AUTHENTIC_INPUTS',basis=None,rejection_reasons=['GC_native_source_missing'],**SAFETY))
    result=dict(schema=VERSION,baseline=BASELINE,input_sha256=request['input_sha256'],native_gc=native,
        native_indices=indices,billing=billing,admitted_indices=encode(admitted),gc_cvd=cvd,authentic_basis=basis,
        authentic_options=option_inputs(cutoff_ns=END_NS),research_GIL_policy=POLICY,
        authentic_canonical=authentic,engineering_canonical=engineering,
        engineering_basis=basis_example(),engineering_options=options_example(),
        provider_account_observation=request.get('provider_account_observation'),
        frozen_H1_evidence=request.get('frozen_H1_evidence'),
        model_versions=dict(cvd='exchange-side-CVD-plus-unknown-volume-bounds-v1',basis='gc-causal-basis-candidates-v1',
            options='existing-American-IV-plus-European-benchmark-scenarios-v1',canonical='unchanged-baseline-engines'),
        incremental_provider_usage_usd='0',credit_consumed_usd='0',cash_spent_usd='0',new_acquisitions=0,
        worker_network_calls=0,production_registration=False,**SAFETY)
    with output_file.open('x') as out:json.dump(encode(result),out,sort_keys=True,separators=(',',':'),allow_nan=False)
