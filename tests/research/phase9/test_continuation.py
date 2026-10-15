"""Calibration, automatic local candles and session rotation; no networking."""
from dataclasses import replace
from decimal import Decimal
import json

import databento_dbn as dbn
import pytest

from monatise.research.institutional.models import digest
from monatise.research.institutional.normalize import observation
from monatise.research.phase9.calibration import fit
from monatise.research.phase9.publication import CandlePublisher
from monatise.research.phase9.rotation import RotationPolicy,RotatingNativeJournal,RotatingSpool,verify_rotated_native
from monatise.research.phase9.pipeline import ResearchPipeline
from tests.research.phase9.test_pipeline import contract,calendar,gate,trade,pipeline,add,NOW_NS,NS
from tests.research.test_databento_live_preparation import scope


def canonical(c,price,index):
    row=trade(c,t=NOW_NS-(100-index)*NS,price=str(price))
    return observation(row,schema='trades',contract=c,archive_sha256=digest('TRAINING'),ordinal=index,
        retrieval_ns=NOW_NS,admission_ns=NOW_NS,evidence_kind='ENGINEERING_SYNTHETIC',enabled_schemas=('trades',))


def test_chronological_calibration_does_not_fit_on_holdout_or_absorb_spikes():
    c=contract();rows=[canonical(c,Decimal('2500')+Decimal('.1')*(i%3),i) for i in range(40)]
    fitted=fit(rows[:20],review_reference='engineering chronological training')
    result=fitted.validate(rows[20:])
    assert result['status']=='HOLDOUT_PASSED' and result['independent_chronological_holdout']
    assert result['last_training_event_ns']<result['first_holdout_event_ns']
    with pytest.raises(ValueError,match='overlap'):fitted.validate(rows[:10])
    original=fitted.sha256
    spike=replace(rows[-1],payload=('250000',2,'BUY'))
    failed=fitted.validate([*rows[20:-1],spike],maximum_rejection_fraction=Decimal(0))
    assert failed['status']=='HOLDOUT_FAILED' and fitted.sha256==original


def bar(c,tf,opened, *, price=2500):
    return dbn.OHLCVMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,ts_event=opened,
        rtype=dbn.RType.OHLCV_1S if tf=='1s' else dbn.RType.OHLCV_1M,
        open=price*NS,high=(price+1)*NS,low=(price-1)*NS,close=price*NS,volume=2)


def test_native_bar_publication_is_automatic_final_and_restart_idempotent(tmp_path):
    p,c=pipeline();pub=CandlePublisher(tmp_path/'outbox.sqlite');start=NOW_NS//(60*NS)*60*NS-60*NS
    for i in range(60):assert add(p,bar(c,'1s',start+i*NS),'ohlcv-1s',i)['accepted']
    ready={('ohlcv-1s',c.metadata.instrument_id)}
    result=pub.advance(p,now_ns=NOW_NS,replay_ready=ready,source_reference='verified-native-replay')
    assert result['published']>=73
    s=pub.summary();assert s['by_timeframe']['1s']==60 and s['by_timeframe']['5s']==12 and s['by_timeframe']['1m']==1
    assert s['local_analytical_outbox_only'] and not s['publication_eligible']
    assert pub.advance(p,now_ns=NOW_NS,replay_ready=ready,source_reference='verified-native-replay')['published']==0
    pub.close();pub=CandlePublisher(tmp_path/'outbox.sqlite')
    assert pub.advance(p,now_ns=NOW_NS,replay_ready=ready,source_reference='verified-native-replay')['published']==0
    p.gates[c.metadata.instrument_id].transport_gap('ohlcv-1s','late_native_revision',event_ns=start+2*NS)
    assert pub.retract_faults(p)>0
    assert pub.summary()['event_counts']['CANDLE_RETRACTED']>0;pub.close()


def test_missing_children_future_or_unreplayed_data_cannot_publish(tmp_path):
    p,c=pipeline();pub=CandlePublisher(tmp_path/'out.sqlite');start=NOW_NS//(60*NS)*60*NS-60*NS
    for i in range(4):assert add(p,bar(c,'1s',start+i*NS),'ohlcv-1s',i)['accepted']
    assert pub.advance(p,now_ns=NOW_NS,replay_ready=set(),source_reference='test')['published']==0
    r=pub.advance(p,now_ns=start+8*NS,replay_ready={('ohlcv-1s',c.metadata.instrument_id)},source_reference='test')
    assert r['published']==0
    r=pub.advance(p,now_ns=NOW_NS,replay_ready={('ohlcv-1s',c.metadata.instrument_id)},source_reference='test')
    assert pub.summary()['by_timeframe']=={'1s':4};assert r['aggregation_rejections'];pub.close()


