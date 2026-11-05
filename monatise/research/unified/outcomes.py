"""Explicit hypothetical bar-fill evaluator. No broker fills or favorable OHLC ordering."""
from .models import fixed_decimal
from decimal import Decimal
import json
from .models import encode
from .eligibility import round_tick


class ShadowOutcomes:
    def __init__(self, store, stream, policy):
        self.store,self.stream,self.policy=store,stream,policy

    @fixed_decimal
    def advance(self, snapshot):
        rows=self.store.db.execute('SELECT * FROM selections WHERE stream=? ORDER BY selected_ns,selection',(self.stream,)).fetchall()
        for row in rows:
            sid=row['selection'];p=json.loads(row['plan']);d=Decimal(1 if p['side']=='BUY' else -1)
            if p.get('contract_key')!=snapshot.instrument.key:continue
            if p.get('frozen_policy_hash')!=self.policy.hash:
                from .store import Conflict
                raise Conflict('OUTCOME_POLICY_DIFFERS_FROM_IMMUTABLE_SELECTED_PLAN')
            tick=snapshot.instrument.tick;mult=snapshot.instrument.multiplier
            fee=self.policy.fee_ticks_per_side*tick*mult;slip=self.policy.slippage_ticks_per_side*tick
            prior={r['kind']:r for r in self.store.db.execute('SELECT * FROM position_events WHERE stream=? AND selection=?',(self.stream,sid))}
            if any(k in prior for k in ('OUTCOME','MISSED_ENTRY','UNRESOLVED')):continue
            fill=json.loads(prior['FILL']['payload']) if 'FILL' in prior else None
            if snapshot.replay_mode=='AS_RECORDED' or self.policy.outcome_mode=='NATIVE_L1':
                from .native_outcomes import advance_native
                advance_native(self,row,p,snapshot,prior)
                continue
            bars=[b for b in snapshot.bars if b.timeframe=='1m' and b.open_ns>row['selected_ns'] and not b.quality]
            for b in bars:
                if fill is None:
                    if b.open_ns>=p['expires_ns']:
                        self.store.position_event(self.stream,sid,'MISSED_ENTRY',b.open_ns,{'reason':'ENTRY_PERMISSION_EXPIRED','fill_model':'NEXT_STRICTLY_LATER_BAR_OPEN'})
                        break
                    # The selected quote model/cost terms are explicit in plan.
                    spread=Decimal(p['spread_points'])
                    price=round_tick(b.open+d*(spread/2+slip),tick,d>0)
                    if not Decimal(p['entry_low'])<=price<=Decimal(p['entry_high']):
                        self.store.position_event(self.stream,sid,'MISSED_ENTRY',b.open_ns,{'reason':'NEXT_BAR_OPEN_OUTSIDE_FROZEN_ZONE','price':str(price),'source':b.source})
                        break
                    risk=d*(price-(Decimal(p['stop'])-d*slip))*mult+2*fee
                    if risk<=0:
                        self.store.position_event(self.stream,sid,'MISSED_ENTRY',b.open_ns,{'reason':'ACTUAL_FILL_RISK_INVALID'})
                        break
                    fill={'price':str(price),'initial_risk':str(risk),'at_ns':b.open_ns,'source':b.source,
                          'available_ns':b.available_ns,'fill_model':'NEXT_STRICTLY_LATER_NATIVE_BAR_OPEN_WITH_EXPLICIT_MODELED_SPREAD',
                          'execution_eligible':False}
                    self.store.position_event(self.stream,sid,'FILL',b.open_ns,fill)
                if b.open_ns<int(fill.get('at_ns',row['selected_ns'])):continue
                stop=Decimal(p['stop']);target=Decimal(p['targets'][0]['price'])
                stop_hit=b.low<=stop if d>0 else b.high>=stop
                # A touch is insufficient even for this hypothetical evaluator.
                target_hit=b.high>=target+tick if d>0 else b.low<=target-tick
                if stop_hit and target_hit:
                    self.store.position_event(self.stream,sid,'UNRESOLVED',b.close_ns,
                        {'reason':'STOP_AND_TARGET_IN_SAME_OHLC_BAR','position_closed':True,
                         'source':b.source,'favorable_sequence_assumed':False})
                    break
                if stop_hit or target_hit:
                    price=(min(stop,b.open) if d>0 else max(stop,b.open)) if stop_hit else target
                    price-=d*slip
                    net=d*(price-Decimal(fill['price']))*mult-2*fee
                    risk=Decimal(fill['initial_risk'])
                    self.store.position_event(self.stream,sid,'OUTCOME',b.close_ns,
                        {'exit_price':str(price),'net_pnl':str(net),'realized_r':str(net/risk),
                         'initial_risk_denominator':str(risk),'exit_reason':'STOP' if stop_hit else 'FIRST_TARGET_TRADE_THROUGH',
                         'source':b.source,'available_ns':b.available_ns,'hypothetical':True,
                         'management':'FULL_EXIT_FIRST_TARGET_FIXED_STOP'})
                    break


@fixed_decimal
def performance(store,stream,*,selected_from=None,selected_to=None):
    selected_rows=store.db.execute('SELECT selection,selected_ns FROM selections WHERE stream=?',(stream,)).fetchall()
    selected_ids={r['selection'] for r in selected_rows if (selected_from is None or r['selected_ns']>=selected_from) and (selected_to is None or r['selected_ns']<selected_to)}
    rows=[r for r in store.db.execute('SELECT * FROM position_events WHERE stream=? ORDER BY at_ns,event',(stream,)).fetchall() if r['selection'] in selected_ids]
    kinds={k:sum(r['kind']==k for r in rows) for k in ('FILL','OUTCOME','MISSED_ENTRY','UNRESOLVED')}
    outcomes=[json.loads(r['payload']) for r in rows if r['kind']=='OUTCOME']
    rs=[Decimal(o['realized_r']) for o in outcomes]
    pos=sum((r for r in rs if r>0),Decimal(0));neg=-sum((r for r in rs if r<0),Decimal(0))
    equity=peak=drawdown=Decimal(0)
    for r in rs:
        equity+=r;peak=max(peak,equity);drawdown=max(drawdown,peak-equity)
    selections=len(selected_ids)
    result={'selections':selections,'fills':kinds['FILL'],'resolved_outcomes':len(rs),
            'missed_entries':kinds['MISSED_ENTRY'],'unresolved_outcomes':kinds['UNRESOLVED'],
            'open_or_censored_fills':kinds['FILL']-len(rs)-kinds['UNRESOLVED'],
            'win_rate_resolved_only':sum(r>0 for r in rs)/len(rs) if rs else None,
            'net_expectancy_r_resolved_only':sum(rs)/len(rs) if rs else None,
            'profit_factor_resolved_only':pos/neg if neg else None,
            'profit_factor_unavailable_reason':'NO_RESOLVED_TRADES' if not rs else 'NO_RESOLVED_LOSSES' if not neg else None,
            'max_realized_r_drawdown':drawdown if rs else None,
            'resolved_net_r':sum(rs) if rs else None,
            'account_drawdown':None,'exact_intrabar_mae_mfe':None,
            'limitations':['Hypothetical reference-cost fills, not broker performance.',
                'Resolved-only statistics can be biased by unresolved/censored outcomes; not profitability validation.',
                'Realized-R drawdown is not mark-to-market account drawdown; exact intrabar MAE/MFE is unavailable from minute OHLC.']}
    return encode(result)
