"""Human-readable availability and existing-engine results, without trade calls."""
import json
from datetime import datetime,UTC


def text_report(report):
    lines=['Monatise native futures analysis — read-only research',
        'As of '+datetime.fromtimestamp(report['request']['cutoff_ns']/10**9,UTC).isoformat()]
    for symbol,value in report['instruments'].items():
        lines+=['',symbol+': '+value['availability']]
        if 'reason' in value:lines.append('Reason: '+value['reason'])
        health=value.get('capture_health',{})
        if health:
            lines.append('Capture: '+health.get('status','UNKNOWN')+'; quarantined='+str(bool(health.get('quarantined')))+'; stale checkpoint='+str(bool(health.get('stale_checkpoint'))))
            if health.get('reasons'):lines.append('Source issues: '+', '.join(health['reasons']))
        components=value.get('components',{})
        for tf in report['request']['timeframes']:
            part=components.get('price:'+tf,{})
            if not part.get('available'):
                lines.append(tf+': unavailable — '+part.get('reason','insufficient validated history'));continue
            lines.append(tf+': '+('historical context' if part.get('historical_only') else 'available')+'; '+part.get('coverage',''))
            for engine in ('structure','liquidity','fibonacci'):
                if engine in part:lines.append('  '+engine+': '+json.dumps(part[engine],sort_keys=True,separators=(',',':')))
                else:
                    state=part.get('engine_health',{}).get(engine,{})
                    lines.append('  '+engine+': unavailable — '+state.get('reason','missing upstream evidence'))
        features=components.get('trade_features',{})
        if features.get('available'):
            metrics=features['result'];lines.append('Captured-window VWAP: '+str(metrics['vwap'])+'; volume-profile POC: '+str(metrics['point_of_control']))
            lines.append('Executed contracts: '+str(metrics['executed_contracts'])+'; CVD: '+str(metrics['cvd']))
            profile=sorted(metrics['profile'],key=lambda row:(-row[1],row[0]))[:10]
            lines.append('Top captured price/volume levels (at most 10): '+json.dumps(profile,separators=(',',':')))
            lines.extend('  '+text for text in metrics['limitations'])
        else:lines.append('Trade features unavailable: '+features.get('reason','missing validated executions'))
        missing=[name for name,part in components.items() if not part.get('available')]
        lines.append('Missing components: '+', '.join(missing))
    lines+=['','Qualification: NOT_EVALUATED. Decision: NO_TRADE.','Native futures prices; broker basis mapping is separate.']
    return '\n'.join(lines)
