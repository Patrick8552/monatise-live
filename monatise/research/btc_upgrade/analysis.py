"""Descriptive/reference analysis is independent of trading permission."""
from dataclasses import replace
from decimal import Decimal as D
from monatise.research.unified.models import current_quote,State,Side,encode
from monatise.research.unified.eligibility import round_tick
from .setups import trend_context

def reference_analysis(snapshot,frames,policy,checks,news,risk,regime):
    warnings=list(news['reasons'])+list(risk['reasons'])
    for tf in ('4h','1h'):
        if frames[tf].state==State.UNAVAILABLE:warnings.append(tf.upper()+'_CONTEXT_UNAVAILABLE')
    q=current_quote(snapshot);source=[]
    if snapshot.quality:source.append('SOURCE_QUALITY_UNRESOLVED')
    if q is None or q.quality:source.append('REFERENCE_QUOTE_UNAVAILABLE')
    elif q.source.startswith('MODELED_SPREAD_FROM_NATIVE_CLOSE'):source.append('OBSERVED_NATIVE_QUOTE_REQUIRED')
    age=snapshot.cutoff_ns-q.receive_ns if q is not None else None
    if age is not None and age>policy.analysis_quote_age_ns:
        source.append('ANALYSIS_QUOTE_STALE_REFRESH_REQUIRED')
    if age is not None and age>policy.trend.quote_age_ns:
        warnings.append('LAST_NATIVE_QUOTE_AGE_SECONDS:'+str(D(age)/10**9))
        warnings.append('FRESH_QUOTE_REQUIRED_BEFORE_ENTRY')
    if not frames['5m'].bars:source.append('REFERENCE_STRUCTURE_UNAVAILABLE')
    eligible=[]
    for row in checks:
        o=row['observation'];g=row['gates']
        if source or g['trigger'] or g['participation']:continue
        if g['economics']==['ENTRY_QUOTE_STALE'] and q is not None:
            # Re-price an INACTIVE reference using the last observed native quote.
            # This never alters execution freshness policy or source timestamps.
            from .setups import trend_plan,range_plan
            ap=replace(policy,trend=replace(policy.trend,quote_age_ns=max(policy.trend.quote_age_ns,age+1)))
            box=regime.get('box') or regime.get('raw',{}).get('range_box')
            plan,codes=range_plan(o,snapshot,ap,frames,box) if o.pathway=='R' else trend_plan(o,snapshot,ap.trend,frames)
            if codes or plan is None:continue
            row={**row,'plan':plan}
        elif g['economics'] or not row['plan']:continue
        if o.pathway=='R':
            if regime['raw']['raw_regime']!='RANGE':continue
            ctx=[]
        else:ctx=list(trend_context(o,frames,policy.trend,snapshot.instrument.tick,analysis=True)[0])
        if ctx:continue
        # Higher-timeframe/news/risk limitations are warnings for an inactive reference plan.
        eligible.append(row)
    # Multiple labels of one episode do not vote. Conflicting sides remain unresolved.
    groups={r['observation'].opportunity_id:r for r in eligible}
    chosen=None
    if len({r['observation'].side for r in groups.values()})==1 and groups:
        chosen=sorted(groups.values(),key=lambda r:(-r['plan'].net_rr[0],r['plan'].lateness_ns,r['observation'].opportunity_id))[0]
    if chosen:
        warnings+=chosen['gates']['context']
        return {'action':chosen['observation'].side,'status':'CONDITIONAL_REFERENCE_NOT_EXECUTION_PERMISSION',
                'plan':encode(chosen['plan']),'trigger':'Completed native M5 structural trigger; obtain a new fresh quote and recheck every execution gate before any order.',
                'limitations':sorted(set(warnings)),'qualification':'DESCRIPTIVE_REFERENCE_ONLY','observed_native_quote_timestamp_ns':q.receive_ns if q is not None else None,'observed_native_quote_age_seconds':str(D(age)/10**9) if age is not None else None,'execution_eligible':False}
    watch=pullback_watch(snapshot,frames,policy,tuple(r['observation'] for r in checks),warnings)
    if watch:return watch
    return {'action':'NO_TRADE','status':'STALE_DATA_REFRESH_REQUIRED' if 'ANALYSIS_QUOTE_STALE_REFRESH_REQUIRED' in source else 'NO_SUPPORTED_CURRENT_REFERENCE_SETUP','plan':None,
            'reason':source or ['NO_FRESH_STRUCTURALLY_VALID_RISK_REWARD_SETUP'],
            'limitations':sorted(set(warnings)),
            'qualification':'ANALYSIS_CONTINUES_WITH_AVAILABLE_EVIDENCE','observed_native_quote_timestamp_ns':q.receive_ns if q is not None else None,'observed_native_quote_age_seconds':str(D(age)/10**9) if age is not None else None,'execution_eligible':False}

