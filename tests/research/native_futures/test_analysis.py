from dataclasses import replace
from decimal import Decimal
import pytest
from monatise.research.native_futures.analysis import analyse_frame,alignment
from monatise.research.databento.candles import HistoricalBar
from monatise.research.institutional.models import digest
from tests.research.phase9.test_pipeline import pipeline,NOW_NS,NS


def bars(values,product='GC'):
    p,c=pipeline(product);start=NOW_NS//(60*NS)*(60*NS)-(len(values)+1)*60*NS
    return tuple(HistoricalBar(c.metadata,'1m',start+i*60*NS,start+(i+1)*60*NS,
        tuple(int(Decimal(v)*NS) for v in (x,x+1,x-1,x)),2,NOW_NS-NS,(digest(['bar',i]),),'ohlcv-1m','ENGINEERING_SYNTHETIC') for i,x in enumerate(values))


@pytest.mark.parametrize('product',['GC','ES','NQ'])
def test_confirmed_native_structure_and_fibonacci_have_no_legacy_engine_dependencies(product):
    rows=bars([2500,2501,2505,2502,2501,2498,2501,2504,2508,2504,2503,2500,2503,2505,2510,2506,2505],product)
    r=analyse_frame(rows,tick_size='.1' if product=='GC' else '.25',cutoff_ns=NOW_NS)
    assert r['structure']['state']=='HIGHER_HIGHS_AND_LOWS'
    assert r['fibonacci']['available'] and r['fibonacci']['direction']=='UP_LEG'
    assert r['fibonacci']['retracements']['0.5']=='2505.0'
    assert not r['crypto_engines_used'] and not r['GIL_rules_used'] and not r['frozen_H1_selector_used']
    assert not r['execution_eligible'] and not r['fibonacci']['executable_levels']
    assert r['structure']['latest_high']['confirmed_at_ns']==rows[-1].close_ns


def test_right_hand_confirmation_has_no_future_bar_lookahead():
    rows=bars([2500,2501,2505,2502,2501,2500,2501,2507,2502,2501])
    before=analyse_frame(rows[:-1],tick_size='.1',cutoff_ns=NOW_NS)
    after=analyse_frame(rows,tick_size='.1',cutoff_ns=NOW_NS)
    assert before['structure']['confirmed_high_count']==1
    assert after['structure']['confirmed_high_count']==2
    with pytest.raises(ValueError,match='available_native_frame'):
        analyse_frame(rows,tick_size='.1',cutoff_ns=rows[-1].close_ns-1)


def test_missing_candle_withholds_dependent_features_without_filling():
    rows=bars([2500]*20)
    r=analyse_frame(rows[:8]+rows[9:],tick_size='.1',cutoff_ns=NOW_NS)
    assert not r['available'] and r['reason']=='noncontiguous_validated_frame' and r['gap_fill_count']==0


def test_mixed_contracts_and_duplicate_bars_are_not_silently_combined():
    a=bars([2500]*20);b=bars([2500]*20,'ES')
    with pytest.raises(ValueError,match='exact_available_native_frame'):analyse_frame(a[:10]+b[10:],tick_size='.1',cutoff_ns=NOW_NS)
    assert not analyse_frame(a[:10]+(a[9],)+a[10:],tick_size='.1',cutoff_ns=NOW_NS)['available']


def test_flat_prices_do_not_invent_swings_fibonacci_or_liquidity():
    r=analyse_frame(bars([2500]*20),tick_size='.1',cutoff_ns=NOW_NS)
    assert not r['structure']['available'] and not r['fibonacci']['available']
    assert not r['liquidity_proxies']['available']


def test_repeated_extrema_are_explicit_price_proxies():
    r=analyse_frame(bars([2500,2501,2505,2502,2501,2498,2501,2504,2505,2504,2503,2498,2503,2505,2507,2506,2505]),tick_size='.1',cutoff_ns=NOW_NS)
    z=r['liquidity_proxies'];assert z['available'] and any(x['touches']==2 for x in z['zones'])
    assert not z['resting_orders_observed'] and not z['participant_identity_known']


def test_short_history_and_timeframe_disagreement_are_explicit():
    r=analyse_frame(bars([2500,2501]),tick_size='.1',cutoff_ns=NOW_NS)
    assert r['available'] and not r['structure']['available']
    assert not alignment({'1m':r})['available']
    a=dict(available=True,structure=dict(available=True,state='HIGHER_HIGHS_AND_LOWS'))
    b=dict(available=True,structure=dict(available=True,state='LOWER_HIGHS_AND_LOWS'))
    assert alignment({'1m':a,'5m':b})['state']=='MIXED_TIMEFRAME_STRUCTURE'
    assert alignment({'1m':a,'5m':a})['state']=='ALIGNED_UP_STRUCTURE'


def test_warmup_runs_new_features_without_legacy_graph(warm,monkeypatch):
    from monatise.research.phase10.history import load_history,WarmedPipeline
    from monatise.research.phase10.market_info import FuturesMarketInfo
    from monatise.research.phase10.access import AnalysisRequest
    path,p,c,kwargs=warm;h=load_history(path,**kwargs)
    monkeypatch.setattr(WarmedPipeline,'analyse',lambda *a,**k:pytest.fail('legacy graph invoked'))
    r=FuturesMarketInfo(WarmedPipeline(p,h),source_health=lambda now:{}).analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))
    v=r['instruments'][c.metadata.raw_symbol]
    assert v['components']['price:1h']['native_analysis']['available']
    assert not v['components']['price:1h']['native_analysis']['structure']['available']


def test_wrong_contract_tick_cannot_change_liquidity_tolerance():
    with pytest.raises(ValueError,match='exact_native_futures_terms'):
        analyse_frame(bars([2500]*20),tick_size='1',cutoff_ns=NOW_NS)
