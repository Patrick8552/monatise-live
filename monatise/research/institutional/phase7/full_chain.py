"""Offline evidence ledger for the complete captured GCZ6 definition scope.

Reuse exact-contract normalization, published OI, coverage and Greek gates.
No clients, paid acquisition, production registration or inferred dealer signs.
"""
from bisect import bisect_right
from collections import Counter
from decimal import Decimal
from math import ceil, log1p
from pathlib import Path
import hashlib,json
from ...databento.live_journal import verify
from ...databento.datasets import DatasetCapability
from ...databento.options import normalize_open_interest
from ..models import digest,encode
from ..normalize import definition,EconomicConvention
from ..options import OptionConvention
from ..runner import source_hashes
from . import SAFETY
from .catalog import reduce_definitions
from .udi import reviewed_definition,UDIReview,OG_SPEC
from .basis import Quote,Timestamp
from .chain import ChainLeg,CoveragePolicy,assess
from .greeks import GreekInput,validated


def partition_rows(rows, *, maximum=512):
    if not 1 <= len(rows) <= 4096 or not 1 <= maximum <= 512:
        raise ValueError('bounded_complete_scope_required')
    count=ceil(len(rows)/maximum)
    groups=[[] for _ in range(count)]
    # Round-robin within each expiry preserves both expiries in each large
    # assessment chunk rather than weakening the existing coverage policy.
    for expiry in sorted({r.contract.metadata.expiration_ns for r in rows}):
        subset=[r for r in rows if r.contract.metadata.expiration_ns==expiry]
        strikes=sorted({r.contract.metadata.strike_fixed for r in subset})
        for index,strike in enumerate(strikes):
            pair=sorted((r for r in subset if r.contract.metadata.strike_fixed==strike),
                        key=lambda r:r.contract.metadata.kind)
            groups[index%count].extend(pair)
    if any(not 1<=len(g)<=maximum for g in groups):
        raise ValueError('complete_scope_partition_exceeds_bound')
    return tuple(tuple(g) for g in groups)


