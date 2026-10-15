"""Phase 11 deterministic regressions; synthetic native DBN, never acquisition."""
from dataclasses import replace
from decimal import Decimal
import hashlib
import databento_dbn as dbn
import pytest

from monatise.research.phase9.quality import PriceGuard,PlausibilityPolicy,QualityGate
from monatise.research.phase9.calibration import fit,prices
from monatise.research.phase9.candles import aggregate_complete,CoverageReview
from monatise.research.phase9.lineage import verify_bar_lineage
from monatise.research.databento.bar_coverage import NativeBarCoverage,review_native_coverage
from monatise.research.databento.live_state import FeedState,Cursor
from monatise.research.databento.semantics import flag_eligibility,transformation_provenance
from monatise.research.institutional.normalize import observation
from monatise.research.institutional.models import digest
from monatise.research.native_futures.intervals import native_intervals
from tests.research.phase9.test_pipeline import contract,calendar,pipeline,trade,add,NOW_NS,NS
from tests.research.phase9.test_continuation import bar
from tests.research.test_databento_live_preparation import scope,system,populate


def canonical(c,row,schema,ordinal):
    return observation(row,schema=schema,contract=c,archive_sha256=digest('synthetic'),ordinal=ordinal,
        retrieval_ns=NOW_NS,admission_ns=NOW_NS,evidence_kind='ENGINEERING_SYNTHETIC',enabled_schemas=(schema,))


def candle(c,t,wick):
    tick=int(c.tick_size*NS);p=2500*NS
    return dbn.OHLCVMsg(publisher_id=c.metadata.publisher_id,instrument_id=c.metadata.instrument_id,
        ts_event=t,rtype=dbn.RType.OHLCV_1S,open=p,high=p+wick*tick,low=p-wick*tick,close=p,volume=2)


@pytest.mark.parametrize('product',['GC','ES','NQ'])
def test_full_excursion_calibration_screening_and_adaptation_agree_for_128_flat_closes(product):
    c=contract(product);policy=PlausibilityPolicy(product,12,Decimal(8),40,'ENGINEERING ONLY',digest('policy'))
    g=PriceGuard(c,policy,anchor='2500',anchor_ns=NOW_NS-200*NS,anchor_sha256=digest('anchor'))
    rows=[]
    for i in range(128):
        row=canonical(c,candle(c,NOW_NS-(150-i)*NS,8 if i%2==0 else 12),'ohlcv-1s',i);rows.append(row)
        ps=prices(row);assert g.inspect(ps,row.event_ns) is None;g.commit(ps[-1],inspected_prices=ps)
    assert list(g.changes)==[c.tick_size*(8 if i%2==0 else 12) for i in range(128)]
    assert g.inspect(prices(canonical(c,candle(c,NOW_NS-NS,13),'ohlcv-1s',129)),NOW_NS-NS) is None
    before=list(g.changes)
    assert g.inspect(prices(canonical(c,candle(c,NOW_NS-NS,1000),'ohlcv-1s',130)),NOW_NS-NS)
    assert list(g.changes)==before
    calibration=fit(rows,review_reference='ENGINEERING ONLY')
    assert calibration.schema=='ohlcv-1s' and calibration.trimmed_training_increments==0


def test_rolling_gate_uses_excursion_and_preserves_rejected_wick():
    p,c=pipeline();start=NOW_NS-200*NS;g=p.gates[c.metadata.instrument_id]
    for i in range(128):assert add(p,candle(c,start+i*NS,8 if i%2==0 else 12),'ohlcv-1s',i)['accepted']
    assert all(v>0 for v in g.guards['ohlcv-1s'].changes)
    before=list(g.guards['ohlcv-1s'].changes)
    result=add(p,candle(c,NOW_NS-NS,10000),'ohlcv-1s',129)
    assert not result['accepted'] and list(g.guards['ohlcv-1s'].changes)==before
    assert not any(result['record_quality']['capabilities'].values())


def test_missing_anchor_bad_ohlc_and_changed_contract_tick_fail_closed():
    c=contract();policy=PlausibilityPolicy('GC',12,Decimal(8),40,'test',digest('p'))
    with pytest.raises(ValueError):PriceGuard(c,policy,anchor='2500.01',anchor_ns=NOW_NS,anchor_sha256=digest('a'))
    with pytest.raises(ValueError):PriceGuard(contract('ES'),policy,anchor='2500',anchor_ns=NOW_NS,anchor_sha256=digest('a'))
    p,c=pipeline();row=dbn.OHLCVMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,ts_event=NOW_NS-NS,
        rtype=dbn.RType.OHLCV_1S,open=2500*NS,high=2499*NS,low=2490*NS,close=2500*NS,volume=1)
    result=add(p,row,'ohlcv-1s');assert not result['accepted']
    assert result['record_quality']['dimensions']['price_valid'] is False


