from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import hashlib,json

import databento_dbn as dn
import pytest

from monatise.research.databento.candles import normalize_candle,ExchangeCalendar,WIDTHS
from monatise.research.institutional.models import digest,encode
from monatise.research.phase9.coordinator import price_components,verify_bar_lineage
from monatise.research.phase10.history import load_history,WarmedPipeline,JoinedBar,join_minutes
from monatise.research.phase10.requests import request_symbols,exact_symbols,capture_from_pointer
from monatise.research.phase10.diagnostics import second_intervals
from monatise.research.phase10.access import AnalysisService,AnalysisRequest
from tests.research.phase9.test_pipeline import pipeline,add,trade,NOW_NS,NS


def bar(c,start,*,schema='ohlcv-1m',price='2500',volume=2):
    p=int(Decimal(price)*NS)
    return dn.OHLCVMsg(publisher_id=c.metadata.publisher_id,instrument_id=c.metadata.instrument_id,
        ts_event=start,rtype=dn.RType.OHLCV_1M if schema=='ohlcv-1m' else dn.RType.OHLCV_1S,
        open=p,high=p,low=p,close=p,volume=volume)


def dbn_file(path,rows,schema,start,end,c):
    header=dn.Metadata(dataset='GLBX.MDP3',start=start,end=end,stype_in=dn.SType.RAW_SYMBOL,
        stype_out=dn.SType.INSTRUMENT_ID,schema=dn.Schema(schema),symbols=[c.metadata.raw_symbol],limit=20000,version=3)
    path.write_bytes(header.encode()+b''.join(bytes(row) for row in rows))
    return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        retrieval_ns=NOW_NS-NS,records=len(rows))


@pytest.fixture
def warm(tmp_path):
    p,c=pipeline();end=NOW_NS//(60*NS)*(60*NS)-61*60*NS;start=end-780*60*NS
    rows=[bar(c,start+i*60*NS) for i in range(780)]
    source=dbn_file(tmp_path/'history.dbn',rows,'ohlcv-1m',start,end,c)
    anchor=dbn_file(tmp_path/'anchor.dbn',[bar(c,start,schema='ohlcv-1s')],'ohlcv-1s',start,start+NS,c)
    manifest=dict(version='reviewed-native-warmup-v1',authorization_sha256=digest('test auth'),
        reviewed_at_ns=NOW_NS-1,review_reference='ENGINEERING_SYNTHETIC_HISTORY_NOT_MARKET_VALIDATION',
        source=source,anchors=anchor,start_ns=start,end_ns=end,evidence_kind='ENGINEERING_SYNTHETIC',
        policies={c.metadata.raw_symbol+':ohlcv-1m':encode(p.gates[c.metadata.instrument_id].policy)},
        calendars={c.metadata.exchange:encode(p.calendars[c.metadata.instrument_id])})
    manifest['manifest_sha256']=digest(manifest);path=tmp_path/'history.json';path.write_text(json.dumps(manifest))
    for i in range(60):assert add(p,bar(c,end+i*60*NS),'ohlcv-1m',10000+i)['accepted']
    assert add(p,trade(c),ordinal=20000)['accepted']
    kwargs=dict(pipeline=p,authorization_sha256=digest('test auth'),
        policy_hashes={c.metadata.raw_symbol+':ohlcv-1m':p.gates[c.metadata.instrument_id].policy.sha256},cutoff_ns=NOW_NS)
    return path,p,c,kwargs


def test_verified_warmup_supplies_engine_history_without_changing_live_gate(warm):
    path,p,c,kwargs=warm;before=digest(tuple(p.gates[c.metadata.instrument_id].lineage_observations()))
    h=load_history(path,**kwargs);service=AnalysisService(WarmedPipeline(p,h))
    r=service.analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))['instruments'][c.metadata.raw_symbol]
    for tf in ('1m','5m','15m'):
        assert r['components']['price:'+tf]['native_analysis']['available']
    assert r['history_warmup']['historical_minutes']==780
    assert not r['history_warmup']['live_soak_gap_repaired']
    assert digest(tuple(p.gates[c.metadata.instrument_id].lineage_observations()))==before
    assert not r['execution_eligible'] and not r['gil_enabled']


