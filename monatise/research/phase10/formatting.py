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
        scope=value.get('validation',{}).get('source_quarantine_scope','NONE')
        if scope=='COMPONENT_SOURCE_QUARANTINE':
            lines.append('Trade timestamp quality is quarantined. Independently validated native candle context is listed separately; flow/VWAP/profile remain unavailable.')
        elif scope!='NONE':
            lines.append('Quarantined instrument: calculated components below are retained context, unavailable for current live use.')
        sealed=health.get('status')=='SEALED_HISTORICAL_CAPTURE'
        if sealed:lines.append('Completed capture: historical context only; no current live connection.')
        components=value.get('components',{})
        history=value.get('history_warmup',health.get('history_warmup',{}))
        if history:
            lines.append('Warm-up history: '+history.get('status','UNKNOWN'))
            if history.get('faults'):lines.append('  Retained history faults: '+json.dumps(history['faults'],sort_keys=True))
            if history.get('reason'):lines.append('  '+history['reason'])
        for tf in report['request']['timeframes']:
            part=components.get('price:'+tf,{})
            if not part.get('available'):
                lines.append(tf+': unavailable — '+part.get('reason','insufficient validated history'));continue
            lines.append(tf+': '+('historical context' if part.get('historical_only') or sealed else 'available')+
                '; validated candles='+str(part.get('validated_candle_count','unknown'))+'; '+part.get('coverage',''))
            if report.get('version')=='native-futures-market-information-v1':
                stats=part['session_statistics']
                lines.append('  Observed OHLC: '+', '.join(str(stats[k]) for k in ('open','high','low','close'))+
                    '; volume contracts='+str(stats['volume_contracts'])+'; age seconds='+str(part['age_ns']/10**9)+
                    '; gaps between observed buckets='+str(part['gaps_between_observed_buckets']))
                native=part.get('native_analysis',{})
                if native.get('available'):
                    structure=native['structure'];fib=native['fibonacci']
                    lines.append('  Native futures structure: '+structure['state']+
                        '; confirmed highs='+str(structure['confirmed_high_count'])+'; confirmed lows='+str(structure['confirmed_low_count']))
                    lines.append('  Confirmed-swing Fibonacci: '+(fib['direction']+'; retracements='+json.dumps(fib['retracements'],sort_keys=True) if fib.get('available') else fib.get('reason','unavailable')))
                    lines.append('  Repeated-extrema liquidity proxies: '+str(len(native['liquidity_proxies']['zones']))+'; resting orders unverified')
                    for name,item in native.get('close_indicators',{}).items():
                        if isinstance(item,dict) and 'available' in item:
                            lines.append('  '+name+': '+(str(item.get('value',item.get('observed'))) if item['available'] else 'unavailable — '+item.get('reason','insufficient closes')))
                    if native.get('close_indicators'):lines.append('  Indicator seeds use this retained native frame; proprietary chart scripts are not reproduced.')
                elif native:lines.append('  Native futures analysis unavailable: '+native.get('reason','insufficient evidence'))
                continue
            for engine in ('regime','structure','liquidity','fibonacci'):
                if engine in part:
                    result=part[engine]
                    if engine=='regime':text=str(result.get('state'))+'; confidence='+str(result.get('confidence'))
                    elif engine=='structure':text=str(result.get('bias'))+'; state='+str(result.get('state'))
                    elif engine=='liquidity':
                        text='buy-side level='+str((result.get('nearest_buy_side') or {}).get('price'))+'; sell-side level='+str((result.get('nearest_sell_side') or {}).get('price'))
                    else:
                        anchor=result.get('primary_anchor')
                        text=('direction='+str(result.get('direction'))+'; anchor quality='+str(anchor.get('quality'))+
                            '; nearest retracement='+str((result.get('nearest_retracement') or {}).get('price'))) if anchor else 'no qualifying current anchor'
                    lines.append('  '+engine+': '+text)
                else:
                    state=part.get('engine_health',{}).get(engine,{})
                    lines.append('  '+engine+': unavailable — '+state.get('reason','missing upstream evidence'))
        scope=value.get('validation',{}).get('source_quarantine_scope')
        if scope:lines.append('Source quarantine applying to this instrument: '+scope)
        if value.get('multi_timeframe'):lines.append('Multi-timeframe structure: '+value['multi_timeframe']['state'])
        for schema,detail in value.get('validation',{}).get('first_fault_details',{}).items():
            lines.append('Validation '+schema+': '+detail.get('classification',detail['reason'])+'; no automatic admission')
        for schema,review in value.get('validation',{}).get('price_fault_reviews',{}).items():
            lines.append('Price review '+schema+': '+review['status']+'; original price rejection retained')
        for review in value.get('validation',{}).get('source_record_reviews',{}).values():
            for issue in review.get('examples',[])[:1]:
                lines.append('Source timestamp review: '+issue['flag']+'; receive minus event ns='+str(issue['receive_minus_event_ns'])+'; no timestamp repair')
        features=components.get('trade_features',{})
        if features.get('available'):
            metrics=features['result'];lines.append('Captured-window VWAP: '+str(metrics['vwap'])+'; volume-profile POC: '+str(metrics['point_of_control']))
            lines.append('Executed contracts: '+str(metrics['executed_contracts'])+'; CVD: '+str(metrics['cvd']))
            delta=metrics['known_side_delta']
            pressure='buyer-initiated' if delta>0 else 'seller-initiated' if delta<0 else 'balanced known sides'
            lines.append('Captured aggressor pressure: '+pressure+'; buy='+str(metrics['buy_contracts'])+
                '; sell='+str(metrics['sell_contracts'])+'; unknown='+str(metrics['unknown_side_contracts']))
            inputs=metrics['inputs']
            lines.append('Trade window UTC: '+datetime.fromtimestamp(inputs['start_ns']/10**9,UTC).isoformat()+
                ' through '+datetime.fromtimestamp(inputs['end_ns']/10**9,UTC).isoformat())
            profile=sorted(metrics['profile'],key=lambda row:(-row[1],row[0]))[:10]
            lines.append('Top captured price/volume levels (at most 10): '+json.dumps(profile,separators=(',',':')))
            lines.extend('  '+text for text in metrics['limitations'])
        else:lines.append('Trade features unavailable: '+features.get('reason','missing validated executions'))
        for schema in ('mbp-1','mbp-10'):
            part=components.get(schema,{})
            if part.get('available') and part.get('quote'):
                q=part['quote'];lines.append(schema+' displayed bid/ask: '+str(q['bid'])+' / '+str(q['ask'])+
                    '; sizes='+str(q['bid_contracts'])+' / '+str(q['ask_contracts'])+'; spread='+str(q['spread'])+
                    '; receive UTC='+datetime.fromtimestamp(q['receive_ns']/10**9,UTC).isoformat()+'; broker executable quote=False')
        oi=components.get('open_interest',{})
        if oi.get('available'):
            lines.append('Published open interest: '+str(oi['contracts'])+' contracts; reference UTC='+
                datetime.fromtimestamp(oi['reference_ns']/10**9,UTC).isoformat()+'; signed dealer position unknown')
        missing=[name for name,part in components.items() if not part.get('available')]
        lines.append('Missing components: '+', '.join(missing))
        seconds=value.get('seconds_bar_diagnostics',{})
        if seconds.get('status')=='CAPTURED_STREAM_COMPARISON_ONLY':
            lines.append('Sparse seconds: '+str(seconds['seconds_without_bar_and_without_captured_trade'])+
                ' without a bar or captured trade; '+str(seconds['seconds_without_bar_but_with_captured_trade'])+
                ' missing bars with captured trades; volume differences='+str(seconds['bar_trade_volume_difference_seconds']))
        lines.append('Participant identities unavailable. Depth/absorption/iceberg detection is not live-validated.')
    if report.get('version')=='native-futures-market-information-v1':
        lines+=['','Native futures market information only; no trading signal or participant identity is inferred.',
            'Crypto engines, frozen H1 selection and GIL qualification are retired from this request path.',
            'No orders or provider requests are created. Exchange completeness remains unverified.']
    else:
        lines+=['','Qualification: NOT_EVALUATED. Decision: NO_TRADE.','Native futures prices; broker basis mapping is separate.',
            'Gamma/GIL certification and complete exchange continuity are unavailable. No orders or provider requests are created.']
    return '\n'.join(lines)
