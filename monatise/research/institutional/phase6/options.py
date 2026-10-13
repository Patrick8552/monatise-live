"""Independent GC-options research inputs, model diagnostics and context levels.

American standard OG remains on the existing IV model. European scenarios are
explicit model engineering, never accepted as authentic OG or dealer positioning.
"""
from dataclasses import dataclass
from math import isfinite
from decimal import Decimal

from monatise.adapters.databento_identity import timestamp_ns
from monatise.application.gold_options import american_futures,black76,european_greeks
from ..options import analyze,OptionConvention,RateAssumption
from ..models import digest,encode,hash_required,number
from . import SAFETY,POLICY


@dataclass(frozen=True)
class OptionInputReview:
    definition_available_ns: int
    rate_available_ns: int
    settlement: str
    settlement_review_reference: str
    source_review_reference: str
    rate_source_sha256: str

    def __post_init__(self):
        timestamp_ns(self.definition_available_ns);timestamp_ns(self.rate_available_ns)
        hash_required(self.rate_source_sha256)
        if (self.settlement != 'exercise_into_underlying_future' or not self.settlement_review_reference
                or not self.source_review_reference):
            raise ValueError('reviewed_standard_OG_settlement_required')


def inputs(*, option=None,underlying=None,convention=None,rate=None,review=None,cutoff_ns,open_interest=None):
    timestamp_ns(cutoff_ns)
    missing=[k for k,v in dict(option_quote=option,underlying_quote=underlying,exercise_convention=convention,
                              dated_rate=rate,input_review=review).items() if v is None]
    if missing:
        return dict(status='BLOCKED_AUTHENTIC_INPUTS',missing=missing,analytics=None,
                    research_policy=POLICY,**SAFETY)
    if (not isinstance(review,OptionInputReview) or not isinstance(convention,OptionConvention)
            or not isinstance(rate,RateAssumption) or review.rate_source_sha256 != rate.source_sha256
            or not option.contract.metadata.receive_ns <= review.definition_available_ns <= cutoff_ns
            or not rate.as_of_ns <= review.rate_available_ns <= cutoff_ns
            or any(not 0<=cutoff_ns-q.event_ns<=30*10**9 for q in (option,underlying))
            or open_interest is not None and open_interest.available_ns > cutoff_ns):
        raise ValueError('reviewed_option_rate_or_OI_unavailable_as_of_cutoff')
    result=analyze(option=option,underlying=underlying,convention=convention,rate=rate,
                   cutoff_ns=cutoff_ns,open_interest=open_interest)
    return dict(status='AMERICAN_IV_RESEARCH_ONLY',analytics=result,open_interest=encode(open_interest),
        settlement=review.settlement,input_review=encode(review),input_sha256=digest(dict(option=option,
            underlying=underlying,convention=convention,rate=rate,review=review,oi=open_interest,cutoff_ns=cutoff_ns)),
        gamma=None,delta=None,vega=None,theta=None,gamma_flip=None,signed_dealer_gex=None,
        missing=[] if open_interest else ['published_open_interest'],american_greeks_certified=False,
        research_policy=POLICY,**SAFETY)


def american_diagnostics(*,future,strike,years,rate,volatility,kind):
    """Sensitivity stability experiment; not a Greek certification.
    Central price bumps: 0.1% and 0.2%; bounded 200/400/800-step CRR.
    """
    rows=[]
    for steps in (200,400,800):
        central=american_futures(future,strike,years,rate,volatility,kind,steps=steps)
        for fraction in (.001,.002):
            h=future*fraction
            up=american_futures(future+h,strike,years,rate,volatility,kind,steps=steps)
            down=american_futures(future-h,strike,years,rate,volatility,kind,steps=steps)
            rows.append(dict(steps=steps,bump_fraction=fraction,price=central,
                             delta_diagnostic=(up-down)/(2*h),gamma_diagnostic=(up-2*central+down)/h**2))
    return dict(status='ENGINEERING_AMERICAN_SENSITIVITY_DIAGNOSTICS',rows=rows,
        gamma_range=max(r['gamma_diagnostic'] for r in rows)-min(r['gamma_diagnostic'] for r in rows),
        model='futures-martingale-CRR-with-early-exercise-existing-v1',evidence_kind='ENGINEERING_SYNTHETIC',
        certified_greeks=None,american_greeks_certified=False,gamma_levels=None,
        input_sha256=digest(dict(future=future,strike=strike,years=years,rate=rate,volatility=volatility,kind=kind)),**SAFETY)


