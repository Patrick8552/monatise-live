"""Causal confirmed swings and descriptive futures structure, no trade rules."""
from decimal import Decimal
from monatise.research.databento.candles import WIDTHS, HistoricalBar
from monatise.research.institutional.models import digest


def analyse_frame(bars, *, tick_size, cutoff_ns, swing_radius=2, maximum_bars=512):
    rows=tuple(bars);tick=Decimal(tick_size)
    if type(swing_radius) is not int or not 1<=swing_radius<=5 or tick<=0:
        raise ValueError('bounded_native_swing_policy_required')
    if type(maximum_bars) is not int or not 16<=maximum_bars<=2048 or len(rows)>100000:
        raise ValueError('bounded_native_frame_required')
    if not rows:return dict(available=False,reason='insufficient_validated_history')
    from monatise.research.phase10.history import JoinedBar
    if (any(not isinstance(b,(HistoricalBar,JoinedBar)) for b in rows) or rows[0].identity.product not in {'GC','ES','NQ'}
            or tick!=Decimal(dict(rows[0].identity.native_terms)['min_price_increment'])/10**9
            or type(cutoff_ns) is not int or cutoff_ns<=0):
        raise ValueError('reviewed_exact_native_futures_terms_required')
    omitted=max(0,len(rows)-maximum_bars);rows=rows[-maximum_bars:]
    if any(b.identity!=rows[0].identity or b.timeframe!=rows[0].timeframe or b.close_ns>cutoff_ns or b.retrieval_ns>cutoff_ns for b in rows):
        raise ValueError('exact_available_native_frame_required')
    if any(a.close_ns!=b.open_ns for a,b in zip(rows,rows[1:])):
        return dict(available=False,reason='noncontiguous_validated_frame',gap_fill_count=0)
    # Strict extrema avoid inventing a pivot direction on flat/equal plateaus.
    swings=[]
    for i in range(swing_radius,len(rows)-swing_radius):
        b=rows[i];neighbours=rows[i-swing_radius:i]+rows[i+1:i+swing_radius+1]
        kinds=[]
        if all(b.prices_fixed[1]>x.prices_fixed[1] for x in neighbours):kinds.append(('HIGH',b.prices_fixed[1]))
        if all(b.prices_fixed[2]<x.prices_fixed[2] for x in neighbours):kinds.append(('LOW',b.prices_fixed[2]))
        if len(kinds)>1:continue  # Intrabar high/low order is unknown.
        for kind,price in kinds:
            swings.append(dict(kind=kind,price_fixed=price,pivot_open_ns=b.open_ns,
                confirmed_at_ns=rows[i+swing_radius].close_ns,source_sha256=digest(tuple(rows[i-swing_radius:i+swing_radius+1]))))
    highs=[s for s in swings if s['kind']=='HIGH'];lows=[s for s in swings if s['kind']=='LOW']
    bias='INSUFFICIENT_CONFIRMED_SWINGS'
    if len(highs)>=2 and len(lows)>=2:
        dh=highs[-1]['price_fixed']-highs[-2]['price_fixed'];dl=lows[-1]['price_fixed']-lows[-2]['price_fixed']
        bias='HIGHER_HIGHS_AND_LOWS' if dh>0 and dl>0 else 'LOWER_HIGHS_AND_LOWS' if dh<0 and dl<0 else 'MIXED_STRUCTURE'
    close=rows[-1].prices_fixed[3];scale=Decimal(10**9)
    def pivot(s):return dict(kind=s['kind'],price=str(Decimal(s['price_fixed'])/scale),pivot_open_ns=s['pivot_open_ns'],confirmed_at_ns=s['confirmed_at_ns'],source_sha256=s['source_sha256'])
    structure=dict(available=bias!='INSUFFICIENT_CONFIRMED_SWINGS',state=bias,confirmed_high_count=len(highs),confirmed_low_count=len(lows),
        latest_high=pivot(highs[-1]) if highs else None,latest_low=pivot(lows[-1]) if lows else None,
        latest_close_beyond_confirmed_high=bool(highs and close>highs[-1]['price_fixed']),
        latest_close_beyond_confirmed_low=bool(lows and close<lows[-1]['price_fixed']),intrabar_break_sequence_inferred=False)
    # Alternating confirmed pivots; consecutive same-kind pivots retain the extreme.
    alternating=[]
    for s in swings:
        if alternating and alternating[-1]['kind']==s['kind']:
            if (s['price_fixed']-alternating[-1]['price_fixed'])*(1 if s['kind']=='HIGH' else -1)>0:alternating[-1]=s
        else:alternating.append(s)
    fib=dict(available=False,reason='insufficient_confirmed_alternating_swings')
    if len(alternating)>=2:
        a,b=alternating[-2:];delta=Decimal(b['price_fixed']-a['price_fixed'])/scale
        if delta:
            end=Decimal(b['price_fixed'])/scale
            fib=dict(available=True,direction='UP_LEG' if delta>0 else 'DOWN_LEG',start=pivot(a),end=pivot(b),
                retracements={r:str(end-delta*Decimal(r)) for r in ('0.382','0.5','0.618','0.786')},
                tick_rounded=False,executable_levels=False,selector_applied=False,signal_qualification=False)
    zones=[]
    # Confirmed repeated swing prices are proxies, never observed resting orders.
    for kind,values in (('HIGH',highs),('LOW',lows)):
        groups=[]
        for s in sorted(values,key=lambda x:x['price_fixed']):
            if groups and s['price_fixed']-groups[-1][0]['price_fixed']<=int(tick*scale):groups[-1].append(s)
            else:groups.append([s])
        for group in groups:
            if len(group)>=2:zones.append(dict(kind=kind,lower=str(Decimal(group[0]['price_fixed'])/scale),upper=str(Decimal(group[-1]['price_fixed'])/scale),touches=len(group),confirmed_at_ns=max(s['confirmed_at_ns'] for s in group)))
    result=dict(available=True,version='native-futures-frame-v1',timeframe=rows[0].timeframe,bar_count=len(rows),omitted_older_bars=omitted,
        start_ns=rows[0].open_ns,end_ns=rows[-1].close_ns,age_ns=cutoff_ns-rows[-1].close_ns,
        swing_policy=dict(left_bars=swing_radius,right_bars=swing_radius,strict_extrema=True,confirmation_uses_closed_bars_only=True),
        structure=structure,fibonacci=fib,liquidity_proxies=dict(available=bool(zones),zones=zones,
            basis='REPEATED_CONFIRMED_PRICE_EXTREMA',resting_orders_observed=False,participant_identity_known=False),
        source_sha256=digest(rows),gap_fill_count=0,crypto_engines_used=False,frozen_H1_selector_used=False,GIL_rules_used=False,execution_eligible=False)
    result['reproducibility_sha256']=digest(result);return result


def alignment(components):
    states={tf:v['structure']['state'] for tf,v in components.items() if v.get('available') and v['structure']['available']}
    directional=[v for v in states.values() if v in {'HIGHER_HIGHS_AND_LOWS','LOWER_HIGHS_AND_LOWS'}]
    return dict(available=len(states)>=2,timeframe_states=states,
        state='INSUFFICIENT_TIMEFRAME_EVIDENCE' if len(states)<2 else 'ALIGNED_UP_STRUCTURE' if len(directional)==len(states) and len(set(directional))==1 and directional[0]=='HIGHER_HIGHS_AND_LOWS' else 'ALIGNED_DOWN_STRUCTURE' if len(directional)==len(states) and len(set(directional))==1 else 'MIXED_TIMEFRAME_STRUCTURE',trade_signal=False)
