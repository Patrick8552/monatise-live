"""Causally ordered observed-L1 shadow outcomes; no OHLC substitution or orders."""
from decimal import Decimal
from .models import QuoteUnavailable


def advance_native(evaluator,row,plan,snapshot,prior):
    import json
    store,stream,policy=evaluator.store,evaluator.stream,evaluator.policy
    sid=row['selection'];d=Decimal(1 if plan['side']=='BUY' else -1)
    tick=snapshot.instrument.tick;mult=snapshot.instrument.multiplier
    fee=policy.fee_ticks_per_side*tick*mult;slip=policy.slippage_ticks_per_side*tick
    fill=json.loads(prior['FILL']['payload']) if 'FILL' in prior else None
    events=sorted(snapshot.quotes+snapshot.quote_invalidations,
        key=lambda q:(q.available_ns,q.receive_ns,q.sequence if q.sequence is not None else -1,
                      q.native_ordinal if q.native_ordinal is not None else -1))
    for q in events:
        if q.available_ns<=row['selected_ns'] or q.receive_ns<=row['selected_ns']:continue
        if fill and q.available_ns<=int(fill['at_ns']):continue
        covered=any(c.kind=='mbp-1' and c.covers(row['selected_ns'],q.receive_ns+1,snapshot.cutoff_ns)
                    for c in snapshot.coverage)
        unavailable=isinstance(q,QuoteUnavailable) or bool(q.quality) or not covered
        if unavailable:
            if fill:
                store.position_event(stream,sid,'UNRESOLVED',q.available_ns,
                    {'reason':'NATIVE_L1_UNAVAILABLE_DURING_OPEN_REFERENCE_POSITION',
                     'source':q.source,'position_closed':True,'hypothetical':True,
                     'favorable_sequence_assumed':False})
                return
            continue
        if fill is None:
            if q.available_ns>=plan['expires_ns']:break
            if not 0<=q.available_ns-q.receive_ns<=policy.quote_age_ns:continue
            price=(q.ask if d>0 else q.bid)+d*slip
            if not Decimal(plan['entry_low'])<=price<=Decimal(plan['entry_high']):continue
            risk=d*(price-(Decimal(plan['stop'])-d*slip))*mult+2*fee
            if risk<=0:continue
            fill={'price':str(price),'initial_risk':str(risk),'source':q.source,
                'at_ns':q.available_ns,'provider_receive_ns':q.receive_ns,
                'fill_model':'NEXT_OBSERVED_NATIVE_L1_WITH_DECLARED_SLIPPAGE',
                'hypothetical':True,'execution_eligible':False}
            store.position_event(stream,sid,'FILL',q.available_ns,fill)
            continue
        market=q.bid if d>0 else q.ask
        stop=Decimal(plan['stop']);target=Decimal(plan['targets'][0]['price'])
        stop_hit=d*(market-stop)<=0
        target_hit=d*(market-target)>=tick
        if stop_hit or target_hit:
            exit_price=(market if stop_hit else target)-d*slip
            net=d*(exit_price-Decimal(fill['price']))*mult-2*fee
            risk=Decimal(fill['initial_risk'])
            store.position_event(stream,sid,'OUTCOME',q.available_ns,
                {'exit_price':str(exit_price),'net_pnl':str(net),'realized_r':str(net/risk),
                 'initial_risk_denominator':str(risk),'exit_reason':'STOP' if stop_hit else 'FIRST_TARGET_TRADE_THROUGH',
                 'source':q.source,'hypothetical':True,'fill_model':'ORDERED_NATIVE_L1_RESEARCH_ONLY'})
            return
    if fill is None and snapshot.cutoff_ns>=plan['expires_ns']:
        store.position_event(stream,sid,'MISSED_ENTRY',plan['expires_ns'],
            {'reason':'NO_ELIGIBLE_OBSERVED_NATIVE_QUOTE_BEFORE_EXPIRY','synthetic_fill_used':False})