def intraday_regime(frames,policy):
    """Available intraday evidence can be described while higher context is unknown."""
    from .regime import metrics,range_box
    m15,m5=frames['15m'],frames['5m'];m=metrics(m15.bars[-policy.regime.lookback:],m15.bars[-policy.regime.lookback-1].close if len(m15.bars)>policy.regime.lookback else None)
    if not m['available'] or State.UNAVAILABLE in (m15.state,m5.state):return {'state':'UNKNOWN','scope':'INTRADAY_REFERENCE_ONLY','reasons':['INTRADAY_EVIDENCE_UNAVAILABLE']}
    if m15.state==m5.state and m15.state in (State.UP,State.DOWN) and m['efficiency']>=policy.regime.trend_efficiency and m['choppiness']<=policy.regime.trend_chop_max:
        return {'state':'TREND','side':'BUY' if m15.state==State.UP else 'SELL','scope':'INTRADAY_REFERENCE_ONLY','metrics':m,'higher_timeframe_permission':'SEPARATELY_EVALUATED'}
    box=range_box(m15.bars,policy.regime)
    return {'state':'RANGE' if box.get('available') else 'TRANSITION','scope':'INTRADAY_REFERENCE_ONLY','metrics':m,'higher_timeframe_permission':'SEPARATELY_EVALUATED'}

def pullback_watch(snapshot,frames,policy,observations,warnings):
    """One interpreted FUTURE watch; never resurrects an expired market trigger."""
    from monatise.research.unified.evidence import structural_breaks
    from monatise.research.unified.diagnostics import executed_window
    q=current_quote(snapshot)
    if snapshot.quality or q is None or q.quality or q.source.startswith('MODELED_SPREAD_FROM_NATIVE_CLOSE') or snapshot.cutoff_ns-q.receive_ns>policy.analysis_quote_age_ns:return None
    m15,m5=frames['15m'],frames['5m']
    if m15.state!=m5.state or m15.state not in (State.UP,State.DOWN):return None
    side=Side.BUY if m15.state==State.UP else Side.SELL;d=side.sign;inst=snapshot.instrument;tick=inst.tick
    breaks=[v for v in structural_breaks(m5,tick) if v[1].side==side]
    if not breaks:return None
    _,origin,guard=breaks[-1]
    if any(d*(b.close-guard.price)<-tick for b in m5.bars if b.close_ns>origin.at_ns):return None
    # Use an already confirmed protective swing for a future retest; no unconfirmed wick stop.
    guards=[p for p in m5.pivots if p.kind==('LOW' if side==Side.BUY else 'HIGH') and p.available_ns<=snapshot.cutoff_ns and d*(origin.level-p.price)>tick]
    if not guards:return None
    protected=max(guards,key=lambda p:p.confirmed_ns)
    spread=q.ask-q.bid;slip=policy.trend.slippage_ticks_per_side*tick
    zone=(origin.level-tick,origin.level+tick)
    entry=(zone[1] if d>0 else zone[0])+d*(spread+slip)
    stop=round_tick(protected.price-d*policy.trend.stop_buffer_ticks*tick,tick,d<0)
    if d*(entry-stop)<=0:return None
    refs=[]
    for tf in ('15m','5m','1h'):
        for p in frames[tf].pivots:
            if p.kind==('HIGH' if d>0 else 'LOW') and p.available_ns<=snapshot.cutoff_ns and d*(p.price-entry)>0:refs.append((p.price,p.key))
    window=executed_window(snapshot,15)
    if window.get('available') and window.get('provider_retained_window_reviewed'):
        poc=D(window['point_of_control'])
        if d*(poc-entry)>0:refs.append((poc,'RETAINED_15M_EXECUTED_POC:'+str(window['start_ns'])+':'+str(window['end_ns'])))
    if not refs:return None
    target,ref=min(refs,key=lambda p:d*p[0])
    fee=policy.trend.fee_ticks_per_side*tick*inst.multiplier
    risk=d*(entry-(stop-d*slip))*inst.multiplier+2*fee
    reward=d*((target-d*slip)-entry)*inst.multiplier-2*fee
    if risk<=0 or reward/risk<policy.trend.min_net_rr:return None
    return {'action':side,'status':'CONDITIONAL_AWAIT_NEW_M5_RETEST_AND_PARTICIPATION',
        'plan':{'entry_zone':encode(zone),'worst_reference_entry':str(entry),'stop':str(stop),'targets':[{'price':str(target),'reference':ref}],
                'net_rr':str(reward/risk),'cost_basis':policy.cost_basis,'protected_swing':protected.key,'break_reference':origin.key},
        'trigger':'After this snapshot, require a new completed M5 retest/rejection of the entry zone, matching price momentum and supported executed participation. Recalculate the retest stop and costs at that time.',
        'limitations':sorted(set(warnings+['FUTURE_TRIGGER_NOT_OBSERVED','REFERENCE_COSTS_NOT_VERIFIED_BROKER_COSTS'])),
        'qualification':'INTERPRETED_WATCH_NOT_ENGINE_QUALIFIED_SIGNAL','execution_eligible':False,
        'observed_native_quote_timestamp_ns':q.receive_ns,'observed_native_quote_age_seconds':str(D(snapshot.cutoff_ns-q.receive_ns)/10**9),'not_before_ns':snapshot.cutoff_ns,'old_replay_triggers_reactivated':False}
