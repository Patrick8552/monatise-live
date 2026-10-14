"""Bounded representative validation over eligible original market inputs.

No surface completion or zero interpolation. Unvalidated remainder stays null.
"""
from collections import Counter
from math import log1p
from pathlib import Path
import hashlib,json,time
from ..models import digest
from ..phase7.greeks import GreekInput,validated
from . import SAFETY,BASIS_STATUS

SURFACE_STATES=('VALIDATED','MODEL_ONLY','STALE','MISSING_INPUT','NUMERICAL_FAILURE','NOT_COMPUTED')


def representative_ids(inputs, *, maximum=48, strata=None):
    if not 1<=maximum<=64:raise ValueError('bounded_representative_validation_required')
    cells={};family_cells={};strata=strata or {}
    for i,x in sorted(inputs.items()):
        ratio=x.strike/x.future
        family_cells.setdefault((*strata.get(i,('unspecified',0)),x.kind),[]).append((abs(ratio-1),i))
        band=0 if ratio<.85 else 1 if ratio<.98 else 2 if ratio<=1.02 else 3 if ratio<=1.15 else 4
        key=(x.years<7/365,x.years>45/365,x.kind,band)
        cells.setdefault(key,[]).append((abs(ratio-1),i))
    ordered=[min(values)[1] for key,values in sorted(family_cells.items())]
    # Extremes within each band and option side; not just eight ATM successes.
    for key,values in sorted(cells.items()):
        values.sort()
        ordered.extend([values[0][1],values[-1][1]])
    seen=set();result=[]
    for i in ordered+sorted(inputs):
        if i not in seen:seen.add(i);result.append(i)
        if len(result)==maximum:break
    return tuple(result)


def surface(ledger, *, rate_evidence, maximum_validation=48, cache=None, timing_receipt=None):
    rate=json.loads(Path(rate_evidence).read_text());cutoff=ledger['provider_market_cutoff_ns'];inputs={};states={}
    for leg in ledger['contracts']:
        i=leg['instrument_id']
        if not leg['in_capture_scope']:states[i]=dict(status='NOT_COMPUTED',gamma=None,reason='outside_declared_90day_capture_scope');continue
        if leg['quote']['status']=='STALE' or leg['underlying_quote']['status']=='STALE':
            states[i]=dict(status='STALE',gamma=None,reason='original_quote_age_gate');continue
        if leg['normalized_contract'] is None or not leg['pair']['eligible']:
            states[i]=dict(status='MISSING_INPUT',gamma=None,reason='ineligible_definition_or_causal_quote_pair');continue
        q,u=leg['quote'],leg['underlying_quote'];years=(leg['expiration_ns']-cutoff)/(365*86400*1e9)
        if years<=0:states[i]=dict(status='STALE',gamma=None,reason='expired_native_definition');continue
        benchmark=rate['rows'][0]
        annual=log1p(benchmark['percentRate']/100*years*365/360)/years
        inputs[i]=GreekInput((float(u['bid'])+float(u['ask']))/2,leg['strike_fixed']/1e9,years,annual,leg['kind'],'American',
            float(q['bid']),float(q['ask']),cutoff,rate['available_at_ns'],rate['source_sha256'],
            leg['normalized_contract']['convention_reference'],'AUTHENTIC_ARCHIVED_RECORD',i)
        states[i]=dict(status='NOT_COMPUTED',gamma=None,reason='eligible_but_outside_bounded_validation_budget')
    selected=representative_ids(inputs,maximum=maximum_validation,strata={l['instrument_id']:(l['family'],l['underlying_id']) for l in ledger['contracts']})
    source_root=Path(__file__).resolve().parents[3]
    model_sources={str(p.relative_to(source_root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (source_root/'application/gold_options.py',Path(__file__).parent.parent/'phase7/greeks.py')}
    probes=[];cache=Path(cache) if cache else None
    if cache:cache.mkdir(parents=True,exist_ok=True)
    for i in selected:
        x=inputs[i];input_hash=digest(x);key=digest(dict(inputs=x,model_sources=model_sources));path=cache/(key+'.json') if cache else None
        at=time.monotonic()
        reused=bool(path and path.exists())
        if reused:
            saved=json.loads(path.read_text());g=saved['result']
            if saved['model_sources']!=model_sources or saved['result_sha256']!=digest(g):raise ValueError('model_cache_source_or_content_hash_mismatch')
        else:
            g=validated(x)
            if path:
                with path.open('x') as f:json.dump(dict(model_sources=model_sources,result_sha256=digest(g),result=g),f,sort_keys=True,allow_nan=False)
                path.chmod(0o400)
        if g.get('input_sha256')!=input_hash:raise ValueError('model_cache_input_hash_mismatch')
        probes.append(dict(instrument_id=i,elapsed_seconds=time.monotonic()-at,cached=reused))
        ok=g['status']=='VALIDATED_MODEL_SENSITIVITIES'
        states[i]=dict(status='VALIDATED' if ok else 'NUMERICAL_FAILURE',gamma=g['gamma'] if ok else None,
            model_result=g,reason=None if ok else g['rejection_reasons'])
    for leg in ledger['contracts']:leg['Greek']=states[leg['instrument_id']]
    counted=Counter(s['status'] for s in states.values())
    totals={state:counted[state] for state in SURFACE_STATES}
    if timing_receipt:Path(timing_receipt).write_text(json.dumps(dict(probes=probes,fully_recomputing_all_eligible_estimated_seconds=
        sum(p['elapsed_seconds'] for p in probes)/len(probes)*len(inputs) if probes else None),indent=2,sort_keys=True))
    return dict(schema='monatise-phase8-bounded-sensitivity-surface-v1',statuses=totals,eligible_input_count=len(inputs),
        validation_budget=maximum_validation,selected_ids=list(selected),
        remaining_eligible_not_computed=len(inputs)-len(selected),full_surface_certified=False,
        status='PARTIAL_VALIDATED_SURFACE',states={str(i):v for i,v in sorted(states.items())},
        model_inputs_sha256=digest(inputs),model_sources=model_sources,rate=rate,basis_status=BASIS_STATUS,
        model_source='MODEL_GENERATED_NOT_EXCHANGE_PUBLISHED',**SAFETY)
