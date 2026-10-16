"""Descriptive executed-flow windows; no participant identity or trade rules.

Window clocks are native trade ts_recv, consistent with Databento OHLCV sampling.
All input executions are already admitted. No size/price observation is rejected
by this module. Reference percentiles and price/flow contrasts describe samples;
they are not vendor thresholds, validated institutional signals or calibration.
"""
from bisect import bisect_left, bisect_right
from decimal import Decimal, localcontext

from monatise.research.institutional.models import MarketObservation, digest

SECOND = 10**9
MINUTE = 60*SECOND


def _positions(values):
    return digest(tuple((v.source.archive_sha256, v.source.ordinal,
                         v.source.record_sha256) for v in values))


def _summary(values, start, end, tick):
    buy = sell = unknown = weighted = volume = 0
    for v in values:
        price, size, side = v.payload
        volume += size
        weighted += int(Decimal(price)*10**9)*size
        if side == 'BUY': buy += size
        elif side == 'SELL': sell += size
        else: unknown += size
    known = buy+sell
    seconds = Decimal(end-start)/SECOND
    prices = tuple(Decimal(v.payload[0]) for v in values)
    with localcontext() as ctx:
        ctx.prec = 40
        result = dict(start_ns=start, end_ns=end, duration_seconds=str(seconds),
            observed_trade_events=len(values), observed_contracts=volume,
            buy_contracts=buy, sell_contracts=sell, unknown_side_contracts=unknown,
            known_side_delta=buy-sell, total_signed_flow=None if unknown else buy-sell,
            buyer_share_of_known_volume=None if not known else str(Decimal(buy)/known),
            unknown_share_of_observed_volume=None if not volume else str(Decimal(unknown)/volume),
            contracts_per_second=str(Decimal(volume)/seconds),
            buy_contracts_per_second=str(Decimal(buy)/seconds),
            sell_contracts_per_second=str(Decimal(sell)/seconds),
            known_delta_per_second=str(Decimal(buy-sell)/seconds),
            vwap=None if not volume else str(Decimal(weighted)/(volume*10**9)),
            first_price=None if not prices else str(prices[0]),
            last_price=None if not prices else str(prices[-1]),
            net_price_change_ticks=None if len(prices)<2 else str((prices[-1]-prices[0])/tick),
            observed_price_range_ticks=None if not prices else str((max(prices)-min(prices))/tick),
            input_positions_sha256=_positions(values),
            zero_observed_events_means='NO_EVENTS_IN_RETAINED_SAMPLE; NOT_PROOF_OF_NO_EXCHANGE_ACTIVITY')
    return result