def test_rotation_preserves_all_native_bytes_global_ordinals_and_hash_chain(tmp_path):
    s=scope();p=RotationPolicy(records_per_segment=3,bytes_per_segment=1024,seconds_per_segment=3600,maximum_segments=30,maximum_total_bytes=65536)
    journal=RotatingNativeJournal(tmp_path/'trades',schema='trades',scope=s,policy=p)
    c=s.contracts[0];original=[]
    for i in range(23):
        row=trade(c,t=NOW_NS+i*3600*NS);original.append(bytes(row))
        assert journal.append(row,capture_ns=NOW_NS+i*3600*NS)[0]==i
    report=journal.close(quality={'quarantined':False},checkpoint={'session_ended':True})
    assert report['record_count']==23 and len(report['segments'])==23
    assert [raw for _,_,raw in verify_rotated_native(tmp_path/'trades')]==original
    index=tmp_path/'trades/rotation.json';r=json.loads(index.read_text());r['segments'][1]['first_ordinal']+=1;index.write_text(json.dumps(r))
    with pytest.raises(ValueError,match='chain'):list(verify_rotated_native(tmp_path/'trades'))


def test_rotating_spool_replay_and_restart_do_not_reuse_native_positions(tmp_path):
    p,c=pipeline();policy=RotationPolicy(records_per_segment=3,bytes_per_segment=1024,maximum_segments=10,maximum_total_bytes=65536)
    spool=RotatingSpool(tmp_path/'spool',policy=policy)
    for i in range(12):
        ordinal,sha,added=spool.append('trades',trade(c,t=NOW_NS-(20-i)*NS),capture_ns=NOW_NS,
            delivery_id=str(i),evidence_kind='ENGINEERING_SYNTHETIC')
        assert ordinal==i+1 and added
    spool.checkpoint('feed_cursor',{'stable':True});assert spool.count==12
    assert len(spool.replay(p))==12
    assert len({v.source.position for v in p.gates[c.metadata.instrument_id].accepted})==12
    spool.close();again=RotatingSpool(tmp_path/'spool',policy=policy);fresh,cc=pipeline()
    assert again.count==12 and again.load('feed_cursor')=={'stable':True};assert len(again.replay(fresh))==12
    assert list(fresh.gates[cc.metadata.instrument_id].accepted)==list(p.gates[c.metadata.instrument_id].accepted)
    again.close()


def test_entire_23_hour_session_rotates_without_candle_or_memory_reset(tmp_path):
    c=contract();g=gate(c);g.rolling=True
    p=ResearchPipeline({c.metadata.instrument_id:g},{c.metadata.instrument_id:calendar(c)},
        enabled_schemas=('trades','ohlcv-1m'),capacity=600,rolling=True)
    pub=CandlePublisher(tmp_path/'outbox.sqlite')
    policy=RotationPolicy(records_per_segment=100,bytes_per_segment=65536,seconds_per_segment=3600,
        maximum_segments=30,maximum_total_bytes=4*1024**2)
    spool=RotatingSpool(tmp_path/'spool',policy=policy)
    start=NOW_NS//(86400*NS)*86400*NS
    for i in range(23*60):
        stamp=start+i*60*NS;row=bar(c,'1m',stamp);at=stamp+76*NS
        ordinal,sha,_=spool.append('ohlcv-1m',row,capture_ns=at,delivery_id=str(i),evidence_kind='ENGINEERING_SYNTHETIC')
        result=p.ingest(row,schema='ohlcv-1m',archive_sha256=sha,ordinal=ordinal,capture_ns=at,admission_ns=at,evidence_kind='ENGINEERING_SYNTHETIC')
        assert result['accepted'],result
        if i%60==59:pub.advance(p,now_ns=at,replay_ready={('ohlcv-1m',c.metadata.instrument_id)},source_reference='engineering-full-session-replay')
    summary=pub.summary()
    assert summary['by_timeframe']['1m']==1380 and summary['by_timeframe']['1h']==23 and summary['by_timeframe']['4h']==5
    assert len(spool.segments)==23 and not g.faults and len(p.bars[c.metadata.instrument_id]['1m'])<=600
    assert not summary['gil_enabled'] and not summary['execution_eligible']
    spool.close();pub.close()


