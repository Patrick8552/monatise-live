from dataclasses import replace
import pytest

from monatise.research.native_futures.cache import source_snapshot,read_cached,checked
from monatise.research.phase9.rotation import atomic_json
from monatise.research.phase10.market_info import FuturesMarketInfo
from monatise.research.phase10.access import AnalysisRequest
from monatise.research.institutional.models import digest
from tests.research.native_futures.test_information_gate import native_pipeline
from tests.research.phase9.test_pipeline import add,trade,NOW_NS,NS
from tests.research.phase9.test_options_service import quote


def fixture(tmp_path):
    pipeline,c=native_pipeline()
    add(pipeline,trade(c),ordinal=1);add(pipeline,quote(c,2500),'mbp-1',2)
    result=FuturesMarketInfo(pipeline,source_health=lambda at:{}).analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))
    body=dict(version='native-analysis-cache-v1',capture_id='/engineering/capture',
        calculation_started_ns=NOW_NS,calculation_completed_ns=NOW_NS+NS,analysis=result)
    path=tmp_path/'cache.json';atomic_json(path,dict(body=body,sha256=digest(body)))
    return pipeline,c,path


def test_valid_dated_data_is_not_hidden_by_a_local_freshness_cutoff():
    p,c=native_pipeline();add(p,trade(c),ordinal=1);add(p,quote(c,2500),'mbp-1',2)
    result=FuturesMarketInfo(p,source_health=lambda at:{}).analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS+86400*NS))
    parts=result['instruments'][c.metadata.raw_symbol]['components']
    assert parts['trade_features']['available'] and parts['mbp-1']['available']
    h=parts['mbp-1']['health']['freshness']
    assert h['age_ns']>=86400*NS and not h['local_freshness_cutoff_applied']
    assert not h['current_or_executable_certified']
    p.gates[c.metadata.instrument_id].transport_gap('mbp-1','engineered_disconnect')
    result=FuturesMarketInfo(p,source_health=lambda at:{}).analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))
    assert not result['instruments'][c.metadata.raw_symbol]['components']['mbp-1']['available']


def test_dated_information_still_respects_an_explicit_as_of_cutoff():
    p,c=native_pipeline();add(p,quote(c,2500),'mbp-1',1)
    g=p.gates[c.metadata.instrument_id]
    h=g.health(now_ns=NOW_NS-NS,schemas=('mbp-1',))['mbp-1']
    assert not h['available'] and h['reason']=='not_available_at_cutoff'


def test_response_recalculates_ages_and_preserves_original_analysis(tmp_path):
    pipeline,c,cache=fixture(tmp_path);before=cache.read_bytes()
    src=tmp_path/'source.json'
    atomic_json(src,source_snapshot(pipeline,capture_id='/engineering/capture',health={'local_clock_offset_bounds_ns':[100,200]},
        observed_at_ns=NOW_NS+NS,status='COMPLETED_FINITE_NATIVE_INFORMATION_TRIAL'))
    r=read_cached(cache,response_ns=NOW_NS+100*NS,source_path=src)
    assert r['delivery']['analysis_age_ns']==100*NS
    assert r['delivery']['source_observation_age_ns']==99*NS
    assert r['delivery']['source_status_at_response']=='NOT_CONTEMPORANEOUSLY_VERIFIED'
    assert r['delivery']['quote_overlay_used']
    item=r['instruments'][c.metadata.raw_symbol]
    assert 'UNAVAILABLE' in item['current_live_use']
    assert item['components']['mbp-1']['quote']['age_at_response_ns']>=100*NS
    assert not item['components']['mbp-1']['quote']['executable_quote']
    q=item['components']['mbp-1']['quote']
    assert q['age_at_source_observation_utc_bounds_ns']==[NOW_NS+NS-q['receive_ns']+100,NOW_NS+NS-q['receive_ns']+200]
    assert cache.read_bytes()==before
    assert r['reproducibility_sha256']==digest({k:v for k,v in r.items() if k!='reproducibility_sha256'})