def _size_reference(values, baseline, start, end):
    sizes = sorted(v.payload[1] for v in baseline)
    n = len(sizes)
    p95 = sizes[(95*n+99)//100-1] if n else None
    median = None if not n else str((Decimal(sizes[(n-1)//2])+sizes[n//2])/2)
    larger = [] if p95 is None else [v for v in values if v.payload[1]>p95]
    examples = sorted(larger, key=lambda v:(-v.payload[1], v.receive_ns,
                       v.source.archive_sha256, v.source.ordinal))[:10]
    return dict(available=bool(n), reference_start_ns=start, reference_end_ns=end,
        reference_observed_events=n, reference_positions_sha256=_positions(baseline),
        median_contracts=median, p95_contracts=p95, percentile_method='NEAREST_RANK',
        descriptive_rule='STRICTLY_GREATER_THAN_PRECEDING_RETAINED_SAMPLE_P95',
        vendor_prescribed_threshold=False, data_rejection_applied=False,
        above_reference_p95_events=None if p95 is None else len(larger),
        above_reference_p95_contracts=None if p95 is None else sum(v.payload[1] for v in larger),
        largest_observed_event_contracts=max((v.payload[1] for v in values), default=None),
        examples=[dict(receive_ns=v.receive_ns, event_ns=v.event_ns,
            contracts=v.payload[1], aggressor=v.payload[2], price=v.payload[0],
            empirical_reference_percentile=str(Decimal(bisect_right(sizes,v.payload[1]))*100/n),
            source_record_sha256=v.source.record_sha256, source_position=v.source.position)
            for v in examples], example_display_limit=10,
        limitation='Trade events are not identified parent orders or institutional accounts. '
                   'A small or truncated reference sample can be unrepresentative.')


def _response(current, reference):
    change = current['net_price_change_ticks']
    delta = current['known_side_delta']
    contrast = ('UNAVAILABLE_TWO_TRADE_EVENTS_REQUIRED' if change is None else
        'BUY_AGGRESSION_WITHOUT_UPWARD_NET_PROGRESS' if delta>0 and Decimal(change)<=0 else
        'SELL_AGGRESSION_WITHOUT_DOWNWARD_NET_PROGRESS' if delta<0 and Decimal(change)>=0 else
        'NO_OPPOSING_PRICE_FLOW_CONTRAST')
    activity_rising = (reference['observed_trade_events']>0 and
        Decimal(current['contracts_per_second'])>Decimal(reference['contracts_per_second']))
    side = 'BUY' if delta>0 else 'SELL' if delta<0 else None
    side_rate_rising = bool(side and reference['observed_trade_events'] and
        Decimal(current['buy_contracts_per_second' if side=='BUY' else 'sell_contracts_per_second'])>
        Decimal(reference['buy_contracts_per_second' if side=='BUY' else 'sell_contracts_per_second']))
    candidate = (current['unknown_side_contracts']==0 and activity_rising and side_rate_rising and
        contrast in {'BUY_AGGRESSION_WITHOUT_UPWARD_NET_PROGRESS',
                     'SELL_AGGRESSION_WITHOUT_DOWNWARD_NET_PROGRESS'})
    return dict(price_flow_contrast=contrast, observed_volume_rate_above_reference=activity_rising,
        aggressor_side_rate_above_reference=side_rate_rising,
        possible_absorption_pattern=candidate,
        interpretation=('POSSIBLE_PASSIVE_SELL_ABSORPTION' if candidate and side=='BUY' else
                        'POSSIBLE_PASSIVE_BUY_ABSORPTION' if candidate else 'ABSORPTION_NOT_ESTABLISHED'),
        unknown_side_prevents_absorption_label=bool(current['unknown_side_contracts']),
        absorption_confirmed=False, institutional_accumulation_confirmed=False,
        criteria='Known-side imbalance against net price progress; observed volume and aggressor '
                 'rates exceed preceding retained reference; no unknown aggressors.',
        limitation='Trade-only interpretation. No temporal depth, replenishment, iceberg, '
                   'participant identity or opening/closing-position evidence. Alternative '
                   'explanations include timing, hedging, short covering and mixed activity.')


def recent_trade_flow(observations, *, cutoff_ns, clock_offset_bounds_ns=None):
    """Causal windows ending at the latest admitted native trade receive timestamp."""
    if type(cutoff_ns) is not int or cutoff_ns<=0:
        raise ValueError('analysis_cutoff_required')
    values=[];positions={};contract=None;previous=None
    for v in observations:
        if not isinstance(v,MarketObservation) or v.schema!='trades' or v.receive_ns is None:
            raise ValueError('native_executed_trades_required')
        if v.source.admission_ns>cutoff_ns:continue
        if contract is not None and (v.contract!=contract or v.source.evidence_kind!=values[0].source.evidence_kind):
            raise ValueError('mixed_contract_or_evidence_kind')
        prior=positions.get(v.source.position)
        if prior is not None:
            if prior!=v:raise ValueError('source_position_revision')
            continue
        if previous is not None and v.receive_ns<previous:
            raise ValueError('unordered_provider_receive_timestamps')
        positions[v.source.position]=v;contract=v.contract;previous=v.receive_ns;values.append(v)
    if not values:return dict(available=False,reason='no_admitted_trade_observations')
    values=tuple(values);times=tuple(v.receive_ns for v in values);end=times[-1]+1
    tick=contract.tick_size
    def sample(start,stop):return values[bisect_left(times,start):bisect_left(times,stop)]
    windows={}
    for label,duration in (('1m',MINUTE),('5m',5*MINUTE),('15m',15*MINUTE)):
        start=end-duration;reference_start=start-30*MINUTE
        current=sample(start,end);baseline=sample(reference_start,start)
        summary=_summary(current,start,end,tick)
        summary.update(earliest_retained_trade_after_requested_start=times[0]>start,
            size_reference=_size_reference(current,baseline,reference_start,start),
            price_response=_response(summary,_summary(baseline,reference_start,start,tick)))
        summary['size_reference']['earliest_retained_trade_after_reference_start']=times[0]>reference_start
        windows[label]=summary
    prior_start=end-6*MINUTE;prior_end=end-MINUTE
    prior=_summary(sample(prior_start,prior_end),prior_start,prior_end,tick)
    current=windows['1m'];a=current['buyer_share_of_known_volume'];b=prior['buyer_share_of_known_volume']
    comparison=dict(current_window='1m',previous_five_minutes=prior,
        buyer_share_change_percentage_points=None if a is None or b is None else str((Decimal(a)-Decimal(b))*100),
        known_delta_rate_change=str(Decimal(current['known_delta_per_second'])-Decimal(prior['known_delta_per_second'])),
        volumes_compared_as_rates=True,
        earliest_retained_trade_after_reference_start=times[0]>prior_start)
    buckets=[]
    for i in range(5):
        start=end-(5-i)*MINUTE;stop=start+MINUTE
        buckets.append(_summary(sample(start,stop),start,stop,tick))
    persistence=dict(buckets=buckets,buy_dominant_buckets=sum(x['known_side_delta']>0 for x in buckets),
        sell_dominant_buckets=sum(x['known_side_delta']<0 for x in buckets),
        balanced_known_side_buckets=sum(x['known_side_delta']==0 and x['buy_contracts']+x['sell_contracts']>0 for x in buckets),
        no_known_side_observations_buckets=sum(x['buy_contracts']+x['sell_contracts']==0 for x in buckets),
        bucket_count=5,participant_identity_inferred=False)
    result=dict(available=True,version='native-descriptive-trade-flow-v1',
        clock_basis='DATABENTO_TRADE_TS_RECV',window_anchor='LATEST_ADMITTED_TRADE_RECEIVE_TIME_PLUS_1NS',
        analysis_cutoff_ns=cutoff_ns,latest_trade_receive_ns=times[-1],window_end_ns=end,
        signed_local_clock_difference_ns=cutoff_ns-times[-1],
        retained_start_ns=times[0],retained_end_ns=end,retained_trade_events=len(values),
        retained_positions_sha256=_positions(values),contract_identity=list(contract.identity),
        coverage='RETAINED_ADMITTED_EXECUTIONS; COMPLETE_EXCHANGE_HISTORY_UNCERTIFIED',
        windows=windows,comparison_1m_vs_preceding_5m=comparison,persistence_5m=persistence,
        institutional_identity_available=False,opening_or_closing_position_known=False,
        trade_signal_produced=False,execution_eligible=False,data_rejection_applied=False,
        methodological_parameters_are_vendor_rules=False,
        limitations=['Window ends at the displayed latest trade, not an assumed current wall clock.',
            'No observed event is not proof of no exchange activity. Retention can truncate references.',
            'Unknown aggressors remain unknown. Price/flow contrasts do not confirm absorption.',
            'Percentiles describe earlier retained trade-event sizes; they do not identify institutions.'])
    if clock_offset_bounds_ns is not None:
        if len(clock_offset_bounds_ns)!=2 or clock_offset_bounds_ns[0]>clock_offset_bounds_ns[1]:
            raise ValueError('ordered_clock_bounds_required')
        result['latest_trade_age_at_source_observation_utc_bounds_ns']=[
            cutoff_ns-times[-1]+offset for offset in clock_offset_bounds_ns]
    result['reproducibility_sha256']=digest(result)
    return result