def test_receive_index_allows_nonmonotonic_exchange_time_without_rewriting_clocks():
    p,c=pipeline();base=NOW_NS-10*NS
    def row(event,received):
        return dbn.TradeMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,ts_event=event,ts_recv=received,
            ts_in_delta=-10,price=2500*NS,size=2,action=dbn.Action.TRADE,side=dbn.Side.BID,depth=0,sequence=1)
    first,second=row(base+2,base+3),row(base+1,base+4)
    assert add(p,first,ordinal=1)['accepted'] and add(p,second,ordinal=2)['accepted']
    v=p.gates[c.metadata.instrument_id].accepted[-1]
    assert (v.event_ns,v.receive_ns,v.publisher_send_ns)==(base+1,base+4,base+14)
    assert transformation_provenance(v)['original_timestamps_preserved']
    assert not add(p,row(base+3,base+2),ordinal=3)['accepted']
    state=FeedState(scope(start_ns=base))
    assert state.ingest('trades',first,capture_ns=NOW_NS,ordinal=1)
    assert state.ingest('trades',second,capture_ns=NOW_NS,ordinal=2)
    snapshot=state.checkpoint()['trades:'+str(c.metadata.instrument_id)]
    assert snapshot['event_order_regressed'] and snapshot['index_ns']==base+4
    with pytest.raises(ValueError,match='overlap_review'):Cursor.recover(snapshot)


def test_cross_clock_order_is_not_causality_but_flags_and_future_bounds_still_reject():
    p,c=pipeline();base=NOW_NS-NS
    def row(flags=0,event=base,receive=base-10):
        return dbn.TradeMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,ts_event=event,ts_recv=receive,
            price=2500*NS,size=2,action=dbn.Action.TRADE,side=dbn.Side.BID,depth=0,sequence=1,flags=flags)
    assert add(p,row())['accepted']
    for flags in (4,8,32,40):
        fresh,_=pipeline();r=add(fresh,row(flags=flags));assert not r['accepted']
        if flags&8:assert r['record_quality']['dimensions']['receive_timestamp_valid'] is False
    fresh,_=pipeline();assert not add(fresh,row(event=NOW_NS+NS,receive=NOW_NS-1))['accepted']
    cursor=Cursor();h=digest('same')
    assert cursor.accept(base,h,index_ns=base) and cursor.accept(base,h,index_ns=base)
    recovered=Cursor.recover(cursor.snapshot())
    assert not recovered.accept(base,h,index_ns=base) and not recovered.accept(base,h,index_ns=base)
    assert recovered.accept(base,h,index_ns=base)


def test_late_event_retracts_final_event_time_bucket_even_with_valid_receive_order():
    p,c=pipeline();start=NOW_NS-10*NS
    assert add(p,trade(c,t=start),ordinal=0)['accepted']
    builder=p.trade_candles[c.metadata.instrument_id]
    review=CoverageReview(start,start+NS,NOW_NS,digest('window'),'synthetic review')
    assert builder.view('1s',review=review,now_ns=NOW_NS)[0]
    late=dbn.TradeMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,ts_event=start,ts_recv=start+NS,
        price=2500*NS,size=2,action=dbn.Action.TRADE,side=dbn.Side.ASK,depth=0,sequence=2)
    assert add(p,late,ordinal=1)['accepted']
    assert not builder.view('1s',review=review,now_ns=NOW_NS)[0]


