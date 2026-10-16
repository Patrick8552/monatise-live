from copy import deepcopy
import json
import pytest
from monatise.research.native_futures.live_view import freeze_service,publish_view
from monatise.research.native_futures.information_gate import NativeInformationGate
from monatise.research.native_futures.cache import checked
from monatise.research.phase10.market_info import FuturesMarketInfo
from monatise.research.phase10.access import AnalysisRequest
from monatise.research.institutional.models import digest
from tests.research.phase9.test_pipeline import pipeline,add,trade,NOW_NS,NS
from tests.research.phase10.test_workflow import bar


def native():
    p,c=pipeline();p.gates[c.metadata.instrument_id]=NativeInformationGate(c)
    start=NOW_NS//(60*NS)*(60*NS)-40*60*NS
    for i in range(35):assert add(p,bar(c,start+i*60*NS),'ohlcv-1m',i+1)['accepted']
    assert add(p,trade(c),ordinal=100)['accepted']
    return p,c


def test_detached_view_preserves_native_features_but_cannot_change_on_later_ingest():
    p,c=native();health=dict(status='CAPTURING',reasons=[],component_rejections={})
    frozen=freeze_service(p,health);req=AnalysisRequest((c.metadata.raw_symbol,),NOW_NS)
    a=frozen.analyse(req)['instruments'][c.metadata.raw_symbol]
    direct=FuturesMarketInfo(p,source_health=lambda now:health).analyse(req)['instruments'][c.metadata.raw_symbol]
    assert a['components']==direct['components']
    p.gates[c.metadata.instrument_id].transport_gap('trades','ENGINEERING_NEW_FAULT')
    p.bars[c.metadata.instrument_id]['1m'].clear();health['reasons'].append('ENGINEERING_CHANGED_SOURCE')
    b=frozen.analyse(req)['instruments'][c.metadata.raw_symbol]
    assert digest(a)==digest(b) and not frozen.source_health(NOW_NS)['independent_raw_replay_performed_for_this_view']
    assert len(frozen.pipeline.bars[c.metadata.instrument_id]['1m'])==35


def test_snapshot_container_mutations_cannot_change_live_gate():
    p,c=native();f=freeze_service(p,{})
    gate=p.gates[c.metadata.instrument_id];snapshot=f.pipeline.gates[c.metadata.instrument_id]
    snapshot.faults['trades']='ENGINEERING';snapshot.latest.clear();snapshot.positions.clear()
    snapshot.price_sources.clear();snapshot.coverage_reviews.clear()
    assert not gate.faults and gate.latest and gate.positions and gate.price_sources
    assert not hasattr(f.pipeline,'ingest')


def test_live_snapshot_requires_native_gate_without_fallback_to_canonical():
    p,c=pipeline()
    with pytest.raises(ValueError,match='native_admitted_pipeline'):freeze_service(p,{})


def test_published_chart_and_text_cache_share_exact_analysis(tmp_path):
    p,c=native();chart=tmp_path/'chart.json';cache=tmp_path/'cache.json'
    result=publish_view(freeze_service(p,dict(status='CAPTURING')),cutoff_ns=NOW_NS,
        capture_id='ENGINEERING_ONLY',reader_commit='a'*40,chart_path=chart,cache_path=cache)
    assert result['status']=='READY'
    body=checked(chart);analysis=checked(cache)['analysis']
    assert body['analysis_sha256']==analysis['reproducibility_sha256']
    assert body['charts'][c.metadata.raw_symbol]['1m']['frame_sha256']==analysis['instruments'][c.metadata.raw_symbol]['components']['price:1m']['native_analysis']['source_sha256']
    assert not body['orders_enabled']


def test_frozen_source_quarantine_is_not_cleared_by_future_source_changes(tmp_path):
    p,c=native();health=dict(quarantined=True,reasons=['ENGINEERING_SOURCE_FAILURE'])
    f=freeze_service(p,health);health.clear()
    chart=tmp_path/'chart.json';cache=tmp_path/'cache.json'
    publish_view(f,cutoff_ns=NOW_NS,capture_id='x',reader_commit='a'*40,chart_path=chart,cache_path=cache)
    assert not checked(chart)['charts'][c.metadata.raw_symbol]['1m']['available']
    assert checked(cache)['analysis']['instruments'][c.metadata.raw_symbol]['availability']=='UNAVAILABLE'