def test_corrupt_optional_history_never_enters_engines(warm):
    path,p,c,kwargs=warm;source=Path(json.loads(path.read_text())['source']['path']);source.write_bytes(b'invalid')
    with pytest.raises(ValueError,match='file_hash'):load_history(path,**kwargs)


def test_historical_download_cannot_enter_an_earlier_as_of_request(warm):
    path,p,c,kwargs=warm;kwargs['cutoff_ns']=NOW_NS-2*NS
    with pytest.raises(ValueError,match='manifest|available'):load_history(path,**kwargs)


def test_edited_policy_cannot_relax_original_live_quality(warm):
    path,p,c,kwargs=warm;m=json.loads(path.read_text());m['policies'][c.metadata.raw_symbol+':ohlcv-1m']['floor_ticks']*=10
    m.pop('manifest_sha256');m['manifest_sha256']=digest(m);path.write_text(json.dumps(m))
    with pytest.raises(ValueError,match='cannot_relax'):load_history(path,**kwargs)


def test_independent_anchor_must_agree_with_first_native_minute(warm):
    path,p,c,kwargs=warm;m=json.loads(path.read_text());a=Path(m['anchors']['path'])
    m['anchors']=dbn_file(a,[bar(c,m['start_ns'],schema='ohlcv-1s',price='2501')],'ohlcv-1s',m['start_ns'],m['start_ns']+NS,c)
    m.pop('manifest_sha256');m['manifest_sha256']=digest(m);path.write_text(json.dumps(m))
    with pytest.raises(ValueError,match='anchor_disagrees'):load_history(path,**kwargs)


def test_history_quality_fault_is_retained_and_live_analysis_survives(warm):
    path,p,c,kwargs=warm;h=load_history(path,**kwargs);h['gates'][c.metadata.instrument_id].transport_gap('ohlcv-1m','ENGINEERING_FAULT')
    r=AnalysisService(WarmedPipeline(p,h)).analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))['instruments'][c.metadata.raw_symbol]
    assert r['history_warmup']['status']=='REJECTED_OR_NOT_AVAILABLE'
    assert r['components']['price:1m']['native_analysis']['available']
    assert 'ENGINEERING_FAULT' in r['history_warmup']['faults']['ohlcv-1m']


def test_bad_optional_join_keeps_valid_live_components(warm):
    path,p,c,kwargs=warm;h=load_history(path,**kwargs)
    # Make the reviewed history overlap a live minute with different native provenance.
    live=next(iter(p.bars[c.metadata.instrument_id]['1m'].values()))
    h['bars'][c.metadata.instrument_id]=(*h['bars'][c.metadata.instrument_id],replace(live,volume=live.volume+1))
    result=AnalysisService(WarmedPipeline(p,h)).analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))['instruments'][c.metadata.raw_symbol]
    assert result['history_warmup']['status']=='REJECTED_HISTORY_JOIN'
    assert result['components']['price:1m']['native_analysis']['available']


def test_overlap_revision_and_missing_parent_child_are_rejected(warm):
    path,p,c,kwargs=warm;h=load_history(path,**kwargs);b=h['bars'][c.metadata.instrument_id][0]
    with pytest.raises(ValueError,match='overlap_revision'):join_minutes((b,),(replace(b,volume=b.volume+1),))
    with pytest.raises(ValueError,match='missing_mixed'):JoinedBar((b,),'5m',h['calendars'][c.metadata.instrument_id])


def test_mixed_parent_preserves_native_evidence_categories_and_lineage(warm):
    path,p,c,kwargs=warm;h=load_history(path,**kwargs);rows=h['bars'][c.metadata.instrument_id]
    # Synthetic fixtures are used to exercise category handling, not passed off as market evidence.
    start=next(i for i,b in enumerate(rows) if b.open_ns%(5*60*NS)==0);children=rows[start:start+5]
    mixed=tuple(replace(b,evidence_kind='AUTHENTIC_HISTORICAL_DOWNLOAD' if i<3 else 'AUTHENTIC_LIVE_CAPTURE') for i,b in enumerate(children))
    parent=JoinedBar(mixed,'5m',h['calendars'][c.metadata.instrument_id])
    assert parent.evidence_kind=='MIXED_AUTHENTIC_HISTORY_AND_LIVE'
    assert parent.source_hashes==tuple(v for b in mixed for v in b.source_hashes)
    with pytest.raises(ValueError,match='synthetic_authentic'):
        JoinedBar((children[0],*mixed[1:]),'5m',h['calendars'][c.metadata.instrument_id])