def test_provider_bar_clock_offset_preserves_raw_capture_and_strict_finalization(tmp_path):
    from tests.research.test_databento_live_preparation import clock_review
    p,c=pipeline();row=bar(c,'1s',NOW_NS-NS);at=NOW_NS-150_000_000
    r=p.ingest(row,schema='ohlcv-1s',archive_sha256=digest('clock_bar'),ordinal=0,capture_ns=at,
        admission_ns=at,evidence_kind='ENGINEERING_SYNTHETIC',clock_review=clock_review())
    assert r['accepted'],r
    b=next(iter(p.bars[c.metadata.instrument_id]['1s'].values()))
    assert b.retrieval_ns==at and b.close_ns==NOW_NS
    pub=CandlePublisher(tmp_path/'clock.sqlite');ready={('ohlcv-1s',c.metadata.instrument_id)}
    assert pub.advance(p,now_ns=NOW_NS+9*NS,replay_ready=ready,source_reference='clock')['published']==0
    assert pub.advance(p,now_ns=NOW_NS+11*NS,replay_ready=ready,source_reference='clock')['published']==1
    pub.close()


def test_rotated_old_delivery_is_idempotent_and_tampering_rejected(tmp_path):
    p,c=pipeline();policy=RotationPolicy(records_per_segment=1,bytes_per_segment=1024,maximum_segments=10,maximum_total_bytes=65536)
    spool=RotatingSpool(tmp_path/'spool',policy=policy)
    a=trade(c,t=NOW_NS-2*NS);b=trade(c,t=NOW_NS-NS)
    first=spool.append('trades',a,capture_ns=NOW_NS,delivery_id='a',evidence_kind='ENGINEERING_SYNTHETIC')
    spool.append('trades',b,capture_ns=NOW_NS,delivery_id='b',evidence_kind='ENGINEERING_SYNTHETIC')
    assert spool.append('trades',a,capture_ns=NOW_NS,delivery_id='a',evidence_kind='ENGINEERING_SYNTHETIC')==(*first[:2],False)
    with pytest.raises(ValueError,match='revision'):spool.append('trades',b,capture_ns=NOW_NS,delivery_id='a',evidence_kind='ENGINEERING_SYNTHETIC')
    sealed=spool.root/spool.segments[0]['path'];sealed.chmod(0o600)
    with sealed.open('r+b') as f:f.seek(100);f.write(b'corrupt')
    with pytest.raises(ValueError,match='integrity'):spool.replay(p)
    spool.close()


def test_clock_review_renewal_preserves_queued_record_capture_provenance():
    from monatise.research.databento.live_models import ClockReview
    from monatise.research.databento.live_state import FeedState
    old=ClockReview(NOW_NS-30*NS,NOW_NS+270*NS,0,1000,digest('old clock'),'engineering old')
    new=ClockReview(NOW_NS,NOW_NS+300*NS,0,1000,digest('new clock'),'engineering new')
    state=FeedState(scope(clock_review=old));state.update_clock_review(new)
    assert state.clock_review==new
    assert state.review_at(NOW_NS-NS)==old and state.review_at(NOW_NS+NS)==new
    with pytest.raises(ValueError,match='ordered_overlapping'):state.update_clock_review(old)
    with pytest.raises(ValueError,match='contemporaneous'):state.review_at(NOW_NS-31*NS)


def test_publication_rollback_does_not_advance_in_memory_high_watermark(tmp_path,monkeypatch):
    p,c=pipeline();pub=CandlePublisher(tmp_path/'out.sqlite');start=NOW_NS//(60*NS)*60*NS-60*NS
    for i in range(2):assert add(p,bar(c,'1s',start+i*NS),'ohlcv-1s',i)['accepted']
    emit=pub._emit;calls=0
    def fail_second(*args):
        nonlocal calls
        calls+=1
        if calls==2:raise ValueError('injected transaction failure')
        return emit(*args)
    monkeypatch.setattr(pub,'_emit',fail_second)
    args=dict(now_ns=NOW_NS,replay_ready={('ohlcv-1s',c.metadata.instrument_id)},source_reference='test')
    with pytest.raises(ValueError,match='injected'):pub.advance(p,**args)
    assert not pub.highest and pub.summary()['active_candles']==0
    monkeypatch.setattr(pub,'_emit',emit)
    assert pub.advance(p,**args)['published']==2;pub.close()


