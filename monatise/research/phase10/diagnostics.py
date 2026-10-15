"""Explain sparse provider bars without filling gaps or asserting completeness."""
from collections import defaultdict
from monatise.research.institutional.models import digest

NS=10**9


def second_intervals(gate,*,cutoff_ns,watermark_ns=None,source_unreliable=False):
    if source_unreliable or any(s in gate.faults for s in ('trades','ohlcv-1s')):
        return dict(status='UNAVAILABLE_UNRELIABLE_SOURCE',gap_fill_count=0,exchange_continuity_certified=False)
    values=list(gate.lineage_observations())
    trades=[v for v in values if v.schema=='trades' and v.source.admission_ns<=cutoff_ns]
    bars=[v for v in values if v.schema=='ohlcv-1s' and v.source.admission_ns<=cutoff_ns]
    if not trades or not bars:
        return dict(status='INSUFFICIENT_CAPTURED_EVIDENCE',gap_fill_count=0,exchange_continuity_certified=False)
    # Provider OHLCV is bucketed by trade ts_recv, unlike event-time derived bars.
    start=max(min(v.receive_ns for v in trades),min(v.payload[0] for v in bars))
    start=(start+NS-1)//NS*NS
    end=min((cutoff_ns-10*NS)//NS*NS,max(v.payload[1] for v in bars),watermark_ns or cutoff_ns)
    if end<=start or (end-start)//NS>100000:
        return dict(status='OUTSIDE_BOUNDED_COMPARISON_WINDOW',gap_fill_count=0,exchange_continuity_certified=False)
    executed=defaultdict(int)
    for v in trades:
        second=v.receive_ns//NS*NS
        if start<=second<end:executed[second]+=v.payload[1]
    published={v.payload[0]:v.payload[6] for v in bars if start<=v.payload[0]<end}
    missing_no_captured_trade=missing_with_captured_trade=volume_differences=0
    for second in range(start,end,NS):
        if second not in published:
            if executed.get(second):missing_with_captured_trade+=1
            else:missing_no_captured_trade+=1
        elif published[second]!=executed.get(second,0):volume_differences+=1
    result=dict(status='CAPTURED_STREAM_COMPARISON_ONLY',start_ns=start,end_ns=end,
        clock='PROVIDER_TRADE_RECEIVE_TIME_FOR_NATIVE_OHLCV',
        seconds_without_bar_and_without_captured_trade=missing_no_captured_trade,
        seconds_without_bar_but_with_captured_trade=missing_with_captured_trade,
        bar_trade_volume_difference_seconds=volume_differences,
        missing_bars_consistent_with_no_captured_trades=missing_with_captured_trade==0,
        transport_or_exchange_completeness_proved=False,exchange_continuity_certified=False,
        gap_fill_count=0,quality_fault_cleared=False,
        limitations=['No captured trade is not proof of no exchange trade.',
            'Trade conditions, retroactive breaks and different stream prefixes may require source review.',
            'Sparse bars remain unsuitable for engines requiring consecutive time buckets.'])
    result['reproducibility_sha256']=digest(result)
    return result
