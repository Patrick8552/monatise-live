"""Read-only genuine native regression. Never connects to a provider."""
import hashlib
import json
import struct
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from monatise.research.databento.datasets import DatasetCapability
from monatise.research.databento.options import normalize_open_interest
from ..normalize import definition, EconomicConvention
from ..options import OptionConvention
from ..models import digest, encode
from .basis import Timestamp, Quote, BasisPolicy, certify, map_level
from .chain import ChainLeg, CoveragePolicy, assess
from .greeks import GreekInput, validated
from . import SAFETY

SPEC='https://www.cmegroup.com/rulebook/COMEX/1a/115.pdf'
FUTURE_SPEC='https://www.cmegroup.com/rulebook/COMEX/1a/113.pdf'
AUTHENTIC='AUTHENTIC_ARCHIVED_RECORD'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def native_records(path, *, expected_hash, expected_count, cutoff_ns, maximum_bytes=32*1024**2):
    """Frame count includes controls/mappings. Every DBN byte must roundtrip."""
    import databento_dbn as dbn
    path=Path(path)
    if path.stat().st_size>maximum_bytes or sha(path)!=expected_hash:raise ValueError('native_archive_hash_or_capacity_mismatch')
    raw=path.read_bytes();offset=0;count=0;previous=0;decoder=dbn.DBNDecoder(has_metadata=False,input_version=3)
    while offset<len(raw):
        if offset+12>len(raw):raise ValueError('truncated_native_frame')
        capture,size=struct.unpack_from('>QI',raw,offset);offset+=12
        if not 16<=size<=4096 or offset+size>len(raw) or not previous<=capture<=cutoff_ns:
            raise ValueError('invalid_native_frame_or_availability')
        payload=raw[offset:offset+size];offset+=size;previous=capture;count+=1
        records=decoder.write_and_decode(payload)
        if len(records)!=1 or bytes(records[0])!=payload:raise ValueError('native_roundtrip_failure')
        yield capture,records[0]
    if count!=expected_count:raise ValueError('native_record_count_mismatch')


def _quote(row, capture, contract, archive_hash):
    top=row.levels[0];b,a=int(top.bid_px),int(top.ask_px)
    if (max(b,a)>=2**63-1 or min(b,a)<=0 or top.bid_sz<=0 or top.ask_sz<=0
            or int(row.flags)&(4|8|32)):return None
    event=Timestamp(int(row.ts_event),int(row.ts_event),int(row.ts_event),str(row.ts_event),
        'Databento GLBX.MDP3 native DBN UTC exchange event',archive_hash,'Databento ts_event UTC nanoseconds',1)
    return Quote(contract,'GLBX.MDP3/XCEC',row.instrument_id,
                 str(Decimal(b)/10**9),str(Decimal(a)/10**9),event,int(row.ts_recv),capture,archive_hash,AUTHENTIC)


