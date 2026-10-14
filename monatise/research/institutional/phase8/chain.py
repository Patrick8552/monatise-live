"""Original-record coverage ledger for an explicitly bounded family universe."""
from bisect import bisect_right
from collections import Counter
from decimal import Decimal
from pathlib import Path
import hashlib,json
from ...databento.live_journal import verify
from ...databento.datasets import DatasetCapability
from ..models import digest,encode
from ..normalize import definition,EconomicConvention
from .catalog import catalogue,weekly_definition,GOLD_ROOTS
from .eligibility import oi_eligibility,quote_eligibility,pair_eligibility
from . import SAFETY,BASIS_STATUS


def load_journals(journals):
    """Verify durable framing/quality and exact native decoder roundtrips."""
    import databento_dbn as dn
    if not 1<=len(journals)<=16:raise ValueError('bounded_native_journal_set_required')
    rows={'definition':[],'mbp-1':[],'statistics':[]};seen={k:set() for k in rows};manifests=[]
    for path in journals:
        m,frames=verify(path);schema=m['schema'];manifests.append(m)
        if schema not in rows or not m['checkpoint'].get('replay_completed'):raise ValueError('required_native_replay_completion')
        decoder=dn.DBNDecoder(has_metadata=False,input_version=3)
        for at,payload in frames:
            decoded=decoder.write_and_decode(payload)
            if len(decoded)!=1 or bytes(decoded[0])!=payload:raise ValueError('native_record_roundtrip_failure')
            sha=hashlib.sha256(payload).hexdigest()
            if sha not in seen[schema]:seen[schema].add(sha);rows[schema].append((at,decoded[0],sha))
    return rows,manifests


