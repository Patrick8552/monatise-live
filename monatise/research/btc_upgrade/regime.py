"""Causal BTC regime hypotheses with explicit UNKNOWN and closed-bar hysteresis."""
from dataclasses import dataclass
from decimal import Decimal as D
from math import log10
from monatise.research.unified.models import State,Side,digest,encode,WIDTHS
from . import require_btc

def metrics(bars,previous_close=None):
    if len(bars)<20:return {'available':False,'reason':'INSUFFICIENT_REGIME_BARS'}
    rows=bars;span=max(b.high for b in rows)-min(b.low for b in rows)
    if span<=0:return {'available':False,'reason':'ZERO_RANGE_NO_TRADE'}
    tr=sum(max(b.high-b.low,abs(b.high-(rows[i-1].close if i else (previous_close if previous_close is not None else b.open))),abs(b.low-(rows[i-1].close if i else (previous_close if previous_close is not None else b.open)))) for i,b in enumerate(rows))
    path=sum(abs(b.close-a.close) for a,b in zip(rows,rows[1:]))
    return {'available':True,'choppiness':D(str(100*log10(float(tr/span))/log10(len(rows)))),
            'efficiency':abs(rows[-1].close-rows[0].close)/path if path else D(0),
            'first_true_range_seed':'PREVIOUS_VALIDATED_CLOSE' if previous_close is not None else 'FIRST_NATIVE_BAR_OPEN','lower':min(b.low for b in rows),'upper':max(b.high for b in rows),'source_ids':tuple(b.source for b in rows)}

def range_box(rows,p):
    previous=rows[-p.lookback-1].close if len(rows)>p.lookback else None
    rows=tuple(rows[-p.lookback:]);m=metrics(rows,previous)
    if not m['available']:return dict(m)
    lo,hi=m['lower'],m['upper'];width=hi-lo;edge=width*p.edge_fraction
    # Distinct excursions separated by a bar away from the same edge.
    def excursions(flags):return sum(v and (i==0 or not flags[i-1]) for i,v in enumerate(flags))
    low_touches=excursions([b.low<=lo+edge for b in rows]);high_touches=excursions([b.high>=hi-edge for b in rows])
    half=len(rows)//2;older,newer=rows[:half],rows[half:]
    drift=max(abs(max(b.high for b in newer)-max(b.high for b in older)),abs(min(b.low for b in newer)-min(b.low for b in older)))/width
    reasons=[]
    if m['choppiness']<p.range_chop_min or m['efficiency']>p.range_efficiency_max:reasons.append('RANGE_ROTATION_NOT_CONFIRMED')
    if min(low_touches,high_touches)<p.min_edge_touches:reasons.append('RANGE_EDGE_REVISITS_INSUFFICIENT')
    if drift>p.boundary_drift_fraction:reasons.append('RANGE_BOUNDARIES_UNSTABLE')
    return dict(m,available=not reasons,reasons=reasons,low_touches=low_touches,high_touches=high_touches,boundary_drift=drift,
                observed_start_ns=rows[0].open_ns,formed_ns=rows[-1].close_ns,available_ns=max(b.available_ns for b in rows),box_id=digest(tuple(b.key for b in rows)))

def classify(snapshot,frames,p):
    require_btc(snapshot);reasons=[]
    for tf in ('4h','1h','15m','5m'):
        f=frames[tf]
        if f.state==State.UNAVAILABLE:reasons.append(tf.upper()+'_CONTEXT_UNAVAILABLE')
        if not f.bars or snapshot.cutoff_ns-f.bars[-1].close_ns>WIDTHS[tf]:reasons.append(tf.upper()+'_FRAME_STALE')
    if snapshot.quality:reasons.append('SOURCE_QUALITY_UNRESOLVED')
    f=frames['15m'];m=metrics(f.bars[-p.lookback:],f.bars[-p.lookback-1].close if len(f.bars)>p.lookback else None);key=f.bars[-1].close_ns if f.bars else 0
    if not m['available']:reasons.append(m['reason'])
    if reasons:return {'raw_regime':'UNKNOWN','side':None,'reasons':reasons,'closed_bar_ns':key,'metrics':m}
    h4,h1,m15,m5=(frames[t].state for t in ('4h','1h','15m','5m'))
    if h4==h1==m15==m5 and h4 in (State.UP,State.DOWN) and m['efficiency']>=p.trend_efficiency and m['choppiness']<=p.trend_chop_max:
        return {'raw_regime':'TREND','side':'BUY' if h4==State.UP else 'SELL','reasons':[],'closed_bar_ns':key,'metrics':m}
    box=range_box(f.bars,p)
    # A range cannot override opposing or aligned directional higher-timeframe context.
    if box['available'] and h4 in (State.NEUTRAL,State.MIXED) and h1 in (State.NEUTRAL,State.MIXED):
        return {'raw_regime':'RANGE','side':None,'reasons':[],'closed_bar_ns':key,'metrics':m,'range_box':box}
    return {'raw_regime':'TRANSITION','side':None,'reasons':['NO_CONFIRMED_REGIME']+box.get('reasons',[]),'closed_bar_ns':key,'metrics':m}

def confirm(raw,prior,required):
    key=raw['raw_regime']+':'+str(raw['side']);stamp=raw['closed_bar_ns']
    if prior and stamp<prior['closed_bar_ns']:
        if raw['raw_regime']=='UNKNOWN':stamp=prior['closed_bar_ns']
        else:raise ValueError('REGIME_BAR_CLOCK_REGRESSION')
    same=bool(prior and prior['candidate']==key)
    count=(prior['count']+(stamp>prior['closed_bar_ns'])) if same else 1
    state=raw['raw_regime']
    if state in ('TREND','RANGE') and count<required:state='TRANSITION'
    return {'regime':state,'side':raw['side'] if state=='TREND' else None,'candidate':key,'count':count,'closed_bar_ns':stamp,'raw':raw,'reason':'CONFIRMED' if state==raw['raw_regime'] else 'WAIT_DISTINCT_CLOSED_M15_CONFIRMATION'}
