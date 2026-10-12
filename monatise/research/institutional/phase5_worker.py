"""Authentic captured-window acceptance and separately labelled engineering runs."""
import json

from . import SAFETY
from .models import digest,encode
from .native import process_gc,END_NS
from .fixtures import contract,candle_evidence,positioning,NOW_NS
from .signals import broker_preview,crypto_preview,CandleEvidence
from .presentation import complete,text_preview
from .options import OptionConvention
from .options_coverage import select,coverage
from .worker import options_fixture,acquisition_proposals

VERSION='monatise-phase5-research-v1'


def main(request,output_file,*,repository,loop):
    from .runner import source_hashes
    if (request.get('schema')!=VERSION
            or request.get('input_sha256')!=digest({k:v for k,v in request.items() if k!='input_sha256'})
            or request.get('source_hashes')!=source_hashes(repository)):
        raise ValueError('phase5_source_bound_input_required')
    native=process_gc(data_root=request['data_root'],prepared_file=request['prepared_file'],repository=repository) if request.get('data_root') else None
    from .native_window import diagnose
    indices=diagnose(request['esnq_root']) if request.get('esnq_root') else None
    authentic={};engineering={};mappings={}
    for asset,instrument in (('GC','XAU/USD'),('ES','US500.cash'),('NQ','US100.cash')):
        source='GCZ6' if asset=='GC' and native else asset+'Z6' if indices and asset in indices['products'] else None
        supplied=request.get('broker_inputs',{}).get(asset)
        evidence=CandleEvidence(**supplied['evidence']) if supplied else None
        if evidence and evidence.evidence_kind!='AUTHENTIC_ARCHIVED_RECORD':
            raise ValueError('engineering_candles_cannot_enter_authentic_acceptance')
        cutoff=supplied['cutoff_ns'] if supplied else END_NS
        primary=supplied.get('positioning') if supplied else None
        raw=loop.run_until_complete(broker_preview(asset=asset,instrument=instrument,now_ns=cutoff,
            evidence=evidence,positioning=primary,institutional_instrument=source,include_canonical=True))
        source_contract=(native['contract'] if asset=='GC' and native else
                         indices['products'][asset]['contract'] if indices and asset in indices['products'] else None)
        mappings[asset]=dict(status='MAPPING_UNAVAILABLE',source_instrument=asset,source_contract=source_contract,
            source_price=None,broker_instrument=instrument,broker_identity=None,observed_basis=None,
            mapped_reference_level=None,mapping_timestamp_ns=cutoff,observation_timestamps=[],
            valid_paired_observations=0,uncertainty=None,expiry_ns=None,data_quality='UNAVAILABLE',mapping_valid=False,
            rejection_reasons=['genuine_synchronized_broker_quotes_unavailable'],context_only=True,**SAFETY)
        context=(dict(indicators=native['indicators'],normalized_sha256=native['normalized_sha256'],
                     quality='CAPTURED_WINDOW_PARTIAL_CONTINUITY_UNCERTIFIED') if asset=='GC' and native else
                 dict(status=indices['products'][asset]['status'],counts=indices['products'][asset]['counts'],
                     normalized_sha256=indices['products'][asset]['normalized_sha256'],canonical_scoring_used=False)
                 if indices and asset in indices['products'] else None)
        authentic[asset]=complete(raw,market='BROKER_CFD',institutional=context,mapping=mappings[asset],
            missing=([] if evidence else ['authenticated_broker_candles'])+['synchronized_broker_quotes']
                    +([] if source else ['accepted_native_definitions_and_observations'])
                    +(['mandatory_primary_FlashAlpha_positioning'] if asset!='GC' and not primary else []))
        authentic[asset]['canonical_evaluation_attempted']=evidence is not None
        authentic[asset]['institutional_context_used_for_scoring']=False
        evidence=candle_evidence(asset)
        raw=loop.run_until_complete(broker_preview(asset=asset,instrument=instrument,now_ns=NOW_NS,evidence=evidence,
            positioning=positioning(asset) if asset!='GC' else None,include_canonical=True))
        engineering[asset]=complete(raw,market='ENGINEERING_BROKER_CFD')
    authentic['BTC']=complete(crypto_preview(asset='BTC',now_ns=END_NS),market='NATIVE_CRYPTO',
        missing=['native_exchange_quotes_candles_and_derivatives'])
    engineering['BTC']=complete(crypto_preview(asset='BTC',now_ns=NOW_NS,evidence=candle_evidence('BTC'),
        derivatives=dict(open_interest=1e9,open_interest_change_pct=2.,cvd_delta=100.,liquidation_short_usd=1000.,
                         liquidation_long_usd=500.,order_book_imbalance=.2,funding_rate=.0001)),market='ENGINEERING_NATIVE_CRYPTO')
    parent,option=contract(),contract(option=True)
    selected=select([option],underlying=parent,expiration_ns=option.metadata.expiration_ns,
                    strikes_fixed=(option.metadata.strike_fixed,))
    option_coverage=coverage(selected,underlying=parent,
        conventions={option.metadata.definition_sha256:OptionConvention('OG','American',option.metadata.definition_sha256,
                                                                        'ENGINEERING_STANDARD_OG_SPECIFICATION')},
        cutoff_ns=NOW_NS,evidence_kind='ENGINEERING_SYNTHETIC')
    proposal=acquisition_proposals()
    proposal['account_observation']=request.get('account_observation')
    proposal['portal_alternative']=dict(acquisition_start_ns=1791212400*10**9,
        acquisition_end_ns=1791213600*10**9,analysis_end_ns=END_NS,
        status='UNSUBMITTED_PROPOSAL',exact_contract_required=True,
        reason='Portal ten-minute selector requires 15:00–15:20; retain full source and analyze 15:00–15:15.')
    result=dict(schema=VERSION,input_sha256=request['input_sha256'],native_gc=native,new_native_esnq=indices,
        authentic_previews=authentic,engineering_previews=engineering,authentic_mappings=mappings,
        authentic_options=dict(status='BLOCKED_AUTHENTIC_INPUTS',definitions=None,underlying=None,open_interest=None,
            quotes=None,iv=None,gamma=None,signed_dealer_gex=None,gamma_flip=None,
            missing=['exact_standard_OG_definitions','reviewed_exercise_settlement','published_OI','synchronized_quotes','dated_rate'],**SAFETY),
        engineering_options=dict(coverage=option_coverage,analytics=options_fixture()),acquisition_proposals=proposal,
        presentation={kind:{asset:text_preview(p) for asset,p in values.items()} for kind,values in
                      (('authentic',authentic),('engineering',engineering))},
        incremental_usage_usd='0',credit_used_usd='0',cash_spent_usd='0',actual_downloads=0,worker_network_downloads=0,
        source_acquisition_downloads=sum(len(v['costs']) for v in indices['products'].values()) if indices else 0,**SAFETY)
    with output_file.open('x') as out:json.dump(encode(result),out,sort_keys=True,separators=(',',':'),allow_nan=False)
