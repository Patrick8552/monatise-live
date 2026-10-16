from dataclasses import replace
from decimal import Decimal
import databento_dbn as dbn
import pytest

from monatise.research.institutional.models import digest
from monatise.research.institutional.indicators import trade_indicators
from monatise.research.native_futures.order_flow import recent_trade_flow, SECOND, MINUTE
from tests.research.test_institutional import trade, NOW_NS

LAST=NOW_NS-SECOND
END=LAST+1


def event(offset=0, *, ordinal=0, size=1, side=dbn.Side.BID, price='2500', product='GC'):
    return trade(receive=LAST-offset,ordinal=ordinal,size=size,side=side,price=price,product=product)


def result(values):
    return recent_trade_flow(values,cutoff_ns=NOW_NS)


def test_nonoverlapping_window_comparison_uses_rates_and_correct_native_clock():
    rows=[event(61*SECOND,ordinal=1,size=10),event(45*SECOND,ordinal=2,size=2),
          event(ordinal=3,size=3,side=dbn.Side.ASK,price='2501')]
    r=result(rows);one=r['windows']['1m'];prior=r['comparison_1m_vs_preceding_5m']['previous_five_minutes']
    assert r['window_end_ns']==END and r['clock_basis']=='DATABENTO_TRADE_TS_RECV'
    assert one['observed_contracts']==5 and one['buy_contracts']==2 and one['sell_contracts']==3
    assert one['known_side_delta']==-1 and one['vwap']=='2500.6'
    assert prior['observed_contracts']==10 and prior['duration_seconds']=='300'
    assert Decimal(one['contracts_per_second'])>Decimal(prior['contracts_per_second'])
    assert Decimal(r['comparison_1m_vs_preceding_5m']['buyer_share_change_percentage_points'])==-60
    expected=trade_indicators(rows[1:],start_ns=END-MINUTE,end_ns=END,session_reference='FIXTURE')
    assert one['vwap']==expected['vwap'] and one['known_side_delta']==expected['known_side_delta']


def test_inclusive_start_exclusive_end_and_future_admission_are_causal():
    boundary=trade(receive=END-MINUTE,ordinal=1,size=4)
    future=event(SECOND,ordinal=2,size=999)
    future=replace(future,source=replace(future.source,admission_ns=NOW_NS+1))
    r=result([boundary,future,event(ordinal=3,size=2)])
    assert r['windows']['1m']['observed_contracts']==6
    assert r['retained_trade_events']==2
    assert r['comparison_1m_vs_preceding_5m']['previous_five_minutes']['observed_trade_events']==0


def test_duplicate_positions_are_counted_once_but_equal_payload_different_positions_survive():
    a=event(ordinal=1,size=3);b=event(ordinal=2,size=3)
    r=result([a,a,b]);assert r['retained_trade_events']==2 and r['windows']['1m']['observed_contracts']==6


def test_revisions_unordered_and_mixed_contracts_are_unavailable_errors():
    with pytest.raises(ValueError,match='revision'):result([event(ordinal=1),event(ordinal=1,price='2501')])
    with pytest.raises(ValueError,match='unordered'):result([event(ordinal=1),event(SECOND,ordinal=2)])
    with pytest.raises(ValueError,match='mixed_contract'):result([event(SECOND,ordinal=1),event(ordinal=2,product='ES')])
    with pytest.raises(ValueError,match='executed_trades'):result([object()])


def test_unknown_aggressors_stay_unknown_and_prevent_absorption_label():
    rows=[event(2*MINUTE,ordinal=1),event(SECOND,ordinal=2,size=30),
          event(ordinal=3,size=30,side=dbn.Side.NONE,price='2499')]
    r=result(rows)['windows']['1m'];assert r['unknown_side_contracts']==30
    assert r['total_signed_flow'] is None and r['unknown_share_of_observed_volume']=='0.5'
    assert not r['price_response']['possible_absorption_pattern']
    assert r['price_response']['unknown_side_prevents_absorption_label']


def test_size_reference_is_causal_strict_nearest_rank_and_examples_do_not_truncate_metrics():
    baseline=[event((180-i)*SECOND,ordinal=i,size=i+1) for i in range(100)]
    current=[event((20-i)*SECOND,ordinal=100+i,size=101+i) for i in range(15)]
    rows=baseline+current+[event(ordinal=200,size=1)]
    r=result(rows)['windows']['1m']['size_reference']
    assert r['reference_observed_events']==100 and r['p95_contracts']==95
    assert r['median_contracts']=='50.5'
    assert r['above_reference_p95_events']==15 and len(r['examples'])==10
    assert r['above_reference_p95_contracts']==sum(range(101,116))
    assert not r['data_rejection_applied'] and not r['vendor_prescribed_threshold']


def test_flat_reference_does_not_label_every_one_contract_trade_large():
    r=result([event(2*MINUTE,ordinal=1),event(SECOND,ordinal=2),event(ordinal=3)])
    s=r['windows']['1m']['size_reference']
    assert s['reference_observed_events']==1 and s['p95_contracts']==1 and s['above_reference_p95_events']==0


def test_absent_reference_and_retention_limits_are_explicit():
    r=result([event(ordinal=1)])
    s=r['windows']['1m']['size_reference']
    assert not s['available'] and s['p95_contracts'] is None and s['above_reference_p95_events'] is None
    assert s['earliest_retained_trade_after_reference_start']
    assert r['windows']['15m']['earliest_retained_trade_after_requested_start']
    assert not r['institutional_identity_available'] and not r['opening_or_closing_position_known']


@pytest.mark.parametrize('side,price,interpretation',[(dbn.Side.BID,'2499','POSSIBLE_PASSIVE_SELL_ABSORPTION'),
    (dbn.Side.ASK,'2501','POSSIBLE_PASSIVE_BUY_ABSORPTION')])
