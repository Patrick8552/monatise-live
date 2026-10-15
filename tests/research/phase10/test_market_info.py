from dataclasses import replace

import pytest

from monatise.research.phase10.market_info import FuturesMarketInfo
from monatise.research.phase10.access import AnalysisRequest
from monatise.research.phase10.formatting import text_report
from tests.research.phase9.test_pipeline import pipeline, add, trade, NOW_NS, NS
from tests.research.phase10.test_workflow import bar, warm


@pytest.mark.parametrize('product',['GC','ES','NQ'])
def test_native_futures_facts_do_not_call_legacy_engines_selectors_or_qualification(product,monkeypatch):
    from monatise.research.phase9.coordinator import NativeFuturesCoordinator
    def forbidden(*args,**kwargs):
        raise AssertionError('legacy analytical graph must not run')
    monkeypatch.setattr(NativeFuturesCoordinator,'analyse',forbidden)
    p,c=pipeline(product)
    monkeypatch.setattr(p,'analyse',forbidden)
    start=NOW_NS//(60*NS)*(60*NS)-2*60*NS
    assert add(p,bar(c,start),'ohlcv-1m',1)['accepted']
    assert add(p,trade(c),ordinal=2)['accepted']
    r=FuturesMarketInfo(p,source_health=lambda now:dict(status='CAPTURING')).analyse(
        AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))
    v=r['instruments'][c.metadata.raw_symbol]
    assert v['components']['price:1m']['validated_candle_count']==1
    assert v['components']['trade_features']['result']['executed_contracts']==2
    assert not r['crypto_engines_used'] and not r['frozen_H1_selector_used'] and not r['GIL_rules_used']
    assert not r['trade_signal_produced'] and not r['execution_eligible']
    assert 'qualification_status' not in r and 'decision' not in r
    assert 'engine_health' not in v['components']['price:1m']
    text=text_report(r)
    assert 'Observed OHLC' in text and 'VWAP' in text
    assert 'regime:' not in text and 'Qualification:' not in text


def test_one_hour_is_ordinary_market_data_without_frozen_selector_expiry():
    p,c=pipeline();start=NOW_NS//(3600*NS)*(3600*NS)-3600*NS
    import databento_dbn as dn
    minute=bar(c,start)
    hour=dn.OHLCVMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,ts_event=start,
        rtype=dn.RType.OHLCV_1H,open=minute.open,high=minute.high,low=minute.low,close=minute.close,volume=2)
    assert add(p,hour,'ohlcv-1h',1)['accepted']
    # Age is explicit; there is no obsolete selector lifetime or signal qualification.
    r=FuturesMarketInfo(p,source_health=lambda now:dict(status='SEALED_HISTORICAL_CAPTURE')).analyse(
        AnalysisRequest((c.metadata.raw_symbol,),NOW_NS+4*3600*NS,timeframes=('1h',)))
    v=r['instruments'][c.metadata.raw_symbol]['components']['price:1h']
    assert v['available'] and v['age_ns']>=4*3600*NS
    assert not v['selector_applied'] and not v['fixed_selector_expiry_applied']
    assert 'original_expiry_ns' not in v


@pytest.mark.parametrize('health',[{'quarantined':True},{'stale_checkpoint':True}])
def test_source_failure_stays_unavailable_despite_calculable_facts(health):
    p,c=pipeline();add(p,trade(c),ordinal=1)
    v=FuturesMarketInfo(p,source_health=lambda now:health).analyse(
        AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))['instruments'][c.metadata.raw_symbol]
    assert v['availability']=='UNAVAILABLE'
    assert v['components']['trade_features']['available']


def test_price_guard_failure_remains_scoped_and_not_bypassed():
    p,c=pipeline();add(p,trade(c),ordinal=1);p.gates[c.metadata.instrument_id].transport_gap('trades','review_required')
    v=FuturesMarketInfo(p,source_health=lambda now:{}).analyse(
        AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))['instruments'][c.metadata.raw_symbol]
    assert not v['components']['trade_features']['available']
    assert v['availability']=='UNAVAILABLE'


def test_warmup_native_information_uses_verified_lineage_without_legacy_graph(warm,monkeypatch):
    from monatise.research.phase10.history import load_history,WarmedPipeline
    path,p,c,kwargs=warm;h=load_history(path,**kwargs)
    def forbidden(*args,**kwargs):raise AssertionError('legacy graph forbidden')
    monkeypatch.setattr(WarmedPipeline,'analyse',forbidden)
    v=FuturesMarketInfo(WarmedPipeline(p,h),source_health=lambda now:{}).analyse(
        AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))['instruments'][c.metadata.raw_symbol]
    assert v['components']['price:1m']['validated_candle_count']==840
    assert v['history_warmup']['status']=='VERIFIED_SEPARATE_ANALYTICAL_HISTORY'