def test_mbo_snapshot_exception_requires_review_and_never_applies_to_trades():
    from monatise.research.databento.advanced import AdvancedAdapters
    c=contract();kw=dict(identity=c.metadata,enabled_schemas=('mbo',),mbo_research_reference='offline MBO review')
    row=dbn.MBOMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,ts_event=NOW_NS-NS,ts_recv=NOW_NS-1,
        order_id=1,price=2500*NS,size=2,action=dbn.Action.ADD,side=dbn.Side.BID,sequence=1,flags=40)
    with pytest.raises(ValueError):AdvancedAdapters(**kw).normalize('mbo',row)
    v=AdvancedAdapters(**kw,mbo_snapshot_reference='explicit snapshot boundary review').normalize('mbo',row)
    assert v.flags==40 and v.receive_ns==row.ts_recv
    quality=flag_eligibility('mbo',40,reviewed_mbo_snapshot=True)
    assert quality['snapshot_book_seed_eligible'] and not quality['temporal_book_liquidity_eligible']
    assert not flag_eligibility('trades',40)['trade_volume_eligible']
    empty=dbn.MBOMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,ts_event=NOW_NS-NS,ts_recv=2**64-1,
        order_id=0,price=2**63-1,size=0,action=dbn.Action.CLEAR,side=dbn.Side.NONE,sequence=0,flags=168)
    assert AdvancedAdapters(**kw,mbo_snapshot_reference='empty snapshot review').normalize('mbo',empty).receive_ns==2**64-1


def sparse_fixture():
    p,c=pipeline();start=NOW_NS//(60*NS)*60*NS-60*NS
    for i in (1,3):assert add(p,bar(c,'1s',start+i*NS),'ohlcv-1s',i)['accepted']
    proof=NativeBarCoverage(c.identity,'ohlcv-1s',start,start+5*NS,NOW_NS,digest('native marker'),digest('verified prefix'),'ENGINEERING SOURCE REVIEW')
    p.gates[c.metadata.instrument_id].coverage_reviews[proof.sha256]=proof
    rows=tuple(p.bars[c.metadata.instrument_id]['1s'].values())
    return p,c,start,proof,rows


def test_sparse_parent_uses_only_observed_prices_volume_and_verified_empty_children():
    p,c,start,proof,rows=sparse_fixture();g=p.gates[c.metadata.instrument_id]
    assert not aggregate_complete(rows,target='5s',calendar=calendar(c))[0]
    parents,rejected=aggregate_complete(rows,target='5s',calendar=calendar(c),coverage_reviews=(proof,))
    assert len(parents)==1 and not rejected
    parent=parents[0];assert parent.open_ns==start and parent.close_ns==start+5*NS and parent.volume==sum(b.volume for b in rows)
    assert parent.source_hashes==tuple(h for b in rows for h in b.source_hashes)
    verify_bar_lineage(g,parents)
    info=native_intervals(g,rows,schema='ohlcv-1s',start_ns=start,end_ns=start+5*NS,cutoff_ns=NOW_NS)
    assert info['counts']=={'VERIFIED_NO_TRADE':3,'OBSERVED_VALID':2} and info['interpolated_bars']==0
    g.coverage_reviews.clear()
    with pytest.raises(ValueError,match='unverified_sparse'):verify_bar_lineage(g,parents)


def test_unknown_rejected_future_or_wrong_instrument_coverage_cannot_repair_sparse_bars():
    p,c,start,proof,rows=sparse_fixture();g=p.gates[c.metadata.instrument_id]
    wrong=replace(proof,identity=contract('ES').identity)
    assert not aggregate_complete(rows,target='5s',calendar=calendar(c),coverage_reviews=(wrong,))[0]
    info=native_intervals(g,rows,schema='ohlcv-1s',start_ns=start,end_ns=start+5*NS,cutoff_ns=NOW_NS-1)
    assert info['counts']=={'UNKNOWN_COVERAGE':5}
    g.transport_gap('ohlcv-1s','missing',event_ns=start+2*NS)
    parents,_=aggregate_complete(rows,target='5s',calendar=calendar(c),coverage_reviews=(proof,))
    with pytest.raises(ValueError,match='unverified_sparse'):verify_bar_lineage(g,parents)
    info=native_intervals(g,rows,schema='ohlcv-1s',start_ns=start,end_ns=start+5*NS,cutoff_ns=NOW_NS)
    assert info['counts']['MISSING_OR_REJECTED']==3


