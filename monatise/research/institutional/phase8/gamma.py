"""Signed sensitivity diagnostics; no dealer inference or production GIL route."""
from collections import defaultdict
from math import isfinite
from ..models import digest
from . import SAFETY,BASIS_STATUS


def scenarios(ledger, *, assumptions):
    if not 1<=len(assumptions)<=8:raise ValueError('bounded_explicit_scenario_assumptions_required')
    contracts=ledger['contracts'];by_underlying=defaultdict(list)
    for row in contracts:by_underlying[row['underlying_id']].append(row)
    output=[];names=set()
    for scenario in assumptions:
        name=scenario['name'];signs=scenario.get('signs')
        if not name or name in names or not scenario.get('assumption_reference'):raise ValueError('unique_named_assumption_reference_required')
        names.add(name)
        if signs is None:
            output.append(dict(name=name,status='POSITIONING_UNKNOWN',net_gamma=None,flip_candidates=None));continue
        if set(signs)!={r['instrument_id'] for r in contracts} or any(type(s) is not int or s not in {-1,0,1} for s in signs.values()):
            raise ValueError('complete_explicit_hypothetical_sign_ledger_required')
        for underlying,rows in sorted(by_underlying.items()):
            included=[];missing=[];strikes=defaultdict(float);expiries=defaultdict(float);total=0.0
            for row in rows:
                oi=row['OI']['value'];g=row['Greek'];gamma=g.get('gamma')
                model=g.get('model_result',{});inputs=model.get('inputs',{})
                if (oi is None or g['status']!='VALIDATED' or gamma is None or not isfinite(gamma) or gamma<0
                        or row['normalized_contract'] is None or model.get('status')!='VALIDATED_MODEL_SENSITIVITIES'
                        or model.get('evidence_kind')!=ledger.get('evidence_kind')
                        or model.get('input_sha256')!=digest(inputs) or inputs.get('native_instrument_id')!=row['instrument_id']
                        or inputs.get('cutoff_ns')!=ledger['provider_market_cutoff_ns']
                        or model.get('gamma')!=gamma):missing.append(row['instrument_id']);continue
                # Raw requested formula: ounce delta-exposure change per $1/oz futures move.
                contribution=signs[row['instrument_id']]*oi*float(row['normalized_contract']['multiplier'])*gamma
                included.append(dict(instrument_id=row['instrument_id'],OI=oi,gamma=gamma,sign=signs[row['instrument_id']],
                    multiplier=row['normalized_contract']['multiplier'],raw_gamma=contribution))
                total+=contribution;strikes[str(row['strike_fixed']/1e9)]+=contribution;expiries[str(row['expiration_ns'])]+=contribution
            # A caller-supplied boolean never substitutes for reviewed coverage.
            complete=not missing and ledger.get('scope_complete') is True and ledger.get('status')=='REVIEWED_SCOPE_COVERED'
            output.append(dict(name=name,underlying_id=underlying,assumption_reference=scenario['assumption_reference'],
                status='CONDITIONAL_SCENARIO_ONLY' if complete else 'PARTIAL_SUBSET_DIAGNOSTIC_NOT_CHAIN_GEX',
                denominator_contracts=len(rows),included_contracts=len(included),missing_contract_ids=missing,
                unknown_missing_exposure_upper_bound=None,raw_subset_gamma=total if included else None,
                qualified_chain_scenario_gamma=total if complete else None,contributions=included,
                strike_concentrations=dict(strikes),expiry_concentrations=dict(expiries),
                price_shock_convention='BASE_MARK_LOCAL_LINEAR_$1_NATIVE_FUTURES_MOVE; NOT_A_REPRICED_CURVE',
                flip_candidates=None,flip_status='INSUFFICIENT_COVERAGE_AND_REPRICED_VALIDATED_CURVE',
                dealer_inventory='UNKNOWN',observed_dealer_GEX=None,institutional_gamma_walls=None))
    return dict(schema='monatise-phase8-native-scenario-diagnostics-v1',scenarios=output,
        units='sum(sign*OI*100*gamma): ounces of delta-exposure change per $1/oz native futures move (oz^2/USD); no F^2 or 1% normalization',
        market_cutoff_ns=ledger['provider_market_cutoff_ns'],scenario_assumptions_observed=False,
        all_results_research_only=True,production_GIL_compatible=False,
        production_design='Native coordinates require separate review/interface; no spot-qualified provider snapshot or routing change',
        basis_status=BASIS_STATUS,spot_mapping=None,input_sha256=digest(dict(ledger=ledger,assumptions=assumptions)),**SAFETY)