def test_flow_price_contrasts_are_only_explained_candidates(side,price,interpretation):
    rows=[event(2*MINUTE,ordinal=1),event(SECOND,ordinal=2,size=30,side=side),
          event(ordinal=3,size=30,side=side,price=price)]
    p=result(rows)['windows']['1m']['price_response']
    assert p['possible_absorption_pattern'] and p['interpretation']==interpretation
    assert not p['absorption_confirmed'] and not p['institutional_accumulation_confirmed']


def test_aligned_price_flow_and_single_trade_are_not_absorption():
    rows=[event(2*MINUTE,ordinal=1),event(SECOND,ordinal=2,size=30),event(ordinal=3,size=30,price='2501')]
    assert not result(rows)['windows']['1m']['price_response']['possible_absorption_pattern']
    assert result([event()])['windows']['1m']['price_response']['price_flow_contrast']=='UNAVAILABLE_TWO_TRADE_EVENTS_REQUIRED'


def test_five_minute_buckets_keep_balanced_unknown_and_unobserved_separate():
    rows=[event(4*MINUTE+SECOND,ordinal=1),event(3*MINUTE+SECOND,ordinal=2,side=dbn.Side.ASK),
          event(2*MINUTE+2*SECOND,ordinal=3),event(2*MINUTE+SECOND,ordinal=4,side=dbn.Side.ASK),
          event(MINUTE+SECOND,ordinal=5,side=dbn.Side.NONE),event(ordinal=6,side=dbn.Side.NONE)]
    p=result(rows)['persistence_5m']
    assert p['buy_dominant_buckets']==1 and p['sell_dominant_buckets']==1
    assert p['balanced_known_side_buckets']==1 and p['no_known_side_observations_buckets']==2
    assert not p['participant_identity_inferred']


def test_original_observations_hashes_and_timestamps_do_not_change():
    rows=[event(SECOND,ordinal=1),event(ordinal=2)]
    before=digest(rows);r=recent_trade_flow(rows,cutoff_ns=NOW_NS,clock_offset_bounds_ns=(10,20))
    assert digest(rows)==before and r['latest_trade_receive_ns']==LAST
    assert r['latest_trade_age_at_source_observation_utc_bounds_ns']==[SECOND+10,SECOND+20]
    assert not r['data_rejection_applied'] and not r['trade_signal_produced']


def test_no_observations_and_future_only_are_unavailable():
    assert not result([])['available']
    v=event();v=replace(v,source=replace(v.source,admission_ns=NOW_NS+1))
    assert not result([v])['available']


def test_later_request_does_not_move_old_window_forward_or_invent_activity():
    v=event()
    later=recent_trade_flow([v],cutoff_ns=NOW_NS+3600*SECOND)
    assert later['window_end_ns']==END
    assert later['signed_local_clock_difference_ns']==3601*SECOND
    assert later['windows']['1m']['observed_trade_events']==1


def test_chart_and_text_share_the_same_recent_flow_and_exclude_other_routes(tmp_path):
    from tests.research.native_futures.test_live_view import native
    from tests.research.phase9.test_pipeline import NOW_NS as CUTOFF
    from monatise.research.native_futures.live_view import freeze_service,publish_view
    from monatise.research.native_futures.cache import checked
    from monatise.research.phase10.formatting import text_report
    p,c=native();view=freeze_service(p,{'status':'CAPTURING'})
    publish_view(view,cutoff_ns=CUTOFF,capture_id='FIXTURE',reader_commit='a'*40,
        chart_path=tmp_path/'chart.json',cache_path=tmp_path/'cache.json')
    report=checked(tmp_path/'cache.json')['analysis'];chart=checked(tmp_path/'chart.json')
    a=report['instruments'][c.metadata.raw_symbol]['components']['recent_trade_flow']
    b=chart['analysis']['instruments'][c.metadata.raw_symbol]['components']['recent_trade_flow']
    assert a==b and a['available']
    assert 'institutional accumulation confirmed=False' in text_report(report)
    assert not report['crypto_engines_used'] and not report['GIL_rules_used']
    assert not report['frozen_H1_selector_used'] and not report['XAUUSD_signal_router_used']


def test_fixed_precision_weighted_price_matches_existing_indicator_at_native_extremes():
    rows=[event(SECOND,ordinal=1,size=2**32-2,price='9000000000.1'),
          event(ordinal=2,size=2**32-3,price='9000000000.2')]
    got=result(rows)['windows']['1m']['vwap']
    expected=trade_indicators(rows,start_ns=END-MINUTE,end_ns=END,session_reference='FIXTURE')['vwap']
    assert got==expected


@pytest.mark.parametrize('health',[{'quarantined':True},{'reasons':['SOURCE_FAILURE']},
    {'component_rejections':{'trades:REPLACE':['native_record_or_recovery_validation_failed']}}])
def test_source_failures_never_supply_recent_flow(health):
    from tests.research.native_futures.test_live_view import native
    from monatise.research.phase10.market_info import FuturesMarketInfo
    from monatise.research.phase10.access import AnalysisRequest
    from tests.research.phase9.test_pipeline import NOW_NS as CUTOFF
    p,c=native();health=dict(health)
    if 'component_rejections' in health:
        health['quarantined']=True;health['component_rejections']={
            'trades:'+str(c.metadata.instrument_id):['native_record_or_recovery_validation_failed']}
    s=FuturesMarketInfo(p,source_health=lambda now:health)
    r=s.analyse(AnalysisRequest((c.metadata.raw_symbol,),CUTOFF))['instruments'][c.metadata.raw_symbol]
    assert not r['components']['recent_trade_flow']['available']