def run(*, captures, rate_evidence, maximum_greek_diagnostics=8):
    import databento_dbn as dbn
    if not 1<=len(captures)<=4 or not 1<=maximum_greek_diagnostics<=8:
        raise ValueError('bounded_capture_and_diagnostic_set_required')
    records={s:[] for s in ('definition','mbp-1','statistics')}
    manifests=[];reports=[];native_seen={s:set() for s in records}
    for capture in captures:
        capture=Path(capture);report=json.loads((capture/'report.json').read_text())
        if (report['status']!='CAPTURED' or report['quality']['quarantined']
                or set(report['replay_completed_schemas'])!=set(records)):
            raise ValueError('complete_nonquarantined_native_replays_required')
        reports.append(report)
        for schema in records:
            manifest,frames=verify(capture/schema);manifests.append(dict(manifest))
            decoder=dbn.DBNDecoder(has_metadata=False,input_version=3)
            for available,payload in frames:
                decoded=decoder.write_and_decode(payload)
                if len(decoded)!=1 or bytes(decoded[0])!=payload:
                    raise ValueError('full_scope_native_roundtrip_failed')
                # Deduplicate an explicitly overlapping incremental replay,
                # keeping the earliest observed local receipt of original bytes.
                key=hashlib.sha256(payload).hexdigest()
                if key not in native_seen[schema]:
                    native_seen[schema].add(key);records[schema].append((available,decoded[0],key))
    if any(reports[i]['capture_end_ns']>=reports[i+1]['capture_end_ns'] for i in range(len(reports)-1)):
        raise ValueError('captures_must_be_causally_ordered')
    cutoff=reports[-1]['capture_end_ns']
    catalog,active=reduce_definitions([(cap,row) for cap,row,h in records['definition']],
        cutoff_ns=cutoff,replay_completed=True,source_reference=digest(manifests))
    if 41271 not in active:raise ValueError('current_native_GCZ6_definition_required')
    selected={x['instrument_id'] for x in catalog['selected_contracts']}
    if not 1<=len(selected)<=4096:raise ValueError('bounded_full_GCZ6_catalog_scope_required')
    exact_scope=set(reports[-1]['scope']['exact_symbols'].values())-{41271}
    allowed_quote_ids=exact_scope|{41271}
    newly_unsubscribed=sorted(selected-exact_scope)
    capability=DatasetCapability('GLBX.MDP3',tuple(records),
        min(cap for cap,row,h in records['definition']),digest(manifests))
    cap,parent_row=active[41271]
    if (str(parent_row.unit_of_measure)!='TRYOZ' or int(parent_row.unit_of_measure_qty)!=100*10**9
            or int(parent_row.display_factor)!=100000000 or int(parent_row.min_price_increment)!=100000000):
        raise ValueError('native_GCZ6_economics_mismatch')
    parent=definition(parent_row,capability=capability,publishers={1:('GLBX.MDP3','GLBX')},as_of_ns=cap,
        convention=EconomicConvention('GC',Decimal('.1'),Decimal(100),'USD_per_troy_oz',
                                      'https://www.cmegroup.com/rulebook/COMEX/1a/113.pdf'))
    contracts={};definition_errors={}
    for identity in sorted(selected):
        available,row=active[identity]
        try:
            contracts[identity]=reviewed_definition(row,underlying=parent,capability=capability,
                publishers={1:('GLBX.MDP3','GLBX')},as_of_ns=available,
                review=UDIReview(hashlib.sha256(bytes(row)).hexdigest(),'phase7-full-native-UDI-outright-review'))
        except ValueError as exc:definition_errors[str(identity)]=str(exc)
    latest={};latest_indices={};futures=[];invalid_quotes=Counter();clock_offsets=[]
    market_asof=0
    for available,row,h in records['mbp-1']:
        if not isinstance(row,dbn.MBP1Msg):continue
        if row.publisher_id!=1 or row.instrument_id not in allowed_quote_ids:
            raise ValueError('full_scope_quote_identity_mismatch')
        market_asof=max(market_asof,int(row.ts_recv))
        clock_offsets.append(available-int(row.ts_recv))
        index=(int(row.ts_recv),int(row.ts_event),int(row.sequence))
        if index<latest_indices.get(row.instrument_id,(0,0,0)):continue
        latest_indices[row.instrument_id]=index
        top=row.levels[0];b,a=int(top.bid_px),int(top.ask_px)
        if (max(b,a)>=2**63-1 or min(b,a)<=0 or b>a or min(top.bid_sz,top.ask_sz)<=0
                or int(row.flags)&(4|8|32) or row.ts_event>row.ts_recv):
            latest.pop(row.instrument_id,None);invalid_quotes[row.instrument_id]+=1;continue
        stamp=Timestamp(row.ts_event,row.ts_event,row.ts_event,str(row.ts_event),
                        'Databento native UTC ts_event',h,'Databento UTC epoch nanoseconds',1)
        q=Quote('GCZ6' if row.instrument_id==41271 else str(active[row.instrument_id][1].raw_symbol),
            'GLBX.MDP3/XCEC',row.instrument_id,str(Decimal(b)/10**9),str(Decimal(a)/10**9),
            stamp,int(row.ts_recv),available,h,'AUTHENTIC_ARCHIVED_RECORD')
        latest[row.instrument_id]=q
        if row.instrument_id==41271:futures.append(q)
    if market_asof<=0:raise ValueError('native_provider_quote_clock_required')
    futures.sort(key=lambda q:(q.event.nominal_ns,q.provider_receive_ns))
    times=[q.event.nominal_ns for q in futures]
    oi_latest={};oi_indices={};oi_errors={};oi_rows=0
    for available,row,h in records['statistics']:
        if not isinstance(row,dbn.StatMsg) or int(row.stat_type)!=9:continue
        oi_rows+=1
        if row.publisher_id!=1 or row.instrument_id not in allowed_quote_ids:
            raise ValueError('full_scope_OI_identity_mismatch')
        index=(int(row.ts_recv),int(row.ts_event))
        if index<oi_indices.get(row.instrument_id,(0,0)):continue
        oi_indices[row.instrument_id]=index
        try:
            oi_latest[row.instrument_id]=normalize_open_interest(row,available_ns=available)
            oi_errors.pop(str(row.instrument_id),None)
        except ValueError as exc:
            oi_latest.pop(row.instrument_id,None);oi_errors[str(row.instrument_id)]=str(exc)
    legs=[];paired={}
    for identity,c in sorted(contracts.items()):
        q=latest.get(identity);u=None
        if q is not None:
            at=bisect_right(times,q.event.nominal_ns)-1
            if at>=0:u=futures[at];paired[identity]=(q,u)
        legs.append(ChainLeg(c,OptionConvention('OG','American',c.metadata.definition_sha256,OG_SPEC),q,u,
            oi_latest.get(identity),active[identity][0],OG_SPEC,'5',
            'CME Rule300.20 and actual native catalog strike lattice'))
    partitions=[]
    for group in partition_rows(legs):
        expected=tuple(sorted((l.contract.metadata.expiration_ns,l.contract.metadata.strike_fixed,l.contract.metadata.kind) for l in group))
        partitions.append(assess(group,underlying=parent,policy=CoveragePolicy('full_captured_GCZ6_catalog_partition',
            expected,digest(expected),'native_parent_replay_completed_full_scope'),
            cutoff_ns=market_asof,evidence_kind='AUTHENTIC_ARCHIVED_RECORD'))
    rejection_counts=Counter(reason for p in partitions for row in p['contracts'] for reason in row['rejection_reasons'])
    missing_oi=sorted(selected-set(oi_latest));missing_quotes=sorted(selected-set(latest))
    totals={kind:sum(oi_latest[i].contracts for i,c in contracts.items() if c.metadata.kind==kind and i in oi_latest) for kind in ('C','P')}
    concentrations={}
    for i,c in contracts.items():
        k=(c.metadata.expiration_ns,c.metadata.strike_fixed);values=concentrations.setdefault(k,{'C':None,'P':None})
        if i in oi_latest:values[c.metadata.kind]=oi_latest[i].contracts
    ranks=[dict(expiration_ns=e,strike=str(Decimal(s)/10**9),call_OI=v['C'],put_OI=v['P'],
                combined_OI=None if None in v.values() else sum(v.values()),gamma_wall=False,
                positioning='UNKNOWN') for (e,s),v in sorted(concentrations.items())]
    rate=json.loads(Path(rate_evidence).read_text())
    if rate['available_at_ns']>cutoff:raise ValueError('dated_rate_not_locally_available')
    benchmark=rate['rows'][0];diagnostics=[]
    underlying=latest.get(41271)
    near=float((Decimal(underlying.bid)+Decimal(underlying.ask))/2) if underlying else 4200
    candidates=sorted(paired,key=lambda i:(abs(contracts[i].metadata.strike_fixed/1e9-near),contracts[i].metadata.expiration_ns,i))
    for identity in candidates[:maximum_greek_diagnostics]:
        q,u=paired[identity];c=contracts[identity]
        reasons=[]
        if (not 0<=market_asof-q.event.nominal_ns<=30*10**9 or not 0<=market_asof-u.event.nominal_ns<=30*10**9
                or abs(q.event.nominal_ns-u.event.nominal_ns)>10**9):reasons.append('stale_or_asynchronous_model_quotes')
        years=(c.metadata.expiration_ns-market_asof)/(365*86400*1e9)
        annual=log1p(benchmark['percentRate']/100*years*365/360)/years
        if reasons:g=dict(status='REJECTED',gamma=None,iv=None,rejection_reasons=reasons,**SAFETY)
        else:
            inputs=GreekInput(float((Decimal(u.bid)+Decimal(u.ask))/2),c.metadata.strike_fixed/1e9,years,annual,
                c.metadata.kind,'American',float(q.bid),float(q.ask),market_asof,rate['available_at_ns'],
                rate['source_sha256'],OG_SPEC,'AUTHENTIC_ARCHIVED_RECORD',identity)
            g=validated(inputs)
        diagnostics.append(dict(instrument_id=identity,symbol=c.metadata.raw_symbol,
            market_asof_clock='Databento ts_recv maximum in archived quotes',
            wall_clock_freshness_certified=False,**g))
    source_hash=digest(source_hashes(Path(__file__).resolve().parents[4]))
    return dict(schema='monatise-phase7-full-GCZ6-scope-v1',capture_asof_local_ns=cutoff,
        quote_asof_provider_receive_ns=market_asof,provider_market_asof_is_not_local_availability=True,
        local_clock_certified=False,local_receive_minus_provider_ns_range=[min(clock_offsets),max(clock_offsets)],
        source_hashes_sha256=source_hash,input_sha256=digest(dict(manifests=manifests,rate=rate,cutoff=cutoff,code=source_hash)),
        native_journals=manifests,typed_record_counts=[r['typed_record_counts'] for r in reports],
        deduplicated_native_record_counts={s:len(v) for s,v in records.items()},catalog=catalog,
        subscribed_option_count=len(exact_scope),new_unsubscribed_option_ids=newly_unsubscribed,
        normalized_option_count=len(contracts),definition_rejections=definition_errors,
        options=dict(status='INSUFFICIENT_CHAIN_COVERAGE' if rejection_counts or definition_errors or newly_unsubscribed else 'REVIEWED_GCZ6_SCOPE_COVERED',
            captured_definition_scope='All captured current GCZ6-linked OG calls/puts, both expiries and complete listed strike tails',
            whole_exchange_chain_certified=False,OI_clearing_finality_certified=False,
            partitions=partitions,rejection_counts=dict(sorted(rejection_counts.items())),
            missing_two_sided_quote_ids=missing_quotes,missing_published_OI_ids=missing_oi,OI_errors=oi_errors,
            OI_record_count=oi_rows,known_OI_subtotals=totals,complete_OI_totals=totals if not missing_oi else None,
            concentrations=ranks,OI_reference_dates_ns=sorted({v.reference_ns for i,v in oi_latest.items() if i in selected}),
            OI_published_range_ns=[min(v.published_ns for i,v in oi_latest.items() if i in selected),max(v.published_ns for i,v in oi_latest.items() if i in selected)] if selected&oi_latest.keys() else None),
        underlying_latest_quote=encode(underlying),invalid_quote_record_counts=dict(invalid_quotes),rate=rate,
        greeks_diagnostic_subset=diagnostics,remaining_Greeks='NOT_COMPUTED_OR_VALIDATED',
        basis=dict(status='REJECTED',estimate=None,uncertainty=None,quote_event_ns=None,
                   reasons=['TradingView bid/ask event/receive UTC unavailable','Local clock/drift unreviewed']),
        gamma=dict(status='BLOCKED',dealer_inventory=None,dealer_gex=None,gamma_flip=None,gamma_wall=None,
                   reasons=['Full validated sensitivities missing','Dealer signs unobserved','Quote quality/clearing finality not certified']),
        spot_mapping=None,decision='NO-TRADE',grid_setup='UNAVAILABLE',recommended_risk_percent=0,
        expected_incremental_data_cost_usd='0',paid_acquisitions=0,
        actual_invoice_reconciliation='UNVERIFIED',**SAFETY)
