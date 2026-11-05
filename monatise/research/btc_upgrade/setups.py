"""BTC-only trend reuse and bounded native range rejections; no order submission."""
from dataclasses import replace
from decimal import Decimal as D
from monatise.research.unified.models import (Side,State,Event,Observation,Plan,Target,Candidate,WIDTHS,current_quote,digest)
from monatise.research.unified.evidence import observations
from monatise.research.unified.eligibility import economic_plan,volume_support,round_tick
from monatise.research.unified.pathways import EVALUATORS
from .regime import range_box

def deadline(observation,snapshot,policy):
    if not observation.trigger:return None
    return min(observation.trigger.at_ns+policy.trigger_bars*WIDTHS['5m'],snapshot.schedule.closes_after(observation.trigger.at_ns-1),snapshot.instrument.expiry_ns)

def trend_observations(snapshot,policy,frames):
    result=[]
    for o in observations(snapshot,policy,frames):
        if o.trigger and o.stage!='INVALIDATED' and snapshot.cutoff_ns>=deadline(o,snapshot,policy):o=replace(o,stage='EXPIRED')
        result.append(o)
    return tuple(result)

def trend_context(o,frames,policy,tick,*,analysis=False):
    reasons,category=EVALUATORS[o.pathway](o,frames,policy,tick)
    if analysis:
        # Reference analysis may state unknown H4 explicitly; no fabricated neutrality.
        reasons=tuple(r for r in reasons if not (r.startswith('H4_') or r.startswith('H1_') or r.startswith('B_H1_')))
    return reasons,category

def trend_plan(o,snapshot,policy,frames):
    plan,codes=economic_plan(o,snapshot,policy,frames)
    if plan:
        plan=replace(plan,expires_ns=deadline(o,snapshot,policy),trigger_ns=o.trigger.at_ns,
                     lateness_ns=snapshot.cutoff_ns-o.trigger.at_ns)
    return plan,codes

def range_observations(snapshot,frames,policy,box):
    if not box or not box.get('available'):return ()
    lo,hi=D(box['lower']),D(box['upper']);formed=box['available_ns'];tick=snapshot.instrument.tick
    rows=frames['5m'].bars
    if not rows:return ()
    b=rows[-1]
    if formed>b.open_ns:return () # Boundary proof must precede the rejection candle.
    width=hi-lo;edge=width*policy.regime.edge_fraction
    lower=b.low<=lo+edge and b.close>=lo+tick and b.close<(lo+hi)/2 and b.close>b.open
    upper=b.high>=hi-edge and b.close<=hi-tick and b.close>(lo+hi)/2 and b.close<b.open
    if lower==upper:return ()
    side=Side.BUY if lower else Side.SELL
    # Any observed break of frozen invalidation cancels this box; never average down.
    buffer=snapshot.instrument.tick*policy.risk.range_stop_buffer_ticks
    if any(x.low<=lo-buffer or x.high>=hi+buffer for x in rows if x.open_ns>=box['formed_ns']):return ()
    origin=Event('RANGE_BOUNDARY',snapshot.instrument.key,side,box['formed_ns'],formed,box['box_id'],lo if lower else hi,box['box_id'])
    trigger=Event('RANGE_REJECTION',snapshot.instrument.key,side,b.close_ns,b.available_ns,box['box_id'],lo if lower else hi,b.key,(origin.key,))
    o=Observation('R',side,origin,'TRIGGERED',origin.available_ns,origin.available_ns,trigger,lo if lower else hi,lo-buffer if lower else hi+buffer,(origin,trigger))
    if snapshot.cutoff_ns>=deadline(o,snapshot,policy.trend):o=replace(o,stage='EXPIRED')
    return (o,)

