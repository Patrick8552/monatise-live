import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import threading
import time

from monatise.research.institutional.models import digest
from monatise.research.native_futures.chart import chart_snapshot, handler_for
from monatise.research.native_futures.chart_delivery import display_projection, CheckedChart
from monatise.research.phase9.rotation import atomic_json
from tests.research.native_futures.test_chart import service
from tests.research.phase9.test_pipeline import NOW_NS


def test_projection_keeps_every_displayed_candle_indicator_and_native_frame_hash():
    s,p,c=service()
    body=chart_snapshot(s,cutoff_ns=NOW_NS,capture_id='x',reader_commit='a'*40)
    original=digest(body);view=display_projection(body)
    assert digest(body)==original and view['full_snapshot_sha256']==original
    assert view['analysis_sha256']==body['analysis_sha256']
    for symbol,info in body['analysis']['instruments'].items():
        for name,part in info['components'].items():
            original=part.get('result',{}).get('inputs',{})
            if 'source_archives' in original:
                projected=view['analysis']['instruments'][symbol]['components'][name]['result']['inputs']
                assert projected['source_archive_count']==len(original['source_archives'])
                assert projected['source_archives_sha256']==digest(original['source_archives'])
                assert projected['input_sha256']==original['input_sha256']
    for symbol,frames in body['charts'].items():
        for tf,frame in frames.items():
            projected=view['charts'][symbol][tf]
            assert projected.get('frame_sha256')==frame.get('frame_sha256')
            assert projected.get('indicators')==frame.get('indicators')
            for a,b in zip(frame['bars'],projected['bars']):
                assert {k:v for k,v in a.items() if k!='source_hashes'}=={
                    k:v for k,v in b.items() if k not in {'source_hash_count','source_hashes_sha256'}}
                assert b['source_hash_count']==len(a['source_hashes'])
                assert b['source_hashes_sha256']==digest(a['source_hashes'])


def test_cache_revalidates_new_file_versions_and_rejects_tampering(tmp_path):
    s,p,c=service();body=chart_snapshot(s,cutoff_ns=NOW_NS,capture_id='x',reader_commit='a'*40)
    path=tmp_path/'chart.json';atomic_json(path,dict(body=body,sha256=digest(body)))
    cache=CheckedChart(path);first,_=cache.read();again,_=cache.read()
    assert first is again
    body['cutoff_ns']+=1;atomic_json(path,dict(body=body,sha256=digest(body)))
    assert cache.read()[0]['cutoff_ns']==NOW_NS+1
    path.write_text('{}')
    import pytest
    with pytest.raises((KeyError,ValueError)):cache.read()


def test_event_stream_pushes_independent_quote_updates_without_analysis_change(tmp_path):
    s,p,c=service();body=chart_snapshot(s,cutoff_ns=NOW_NS,capture_id='x',reader_commit='a'*40)
    path=tmp_path/'chart.json';atomic_json(path,dict(body=body,sha256=digest(body)))
    source=tmp_path/'source.json'
    def publish(at):
        quote=dict(available=True,quote=dict(bid='2500',ask='2500.1',receive_ns=at,available_ns=at))
        state=dict(capture_id='x',status='CAPTURING',observed_at_ns=at,health={},
                   instruments={c.metadata.raw_symbol:dict(identity=list(c.identity),quotes={'mbp-1':quote})})
        atomic_json(source,dict(body=state,sha256=digest(state)))
    publish(NOW_NS)
    server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(path,source))
    server.delivery_deadline=time.monotonic()+4
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    conn=HTTPConnection('127.0.0.1',server.server_port,timeout=2)
    try:
        conn.request('GET','/api/events');response=conn.getresponse()
        assert response.status==200 and response.headers['Content-Type']=='text/event-stream'
        first=json.loads(response.readline().decode().removeprefix('data: '));response.readline()
        publish(NOW_NS+1)
        second=json.loads(response.readline().decode().removeprefix('data: '))
        assert first['view_revision']==second['view_revision']==digest(body)
        assert second['delivery']['source_observed_at_ns']==NOW_NS+1
        assert second['delivery']['quote_snapshots'][c.metadata.raw_symbol]['mbp-1']['quote']['receive_ns']==NOW_NS+1
    finally:conn.close();server.shutdown();server.server_close();thread.join(2)
