"""Plain close-based indicators on the caller's validated native candle sequence.

No chart vendor scripts, signal router, trade qualification or gap filling.
Seeds are explicit, so short-window values need not equal a longer chart history.
"""
from decimal import Decimal, localcontext


def close_indicators(prices_fixed, *, include_series=False):
    if (not isinstance(prices_fixed,tuple) or not 1<=len(prices_fixed)<=2048
            or any(type(v) is not int or v<=0 for v in prices_fixed)):
        raise ValueError('bounded_native_fixed_point_closes_required')
    if type(include_series) is not bool:raise ValueError('explicit_series_flag_required')
    values=tuple(Decimal(v)/10**9 for v in prices_fixed)
    result=dict(input_bars=len(values),price_basis='VALIDATED_NATIVE_CANDLE_CLOSE',
        seed_scope='RETAINED_FRAME_ONLY; CAN_DIFFER_FROM_LONGER_CHART_HISTORY',
        proprietary_chart_scripts_reproduced=False,trade_signal=False)
    paths=dict(ema20=[None]*len(values),rsi14=[None]*len(values),rsi14_sma14=[None]*len(values))
    if include_series:result['series']=paths
    with localcontext() as ctx:
        ctx.prec=36
        if len(values)>=20:
            ema=sum(values[:20])/20;alpha=Decimal(2)/21
            paths['ema20'][19]=str(ema)
            for i,v in enumerate(values[20:],20):
                ema=alpha*v+(1-alpha)*ema;paths['ema20'][i]=str(ema)
            result['ema20']=dict(available=True,value=str(ema),seed='SMA_OF_FIRST_20_CLOSES')
        else:result['ema20']=dict(available=False,reason='20_validated_closes_required')
        if len(values)<15:
            result['rsi14']=dict(available=False,reason='15_validated_closes_required')
            result['rsi14_sma14']=dict(available=False,reason='28_validated_closes_required')
            result['rsi_cross_above_sma_within_4_bars']=dict(available=False,reason='32_validated_closes_required')
            return result
        changes=[b-a for a,b in zip(values,values[1:])]
        gain=sum(max(v,Decimal(0)) for v in changes[:14])/14
        loss=sum(max(-v,Decimal(0)) for v in changes[:14])/14
        def rsi():
            return Decimal(50) if gain==loss==0 else Decimal(100) if loss==0 else 100-100/(1+gain/loss)
        series=[rsi()]
        for d in changes[14:]:
            gain=(gain*13+max(d,Decimal(0)))/14;loss=(loss*13+max(-d,Decimal(0)))/14;series.append(rsi())
        paths['rsi14'][14:]=[str(v) for v in series]
        result['rsi14']=dict(available=True,value=str(series[-1]),smoothing='WILDER_RMA',flat_seed_value='50')
        sma=[sum(series[i-13:i+1])/14 for i in range(13,len(series))]
        result['rsi14_sma14']=dict(available=bool(sma),**({'value':str(sma[-1])} if sma else {'reason':'28_validated_closes_required'}))
        paths['rsi14_sma14'][27:]=[str(v) for v in sma]
        aligned=series[13:]
        if len(sma)>=5:
            cross=[i for i in range(len(sma)-4,len(sma)) if aligned[i-1]<=sma[i-1] and aligned[i]>sma[i]]
            result['rsi_cross_above_sma_within_4_bars']=dict(available=True,observed=bool(cross),
                bars_since_latest_cross=len(sma)-1-cross[-1] if cross else None,qualification=False)
        else:result['rsi_cross_above_sma_within_4_bars']=dict(available=False,reason='32_validated_closes_required')
    return result