def range_plan(o,snapshot,policy,frames,box):
    q=current_quote(snapshot)
    if q is None or q.quality:return None,('ENTRY_QUOTE_UNAVAILABLE',)
    p=policy.trend
    if snapshot.cutoff_ns-q.receive_ns>p.quote_age_ns:return None,('ENTRY_QUOTE_STALE',)
    b=next((b for b in frames['5m'].bars if b.key==o.trigger.bar_id),None)
    if not b:return None,('TRIGGER_BAR_UNAVAILABLE',)
    d=o.side.sign;inst=snapshot.instrument;tick=inst.tick;spread=q.ask-q.bid;slip=p.slippage_ticks_per_side*tick
    current=(q.ask if d>0 else q.bid)+d*slip;cap=b.close+d*(spread+p.entry_tolerance_ticks*tick+slip)
    if d*(current-cap)>0:return None,('MISSED_ENTRY',)
    low,high=sorted((current,cap));entry=round_tick(high if d>0 else low,tick,d>0)
    stop=round_tick(o.stop_level,tick,d<0)
    if d*((q.bid if d>0 else q.ask)-stop)<=0:return None,('RANGE_INVALIDATED',)
    mid=(D(box['lower'])+D(box['upper']))/2
    target=round_tick(mid,tick,d<0)
    if d*(target-entry)<=0:return None,('RANGE_MIDPOINT_ALREADY_PASSED',)
    if any(t.quality for t in snapshot.trades if o.trigger.at_ns<=t.receive_ns<=snapshot.cutoff_ns):return None,('RANGE_TRIGGER_WINDOW_FLAGGED',)
    if any(d*(t.price-target)>=0 for t in snapshot.trades if o.trigger.at_ns<=t.receive_ns<=snapshot.cutoff_ns):return None,('RANGE_MIDPOINT_PREVIOUSLY_PASSED',)
    fee=p.fee_ticks_per_side*tick*inst.multiplier
    risk=d*(entry-(stop-d*slip))*inst.multiplier+2*fee
    rr=(d*((target-d*slip)-entry)*inst.multiplier-2*fee)/risk if risk>0 else D(-1)
    if rr<p.min_net_rr:return None,('NET_RANGE_RR_INSUFFICIENT',)
    cost=(spread+2*slip)*inst.multiplier+2*fee
    targets=(Target(target,'range-midpoint:'+box['box_id'],box['available_ns']),)
    return Plan(o.opportunity_id,o.side,entry,low,high,stop,targets,(rr,),risk,cost,cost/risk,
                snapshot.cutoff_ns-o.trigger.at_ns,o.trigger.key,o.trigger.at_ns,o.armed_ns,
                deadline(o,snapshot,p),box['box_id'],tuple(e.key for e in o.events),
                'EXPLICIT_TICK_EQUIVALENT_RESEARCH_COSTS',spread),()

def inspect(o,snapshot,policy,frames,regime,box=None):
    stage=[];participation=[];economics=[];context=[];plan=None
    if not o.canonical:stage.append('OPPORTUNITY_IDENTITY_AMBIGUOUS')
    if o.stage!='TRIGGERED':stage.append('LIFECYCLE_'+o.stage)
    if o.trigger and snapshot.cutoff_ns>=deadline(o,snapshot,policy.trend):stage.append('MARKET_TRIGGER_EXPIRED')
    if snapshot.quality:
        participation=['PARTICIPATION_NOT_EVALUATED_SOURCE_QUALITY']
        economics=['ECONOMICS_NOT_EVALUATED_SOURCE_QUALITY']
    elif not stage:
        participation=list(volume_support(o,snapshot,policy.trend,frames))
        # Economics are independently attributed even when volume/news/context fail.
        plan,codes=range_plan(o,snapshot,policy,frames,box) if o.pathway=='R' else trend_plan(o,snapshot,policy.trend,frames)
        economics=list(codes)
    if o.pathway=='R':
        if regime['regime']!='RANGE':context.append('CONFIRMED_RANGE_REGIME_REQUIRED')
        if not policy.range_enabled:context.append('RANGE_RESEARCH_NOT_ENABLED')
    else:
        context.extend(trend_context(o,frames,policy.trend,snapshot.instrument.tick)[0])
        if regime['regime']!='TREND' or regime.get('side')!=o.side:context.append('CONFIRMED_MATCHING_TREND_REGIME_REQUIRED')
        rows=frames['5m'].bars
        if len(rows)<3 or o.side.sign*(rows[-1].close-rows[-3].close)<=0:context.append('TREND_MOMENTUM_NOT_CONFIRMED')
    return {'observation':o,'plan':plan,'gates':{'trigger':stage,'participation':participation,'economics':economics,'context':context},'context_category':'BTC_RANGE' if o.pathway=='R' else 'BTC_TREND'}