def test_heartbeat_is_not_coverage_and_recovery_does_not_claim_uncaptured_prefix():
    p,c,start,proof,rows=sparse_fixture()
    s=scope(schemas=('definition','ohlcv-1s'),start_ns=start)
    state=FeedState(s);g=p.gates[c.metadata.instrument_id]
    assert review_native_coverage(state,g,'ohlcv-1s',now_ns=NOW_NS,source_reference='test') is None
    state.acknowledged.add('ohlcv-1s');state.completed.add('ohlcv-1s');state.verified_definitions.add(c.metadata.instrument_id)
    state.ingest('ohlcv-1s',system(dbn.SystemCode.HEARTBEAT),capture_ns=NOW_NS,ordinal=0)
    assert review_native_coverage(state,g,'ohlcv-1s',now_ns=NOW_NS,source_reference='test') is None
    state.ingest('ohlcv-1s',dbn.SystemMsg(ts_event=start+5*NS,msg='native end',code=dbn.SystemCode.END_OF_INTERVAL),capture_ns=NOW_NS,ordinal=1)
    assert review_native_coverage(state,g,'ohlcv-1s',now_ns=NOW_NS,source_reference='test') is not None
    checkpoints=state.checkpoint();checkpoints['ohlcv-1s:'+str(c.metadata.instrument_id)]=dict(event_ns=start+4*NS,hashes_at_event=[digest('a')])
    recovered=FeedState(s,checkpoints=checkpoints,recovery_review_reference='explicit reviewed boundary')
    assert recovered.coverage_start_ns['ohlcv-1s:'+str(c.metadata.instrument_id)]==start+5*NS


def test_utc_sparse_publication_and_native_request_do_not_call_legacy_graph(tmp_path,monkeypatch):
    from monatise.research.phase9.publication import CandlePublisher
    from monatise.research.phase10.market_info import FuturesMarketInfo
    from monatise.research.phase10.access import AnalysisRequest
    from monatise.research.phase9.coordinator import NativeFuturesCoordinator
    def forbidden(*a,**kw):raise AssertionError('legacy graph must not run')
    monkeypatch.setattr(NativeFuturesCoordinator,'analyse',forbidden)
    p,c,start,proof,rows=sparse_fixture();pub=CandlePublisher(tmp_path/'outbox.sqlite')
    result=pub.advance(p,now_ns=NOW_NS,replay_ready={('ohlcv-1s',c.metadata.instrument_id)},source_reference='reviewed offline sparse proof',interval_watermarks={'ohlcv-1s':start+5*NS})
    assert result['published']==3 and pub.summary()['by_timeframe']=={'1s':2,'5s':1}
    service=FuturesMarketInfo(p,source_health=lambda now:{})
    value=service.analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS,timeframes=('5s',)))['instruments'][c.metadata.raw_symbol]
    assert value['components']['price:5s']['available']
    assert value['components']['price:5s']['sparse_coverage_proofs']
    assert not any(value[k] for k in ('crypto_engines_used','frozen_H1_selector_used','GIL_rules_used','trade_signal_produced'))
    pub.close()


def test_prospective_calibration_uses_same_receive_order_as_live_guard():
    from monatise.research.phase9.calibration import fit
    c=contract();base=NOW_NS-50*NS;rows=[]
    for i in range(20):
        row=dbn.TradeMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,ts_event=base+(i//2)*NS,
            ts_recv=base+(i+1)*NS,price=2500*NS,size=2,action=dbn.Action.TRADE,side=dbn.Side.BID,depth=0,sequence=i)
        rows.append(canonical(c,row,'trades',i))
    # An exchange clock regression leaves provider ordering and multiplicity intact.
    rows[4]=replace(rows[4],event_ns=rows[3].event_ns-1)
    fitted=fit(rows[:10],review_reference='new synthetic future policy')
    result=fitted.validate(rows[10:])
    assert result['status']=='HOLDOUT_PASSED' and result['ordering_clock']=='PROVIDER_INDEX'
    assert result['excursion_measurement'].endswith('-v2')


def test_sparse_coverage_uses_its_contemporaneous_clock_not_an_expired_child_clock():
    from monatise.research.databento.live_models import ClockReview
    p,c,start,proof,rows=sparse_fixture()
    # A long quiet parent cannot borrow a child's already expired clock review.
    old=ClockReview(start-NS,start+3*NS,0,1000,digest('old clock'),'synthetic old',0)
    old_rows=tuple(replace(b,retrieval_ns=start+2*NS,clock_review=old) for b in rows[:1])
    new=ClockReview(NOW_NS-NS,NOW_NS+NS,0,1000,digest('new clock'),'synthetic new',0)
    proof=replace(proof,clock_review=new)
    parent,_=aggregate_complete(old_rows,target='5s',calendar=calendar(c),coverage_reviews=(proof,))
    assert parent and parent[0].clock_review==new and parent[0].retrieval_ns==NOW_NS


