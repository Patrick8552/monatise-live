"""Offline follow-up over sealed live journals, catalog and rate evidence.

No provider client construction here. This rerun cannot produce execution or
invent a quote event timestamp from a TradingView observation or candle time.
"""
from bisect import bisect_right
from decimal import Decimal
from math import log1p
from pathlib import Path
import hashlib,json

from monatise.research.databento.live_journal import verify
from monatise.research.databento.datasets import DatasetCapability
from monatise.research.databento.options import normalize_open_interest
from ..normalize import definition,EconomicConvention
from ..options import OptionConvention
from ..models import digest,encode
from ..runner import source_hashes as repository_source_hashes
from .udi import reviewed_definition,UDIReview,OG_SPEC
from .basis import Timestamp,Quote
from .chain import ChainLeg,CoveragePolicy,assess
from .greeks import GreekInput,validated
from . import SAFETY


def run(*,capture,catalog_manifest,rate_evidence,maximum_greek_diagnostics=8):
    import databento_dbn as dbn
    if not 1<=maximum_greek_diagnostics<=8:raise ValueError('bounded_diagnostic_subset_required')
    capture=Path(capture);report=json.loads((capture/'report.json').read_text())
    if report['status']!='CAPTURED' or report['quality']['quarantined']:raise ValueError('quarantined_capture_not_admissible')
    cutoff=report['capture_end_ns'];raw={};manifests={};source_hashes={}
    for schema in ('definition','mbp-1','statistics'):
        manifest,frames=verify(capture/schema);manifests[schema]=manifest;rows=[]
        decoder=dbn.DBNDecoder(has_metadata=False,input_version=3)
        for available,payload in frames:
            decoded=decoder.write_and_decode(payload)
            if len(decoded)!=1 or bytes(decoded[0])!=payload:raise ValueError('followup_native_roundtrip_failed')
            rows.append((available,decoded[0]))
        raw[schema]=rows;source_hashes[schema]=manifest['raw_sha256']
    defs={row.instrument_id:(cap,row) for cap,row in raw['definition'] if isinstance(row,dbn.InstrumentDefMsg)}
    symbols=report['scope']['exact_symbols']
    if set(defs)!=set(symbols.values()):raise ValueError('exact_current_definition_set_required')
    capability=DatasetCapability('GLBX.MDP3',('definition','mbp-1','statistics'),
        min(cap for cap,_ in raw['definition']),source_hashes['definition'])
    parent_cap,parent_row=defs[symbols['GCZ6']]
    if (str(parent_row.unit_of_measure)!='TRYOZ' or int(parent_row.unit_of_measure_qty)!=100*10**9
            or int(parent_row.display_factor)!=100000000 or int(parent_row.min_price_increment)!=100000000):
        raise ValueError('native_underlying_economics_mismatch')
    parent=definition(parent_row,capability=capability,publishers={1:('GLBX.MDP3','GLBX')},as_of_ns=parent_cap,
        convention=EconomicConvention('GC',Decimal('.1'),Decimal(100),'USD_per_troy_oz',
                                     'https://www.cmegroup.com/rulebook/COMEX/1a/113.pdf'))
    contracts={};rejected={};udi=[]
    for identity,(cap,row) in defs.items():
        if identity==parent.metadata.instrument_id:continue
        try:
            review=UDIReview(hashlib.sha256(bytes(row)).hexdigest(),'phase7-followup-exact-native-CME-UDI-review')
            contracts[identity]=reviewed_definition(row,underlying=parent,capability=capability,
                publishers={1:('GLBX.MDP3','GLBX')},as_of_ns=cap,review=review)
            if str(row.user_defined_instrument)=='Y':udi.append(identity)
        except ValueError as exc:rejected[str(identity)]=str(exc)
    latest={};futures=[];quote_rejections=[]
    for cap,row in raw['mbp-1']:
        if not isinstance(row,dbn.MBP1Msg):continue
        top=row.levels[0];b,a=int(top.bid_px),int(top.ask_px)
        if (max(b,a)>=2**63-1 or min(b,a)<=0 or b>a or min(top.bid_sz,top.ask_sz)<=0 or int(row.flags)&(4|8|32)):
            latest.pop(row.instrument_id,None);quote_rejections.append(row.instrument_id);continue
        if row.publisher_id!=1 or row.instrument_id not in defs or row.ts_event>row.ts_recv:
            raise ValueError('followup_exact_quote_identity_or_event_receive_order_failed')
        stamp=Timestamp(row.ts_event,row.ts_event,row.ts_event,str(row.ts_event),'Databento native UTC ts_event',
            source_hashes['mbp-1'],'Databento UTC epoch nanoseconds',1)
        q=Quote(str(defs[row.instrument_id][1].raw_symbol),'GLBX.MDP3/XCEC',row.instrument_id,
            str(Decimal(b)/10**9),str(Decimal(a)/10**9),stamp,row.ts_recv,cap,source_hashes['mbp-1'],'AUTHENTIC_ARCHIVED_RECORD')
        latest[row.instrument_id]=q
        if row.instrument_id==parent.metadata.instrument_id:futures.append(q)
    futures=sorted(futures,key=lambda q:(q.event.nominal_ns,q.provider_receive_ns))
    future_clocks=[q.event.nominal_ns for q in futures]
    ois={};oi_errors=[]
    for cap,row in raw['statistics']:
        if not isinstance(row,dbn.StatMsg) or int(row.stat_type)!=9:continue
        try:ois[row.instrument_id]=normalize_open_interest(row,available_ns=cap)
        except ValueError:
            ois.pop(row.instrument_id,None);oi_errors.append(row.instrument_id)
    legs=[];paired={}
    for identity,c in sorted(contracts.items()):
        q=latest.get(identity);u=None
        if q is not None:
            index=bisect_right(future_clocks,q.event.nominal_ns)-1
            if index>=0:u=futures[index];paired[identity]=(q,u)
        legs.append(ChainLeg(c,OptionConvention('OG','American',c.metadata.definition_sha256,OG_SPEC),q,u,ois.get(identity),
            defs[identity][0],OG_SPEC,'5','CME Rule300.20 and native OG catalog five-dollar strike lattice'))
    expected=tuple(sorted((row.expiration,row.strike_price,str(row.instrument_class)) for _,row in defs.values()
        if str(row.instrument_class) in {'C','P'}))
    coverage=assess(legs,underlying=parent,policy=CoveragePolicy('declared_two_expiry_4100_4275_catalog_band',
        expected,digest(expected),'native_midnight_catalog_plus_current_exact_definitions'),cutoff_ns=cutoff,evidence_kind='AUTHENTIC_ARCHIVED_RECORD')
    coverage['declared_scope_status']=coverage['status']
    coverage.update(status='INSUFFICIENT_CHAIN_COVERAGE',complete_exchange_chain=False,
        current_all_strikes_and_expirations_certified=False,
        catalog_manifest=json.loads(Path(catalog_manifest).read_text()))
    coverage['rejection_reasons']=sorted(set(coverage['rejection_reasons']+['unobserved_expiry_and_strike_tails',
        'whole_catalog_intraday_creations_and_deletions_unverified','OI_final_clearing_status_unverified']))
    rate=json.loads(Path(rate_evidence).read_text());benchmark=rate['rows'][0]
    if rate['available_at_ns']>cutoff:raise ValueError('rate_unavailable_at_capture_cutoff')
    diagnostics=[]
    candidates=sorted(paired,key=lambda i:(abs(contracts[i].metadata.strike_fixed/1e9-4200),contracts[i].metadata.expiration_ns,i))
    for identity in candidates[:maximum_greek_diagnostics]:
        q,u=paired[identity];c=contracts[identity];years=(c.metadata.expiration_ns-cutoff)/(365*86400*1e9)
        # Explicit flat overnight-rate extrapolation, not observed term OIS.
        annual=log1p(benchmark['percentRate']/100*years*365/360)/years
        x=GreekInput(float((Decimal(u.bid)+Decimal(u.ask))/2),c.metadata.strike_fixed/1e9,years,annual,
            c.metadata.kind,'American',float(q.bid),float(q.ask),cutoff,rate['available_at_ns'],rate['source_sha256'],
            OG_SPEC,'AUTHENTIC_ARCHIVED_RECORD',identity)
        if (max(cutoff-q.event.nominal_ns,cutoff-u.event.nominal_ns)>30*10**9
                or abs(q.event.nominal_ns-u.event.nominal_ns)>10**9):
            g=dict(status='REJECTED',gamma=None,iv=None,rejection_reasons=['stale_or_asynchronous_model_quotes'],**SAFETY)
        else:g=validated(x)
        diagnostics.append(dict(instrument_id=identity,symbol=c.metadata.raw_symbol,**g))
    basis=dict(status='REJECTED',basis=None,uncertainty=None,qualified_spot_mapping=False,
        rejection_reasons=['TradingView_bid_ask_event_and_provider_receive_timestamps_unavailable',
                           'authoritative_local_clock_and_drift_not_verified'],**SAFETY)
    code_hash=digest(repository_source_hashes(Path(__file__).resolve().parents[4]))
    return dict(schema='monatise-phase7-certification-followup-v1',as_of_ns=cutoff,source_hashes_sha256=code_hash,
        evidence_kind='AUTHENTIC_ARCHIVED_RECORD',input_sha256=digest(dict(source_hashes=source_hashes,
            catalog=coverage['catalog_manifest'],rate=rate,cutoff=cutoff,source_hashes_sha256=code_hash)),
        market_data=dict(native_record_counts=report['typed_record_counts'],native_journals=manifests,
            exact_option_count=len(defs)-1,normalized_option_count=len(contracts),UDI_count=len(udi),
            UDI_ids=sorted(udi),definition_rejections=rejected,OI_errors=sorted(set(oi_errors)),
            valid_latest_quotes=len(latest),invalid_quote_record_count=len(quote_rejections),
            latest_quotes={str(i):encode(q) for i,q in sorted(latest.items())}),
        options=coverage,basis=basis,rate=rate,greeks_diagnostic_subset=diagnostics,
        non_diagnostic_contract_Greeks='NOT_COMPUTED_OR_VALIDATED',
        gamma=dict(status='BLOCKED_CERTIFICATION',dealer_gex=None,gamma_flip=None,wall=None,
            rejection_reasons=['incomplete_exchange_scope','unknown_dealer_inventory','unvalidated_sensitivities_for_full_scope']),
        mappings=dict(status='UNAVAILABLE',qualified_spot_entries=None,actual_broker_price=None),
        trade_qualification_performed=False,incremental_data_cost_estimated_usd='0',paid_acquisitions=0,
        actual_usage_reconciliation='NOT_INDEPENDENTLY_RECONCILED',**SAFETY)
