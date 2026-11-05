"""Monotone pause precedence and bounded local shadow exposure, never broker sizing."""
import json
from decimal import Decimal as D
from monatise.research.unified.models import NS
SEVERITY={'NORMAL':0,'WIDEN':1,'REDUCE':2,'PAUSE':3}
def combine_actions(actions):
    actions=tuple(actions)
    if any(a not in SEVERITY for a in actions):raise ValueError('KNOWN_RISK_ACTION_REQUIRED')
    return max(actions,key=SEVERITY.get,default='NORMAL')
def ledger_state(store,stream,contract,cutoff):
    open_risk=D(0);contracts=0;daily_loss=D(0);unresolved=[]
    day=cutoff//(86400*NS)*(86400*NS)
    for r in store.db.execute('SELECT * FROM selections WHERE stream=? AND selected_ns<=?',(stream,cutoff)):
        p=json.loads(r['plan'])
        if p.get('contract_key')!=contract:continue
        events={e['kind']:e for e in store.db.execute('SELECT * FROM position_events WHERE stream=? AND selection=? AND at_ns<=?',(stream,r['selection'],cutoff))}
        if 'OUTCOME' in events:
            e=events['OUTCOME'];v=D(json.loads(e['payload'])['net_pnl'])
            if e['at_ns']>=day:daily_loss+=max(D(0),-v)
            continue
        if 'MISSED_ENTRY' in events:continue
        if 'UNRESOLVED' in events:unresolved.append(r['selection'])
        if 'FILL' in events or 'UNRESOLVED' in events or cutoff<p['expires_ns']:
            contracts+=1;open_risk+=D(p['initial_risk'])
    return {'contracts':contracts,'open_risk_usd':open_risk,'gross_realized_loss_usd':daily_loss,
            'unresolved_selections':unresolved,'risk_day_start_ns':day,'scope':'LOCAL_SHADOW_LEDGER_ONLY_NOT_BROKER_ACCOUNT'}
def gates(state,policy,plan=None,manual_pause=False):
    reasons=[]
    if manual_pause:reasons.append('MANUAL_RISK_PAUSE')
    if state['unresolved_selections']:reasons.append('UNRESOLVED_EXPOSURE_PAUSE')
    if state['gross_realized_loss_usd']>=policy.max_daily_loss_usd:reasons.append('DAILY_LOSS_CAP')
    if state['contracts']>=policy.max_contracts:reasons.append('INVENTORY_CAP')
    if state['open_risk_usd']>=policy.max_open_risk_usd:reasons.append('OPEN_RISK_CAP')
    if plan:
        if plan.initial_risk>policy.max_trade_risk_usd:reasons.append('TRADE_RISK_CAP')
        if state['open_risk_usd']+plan.initial_risk>policy.max_open_risk_usd:reasons.append('PROJECTED_OPEN_RISK_CAP')
        if state['gross_realized_loss_usd']+state['open_risk_usd']+plan.initial_risk>policy.max_daily_loss_usd:reasons.append('PROJECTED_DAILY_LOSS_CAP')
    return {'action':combine_actions(['PAUSE' if reasons else 'NORMAL']),'reasons':reasons,'state':state}
