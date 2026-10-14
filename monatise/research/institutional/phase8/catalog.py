"""Family-aware extension of the Phase 7 lifecycle/economic review.

The existing reducer only admits OG/GC; do not rewrite weekly native assets to
fit it. Preserve original records and reduce each publisher/native identity.
"""
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
import hashlib,re
from monatise.adapters.databento_identity import timestamp_ns
from ...databento.datasets import InstrumentMetadata
from ..models import Contract, digest
from ..phase7.udi import reviewed_definition,UDIReview
from . import SAFETY,BASIS_STATUS

WEEKLY_SPEC='https://www.cmegroup.com/rulebook/COMEX/10/1008.pdf'
WEEKLY_FAQ='https://www.cmegroup.com/articles/faqs/metals-weekly-options.html'
GOLD_ROOTS=('OG',)+tuple(f'G{i}{d}' for i in range(1,6) for d in 'MTWR')+tuple(f'OG{i}' for i in range(1,6))
MICRO_ROOTS=('OMG',)+tuple(f'{i}{d}G' for i in range(1,6) for d in ('M','W','F'))


@dataclass(frozen=True)
class WeeklyMetadata(InstrumentMetadata):
    """Isolated extension; the shared production product allowlist stays fixed."""
    def __post_init__(self):
        for t in (self.event_ns,self.receive_ns,self.expiration_ns):timestamp_ns(t)
        match=re.fullmatch(re.escape(self.product)+r'([FGHJKMNQUVXZ])(\d{1,2}) ([CP])(\d+(?:\.\d+)?)',self.raw_symbol)
        terms=dict(self.native_terms)
        if (self.dataset!='GLBX.MDP3' or self.product not in GOLD_ROOTS or self.product=='OG'
                or self.exchange!='XCEC' or self.publisher_id!=1 or type(self.instrument_id) is not int
                or not 0<self.instrument_id<2**32 or not self.event_ns<=self.receive_ns<self.expiration_ns
                or not re.fullmatch(r'[a-f0-9]{64}',self.definition_sha256) or not isinstance(self.native_terms,tuple)
                or any(not isinstance(t,tuple) or len(t)!=2 or any(not isinstance(v,str) for v in t) for t in self.native_terms)
                or len(terms)!=len(self.native_terms) or terms.get('currency')!='USD' or match is None
                or self.kind!=match[3] or type(self.strike_fixed) is not int or not 0<self.strike_fixed<2**63-1
                or Decimal(match[4])*10**9!=self.strike_fixed or type(self.underlying_id) is not int
                or not 0<self.underlying_id<2**32 or type(self.maturity_year) is not int
                or not 1900<=self.maturity_year<=2200 or self.maturity_month!='FGHJKMNQUVXZ'.index(match[1])+1
                or self.maturity_year%10**len(match[2])!=int(match[2])
                or terms.get('unit_of_measure')!='TRYOZ' or terms.get('unit_of_measure_qty')!=str(100*10**9)
                or terms.get('cfi','')[2:3]!='A' or terms.get('min_price_increment') not in {'10000000','100000000'}):
            raise ValueError('validated_exact_immutable_weekly_metadata_required')


