"""Single preferred BTC reference setup; execution permission never hides analysis."""
from datetime import datetime,timezone
from zoneinfo import ZoneInfo

def text_report(result):
    a=result['analysis'];p=a.get('plan');i=result['instrument'];stamp=datetime.fromtimestamp(result['cutoff_ns']/10**9,timezone.utc)
    lines=[f"BTC {i['symbol']} — {a['action']}", 'CME FUTURES REFERENCE PRICES',
           f"Data: {stamp.astimezone(ZoneInfo('Africa/Lagos')).isoformat()} (UTC {stamp.isoformat()})"]
    if a['status']=='STALE_DATA_REFRESH_REQUIRED':lines.append('Stale quote: refresh native data before reassessing; conditional analysis threshold exceeded.')
    if p:
        zone=p.get('entry_zone',[p.get('entry_low'),p.get('entry_high')])
        lines += [f"Status: {a['status']}",f"Entry zone: {zone[0]}–{zone[1]}",
                  f"Trigger: {a['trigger']}",f"Structural stop/invalidation: {p['stop']}",
                  'Targets: '+', '.join(str(t['price']) for t in p['targets']),
                  'Net reward/risk: '+(', '.join(p['net_rr']) if isinstance(p['net_rr'],list) else p['net_rr'])]
    else:
        lines += ['No supported setup: '+', '.join(a.get('reason',[])),
                  'Reconsider after a new confirmed structural trigger or supported future retest with valid invalidation and reward/risk.']
    if a.get('observed_native_quote_timestamp_ns') is not None:lines.append('Native quote timestamp: '+datetime.fromtimestamp(a['observed_native_quote_timestamp_ns']/10**9,timezone.utc).isoformat())
    if a.get('observed_native_quote_age_seconds') is not None:lines.append('Last observed native quote age at snapshot: '+a['observed_native_quote_age_seconds']+' seconds; revalidate before entry.')
    r=a.get('regime',{});lines.append('Available intraday regime: '+r.get('state','UNKNOWN')+(' '+r['side'] if r.get('side') else ''))
    if a.get('limitations'):lines.append('Limitations: '+', '.join(a['limitations']))
    lines += [f"Trading permission: {result['trade_action']} ({result['reason']}); execution disabled.",
              'Reference analysis only; no verified FTMO/Equity Edge CFD basis or broker sizing.']
    return '\n'.join(lines)+'\n'