def test_live_coverage_compaction_retains_referenced_and_distinct_proofs():
    from dataclasses import replace
    from types import SimpleNamespace
    from monatise.research.phase9.service import compact_live_coverage
    from monatise.research.databento.bar_coverage import NativeBarCoverage
    p,c=native();gate=p.gates[c.metadata.instrument_id];start=NOW_NS//(60*NS)*(60*NS)-120*NS
    a=NativeBarCoverage(c.identity,'ohlcv-1m',start,start+60*NS,NOW_NS,digest('marker'),digest('prefix-a'),'SOURCE-A')
    b=replace(a,end_ns=start+120*NS,prefix_sha256=digest('prefix-b'))
    tied=replace(b,available_ns=NOW_NS+1)
    different=replace(b,review_reference='SOURCE-B')
    for proof in (a,b,tied,different):gate.coverage_reviews[proof.sha256]=proof
    frames={'1m':{start:SimpleNamespace(coverage_reviews=(a,))}}
    before=dict(gate.coverage_reviews);frozen=freeze_service(p,{})
    compact_live_coverage(gate,frames)
    assert set(gate.coverage_reviews)=={a.sha256,tied.sha256,different.sha256}
    assert frozen.pipeline.gates[c.metadata.instrument_id].coverage_reviews==before
    assert not gate.faults


def test_owned_process_handoff_preserves_exact_features_and_binds_source(tmp_path):
    from monatise.research.native_futures.live_view import write_view_input,read_view_input
    p,c=native();f=freeze_service(p,dict(status='CAPTURING'));path=tmp_path/'view.pkl'
    manifest=write_view_input(f,path=path,cutoff_ns=NOW_NS,capture_id='test',reader_commit='a'*40)
    restored,meta=read_view_input(manifest,capture_id='test',reader_commit='a'*40)
    req=AnalysisRequest((c.metadata.raw_symbol,),NOW_NS)
    assert restored.analyse(req)==f.analyse(req)
    with pytest.raises(ValueError,match='identity_mismatch'):read_view_input(manifest,capture_id='other',reader_commit='a'*40)
    path.write_bytes(path.read_bytes()+b'changed')
    with pytest.raises(ValueError,match='hash_mismatch'):read_view_input(manifest,capture_id='test',reader_commit='a'*40)


def test_handoff_cannot_execute_arbitrary_classes_even_with_valid_file_hash(tmp_path):
    import hashlib,os,pickle
    from monatise.research.native_futures.live_view import write_view_input,read_view_input
    from monatise.research.phase9.rotation import atomic_json
    p,c=native();manifest=write_view_input(freeze_service(p,{}),path=tmp_path/'view.pkl',cutoff_ns=NOW_NS,capture_id='test',reader_commit='a'*40)
    marker=tmp_path/'must-not-exist'
    class Unapproved:
        def __reduce__(self):return os.system,('touch '+str(marker),)
    payload=pickle.dumps(Unapproved());(tmp_path/'view.pkl').write_bytes(payload)
    meta=json.loads(manifest.read_text());meta.update(bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest());atomic_json(manifest,meta)
    with pytest.raises(ValueError,match='unapproved_view_handoff_class'):
        read_view_input(manifest,capture_id='test',reader_commit='a'*40)
    assert not marker.exists()


def test_chart_calculation_runs_in_a_different_os_process_without_source_mutation(tmp_path):
    import os,subprocess,sys
    from pathlib import Path
    from monatise.research.native_futures.live_view import write_view_input
    p,c=native();before=digest(tuple(p.gates[c.metadata.instrument_id].accepted))
    manifest=write_view_input(freeze_service(p,dict(status='CAPTURING')),path=tmp_path/'view.pkl',cutoff_ns=NOW_NS,capture_id='test',reader_commit='a'*40)
    code="""
import json,os,sys
from monatise.research.native_futures.live_view import read_view_input,publish_view
service,meta=read_view_input(sys.argv[1],capture_id='test',reader_commit='a'*40)
r=publish_view(service,cutoff_ns=meta['cutoff_ns'],capture_id='test',reader_commit='a'*40,chart_path=sys.argv[2],cache_path=sys.argv[3])
assert not any(name.startswith(('monatise.engines','monatise.application','monatise.routing')) for name in sys.modules)
print(json.dumps(dict(pid=os.getpid(),status=r['status'])))
"""
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[3]))
    result=subprocess.run([sys.executable,'-c',code,str(manifest),str(tmp_path/'chart.json'),str(tmp_path/'cache.json')],capture_output=True,text=True,env=env,timeout=20)
    assert result.returncode==0,result.stderr
    receipt=json.loads(result.stdout);assert receipt['pid']!=os.getpid() and receipt['status']=='READY'
    assert before==digest(tuple(p.gates[c.metadata.instrument_id].accepted))
