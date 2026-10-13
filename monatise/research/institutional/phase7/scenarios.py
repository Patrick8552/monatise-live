"""Explicit hypothetical inventory scenarios over validated sensitivity curves.

OI is unsigned. This module never asserts observed dealer gamma, and never
promotes high aggregate OI to a gamma wall. Bracketed roots are conditional on
the covered scope, rates, sticky-strike volatility and stated sign assignments.
"""
from math import isfinite
from ..models import digest
from . import SAFETY


def exposures(chain, *, scenarios, futures_grid, curve, model_reference):
    base=dict(status='INSUFFICIENT_CHAIN_COVERAGE',scenarios=[],gamma_flip=None,
              observed_dealer_gex=None,independent_dealer_positioning=None, **SAFETY)
    if chain['status']!='REVIEWED_SCOPE_COVERED' or not chain['scope_complete']:
        base['rejection_reasons']=chain['rejection_reasons'];return base
    if (not model_reference or not 3<=len(futures_grid)<=33 or not 1<=len(scenarios)<=8
            or any(not isfinite(f) or f<=0 for f in futures_grid)
            or list(futures_grid)!=sorted(set(futures_grid))): raise ValueError('bounded_reviewed_scenario_grid_required')
    contracts={r['contract']['metadata']['instrument_id']:r for r in chain['contracts']}
    strikes=[r['contract']['metadata']['strike_fixed']/1e9 for r in contracts.values()]
    if futures_grid[0]<min(strikes) or futures_grid[-1]>max(strikes):
        base['rejection_reasons']=['scenario_grid_outside_reviewed_strike_coverage'];return base
    output=[];cache={}
    def evaluate(f,signs):
        if f not in cache:cache[f]=curve(f)
        sensitivity=cache[f]
        if set(sensitivity)!=set(contracts): raise ValueError('complete_sensitivity_curve_required')
        total=0.0;unsigned=0.0;per_leg={}
        for identity,row in contracts.items():
            g=sensitivity[identity];gamma=g.get('gamma')
            if (g.get('status')!='VALIDATED_MODEL_SENSITIVITIES'
                    or g.get('evidence_kind')!=chain['evidence_kind'] or not g.get('input_sha256')
                    or gamma is None or not isfinite(gamma) or gamma<0):
                raise ValueError('unvalidated_sensitivity_curve')
            inputs=g.get('inputs',{})
            m=row['contract']['metadata']
            if (inputs.get('native_instrument_id')!=identity or inputs.get('future')!=f
                    or inputs.get('strike')!=m['strike_fixed']/1e9 or inputs.get('kind')!=m['kind']
                    or inputs.get('style')!='American' or inputs.get('cutoff_ns')!=chain['cutoff_ns']):
                raise ValueError('sensitivity_contract_model_or_clock_mismatch')
            oi=row['open_interest']
            if oi is None:raise ValueError('missing_OI_cannot_be_zero')
            quantity=gamma*oi['contracts']*float(row['contract']['multiplier'])*f*f*.01
            unsigned+=quantity;per_leg[str(identity)]=signs[identity]*quantity;total+=per_leg[str(identity)]
        return dict(future=f,hypothetical_signed_gamma_usd_per_1pct=total,
                    unsigned_gamma_weighted_OI=unsigned,per_leg_scenario_gamma=per_leg)
    names=set()
    for scenario in scenarios:
        name=scenario['name'];signs=scenario.get('signs')
        if name in names or not name:raise ValueError('unique_scenario_names_required')
        names.add(name)
        if signs is None:
            output.append(dict(name=name,status='POSITIONING_UNKNOWN',roots=None,curve=None));continue
        if (not scenario.get('assumption_reference') or set(signs)!=set(contracts)
                or any(type(v) is not int or v not in {-1,0,1} for v in signs.values())):
            raise ValueError('explicit_per_contract_hypothetical_signs_required')
        try:
            points=[evaluate(f,signs) for f in futures_grid];roots=[]
            for a,b in zip(points,points[1:]):
                lo,hi=a['future'],b['future'];ga=a['hypothetical_signed_gamma_usd_per_1pct'];gb=b['hypothetical_signed_gamma_usd_per_1pct']
                # Zero nodes and flat-zero ranges are not proven sign changes.
                if ga*gb>=0:continue
                evaluations=0
                while hi-lo>.1 and evaluations<24:
                    middle=(lo+hi)/2;gm=evaluate(middle,signs)['hypothetical_signed_gamma_usd_per_1pct'];evaluations+=1
                    if gm==0:
                        lo=middle-.025;hi=middle+.025;break
                    if ga*gm<0:hi=middle
                    else:lo=middle;ga=gm
                roots.append(dict(candidate_gc_interval=[lo,hi],original_bracket=[a['future'],b['future']],
                    evaluations=evaluations,status='HYPOTHETICAL_SCENARIO_SIGN_TRANSITION'))
            output.append(dict(name=name,status='SCENARIO_ONLY',assumption_reference=scenario['assumption_reference'],
                signs={str(k):v for k,v in signs.items()},curve=points,roots=roots,
                root_limit='Grid may miss multiple or tangential roots; no global uniqueness claim.'))
        except (ValueError,TypeError,ArithmeticError) as exc:
            output.append(dict(name=name,status='REJECTED',roots=None,curve=None,rejection_reasons=[str(exc)]))
    base.update(status='SCENARIO_RESEARCH_ONLY',scenarios=output,model_reference=model_reference,
                scope_sha256=chain['scope_sha256'],input_sha256=digest(dict(chain=chain,scenarios=scenarios,
                futures_grid=futures_grid,model_reference=model_reference)),
                rejection_reasons=['dealer_inventory_not_observed'],
                units='USD delta-notional change per 1% futures move; gamma * OI * 100 * F^2 * .01')
    return base
