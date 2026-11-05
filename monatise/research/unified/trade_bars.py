"""Transparent Databento receive-time minute bars from covered executions.

No forward filling, no synthetic no-print candle, no event-time/backdated
availability claim. This is a named optional research source transformation.
"""
from dataclasses import replace
from .models import Bar, MINUTE, identity, digest


def reconstruct_minutes(archive):
    """Replace vendor minutes only where retained trade coverage proves a window.

    Preserve vendor warm-up outside coverage. Mark discrepancies rather than
    hiding different trade conditions, breaks, or missing records.
    """
    from collections import defaultdict
    groups=defaultdict(list)
    for trade in archive.trades:
        groups[trade.receive_ns//MINUTE*MINUTE].append(trade)
    vendor={bar.open_ns:bar for bar in archive.bars}
    covered=set()
    for c in archive.coverage:
        if c.kind=='trades':
            first=(c.start_ns+MINUTE-1)//MINUTE*MINUTE
            covered.update(range(first,c.end_ns//MINUTE*MINUTE,MINUTE))
    rebuilt={};mismatches=[];no_print=[]
    latency=0 if archive.mode=='AS_RECORDED' else archive.report.get('publication_latency_ns',0)
    for start in sorted(covered):
        end=start+MINUTE
        proofs=[c for c in archive.coverage if c.kind=='trades' and c.start_ns<=start and end<=c.end_ns]
        if not proofs:continue
        rows=sorted(groups.get(start,()),key=lambda t:(t.receive_ns,t.available_ns,
            t.sequence if t.sequence is not None else -1,t.native_ordinal if t.native_ordinal is not None else -1))
        if not rows:
            if start in vendor:
                mismatches.append({'open_ns':start,'reason':'VENDOR_BAR_WITHOUT_RETAINED_EXECUTIONS'})
                rebuilt[start]=replace(vendor[start],quality=tuple(sorted(set(vendor[start].quality+('TRADE_VENDOR_AGGREGATE_MISMATCH',)))))
            else:no_print.append(start)
            continue
        available=max(end+latency,min(c.available_ns for c in proofs),max(t.available_ns for t in rows))
        prices=[t.price for t in rows]
        quality={q for t in rows for q in t.quality}
        old=vendor.get(start)
        if old:quality.update(old.quality)
        geometry=(prices[0],max(prices),min(prices),prices[-1],sum(t.size for t in rows))
        if old and geometry!=(old.open,old.high,old.low,old.close,old.volume):
            mismatches.append({'open_ns':start,'reason':'PRICE_OR_VOLUME_DISAGREEMENT'})
            quality.add('TRADE_VENDOR_AGGREGATE_MISMATCH')
        rebuilt[start]=Bar(archive.instrument.key,'1m',start,end,available,*geometry,
            identity('receive-time-trade-bar-v1',*(t.source for t in rows),*(c.source for c in proofs)),tuple(sorted(quality)))
    bars=dict(vendor);bars.update(rebuilt)
    report={**archive.report,'bar_source_mode':'TRADE_AGGREGATED_WHERE_COVERED',
        'trade_aggregation':{'clock':'DATABENTO_TS_RECV','bar_interval':'LEFT_CLOSED_RIGHT_OPEN',
            'rebuilt_minutes':len(rebuilt),'reviewed_no_print_minutes':len(no_print),
            'vendor_disagreements':mismatches,'vendor_warmup_minutes':len(vendor.keys()-rebuilt.keys()),
            'retroactive_trade_break_adjustments':'NOT_INFERRED','forward_filled_bars':0}}
    manifest=digest({'parent_manifest_hash':archive.manifest_hash,'bar_source_mode':'TRADE_AGGREGATED_WHERE_COVERED',
        'transformation':'receive-time-trade-bars-v1'})
    report['parent_manifest_hash']=archive.manifest_hash;report['manifest_hash']=manifest
    # Reviewed absence can support parent aggregation without fabricating a bar.
    coverage=tuple(archive.coverage)+tuple(replace(c,kind='ohlcv-1m',source=identity('trade-derived-coverage',c.source))
        for c in archive.coverage if c.kind=='trades')
    return replace(archive,bars=tuple(sorted(bars.values(),key=lambda b:b.open_ns)),coverage=coverage,
                   manifest_hash=manifest,report=report)