def catalogue(records, *, cutoff_ns, replay_completed, requested_roots, source_reference):
    import databento_dbn as dn
    if not 0<cutoff_ns or not source_reference or not set(requested_roots)<=set(GOLD_ROOTS+MICRO_ROOTS+('GC','MGC')):
        raise ValueError('explicit_supported_native_parent_scope_required')
    latest={};seen=set();excluded=0;count=0
    for available,row in records:
        if not isinstance(row,dn.InstrumentDefMsg):continue
        count+=1
        if count>500000:raise ValueError('bounded_catalogue_required')
        if (row.publisher_id!=1 or not 0<row.ts_event<=row.ts_recv or not 0<available<=cutoff_ns
                or str(row.security_update_action) not in {'A','M','D'}):raise ValueError('native_lifecycle_invalid')
        seen.add((row.publisher_id,row.instrument_id))
        if row.leg_count or str(row.asset) not in requested_roots or str(row.instrument_class) not in {'C','P','F'}:
            excluded+=1;continue
        identity=(row.publisher_id,row.instrument_id);index=(int(row.ts_recv),int(row.ts_event));sha=hashlib.sha256(bytes(row)).hexdigest()
        previous=latest.get(identity)
        if previous and index==previous[0] and sha!=previous[3]:raise ValueError('ambiguous_same_clock_native_definition')
        if previous is None or index>previous[0]:latest[identity]=(index,available,row,sha)
    if not count:raise ValueError('genuine_definitions_required')
    active={i[1]:(v[1],v[2]) for i,v in latest.items() if str(v[2].security_update_action)!='D' and v[2].expiration>cutoff_ns}
    options={i:(a,r) for i,(a,r) in active.items() if str(r.instrument_class) in {'C','P'}}
    economic={};rows=[];parts={}
    for i,(available,row) in sorted(options.items()):
        family=str(row.asset);key=(family,int(row.underlying_id),int(row.expiration),int(row.strike_price),str(row.instrument_class))
        if key in economic:raise ValueError('ambiguous_family_economic_identity')
        economic[key]=i
        info=dict(instrument_id=i,publisher_id=int(row.publisher_id),family=family,raw_symbol=str(row.raw_symbol),
            underlying_id=int(row.underlying_id),underlying_symbol=str(row.underlying),expiration_ns=int(row.expiration),
            strike_fixed=int(row.strike_price),kind=str(row.instrument_class),available_ns=available,
            event_ns=int(row.ts_event),provider_receive_ns=int(row.ts_recv),native_sha256=hashlib.sha256(bytes(row)).hexdigest(),
            native_multiplier=str(Decimal(int(row.unit_of_measure_qty))/10**9),native_tick=str(Decimal(int(row.min_price_increment))/10**9),
            unit=str(row.unit_of_measure),currency=str(row.currency),cfi=str(row.cfi),user_defined_instrument=str(row.user_defined_instrument),
            convention='MONTHLY_OG_REVIEW' if family=='OG' else 'WEEKLY_GC_REVIEW' if family in GOLD_ROOTS else 'MICRO_SEPARATE_CATALOGUE_ONLY')
        rows.append(info);parts.setdefault((family,int(row.underlying_id),int(row.expiration)),[]).append(info)
    partitions=[]
    for (family,underlying,expiry),subset in sorted(parts.items()):
        strikes=sorted({x['strike_fixed'] for x in subset})
        keys={(x['strike_fixed'],x['kind']) for x in subset}
        missing=[(s,k) for s in strikes for k in ('C','P') if (s,k) not in keys]
        partitions.append(dict(family=family,underlying_id=underlying,expiry_ns=expiry,contracts=len(subset),strike_pairs=len(strikes),
            calls=sum(x['kind']=='C' for x in subset),puts=sum(x['kind']=='P' for x in subset),
            missing_pairs=missing,strike_min_fixed=min(strikes),strike_max_fixed=max(strikes),
            actual_strikes_fixed=strikes,complete_captured_pair_lattice=not missing))
    report=dict(status='CAPTURED_FAMILY_CATALOGUE' if replay_completed else 'INCOMPLETE_PARENT_REPLAY',
        source_reference=source_reference,cutoff_ns=cutoff_ns,typed_definition_records=count,
        unique_native_identities=len(seen),excluded_multileg_or_out_of_scope=excluded,
        requested_roots=list(requested_roots),family_counts=dict(sorted(Counter(x['family'] for x in rows).items())),
        roots_without_active_observations=sorted(set(requested_roots)-{str(r.asset) for a,r in active.values()}),
        contracts=rows,partitions=partitions,replay_completed=replay_completed,
        basis_status=BASIS_STATUS,whole_exchange_universe_certified=False,**SAFETY)
    report['catalogue_sha256']=digest(report)
    return report,active


def weekly_definition(record, *, underlying,capability,publishers,as_of_ns,review_reference):
    """Hash-bound weekly adapter; original monthly and production gates unchanged."""
    family=str(record.asset)
    if family=='OG':
        return reviewed_definition(record,underlying=underlying,capability=capability,publishers=publishers,
            as_of_ns=as_of_ns,review=UDIReview(hashlib.sha256(bytes(record)).hexdigest(),review_reference))
    capability.require('definition',at_ns=as_of_ns)
    native=hashlib.sha256(bytes(record)).hexdigest()
    match=re.fullmatch(re.escape(family)+r'([FGHJKMNQUVXZ])(\d{1,2}) ([CP])(\d+(?:\.\d+)?)',str(record.raw_symbol))
    tick=Decimal(int(record.min_price_increment))/10**9
    if (family not in GOLD_ROOTS or family=='OG' or not review_reference or not match
            or record.leg_count or str(record.security_type)!='OOF' or str(record.instrument_class) not in {'C','P'}
            or str(record.cfi)[2:3]!='A' or str(record.user_defined_instrument) not in {'Y','N'}
            or str(record.security_update_action) not in {'A','M'} or str(record.exchange)!='XCEC'
            or publishers.get(record.publisher_id)!=('GLBX.MDP3','GLBX')
            or underlying.metadata.product!='GC' or underlying.asset_class!='futures'
            or (record.publisher_id,record.underlying_id,str(record.underlying))!=(underlying.metadata.publisher_id,underlying.metadata.instrument_id,underlying.metadata.raw_symbol)
            or str(record.currency)!='USD' or str(record.strike_price_currency)!='USD' or str(record.unit_of_measure)!='TRYOZ'
            or int(record.unit_of_measure_qty)!=100*10**9 or int(record.display_factor)!=10000000
            or tick not in {Decimal('.01'),Decimal('.1')}
            or not 0<record.ts_event<=record.ts_recv<=as_of_ns<record.expiration<=underlying.metadata.expiration_ns
            or Decimal(match[4])*10**9!=record.strike_price or match[3]!=str(record.instrument_class)):
        raise ValueError('reviewed_exact_native_weekly_GC_contract_required')
    terms=tuple((n,str(getattr(record,n))) for n in ('currency','unit_of_measure','unit_of_measure_qty','display_factor',
        'min_price_increment','min_price_increment_amount','user_defined_instrument','leg_count','cfi'))
    metadata=WeeklyMetadata('GLBX.MDP3',record.publisher_id,record.instrument_id,str(record.raw_symbol),family,'XCEC',
        str(record.instrument_class),int(record.ts_event),int(record.ts_recv),int(record.expiration),record.maturity_year,
        record.maturity_month,int(record.strike_price),record.underlying_id,terms,native)
    return Contract(metadata,'futures_option','USD',tick,Decimal(100),'USD_per_troy_oz',review_reference+':'+WEEKLY_SPEC)
