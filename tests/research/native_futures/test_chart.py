import json
from dataclasses import replace
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import pytest
from monatise.research.native_futures.chart import chart_snapshot,handler_for
from monatise.research.native_futures.technicals import close_indicators
from monatise.research.institutional.models import digest
from monatise.research.phase10.market_info import FuturesMarketInfo
from monatise.research.phase9.rotation import atomic_json
from tests.research.phase9.test_pipeline import pipeline,add,trade,NOW_NS,NS
from tests.research.phase10.test_workflow import bar


def service(health=None):
    p,c=pipeline();start=NOW_NS//(60*NS)*(60*NS)-40*60*NS
    for i in range(35):assert add(p,bar(c,start+i*60*NS),'ohlcv-1m',i+1)['accepted']
    add(p,trade(c),ordinal=100)
    return FuturesMarketInfo(p,source_health=lambda now:health or dict(status='SEALED_HISTORICAL_CAPTURE')),p,c


def test_chart_exactly_matches_native_frame_and_retains_every_source_hash(monkeypatch):
    s,p,c=service();monkeypatch.setattr(p,'analyse',lambda *a,**k:pytest.fail('legacy graph'))
    before=digest(p.bars)
    body=chart_snapshot(s,cutoff_ns=NOW_NS,capture_id='ENGINEERING_ONLY',reader_commit='a'*40)
    f=body['charts'][c.metadata.raw_symbol]['1m'];info=body['analysis']['instruments'][c.metadata.raw_symbol]
    native=info['components']['price:1m']['native_analysis']
    assert f['frame_sha256']==native['source_sha256'] and len(f['bars'])==35
    assert all(b['source_hashes'] and type(b['open_ns']) is str for b in f['bars'])
    assert f['indicators']['ema20']==native['close_indicators']['ema20']
    assert not body['forming_bars_included'] and not body['orders_enabled'] and not body['external_chart_feed']
    assert digest(p.bars)==before


@pytest.mark.parametrize('health',[dict(quarantined=True),dict(stale_checkpoint=True),dict(reasons=['storage_fault'])])
def test_global_quarantine_never_becomes_usable_chart(health):
    s,p,c=service(health);body=chart_snapshot(s,cutoff_ns=NOW_NS,capture_id='x',reader_commit='a'*40)
    assert all(not f['available'] and f['bars']==[] for f in body['charts'][c.metadata.raw_symbol].values())


def test_missing_time_bucket_is_not_flat_filled_and_indicators_remain_unavailable():
    s,p,c=service();series=p.bars[c.metadata.instrument_id]['1m'];del series[sorted(series)[15]]
    body=chart_snapshot(s,cutoff_ns=NOW_NS,capture_id='x',reader_commit='a'*40)
    f=body['charts'][c.metadata.raw_symbol]['1m']
    assert len(f['bars'])==34 and f['synthetic_bars']==0
    assert not f['analysis_frame_matched'] and not f['indicators']['available']
    assert any(b['time_ms']-a['time_ms']==120000 for a,b in zip(f['bars'],f['bars'][1:]))


def test_altered_lineage_does_not_reach_chart():
    s,p,c=service();series=p.bars[c.metadata.instrument_id]['1m'];key=sorted(series)[-1]
    series[key]=replace(series[key],source_hashes=('f'*64,))
    b=chart_snapshot(s,cutoff_ns=NOW_NS,capture_id='x',reader_commit='a'*40)
    assert b['charts'][c.metadata.raw_symbol]['1m']['bars']==[]


def test_indicator_series_has_exact_seed_alignment_and_same_last_values():
    closes=tuple((2500+i%7)*10**9 for i in range(45))
    result=close_indicators(closes,include_series=True);latest=close_indicators(closes)
    for key,seed in [('ema20',19),('rsi14',14),('rsi14_sma14',27)]:
        assert result[key]==latest[key]
        assert result['series'][key][-1]==latest[key]['value']
        assert result['series'][key][:seed]==[None]*seed
        for i in range(seed,len(closes)):
            assert result['series'][key][i]==close_indicators(closes[:i+1])[key]['value']


def test_loopback_server_only_serves_whitelisted_checked_read_only_routes(tmp_path):
    s,p,c=service();body=chart_snapshot(s,cutoff_ns=NOW_NS,capture_id='x',reader_commit='a'*40)
    snap=tmp_path/'chart.json';atomic_json(snap,dict(body=body,sha256=digest(body)))
    server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(snap));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    def request(method,path,headers=None):
        conn=HTTPConnection('127.0.0.1',server.server_port,timeout=2);conn.request(method,path,headers=headers or {})
        response=conn.getresponse();data=response.read();result=(response.status,dict(response.getheaders()),data);conn.close();return result
    try:
        status,headers,data=request('GET','/api/chart');assert status==200
        assert digest(json.loads(data)['body'])==digest(body) and headers['Cache-Control']=='no-store'
        assert "connect-src 'self'" in headers['Content-Security-Policy'] and 'Access-Control-Allow-Origin' not in headers
        assert request('GET','/',{'Host':'malicious.example'})[0]==403
        assert request('POST','/api/order')[0]==501
        assert request('GET','/../../.env')[0]==404
        assert request('GET','/')[0]==200 and request('GET','/app.js')[0]==200
        snap.write_text('{}');assert request('GET','/api/chart')[0]==503
    finally:server.shutdown();server.server_close();thread.join(2)