def test_service_wires_rotating_journals_spool_and_automatic_publication(tmp_path):
    import asyncio
    from tests.research.phase9.test_options_service import make_plan,live_pipeline
    from tests.research.test_databento_live_preparation import FakeClient
    from monatise.research.phase9.service import PersistentResearchService
    s=scope(duration_seconds=1,start_ns=NOW_NS-120*NS,schemas=('definition','trades','ohlcv-1s','ohlcv-1m'))
    s=replace(s,capability=replace(s.capability,schemas=s.schemas))
    class WithBars(FakeClient):
        def start(self):
            schema=self.subscription['schema'];cb=self.callbacks[0]
            if schema=='definition':
                from tests.research.test_databento_live_preparation import native,system
                cb(system(dbn.SystemCode.SUBSCRIPTION_ACK))
                for c in s.contracts:cb(native(c.metadata.product,ts_recv=NOW_NS-86400*NS+2))
                cb(system(dbn.SystemCode.REPLAY_COMPLETED));return
            if not schema.startswith('ohlcv-'):return super().start()
            import databento_dbn as dn
            cb(dn.SystemMsg(ts_event=NOW_NS,msg='subscribed',code=dn.SystemCode.SUBSCRIPTION_ACK))
            start=NOW_NS//(60*NS)*60*NS-60*NS
            for c in s.contracts:cb(bar(c,schema[6:],start))
            cb(dn.SystemMsg(ts_event=start+60*NS,msg='end',code=dn.SystemCode.END_OF_INTERVAL))
            cb(dn.SystemMsg(ts_event=NOW_NS,msg='replay completed',code=dn.SystemCode.REPLAY_COMPLETED))
    clients=[]
    def factory(*a):
        c=WithBars();clients.append(c);return c
    policy=RotationPolicy(records_per_segment=3,bytes_per_segment=4096,maximum_segments=20,maximum_total_bytes=65536)
    spool=RotatingSpool(tmp_path/'spool',policy=policy);pub=CandlePublisher(tmp_path/'pub.sqlite')
    service_pipeline=live_pipeline(s)
    result=asyncio.run(PersistentResearchService(make_plan(s),spool,service_pipeline,client_factory=factory,
        clock_ns=lambda:NOW_NS,rotation_policy=policy,publisher=pub).run(api_key='ENGINEERING',output=tmp_path/'out',
        permit_ledger=tmp_path/'permits',evidence_kind='ENGINEERING_SYNTHETIC'))
    assert result['analytical_publication']['active_candles']>=6
    assert not result['reports'][0]['quality']['quarantined']
    assert all(not g.faults for g in service_pipeline.gates.values())
    assert all(c.terminated for c in clients) and len(clients)==4
    assert not result['execution_eligible']
    for schema in s.schemas:assert list(verify_rotated_native(tmp_path/'out/attempt-00'/schema))
    pub.close();spool.close()


def test_native_interval_markers_gate_publication_and_reject_late_bars(tmp_path):
    from monatise.research.databento.live_state import FeedState
    s=scope(start_ns=NOW_NS-120*NS,schemas=('definition','ohlcv-1s'))
    s=replace(s,capability=replace(s.capability,schemas=s.schemas));state=FeedState(s)
    state.acknowledged.add('ohlcv-1s')
    end=NOW_NS-20*NS
    marker=dbn.SystemMsg(ts_event=end,msg='end',code=dbn.SystemCode.END_OF_INTERVAL)
    assert state.ingest('ohlcv-1s',marker,capture_ns=NOW_NS,ordinal=0) is None
    assert not state.quality_reasons and state.interval_watermarks['ohlcv-1s']==end
    with pytest.raises(ValueError,match='after_native_interval'):
        state.ingest('ohlcv-1s',bar(s.contracts[0],'1s',end-NS),capture_ns=NOW_NS,ordinal=1)
    p,c=pipeline();row=bar(c,'1s',end)
    assert add(p,row,'ohlcv-1s')['accepted'];pub=CandlePublisher(tmp_path/'pub.sqlite')
    args=dict(now_ns=NOW_NS,replay_ready={('ohlcv-1s',c.metadata.instrument_id)},source_reference='test')
    assert pub.advance(p,**args,interval_watermarks={'ohlcv-1s':end})['published']==0
    assert pub.advance(p,**args,interval_watermarks={'ohlcv-1s':end+NS})['published']==1;pub.close()


@pytest.mark.parametrize('schema,delta,ack',[('trades',0,True),('ohlcv-1s',1,True),('ohlcv-1s',0,False),('ohlcv-1s',30*NS,True)])
def test_invalid_interval_controls_remain_fail_closed(schema,delta,ack):
    from monatise.research.databento.live_state import FeedState
    s=scope(schemas=('definition','trades','ohlcv-1s'));state=FeedState(s)
    if ack:state.acknowledged.add(schema)
    row=dbn.SystemMsg(ts_event=NOW_NS+delta,msg='invalid end',code=dbn.SystemCode.END_OF_INTERVAL)
    state.ingest(schema,row,capture_ns=NOW_NS,ordinal=0)
    assert 'invalid_native_interval_watermark' in state.quality_reasons
    assert not state.interval_watermarks