def test_reader_rebuilds_sparse_coverage_only_from_verified_native_controls(tmp_path):
    import json
    from types import SimpleNamespace
    from monatise.research.databento.live_journal import NativeJournal
    from monatise.research.institutional.models import encode
    from monatise.research.phase9.rotation import RotatingSpool,RotationPolicy
    from monatise.research.phase10.source import load_capture
    from monatise.research.phase10.access import AnalysisRequest
    from monatise.research.databento.semantics import VERSION
    p,c=pipeline();g=p.gates[c.metadata.instrument_id];start=NOW_NS//(60*NS)*60*NS-60*NS
    root=tmp_path/'capture';root.mkdir();anchors=root/'anchors';refs={};policies={}
    for schema,record in [('trades',trade(c,t=start-NS)),('ohlcv-1s',bar(c,'1s',start-NS))]:
        j=NativeJournal(anchors/schema,schema=schema,scope=SimpleNamespace(schemas=(schema,),sha256=digest(schema),maximum_records=10,maximum_bytes=4096),evidence_kind='ENGINEERING_SYNTHETIC')
        _,sha=j.append(record,capture_ns=NOW_NS);j.close(quality={'quarantined':False},checkpoint={})
        key=c.metadata.raw_symbol+':'+schema;refs[key]=dict(policy_sha256=g.policy.sha256,anchor_record_sha256=sha,anchor_event_ns=record.ts_event);policies[key]=encode(g.policy)
    scope=dict(contracts=[encode(c)],schemas=['trades','ohlcv-1s'],start_ns=start,session_end_ns=start+86400*NS,session_review_reference='ENGINEERING SESSION')
    auth=dict(normalization_semantics=VERSION,plan={'steps':[{'scope':scope}]},calibration_references=refs)
    (root/'authorization.json').write_text(json.dumps(auth))
    (root/'analysis-inputs.json').write_text(json.dumps(dict(version='phase10-analysis-inputs-v1',normalization_semantics=VERSION,authorization_sha256=digest(auth),anchor_root=str(anchors),session_open_ns=start,policies=policies)))
    spool=RotatingSpool(root/'spool',policy=RotationPolicy(records_per_segment=100,bytes_per_segment=4096,maximum_segments=10,maximum_total_bytes=65536))
    records=[('trades',system(dbn.SystemCode.SUBSCRIPTION_ACK),False),('trades',trade(c,t=start+NS),True),('trades',system(dbn.SystemCode.REPLAY_COMPLETED),False),('ohlcv-1s',system(dbn.SystemCode.SUBSCRIPTION_ACK),False)]
    records += [('ohlcv-1s',bar(c,'1s',start+i*NS),True) for i in (1,3)]
    records += [('ohlcv-1s',system(dbn.SystemCode.REPLAY_COMPLETED),False),('ohlcv-1s',dbn.SystemMsg(ts_event=start+5*NS,msg='closed interval',code=dbn.SystemCode.END_OF_INTERVAL),False)]
    for i,(schema,record,admitted) in enumerate(records):spool.append(schema,record,capture_ns=NOW_NS,delivery_id=digest(auth['plan'])+':0:'+schema+':'+str(i),evidence_kind='ENGINEERING_SYNTHETIC',admitted=admitted)
    spool.checkpoint('feed_cursor',{'spool_records':spool.count,'cursors':{}});spool.close()
    final=root/'capture/attempt-00';final.mkdir(parents=True);(final/'report.json').write_text(json.dumps({'scope_sha256':digest(scope),'quality':{'quarantined':False,'reasons':[]}}))
    reader=load_capture(root,cutoff_ns=NOW_NS)
    report=reader.analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS,timeframes=('5s',)))['instruments'][c.metadata.raw_symbol]
    assert report['components']['price:5s']['available']
    assert report['native_interval_classification']['1s']['counts']=={'VERIFIED_NO_TRADE':1,'OBSERVED_VALID':2}
    # Wider native source quarantine must continue to suppress all current analysis.
    d=json.loads((final/'report.json').read_text());d['quality']['quarantined']=True;d['quality']['reasons']=['connection_stalled_definition'];(final/'report.json').write_text(json.dumps(d))
    assert load_capture(root,cutoff_ns=NOW_NS).analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))['instruments'][c.metadata.raw_symbol]['availability']=='UNAVAILABLE'
