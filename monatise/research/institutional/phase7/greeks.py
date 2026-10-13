"""Model sensitivities, never exchange-published Greeks or dealer inventory.

Reuse existing Black76/CRR/IV. An independently discretized implicit finite
difference American obstacle solver validates prices/sensitivities. Projection
is first-order in time, so two refinements and bump sizes must agree. Failure
returns null Greeks. ACT/365F; theta per calendar day, vega per unit volatility.
"""
from dataclasses import dataclass, replace
from math import exp, isfinite

from monatise.application.gold_options import (american_futures, black76,
    european_greeks, implied_volatility, _inputs)
from ..models import digest, encode
from . import SAFETY


@dataclass(frozen=True)
class GreekInput:
    future: float
    strike: float
    years: float
    rate: float | None
    kind: str
    style: str
    bid: float
    ask: float
    cutoff_ns: int
    rate_as_of_ns: int | None
    rate_source_sha256: str | None
    convention_reference: str | None
    evidence_kind: str
    native_instrument_id: int | None = None


def american_fd(future,strike,years,rate,volatility,kind,*,space=400,time=400):
    """Implicit Euler, uniform futures grid, Thomas solve, intrinsic obstacle.

    Futures drift is zero. Boundaries use American intrinsic/discounted payoff;
    the upper boundary is at four times max(F,K), well outside test domains.
    """
    _inputs(future,strike,years,rate,volatility,kind)
    if not 100<=space<=1600 or not 100<=time<=1600: raise ValueError('bounded_FD_mesh_required')
    ds=4*max(future,strike)/space;dt=years/time;sign=1 if kind=='C' else -1
    intrinsic=[max(sign*(i*ds-strike),0) for i in range(space+1)];values=intrinsic[:]
    a=[-.5*volatility**2*i*i*dt for i in range(1,space)]
    diagonal=[1-2*v+rate*dt for v in a]; upper=a[:]
    for step in range(1,time+1):
        elapsed=step*dt
        left=max(intrinsic[0],intrinsic[0]*exp(-rate*elapsed))
        right=max(intrinsic[-1],intrinsic[-1]*exp(-rate*elapsed))
        rhs=values[1:-1];rhs[0]-=a[0]*left;rhs[-1]-=upper[-1]*right
        cp=[];dp=[]
        for j in range(space-1):
            denominator=diagonal[j]-(a[j]*cp[j-1] if j else 0)
            if denominator<=0: raise ValueError('FD_solve_unstable')
            cp.append(upper[j]/denominator)
            dp.append((rhs[j]-(a[j]*dp[j-1] if j else 0))/denominator)
        solved=[0.0]*(space-1);solved[-1]=dp[-1]
        for j in range(space-3,-1,-1): solved[j]=dp[j]-cp[j]*solved[j+1]
        values=[left]+[max(v,intrinsic[j+1]) for j,v in enumerate(solved)]+[right]
    location=future/ds;i=int(location);fraction=location-i
    return values[i]*(1-fraction)+values[i+1]*fraction


def sensitivities(price, x, iv, *, fraction):
    f,k,t,r=x.future,x.strike,x.years,x.rate;h=f*fraction
    v=min(.002,iv/4);dt=min(1/365,t/10)
    p=price(f,k,t,r,iv,x.kind);up=price(f+h,k,t,r,iv,x.kind);down=price(f-h,k,t,r,iv,x.kind)
    return dict(price=p,delta=(up-down)/(2*h),gamma=(up-2*p+down)/(h*h),
        vega=(price(f,k,t,r,iv+v,x.kind)-price(f,k,t,r,iv-v,x.kind))/(2*v),
        theta=(price(f,k,t-dt,r,iv,x.kind)-price(f,k,t+dt,r,iv,x.kind))/(2*dt*365))


