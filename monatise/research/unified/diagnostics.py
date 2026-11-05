"""Descriptive native evidence, never an extra strategy vote or qualified signal."""
from .models import fixed_decimal
from decimal import Decimal
from .models import MINUTE


@fixed_decimal
def fibonacci(frame):
    alternating=[]
    for p in frame.pivots:
        if alternating and alternating[-1].kind==p.kind:
            if (p.price-alternating[-1].price)*(1 if p.kind=='HIGH' else -1)>0:
                alternating[-1]=p
        else:alternating.append(p)
    if len(alternating)<2:
        return {'available':False,'reason':'INSUFFICIENT_CONFIRMED_ALTERNATING_ANCHORS'}
    a,b=alternating[-2:];move=b.price-a.price
    if not move:return {'available':False,'reason':'ZERO_CONFIRMED_LEG'}
    return {'available':True,'start_reference':a.key,'end_reference':b.key,
            'start':str(a.price),'end':str(b.price),'confirmed_available_ns':max(a.available_ns,b.available_ns),
            'retracements':{r:str(b.price-move*Decimal(r)) for r in ('0.382','0.5','0.618','0.786')},
            'tick_rounded':False,'signal_qualification':False}


@fixed_decimal
def executed_window(snapshot,minutes):
    end=snapshot.cutoff_ns;start=end-minutes*MINUTE
    rows=[t for t in snapshot.trades if start<=t.receive_ns<end]
    if not rows:return {'available':False,'reason':'NO_RETAINED_EXECUTIONS_IN_WINDOW','start_ns':start,'end_ns':end}
    if any(t.quality for t in rows):return {'available':False,'reason':'FLAGGED_WINDOW_EXECUTIONS','start_ns':start,'end_ns':end}
    profile={};weighted=Decimal(0);buy=sell=unknown=volume=0
    for t in rows:
        volume+=t.size;weighted+=t.price*t.size;profile[t.price]=profile.get(t.price,0)+t.size
        if t.aggressor=='BUY':buy+=t.size
        elif t.aggressor=='SELL':sell+=t.size
        else:unknown+=t.size
    poc=min(profile,key=lambda p:(-profile[p],p))
    return {'available':True,'start_ns':start,'end_ns':end,'executed_contracts':volume,
            'buy_contracts':buy,'sell_contracts':sell,'unknown_side_contracts':unknown,
            'known_side_delta':buy-sell,'vwap':str(weighted/volume),'point_of_control':str(poc),
            'profile':[[str(p),profile[p]] for p in sorted(profile)],
            'provider_retained_window_reviewed':any(c.kind=='trades' and c.covers(start,end,snapshot.cutoff_ns) for c in snapshot.coverage),
            'complete_exchange_continuity_certified':False,'scope':'EXACT_RETAINED_WINDOW_NOT_FULL_SESSION',
            'absorption_confirmed':False,'participant_identity':'UNAVAILABLE'}


def describe(snapshot,frames):
    context={}
    for tf,f in frames.items():
        highs=[p for p in f.pivots if p.kind=='HIGH'];lows=[p for p in f.pivots if p.kind=='LOW']
        context[tf]={'state':f.state,'confirmed_highs':len(highs),'confirmed_lows':len(lows),
                     'last_high':{'id':highs[-1].key,'price':str(highs[-1].price),'available_ns':highs[-1].available_ns} if highs else None,
                     'last_low':{'id':lows[-1].key,'price':str(lows[-1].price),'available_ns':lows[-1].available_ns} if lows else None,
                     'fibonacci':fibonacci(f),'resting_orders_observed':False}
    return {'frames':context,'retained_executions':{str(m)+'m':executed_window(snapshot,m) for m in (5,15,60)},
            'session_vwap_or_cvd':'NOT_CLAIMED','order_book_depth':'NOT_CONNECTED','options_oi':'NOT_CONNECTED'}