def test_cross_capture_and_contract_cache_merges_fail(tmp_path):
    pipeline,c,cache=fixture(tmp_path);src=tmp_path/'source.json'
    envelope=source_snapshot(pipeline,capture_id='/wrong/capture',health={},observed_at_ns=NOW_NS,status='LIVE')
    atomic_json(src,envelope)
    with pytest.raises(ValueError,match='cross_capture'):read_cached(cache,source_path=src)
    envelope['body']['capture_id']='/engineering/capture'
    envelope['body']['instruments'][c.metadata.raw_symbol]['identity'][2]+=1
    envelope['sha256']=digest(envelope['body']);atomic_json(src,envelope)
    with pytest.raises(ValueError,match='cross_contract'):read_cached(cache,source_path=src)


def test_cache_integrity_and_failed_refresh_remain_visible(tmp_path):
    pipeline,c,cache=fixture(tmp_path)
    atomic_json(str(cache)+'.status',dict(status='REFRESH_FAILED',error_type='EngineeringFailure'))
    r=read_cached(cache,response_ns=NOW_NS+NS)
    assert r['delivery']['worker']['status']=='REFRESH_FAILED'
    envelope=__import__('json').loads(cache.read_text());envelope['body']['capture_id']='changed'
    atomic_json(cache,envelope)
    with pytest.raises(ValueError,match='hash_mismatch'):read_cached(cache)


def test_quick_snapshot_does_not_call_full_analytical_graph(tmp_path,monkeypatch):
    p,c=native_pipeline();add(p,quote(c,2500),'mbp-1',1)
    monkeypatch.setattr(FuturesMarketInfo,'analyse',lambda *a,**kw:pytest.fail('full analysis in capture'))
    data=source_snapshot(p,capture_id='/engineering/capture',health={},observed_at_ns=NOW_NS,status='CAPTURING')
    assert data['body']['instruments'][c.metadata.raw_symbol]['quotes']['mbp-1']['available']


def test_native_candle_needs_no_extra_ten_second_local_delay(tmp_path):
    import databento_dbn as dn
    from monatise.research.phase9.publication import CandlePublisher
    p,c=native_pipeline();end=NOW_NS//(60*NS)*(60*NS);start=end-60*NS
    row=dn.OHLCVMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,ts_event=start,
        rtype=dn.RType.OHLCV_1M,open=2500*NS,high=2501*NS,low=2499*NS,close=2500*NS,volume=10)
    assert p.ingest(row,schema='ohlcv-1m',archive_sha256=digest('native'),ordinal=1,capture_ns=end,
        admission_ns=end,evidence_kind='ENGINEERING_SYNTHETIC')['accepted']
    report=FuturesMarketInfo(p,source_health=lambda at:{}).analyse(AnalysisRequest((c.metadata.raw_symbol,),end))
    assert report['instruments'][c.metadata.raw_symbol]['components']['price:1m']['available']
    pub=CandlePublisher(tmp_path/'candles.sqlite')
    try:
        kwargs=dict(now_ns=end,replay_ready={('ohlcv-1m',c.metadata.instrument_id)},source_reference='engineering')
        assert pub.advance(p,interval_watermarks={'ohlcv-1m':start},**kwargs)['published']==0
        assert pub.advance(p,interval_watermarks={'ohlcv-1m':end},**kwargs)['published']==1
    finally:pub.close()


def test_old_queued_resume_cannot_override_a_new_inline_network_pause():
    import threading
    from monatise.research.databento.sdk_transport import OwnedSDKClient
    pending=[]
    class Loop:
        def call_soon_threadsafe(self,fn):pending.append(fn)
    class Transport:
        reading=False
        def is_closing(self):return False
        def resume_reading(self):self.reading=True
        def pause_reading(self):self.reading=False
    client=OwnedSDKClient.__new__(OwnedSDKClient)
    client._closed=False;client._loop=Loop();client._transport=Transport()
    client._thread=threading.Thread();client._reading_requested=False
    client.set_reading(True)  # Consumer schedules a resume on the network loop.
    client._thread=threading.current_thread()
    client.set_reading(False)  # Newer callback pauses inline before queued resume.
    pending[0]()
    assert not client._transport.reading and not client._reading_requested