@dataclass(frozen=True)
class BenchmarkLeg:
    reference: str
    kind: str
    strike: float
    years: float
    rate: float
    volatility: float
    open_interest: int | None
    multiplier: float
    input_sha256: str

    def __post_init__(self):
        hash_required(self.input_sha256)
        if (not self.reference or self.kind not in {'C','P'}
                or any(isinstance(x,bool) or not isfinite(x) for x in (self.strike,self.years,self.rate,self.volatility,self.multiplier))
                or min(self.strike,self.years,self.multiplier)<=0 or not .0001<=self.volatility<=5
                or not -.1<=self.rate<=.5 or not 0<self.years<=10
                or self.open_interest is not None and (type(self.open_interest) is not int or self.open_interest<0)):
            raise ValueError('bounded_explicit_benchmark_inputs_required')


def benchmark_scenarios(*, legs, price_grid, scenarios):
    """Unsigned OI gamma and assumed signed scenarios on an explicit European
    benchmark. Signs are user-supplied inventory assumptions, never inferred OI.
    Gamma roots are interpolated candidate grid crossings, not observed flips.
    """
    if (not 1<=len(legs)<=8 or len({l.reference for l in legs})!=len(legs)
            or not 2<=len(price_grid)<=101 or list(price_grid)!=sorted(set(price_grid))
            or any(number(p,positive=True)<=0 for p in price_grid) or not 1<=len(scenarios)<=8):
        raise ValueError('bounded_unique_benchmark_scenario_scope_required')
    rows=[]; summaries=[]
    for scenario in scenarios:
        signs=scenario.get('signs',{})
        if (not scenario.get('name') or not scenario.get('assumption_reference')
                or set(signs)!={l.reference for l in legs}
                or any(type(s) is not int or s not in {-1,0,1} for s in signs.values())):
            raise ValueError('explicit_per_leg_inventory_assumptions_required')
        curve=[]
        for future in price_grid:
            unsigned=0.; signed=0.; details=[];missing=False
            for leg in legs:
                g=european_greeks(float(future),leg.strike,leg.years,leg.rate,leg.volatility,leg.kind)
                dt=min(1/365,leg.years/10)
                # Calendar theta holding futures, rate and volatility constant.
                theta=-(black76(float(future),leg.strike,leg.years+dt,leg.rate,leg.volatility,leg.kind)-
                        black76(float(future),leg.strike,leg.years-dt,leg.rate,leg.volatility,leg.kind))/(2*dt)
                exposure=None if leg.open_interest is None else g['gamma']*leg.open_interest*leg.multiplier*float(future)**2*.01
                missing |= exposure is None
                if exposure is not None:unsigned+=exposure;signed+=signs[leg.reference]*exposure
                details.append(dict(reference=leg.reference,greeks=dict(g,theta_per_year=theta,theta_per_day=theta/365),
                                    unsigned_gamma_1pct=exposure,assumed_inventory_sign=signs[leg.reference]))
            curve.append(dict(future=str(future),unsigned_gamma_1pct=None if missing else unsigned,
                scenario_signed_gamma_1pct=None if missing else signed,known_unsigned_subtotal=unsigned,legs=details))
        roots=[]
        for a,b in zip(curve,curve[1:]):
            x,y=a['scenario_signed_gamma_1pct'],b['scenario_signed_gamma_1pct']
            if x is not None and y is not None and x*y<0:
                roots.append(float(a['future'])+(float(b['future'])-float(a['future']))*(-x)/(y-x))
        summaries.append(dict(name=scenario['name'],assumption_reference=scenario['assumption_reference'],
            signs=signs,curve=curve,candidate_grid_crossings=roots,zero_exposure_is_not_a_flip=True))
    missing=[l.reference for l in legs if l.open_interest is None]
    oi_by_strike={};oi_by_kind={}
    for leg in legs:
        for table,key in ((oi_by_strike,str(leg.strike)),(oi_by_kind,leg.kind)):
            if key not in table:table[key]=0
            table[key]=None if table[key] is None or leg.open_interest is None else table[key]+leg.open_interest
    return dict(status='ENGINEERING_EUROPEAN_BENCHMARK_SCENARIOS',scenarios=summaries,
        selected_strike_OI=oi_by_strike,selected_call_put_OI=oi_by_kind,missing_OI=missing,
        complete_chain=False,signed_dealer_gex=None,verified_gamma_flip=None,
        units='USD delta-notional sensitivity per 1% futures move',
        assumption='Fixed leg IV, ACT/365F maturity and rates over grid; European Black76 applicability is unverified for standard OG.',
        methodology='existing-Black76-gamma*OI*multiplier*F^2*0.01; explicit assumed inventory signs',
        evidence_kind='ENGINEERING_SYNTHETIC',research_policy=POLICY,
        input_sha256=digest(dict(legs=legs,grid=price_grid,scenarios=scenarios)),**SAFETY)