def test_latest_unfinalized_bar_does_not_erase_prior_final_minute_context():
    p,c=pipeline();now=NOW_NS-10*NS;end=NOW_NS//(60*NS)*60*NS
    for i in range(4):
        opened=end-(4-i)*60*NS
        assert add(p,bar(c,'1m',opened),'ohlcv-1m',i,stamp=now)['accepted']
    result=p.analyse(c.metadata.instrument_id,now_ns=now,mandatory=('price:1m',))
    component=result['components']['price:1m']
    assert component['available'] and component['close_ns']==end-60*NS
    assert result['candle_quality']['1m']['forming_or_not_yet_available']==1
    assert len(p.bars[c.metadata.instrument_id]['1m'])==4
    assert not result['execution_eligible'] and result['qualification_status']=='NOT_EVALUATED'


def test_reviewed_session_drain_accepts_closing_bars_without_extending_market_session(tmp_path):
    from monatise.research.databento.live_state import FeedState
    end=NOW_NS//(60*NS)*60*NS
    s=scope(start_ns=end-120*NS,session_end_ns=end,schemas=('definition','ohlcv-1m'),session_drain_seconds=30)
    state=FeedState(s);state.acknowledged.add('ohlcv-1m')
    assert state.ingest('ohlcv-1m',bar(s.contracts[0],'1m',end-60*NS),capture_ns=end+NS,ordinal=0)
    with pytest.raises(ValueError,match='identity_clocks_session'):
        state.ingest('ohlcv-1m',bar(s.contracts[0],'1m',end),capture_ns=end+61*NS,ordinal=1)
    with pytest.raises(ValueError,match='identity_clocks_session'):
        state.ingest('ohlcv-1m',bar(s.contracts[0],'1m',end-60*NS),capture_ns=end+30*NS,ordinal=2)
    closed=FeedState(replace(s,session_drain_seconds=0))
    with pytest.raises(ValueError):closed.ingest('ohlcv-1m',bar(s.contracts[0],'1m',end-60*NS),capture_ns=end+NS,ordinal=0)
    for v in (-1,121,True):
        with pytest.raises(ValueError):replace(s,session_drain_seconds=v)


def test_publication_incremental_tick_does_not_rebuild_published_day(tmp_path,monkeypatch):
    import monatise.research.phase9.publication as module
    p,c=pipeline();pub=CandlePublisher(tmp_path/'pub.sqlite');start=NOW_NS//(86400*NS)*86400*NS-86400*NS
    for i in range(23*60):assert add(p,bar(c,'1m',start+i*60*NS),'ohlcv-1m',i)['accepted']
    args=dict(now_ns=NOW_NS,replay_ready={('ohlcv-1m',c.metadata.instrument_id)},source_reference='incremental')
    assert pub.advance(p,**args)['published']>1380
    counts=[];aggregate=module.aggregate_complete
    def measured(rows,**kw):counts.append((kw['target'],len(rows)));return aggregate(rows,**kw)
    monkeypatch.setattr(module,'aggregate_complete',measured)
    assert pub.advance(p,**args)['published']==0
    assert all(n<=240 for tf,n in counts),counts
    pub.close()


def test_slow_clock_refresh_does_not_pause_native_record_processing(tmp_path):
    import asyncio,time
    from monatise.research.databento.live_models import ClockReview
    from monatise.research.databento.live_feed import CMELiveCapture
    from tests.research.test_databento_live_preparation import FakeClient,permit
    origin=time.monotonic_ns();clock=lambda:NOW_NS+time.monotonic_ns()-origin
    old=ClockReview(NOW_NS-280*NS,NOW_NS+20*NS,0,1000,digest('old'),'old research bounds')
    s=scope(duration_seconds=1,clock_review=old);delivered=[];refreshed=[]
    def refresh():
        time.sleep(.2);at=clock();refreshed.append(time.monotonic())
        return ClockReview(at,at+300*NS,0,1000,digest('new'),'new research bounds')
    def sink(*args):delivered.append(time.monotonic())
    result=asyncio.run(CMELiveCapture(s,client_factory=lambda *a:FakeClient(),clock_ns=clock,clock_refresh=refresh).run(
        api_key='ENGINEERING',permit=permit(s),permit_ledger=tmp_path/'permit',output=tmp_path/'run',
        evidence_kind='ENGINEERING_SYNTHETIC',record_sink=sink))
    assert delivered and refreshed and delivered[0]<refreshed[0]
    assert len(result['clock_reviews'])==1 and not result['quality']['quarantined']