def replay(request):
    import databento_dbn as dbn
    for path,expected_hash in request['files'].items():
        if sha(path)!=expected_hash:raise ValueError('request_evidence_changed')
    capture=Path(request['capture']);report=json.loads((capture/'report.json').read_text())
    scope=json.loads((capture/'scope.json').read_text())
    if (report['status']!='CAPTURED' or report['errors'] or not report['connections_closed']
            or report['scope']!=scope or report['automatic_retries']!=0):raise ValueError('quarantined_or_inconsistent_capture')
    cutoff=report['capture_end_ns'];ids={v:k for k,v in scope['exact_symbols'].items()}
    records={};counts={}
    for schema,check in report['source_checks'].items():
        records[schema]=list(native_records(capture/(schema+'.native'),expected_hash=check['sha256'],
            expected_count=check['records'],cutoff_ns=cutoff));counts[schema]=len(records[schema])
    capability=DatasetCapability('GLBX.MDP3',('definition','mbp-1','statistics'),
        min(c for c,_ in records['definition']),report['source_checks']['definition']['sha256'])
    definitions={};available={};raw_definitions={};definition_rejections={}
    for cap,row in records['definition']:
        if not isinstance(row,dbn.InstrumentDefMsg):continue
        if row.instrument_id not in ids or row.publisher_id!=1 or str(row.raw_symbol)!=ids[row.instrument_id]:
            raise ValueError('native_definition_outside_exact_capture_scope')
        product=str(row.asset)
        if (str(row.unit_of_measure)!='TRYOZ' or int(row.unit_of_measure_qty)!=100*10**9
                or int(row.min_price_increment)!=100000000
                or int(row.display_factor)!=(10000000 if product=='OG' else 100000000)):
            raise ValueError('unreviewed_native_price_or_multiplier_convention')
        convention=EconomicConvention(product,Decimal('.1'),Decimal(100),'USD_per_troy_oz',SPEC if product=='OG' else FUTURE_SPEC)
        raw_definitions[row.instrument_id]=dict(symbol=str(row.raw_symbol),kind=str(row.instrument_class),
            strike_fixed=int(row.strike_price),expiration_ns=int(row.expiration),
            user_defined_instrument=str(row.user_defined_instrument),definition_record_sha256=hashlib.sha256(bytes(row)).hexdigest())
        try:
            definitions[row.instrument_id]=definition(row,capability=capability,publishers={1:('GLBX.MDP3','GLBX')},
                as_of_ns=cap,convention=convention);available[row.instrument_id]=cap
        except ValueError as exc:
            definition_rejections[str(row.instrument_id)]=str(exc)
    if set(raw_definitions)!=set(ids):raise ValueError('missing_native_definitions')
    latest={};gc_events={}
    for cap,row in records['mbp-1']:
        if not isinstance(row,dbn.MBP1Msg):continue
        if row.instrument_id not in ids or row.publisher_id!=1:raise ValueError('native_quote_scope_mismatch')
        q=_quote(row,cap,ids[row.instrument_id],report['source_checks']['mbp-1']['sha256'])
        if q is None:continue
        latest[row.instrument_id]=q
        if ids[row.instrument_id]=='GCZ6':gc_events.setdefault(int(row.ts_event),[]).append(q)
    interest={}
    for cap,row in records['statistics']:
        if not isinstance(row,dbn.StatMsg):continue
        if row.instrument_id not in ids or row.publisher_id!=1:raise ValueError('native_statistics_scope_mismatch')
        if int(row.stat_type)==9:
            # Corrections are not silently ignored; they quarantine the input.
            oi=normalize_open_interest(row,available_ns=cap);interest[row.instrument_id]=oi
    parent=definitions[scope['exact_symbols']['GCZ6']]
    prior=json.loads(Path(request['basis_reference']).read_text());pairs=[]
    spots={s['source_time_raw']:s for s in report['spot_quotes']}
    for pair in prior['pairs']:
        spot=spots.get(pair['spot_time_assumed_utc']);candidates=gc_events.get(pair['gc_event_ns'],[])
        matches=[q for q in candidates if (Decimal(q.bid),Decimal(q.ask))==(Decimal(pair['gc_bid']),Decimal(pair['gc_ask']))]
        if spot is None or not matches or (spot['bid'],spot['ask'])!=(pair['spot_bid'],pair['spot_ask']):
            raise ValueError('prior_pair_not_supported_by_archived_observations')
        # This conversion deliberately remains a named UTC *hypothesis*. The
        # raw provider timestamp has no offset. No authority reference supplied.
        naive=datetime.strptime(spot['source_time_raw'],'%Y-%m-%d %H:%M:%S')
        ns=int(naive.replace(tzinfo=timezone.utc).timestamp())*10**9
        timestamp=Timestamp(ns,ns,ns+10**9-1,spot['source_time_raw'],
            'FXCM RatesXML3 timezone UNVERIFIED; conditional UTC hypothesis',spot['source_sha256'],None,10**9)
        q=Quote('XAUUSD','FXCM/RatesXML3',0,spot['bid'],spot['ask'],timestamp,
            spot['local_receive_ns'],spot['local_receive_ns'],spot['source_sha256'],AUTHENTIC)
        pairs.append((matches[-1],q))
    clock=scope['clock_review'];error=clock['offset_upper_ns']+int(
        (cutoff-clock['observed_at_ns'])*clock['drift_bound_ppm']/1e6)
    policy=BasisPolicy('phase7 conservative research thresholds inherited Phase6; not empirical certification',
        'GCZ6',parent.metadata.instrument_id,clock_error_bound_ns=error,
        identity_review_reference='native_definition_hashes_and_CME_specifications')
    basis=certify(pairs,policy=policy,cutoff_ns=cutoff)
    legs=[];greeks=[]
    for identity,c in sorted(definitions.items()):
        m=c.metadata
        if m.product!='OG':continue
        convention=OptionConvention('OG','American',m.definition_sha256,SPEC)
        # Adjacent selected strikes are not the exchange listing increment.
        legs.append(ChainLeg(c,convention,latest.get(identity),latest.get(parent.metadata.instrument_id),
            interest.get(identity),available[identity],SPEC,None,None))
        q=latest.get(identity);u=latest.get(parent.metadata.instrument_id)
        if q is not None and u is not None:
            x=GreekInput(float((Decimal(u.bid)+Decimal(u.ask))/2),m.strike_fixed/1e9,
                (m.expiration_ns-cutoff)/(365*86400*1e9),None,m.kind,'American',float(q.bid),float(q.ask),
                cutoff,None,None,SPEC,AUTHENTIC,identity)
            greeks.append(dict(instrument_id=identity,**validated(x)))
    expected=tuple(sorted((m['expiration_ns'],m['strike_fixed'],m['kind']) for m in raw_definitions.values() if m['kind'] in {'C','P'}))
    coverage=assess(legs,underlying=parent,policy=CoveragePolicy('unreviewed_selected_Oct13_scope',expected),
        cutoff_ns=cutoff,evidence_kind=AUTHENTIC)
    context=json.loads(Path(request['technical_reference']).read_text())
    technical={k:dict(provider=v['provider'],source_sha256=v['source_sha256'],completed_count=v['completed_count'],
        last_close_utc=v['last_close_utc'],indicators=v['indicators'],recent_swings=v['recent_swings'],
        unfilled_fvg=v['unfilled_fvg']) for k,v in context.items()}
    return dict(schema='monatise-phase7-genuine-regression-v1',evidence_kind=AUTHENTIC,
        replay_input_sha256=digest(request),as_of_ns=cutoff,freshness='HISTORICAL_CAPTURE_NOT_CURRENT_LIVE',
        market_data=dict(underlying=encode(parent),native_record_counts=counts,native_hashes=report['source_checks'],
            raw_definition_audit={str(i):m for i,m in sorted(raw_definitions.items())},
            native_definition_rejections=definition_rejections,
            raw_selected_OI=[dict(instrument_id=i,symbol=ids[i],strike_fixed=raw_definitions[i]['strike_fixed'],
                kind=raw_definitions[i]['kind'],open_interest=encode(oi),
                standard_definition_validated=i in definitions,gamma_wall=False) for i,oi in sorted(interest.items())],
            quote_timestamps={str(i):encode(q) for i,q in sorted(latest.items())}),
        timestamp_evidence=dict(FXCM_timezone_authoritative=False,precision_ns=10**9,
            local_clock_status='UNAUTHENTICATED_SNTP_RESEARCH_ONLY',
            statement_UTC_documentation_applies_to_XML=False,raw_poll_response_bytes_available=False),
        basis=basis,options=coverage,greeks=greeks,
        gamma=dict(status='INSUFFICIENT_CHAIN_COVERAGE',dealer_gex=None,gamma_flip=None,
            hypothetical_scenarios=[],rejection_reasons=['insufficient_chain_coverage','dated_rate_missing','validated_American_gamma_missing','dealer_inventory_unknown']),
        mappings=[map_level(Decimal(s)/10**9,contract='GCZ6',basis=basis,now_ns=cutoff) for s in sorted({l.contract.metadata.strike_fixed for l in legs})],
        technical_analysis=dict(status='ARCHIVED_CONTEXT_ONLY',snapshots=technical,
            rejection_reasons=['no_hash_bound_canonical_technical_qualification_for_this_capture']),
        trade_qualification_performed=False,incremental_data_cost_usd='0',credit_consumed_usd='0',new_acquisitions=0,**SAFETY)
