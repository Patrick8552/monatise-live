from dataclasses import replace
from decimal import Decimal
import pytest
from monatise.research.native_futures.information_gate import NativeInformationGate,MODE
from monatise.research.phase9.pipeline import ResearchPipeline
from monatise.research.databento.live_state import FeedState
from tests.research.phase9.test_pipeline import contract,calendar,trade,add,NOW_NS,NS
from tests.research.test_databento_live_preparation import scope


def native_pipeline():
    c=contract();g=NativeInformationGate(c)
    return ResearchPipeline({c.metadata.instrument_id:g},{c.metadata.instrument_id:calendar(c)},
        enabled_schemas=('trades','ohlcv-1m','mbp-1')),c


def test_large_valid_prices_are_information_not_custom_statistical_faults():
    p,c=native_pipeline()
    for i,price in enumerate(('2500','2800','2200')):
        r=add(p,trade(c,t=NOW_NS-(3-i)*NS,price=price),ordinal=i)
        assert r['accepted'] and r['custom_price_anomaly_applied'] is False
    assert not p.gates[c.metadata.instrument_id].faults
    assert len(p.gates[c.metadata.instrument_id].accepted)==3
    assert not hasattr(p.gates[c.metadata.instrument_id],'guard')


def test_native_integrity_stays_enforced_and_same_position_is_idempotent():
    p,c=native_pipeline();row=trade(c)
    assert add(p,row,ordinal=1)['accepted']
    assert add(p,row,ordinal=1)['duplicate']
    assert not add(p,trade(c,flags=8),ordinal=2)['accepted']
    p,c=native_pipeline()
    assert not add(p,trade(c,price='2500.01'),ordinal=1)['accepted']
    p,c=native_pipeline();assert add(p,row,ordinal=2)['accepted']
    assert not add(p,trade(c,t=NOW_NS-2*NS),ordinal=3)['accepted']


def test_initial_schema_start_is_explicit_and_does_not_need_any_replay_prefix():
    c=contract();s=scope(contracts=(c,),schemas=('definition','trades','mbp-1'),start_ns=NOW_NS-100*NS,
        initial_schema_starts=(('mbp-1',NOW_NS-10*NS),))
    state=FeedState(s)
    assert state.replay_start('trades')==NOW_NS-100*NS
    assert state.replay_start('mbp-1')==NOW_NS-10*NS
    assert not state.cursors['mbp-1:'+str(c.metadata.instrument_id)].replay_prefix
    with pytest.raises(ValueError,match='per_schema'):
        replace(s,initial_schema_starts=(('mbp-1',s.start_ns-1),))
    with pytest.raises(ValueError):replace(s,initial_schema_starts=(('mbp-1',NOW_NS+NS),)).validate_at(NOW_NS)


def test_native_mode_source_replay_never_needs_a_calibration_or_price_anchor(tmp_path):
    import json
    from monatise.research.institutional.models import encode,digest
    from monatise.research.phase9.rotation import RotatingSpool,RotationPolicy
    from monatise.research.phase10.source import load_capture
    from monatise.research.phase10.access import AnalysisRequest
    from monatise.research.databento.semantics import VERSION
    c=contract();cal=calendar(c);root=tmp_path/'native';root.mkdir()
    sc=dict(contracts=[encode(c)],schemas=['trades'],session_end_ns=cal.valid_to_ns,session_review_reference='ENGINEERING',start_ns=NOW_NS-100*NS)
    auth=dict(normalization_semantics=VERSION,quality_mode=MODE,plan=dict(steps=[dict(scope=sc)]))
    (root/'authorization.json').write_text(json.dumps(auth))
    from tests.research.phase10.test_workflow import dbn_file
    import databento_dbn as dn
    row=dn.StatMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,ts_event=NOW_NS-2*NS,
        ts_recv=NOW_NS-2*NS+1,ts_ref=NOW_NS-86400*NS,quantity=100,price=2**63-1,
        stat_type=dn.StatType.OPEN_INTEREST,update_action=dn.StatUpdateAction.NEW,channel_id=1,sequence=1)
    h=dbn_file(tmp_path/'oi.dbn',[row],'statistics',NOW_NS-86400*NS,NOW_NS,c)
    h.update(schema='statistics',start_ns=NOW_NS-86400*NS,end_ns=NOW_NS,request_limit=20000)
    inputs=dict(version='phase10-analysis-inputs-v1',normalization_semantics=VERSION,authorization_sha256=digest(auth),calendars={str(c.metadata.instrument_id):encode(cal)},native_history=[h])
    (root/'analysis-inputs.json').write_text(json.dumps(inputs))
    spool=RotatingSpool(root/'spool',policy=RotationPolicy())
    for i,price in enumerate(('2500','2800')):
        spool.append('trades',trade(c,t=NOW_NS-(2-i)*NS,price=price),capture_ns=NOW_NS,
            delivery_id=digest(auth['plan'])+':0:trades:'+str(i),evidence_kind='ENGINEERING_SYNTHETIC')
    spool.checkpoint('feed_cursor',dict(spool_records=spool.count,cursors={}));spool.close()
    end=root/'capture/attempt-00';end.mkdir(parents=True)
    (end/'report.json').write_text(json.dumps(dict(scope_sha256=digest(sc),quality=dict(quarantined=False,reasons=[]))))
    service=load_capture(root,cutoff_ns=NOW_NS);result=service.analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))['instruments'][c.metadata.raw_symbol]
    assert result['components']['trade_features']['available']
    assert result['components']['open_interest']['available'] and result['components']['open_interest']['contracts']==100
    assert result['availability']=='UNAVAILABLE'  # No native replay controls in this fixture.
    assert result['validation']['quality_mode']==MODE and not result['validation']['custom_price_anomaly_applied']


def test_partial_native_replay_is_not_live_ready_even_with_valid_prices():
    from monatise.research.phase10.market_info import FuturesMarketInfo
    from monatise.research.phase10.access import AnalysisRequest
    p,c=native_pipeline();add(p,trade(c),ordinal=1)
    r=FuturesMarketInfo(p,source_health=lambda at:{'replay_completed':['definition']}).analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))
    assert r['instruments'][c.metadata.raw_symbol]['availability']=='UNAVAILABLE'


def test_native_archive_and_live_children_produce_real_parents_without_kind_mixing_failure():
    import databento_dbn as dn
    from monatise.research.institutional.models import digest
    from monatise.research.phase10.market_info import FuturesMarketInfo
    from monatise.research.phase10.access import AnalysisRequest
    p,c=native_pipeline();end=(NOW_NS-60*NS)//(300*NS)*(300*NS);start=end-600*NS
    for i in range(10):
        r=dn.OHLCVMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,ts_event=start+i*60*NS,
            rtype=dn.RType.OHLCV_1M,open=2500*NS,high=2501*NS,low=2499*NS,close=2500*NS,volume=10)
        result=p.ingest(r,schema='ohlcv-1m',archive_sha256=digest('archive' if i<5 else 'live'),ordinal=i,
            capture_ns=NOW_NS,admission_ns=NOW_NS,evidence_kind='AUTHENTIC_ARCHIVED_RECORD' if i<5 else 'AUTHENTIC_LIVE_CAPTURE')
        assert result['accepted']
    report=FuturesMarketInfo(p,source_health=lambda at:{}).analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))
    result=report['instruments'][c.metadata.raw_symbol]
    assert result['components']['price:5m']['available']
    assert result['components']['price:5m']['validated_candle_count']==2
    assert result['history_warmup']['old_capture_repaired'] is False