def test_only_reviewed_closed_buckets_can_be_skipped(warm):
    path,p,c,kwargs=warm;h=load_history(path,**kwargs);rows=h['bars'][c.metadata.instrument_id][:3];a,b=rows[0],rows[2]
    cal=p.calendars[c.metadata.instrument_id];closed=ExchangeCalendar(cal.dataset,cal.exchange,cal.source_reference,
        cal.source_sha256,cal.version,cal.valid_from_ns,cal.valid_to_ns,((cal.valid_from_ns,a.close_ns),(b.open_ns,cal.valid_to_ns)))
    with pytest.raises(ValueError,match='noncontiguous'):price_components(c,(a,b),now_ns=NOW_NS,calendar=closed)
    result=price_components(c,(a,b),now_ns=NOW_NS,calendar=closed,reviewed_history=True)
    assert len(result['omitted_session_buckets'])==1 and result['validated_candle_count']==2
    with pytest.raises(ValueError,match='missing_bar'):price_components(c,(a,b),now_ns=NOW_NS,calendar=cal,reviewed_history=True)


@pytest.mark.parametrize('text,expected',[
    ('Analyse GC, ES and NQ using Databento',('GC','ES','NQ')),
    ('Analyze NQ with Databento live feeds.',('NQ',)),
    ('analyse GC using Databento live data',('GC',)),
])
def test_read_only_request_phrase(text,expected):assert request_symbols(text)==expected


@pytest.mark.parametrize('text',['Buy GC using Databento','Analyse GC and GC using Databento',
    'Analyse CL using Databento','Analyse GC then execute using Databento','Analyse GC using another provider'])
def test_request_cannot_expand_assets_or_execution(text):
    with pytest.raises(ValueError):request_symbols(text)


def test_contract_alias_requires_unique_loaded_identity_and_safe_pointer(tmp_path):
    p,c=pipeline();assert exact_symbols(('GC',),p)==(c.metadata.raw_symbol,)
    with pytest.raises(ValueError):exact_symbols(('NQ',),p)
    target=tmp_path/'capture';target.mkdir();pointer=tmp_path/'active.txt';pointer.write_text(str(target))
    assert capture_from_pointer(pointer)==target
    pointer.write_text('relative-path')
    with pytest.raises(ValueError):capture_from_pointer(pointer)


def test_sparse_seconds_use_trade_receive_time_and_do_not_certify_absence():
    p,c=pipeline();start=NOW_NS//(60*NS)*(60*NS)-60*NS
    # First and last seconds contain executions; middle seconds have no captured trade.
    for n in (0,2):
        assert add(p,trade(c,t=start+n*NS),'trades',n)['accepted']
        assert add(p,bar(c,start+n*NS,schema='ohlcv-1s'),'ohlcv-1s',n+10)['accepted']
    result=second_intervals(p.gates[c.metadata.instrument_id],cutoff_ns=NOW_NS)
    assert result['seconds_without_bar_and_without_captured_trade']>=1
    assert result['seconds_without_bar_but_with_captured_trade']==0
    assert not result['exchange_continuity_certified'] and result['gap_fill_count']==0
    assert not result['quality_fault_cleared']


def test_missing_second_with_a_captured_trade_and_source_fault_stay_visible():
    p,c=pipeline();start=NOW_NS//(60*NS)*(60*NS)-60*NS
    for n in (0,1,2):assert add(p,trade(c,t=start+n*NS),'trades',n)['accepted']
    for n in (0,2):assert add(p,bar(c,start+n*NS,schema='ohlcv-1s'),'ohlcv-1s',n+10)['accepted']
    result=second_intervals(p.gates[c.metadata.instrument_id],cutoff_ns=NOW_NS)
    assert result['seconds_without_bar_but_with_captured_trade']==1
    p.gates[c.metadata.instrument_id].transport_gap('trades','ENGINEERING_GAP')
    assert second_intervals(p.gates[c.metadata.instrument_id],cutoff_ns=NOW_NS)['status']=='UNAVAILABLE_UNRELIABLE_SOURCE'