def validated(x: GreekInput, *, price_absolute_tolerance=.2, relative_tolerance=.15):
    try:input_hash=digest(x)
    except ValueError:input_hash=None
    result=dict(status='REJECTED',iv=None,delta=None,gamma=None,vega=None,theta=None,
        source='MODEL_GENERATED_NOT_EXCHANGE_PUBLISHED',assumptions=dict(day_count='ACT/365F',
        rate='dated_continuously_compounded_flat_rate',volatility='flat_per_leg_sticky_strike',
        theta_unit='premium_USD_per_oz_per_calendar_day',vega_unit='premium_per_unit_volatility',
        delta_unit='premium_per_futures_USD',gamma_unit='premium_per_futures_USD_squared'),
        diagnostics=[],rejection_reasons=[],evidence_kind=x.evidence_kind,input_sha256=input_hash,**SAFETY)
    result.update(inputs=encode(x),confidence='NUMERICAL_RESEARCH_TOLERANCE_ONLY')
    try:
        if (x.evidence_kind not in {'ENGINEERING_SYNTHETIC','AUTHENTIC_ARCHIVED_RECORD'}
                or x.rate is None or x.rate_as_of_ns is None or not x.rate_source_sha256
                or len(x.rate_source_sha256)!=64 or not x.convention_reference
                or not 0<=x.cutoff_ns-x.rate_as_of_ns<=86400*10**9):
            raise ValueError('dated_rate_and_reviewed_convention_required')
        if (not all(isfinite(v) for v in (x.bid,x.ask)) or not 0<x.bid<=x.ask
                or x.ask-x.bid>max(.1,.2*(x.bid+x.ask)/2)
                or x.style not in {'American','European'}): raise ValueError('invalid_option_premium_or_style')
        iv=implied_volatility((x.bid+x.ask)/2,future=x.future,strike=x.strike,years=x.years,
                             rate=x.rate,kind=x.kind,style=x.style)
        result['iv']=iv
        if x.style=='European':
            primary=european_greeks(x.future,x.strike,x.years,x.rate,iv,x.kind)
            diagnostics=[sensitivities(black76,x,iv,fraction=h) for h in (.002,.001)]
            primary.update(price=black76(x.future,x.strike,x.years,x.rate,iv,x.kind),theta=diagnostics[-1]['theta'])
            model='BLACK76_ANALYTIC_WITH_FINITE_DIFFERENCE_VALIDATION'
        else:
            diagnostics=[]
            # Odd/even averaging reduces lattice parity, but cannot certify by
            # itself: independent mesh/bump checks remain mandatory.
            for n,h in ((200,.02),(400,.01)):
                def crr(f,k,t,r,v,kind,n=n):
                    return (american_futures(f,k,t,r,v,kind,steps=n)+american_futures(f,k,t,r,v,kind,steps=n+1))/2
                diagnostics.append(sensitivities(crr,x,iv,fraction=h))
            for n,h in ((400,.02),(800,.01)):
                def fd(f,k,t,r,v,kind,n=n): return american_fd(f,k,t,r,v,kind,space=n,time=n)
                diagnostics.append(sensitivities(fd,x,iv,fraction=h))
            primary=diagnostics[1];model='AMERICAN_FUTURES_CRR_INDEPENDENT_IMPLICIT_OBSTACLE_FD'
        result.update(diagnostics=diagnostics,model=model,
            validation_tolerances=dict(price_absolute=price_absolute_tolerance,relative=relative_tolerance,
                delta_absolute=.02,gamma_absolute=1e-6,vega_absolute=.05,theta_absolute=.005))
        for d in diagnostics:
            if any(not isfinite(v) for v in d.values()) or d['gamma'] < -1e-8 or d['vega'] < -1e-6:
                raise ValueError('nonphysical_or_nonfinite_Greeks')
            for name in ('price','delta','gamma','vega','theta'):
                absolute={'price':price_absolute_tolerance,'delta':.02,'gamma':1e-6,'vega':.05,'theta':.005}[name]
                if abs(d[name]-primary[name]) > max(absolute,relative_tolerance*abs(primary[name])):
                    raise ValueError('numerical_Greek_or_price_convergence_failed:'+name)
        if abs(primary['price']-(x.bid+x.ask)/2)>max(price_absolute_tolerance,(x.ask-x.bid)/2):
            raise ValueError('IV_repricing_validation_failed')
        result.update(status='VALIDATED_MODEL_SENSITIVITIES',**{k:primary[k] for k in ('delta','gamma','vega','theta')})
    except (ValueError,TypeError,ArithmeticError) as exc: result['rejection_reasons']=[str(exc)]
    return result


def validated_curve(inputs):
    """Bind exact instrument IDs to reviewed inputs; revalidate every grid point.

    Counterfactual premiums are model outputs, never manufactured observations.
    Sticky-strike IV is held fixed at the validated base-market solution. This
    expensive offline seam is deliberately capped at 64 legs and 256 points.
    """
    if not 1<=len(inputs)<=64 or len({x.native_instrument_id for x in inputs})!=len(inputs):
        raise ValueError('bounded_exact_instrument_curve_inputs_required')
    base={}
    for x in inputs:
        if type(x.native_instrument_id) is not int or x.native_instrument_id<=0:
            raise ValueError('exact_native_instrument_id_required')
        g=validated(x)
        if g['status']!='VALIDATED_MODEL_SENSITIVITIES':raise ValueError('base_curve_sensitivities_unvalidated')
        base[x.native_instrument_id]=g
    cache={}
    def curve(future):
        if future not in cache:
            if len(cache)>=256:raise ValueError('bounded_curve_evaluation_budget_exceeded')
            values={}
            for x in inputs:
                initial=base[x.native_instrument_id]
                model=american_futures if x.style=='American' else black76
                premium=model(future,x.strike,x.years,x.rate,initial['iv'],x.kind)
                counterfactual=replace(x,future=future,bid=premium,ask=premium)
                g=validated(counterfactual)
                g.update(counterfactual_model_repricing=True,observed_market_quote=False,
                         base_market_inputs_sha256=initial['input_sha256'],volatility_assumption='sticky_strike')
                values[x.native_instrument_id]=g
            cache[future]=values
        return cache[future]
    return curve