def coverage(*,journals,requested_roots,scope_ids,local_cutoff_ns):
    import databento_dbn as dn
    rows,manifests=load_journals(journals)
    cat,active=catalogue([(at,r) for at,r,h in rows['definition']],cutoff_ns=local_cutoff_ns,
        replay_completed=True,requested_roots=requested_roots,source_reference=digest(manifests))
    scope=set(scope_ids)
    if not 1<=len(scope)<=16384:raise ValueError('bounded_exact_option_scope_required')
    missing_scope=scope-{x['instrument_id'] for x in cat['contracts']}
    if missing_scope:raise ValueError('captured_option_scope_no_longer_matches_current_catalogue')
    capability=DatasetCapability('GLBX.MDP3',('definition','mbp-1','statistics'),min(at for at,r,h in rows['definition']),digest(manifests))
    futures={};contracts={};definition_errors={}
    for i,(at,row) in active.items():
        if str(row.asset)=='GC' and str(row.instrument_class)=='F':
            try:
                if str(row.unit_of_measure)!='TRYOZ' or row.unit_of_measure_qty!=100*10**9 or row.min_price_increment!=100000000:
                    raise ValueError('exact_native_GC_economics_required')
                futures[i]=definition(row,capability=capability,publishers={1:('GLBX.MDP3','GLBX')},as_of_ns=at,
                    convention=EconomicConvention('GC',Decimal('.1'),Decimal(100),'USD_per_troy_oz','https://www.cmegroup.com/rulebook/COMEX/1a/113.pdf'))
            except ValueError as exc:definition_errors[str(i)]=str(exc)
    for i in sorted(scope):
        at,row=active[i]
        try:
            contracts[i]=weekly_definition(row,underlying=futures[row.underlying_id],capability=capability,
                publishers={1:('GLBX.MDP3','GLBX')},as_of_ns=at,review_reference='phase8-hash-bound-family-contract-review')
        except (ValueError,KeyError) as exc:definition_errors[str(i)]=str(exc)
    quotes={};quote_indices={};future_quotes={};market_cutoff=0
    for available,row,h in rows['mbp-1']:
        if not isinstance(row,dn.MBP1Msg):continue
        if row.publisher_id!=1:raise ValueError('native_quote_publisher_mismatch')
        if row.instrument_id not in scope and row.instrument_id not in futures:continue
        market_cutoff=max(market_cutoff,int(row.ts_recv))
        index=(int(row.ts_recv),int(row.ts_event),int(row.sequence))
        if index<quote_indices.get(row.instrument_id,(0,0,0)):continue
        quotes[row.instrument_id]=(available,row,h);quote_indices[row.instrument_id]=index
        if row.instrument_id in futures:future_quotes.setdefault(row.instrument_id,[]).append((available,row,h))
    if not market_cutoff:raise ValueError('native_provider_market_cutoff_required')
    times={}
    for i,values in future_quotes.items():
        values.sort(key=lambda x:(x[1].ts_event,x[1].ts_recv,x[1].sequence));times[i]=[int(x[1].ts_event) for x in values]
    oi_rows={};oi_indices={};oi_observation_count=Counter();quote_observation_count=Counter()
    for at,row,h in rows['mbp-1']:
        if isinstance(row,dn.MBP1Msg):quote_observation_count[row.instrument_id]+=1
    for available,row,h in rows['statistics']:
        if not isinstance(row,dn.StatMsg) or int(row.stat_type)!=9:continue
        if row.publisher_id!=1:raise ValueError('native_OI_publisher_mismatch')
        oi_observation_count[row.instrument_id]+=1;index=(int(row.ts_recv),int(row.ts_event))
        if index>=oi_indices.get(row.instrument_id,(0,0)):
            oi_rows[row.instrument_id]=(available,row,h);oi_indices[row.instrument_id]=index
    ledger=[]
    for c in cat['contracts']:
        i=c['instrument_id'];captured=i in scope
        observed=oi_rows.get(i);oi=oi_eligibility(observed[1] if observed else None,identity=(1,i),available_ns=observed[0] if observed else 0,
            local_cutoff_ns=local_cutoff_ns,market_cutoff_ns=market_cutoff,captured=captured,entitled=True if captured else None)
        q=quotes.get(i);qinfo=quote_eligibility(q[1] if q else None,identity=(1,i),market_cutoff_ns=market_cutoff,
            available_ns=q[0] if q else 0,local_cutoff_ns=local_cutoff_ns)
        qinfo['record_sha256']=q[2] if q else None
        if not captured:qinfo.update(status='NOT_CAPTURED',eligible=False,reasons=['outside_declared_quote_capture_scope'])
        underlying=None
        if q and c['underlying_id'] in times:
            position=bisect_right(times[c['underlying_id']],q[1].ts_event)-1
            if position>=0:underlying=future_quotes[c['underlying_id']][position]
        uinfo=quote_eligibility(underlying[1] if underlying else None,identity=(1,c['underlying_id']),market_cutoff_ns=market_cutoff,
            available_ns=underlying[0] if underlying else 0,local_cutoff_ns=local_cutoff_ns)
        uinfo['record_sha256']=underlying[2] if underlying else None
        pair=pair_eligibility(qinfo,uinfo)
        normalized=contracts.get(i);definition_error=definition_errors.get(str(i))
        ledger.append(dict(**c,in_capture_scope=captured,normalized_contract=encode(normalized),definition_error=definition_error,
            OI=oi,quote=qinfo,underlying_quote=uinfo,pair=pair,observed_quote_records=quote_observation_count[i],
            observed_OI_records=oi_observation_count[i],Greek=dict(status='NOT_COMPUTED',gamma=None,reason='model_work_not_yet_evaluated'),
            exposure_missing=oi['value'] is None,OI_not_available_is_not_zero=True))
    groups={}
    for leg in ledger:
        key=(leg['family'],leg['underlying_id'],leg['expiration_ns']);groups.setdefault(key,[]).append(leg)
    aggregate=[]
    for key,legs in sorted(groups.items()):
        pair_map={}
        for l in legs:pair_map.setdefault(l['strike_fixed'],{})[l['kind']]=l
        counts=Counter(l['OI']['status'] for l in legs);qr=Counter(reason for l in legs for reason in l['quote']['reasons']+l['pair']['reasons'])
        aggregate.append(dict(family=key[0],underlying_id=key[1],expiry_ns=key[2],denominator_contracts=len(legs),
            captured_contracts=sum(l['in_capture_scope'] for l in legs),normalized_contracts=sum(l['normalized_contract'] is not None for l in legs),
            OI_states=dict(counts),quote_eligible=sum(l['quote']['eligible'] for l in legs),paired_quote_eligible=sum(l['pair']['eligible'] for l in legs),
            quote_rejection_counts=dict(qr),strike_pair_denominator=len(pair_map),
            observed_complete_call_put_pairs=sum(set(p)=={'C','P'} for p in pair_map.values()),
            OI_eligible_pairs=sum(set(p)=={'C','P'} and all(x['OI']['value'] is not None for x in p.values()) for p in pair_map.values()),
            quote_eligible_pairs=sum(set(p)=={'C','P'} and all(x['pair']['eligible'] for x in p.values()) for p in pair_map.values()),
            known_OI_subtotal=sum(l['OI']['value'] for l in legs if l['OI']['value'] is not None),
            missing_exposure_contracts=sum(l['OI']['value'] is None for l in legs),unknown_missing_exposure_upper_bound=None))
    return dict(schema='monatise-phase8-coverage-ledger-v1',catalogue=cat,contracts=ledger,partitions=aggregate,
        local_capture_cutoff_ns=local_cutoff_ns,provider_market_cutoff_ns=market_cutoff,scope_ids=sorted(scope),
        normalized_contract_count=len(contracts),definition_errors=definition_errors,
        native_manifests=manifests,deduplicated_record_counts={s:len(r) for s,r in rows.items()},
        clock_certificate=False,evidence_kind='AUTHENTIC_ARCHIVED_RECORD',basis_status=BASIS_STATUS,spot_mapping=None,whole_exchange_chain_certified=False,
        scope_complete=False,status='INSUFFICIENT_CHAIN_COVERAGE',**SAFETY)