def map_level(*, level_kind,level,underlying_contract,basis_report,observation_ns,available_ns,
              cutoff_ns,option_expiry_ns=None,assumption_reference=None,option_contract=None,
              level_source_sha256=None,evidence_kind=None):
    """Bind options-derived levels to the exact futures basis model, never orders."""
    for t in (observation_ns,available_ns,cutoff_ns):timestamp_ns(t)
    base=dict(status='MAPPING_UNAVAILABLE',actual_GC_option_strike=None,calculated_GC_gamma_level=None,
              contextual_XAUUSD_level=None,contextual_XAUUSD_interval=None,actual_broker_XAUUSD_price=None,
              context_only=True,**SAFETY)
    try:
        hash_required(level_source_sha256)
        if (level_kind not in {'ACTUAL_OPTION_STRIKE','CALCULATED_GAMMA_SCENARIO'}
                or tuple(basis_report.get('contract',()))!=tuple(underlying_contract.identity)
                or basis_report.get('status')!='RESEARCH_CONTEXT_ESTIMATE'
                or basis_report.get('cutoff_ns')!=cutoff_ns or not observation_ns<=available_ns<=cutoff_ns
                or not 0<=cutoff_ns-observation_ns<=30*10**9 or cutoff_ns>=basis_report['expires_ns']
                or underlying_contract.metadata.product!='GC'
                or evidence_kind not in {'AUTHENTIC_ARCHIVED_RECORD','ENGINEERING_SYNTHETIC'}
                or evidence_kind!=basis_report.get('evidence_kind')
                or number(basis_report['uncertainty'])>number(basis_report['policy']['maximum_uncertainty'])
                or option_expiry_ns is None or not cutoff_ns<option_expiry_ns<=underlying_contract.metadata.expiration_ns
                or level_kind=='CALCULATED_GAMMA_SCENARIO' and not assumption_reference):
            raise ValueError('option_level_contract_expiry_assumptions_or_basis_unavailable')
        original=number(level,positive=True);mapped=original-number(basis_report['basis']);u=number(basis_report['uncertainty'])
        if level_kind=='ACTUAL_OPTION_STRIKE':
            if (option_contract is None or option_contract.metadata.product!='OG'
                    or option_contract.asset_class!='futures_option'
                    or option_contract.multiplier!=underlying_contract.multiplier
                    or option_contract.metadata.underlying_id!=underlying_contract.metadata.instrument_id
                    or option_contract.metadata.publisher_id!=underlying_contract.metadata.publisher_id
                    or option_contract.metadata.receive_ns>available_ns
                    or option_contract.metadata.expiration_ns!=option_expiry_ns
                    or original!=Decimal(option_contract.metadata.strike_fixed)/10**9):
                raise ValueError('actual_option_strike_requires_exact_definition_lineage')
            if level_source_sha256!=option_contract.metadata.definition_sha256:
                raise ValueError('option_strike_source_hash_mismatch')
        if u<0 or mapped-u<=0:raise ValueError('invalid_mapped_options_interval')
        return dict(base,status='OPTIONS_CONTEXT_ESTIMATE',
            actual_GC_option_strike=str(original) if level_kind=='ACTUAL_OPTION_STRIKE' else None,
            calculated_GC_gamma_level=str(original) if level_kind=='CALCULATED_GAMMA_SCENARIO' else None,
            contextual_XAUUSD_level=str(mapped),contextual_XAUUSD_interval=[str(mapped-u),str(mapped+u)],
            actual_broker_XAUUSD_price=basis_report.get('actual_broker_mid'),
            broker_price_observation_ns=basis_report.get('broker_price_observation_ns'),
            level_source_sha256=level_source_sha256,evidence_kind=evidence_kind,
            basis_model_version=basis_report['version'],basis_input_sha256=basis_report['input_sha256'],
            underlying_contract=underlying_contract.identity,cutoff_ns=cutoff_ns,observation_ns=observation_ns,
            available_ns=available_ns,option_expiry_ns=option_expiry_ns,assumption_reference=assumption_reference)
    except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
        return dict(base,rejection_reasons=[str(exc)])
