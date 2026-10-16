"""Synthetic fault injection and canonical engine integration; no acquisition."""
from dataclasses import replace
from decimal import Decimal
import json

import databento_dbn as dbn
import pytest

from monatise.adapters.databento_identity import DatabentoPublisherPolicy
from monatise.adapters.databento_gold import definition as legacy_definition
from monatise.research.databento.candles import ExchangeCalendar, HistoricalBar, WIDTHS
from monatise.research.databento.live_models import native_definition
from monatise.research.databento.live_state import FeedState
from monatise.research.institutional.models import digest
from monatise.research.institutional.normalize import observation
from monatise.research.phase9.availability import FreshnessPolicy, inherited_policy
from monatise.research.phase9.quality import PlausibilityPolicy, QualityGate
from monatise.research.phase9.pipeline import ResearchPipeline
from monatise.research.phase9.candles import ContinuousCandles, CoverageReview, aggregate_complete
from monatise.research.phase9.storage import DurableSpool
from tests.research.test_databento_live_preparation import native, capability, scope, populate, NOW_NS
from tests.test_gold_technical_first import synthetic_candles
from monatise.research.phase9.coordinator import instant

NS=10**9


def contract(product='GC'):
    return native_definition(native(product,ts_event=NOW_NS-20*86400*NS,ts_recv=NOW_NS-20*86400*NS+1),
        capability=capability(),publishers={1:('GLBX.MDP3','GLBX')},as_of_ns=NOW_NS)


def calendar(c):
    start=(NOW_NS-15*86400*NS)//(60*NS)*60*NS
    end=(NOW_NS+86400*NS)//(60*NS)*60*NS
    return ExchangeCalendar('GLBX.MDP3',c.metadata.exchange,'ENGINEERING_SESSION',digest('calendar'),'v1',start,end,((start,end),))


def gate(c):
    floors={'GC':1000,'ES':400,'NQ':800}
    p=PlausibilityPolicy(c.metadata.product,floors[c.metadata.product],Decimal(8),40,
        'ENGINEERING_TEST_ONLY_NOT_EMPIRICALLY_CALIBRATED',digest('test policy '+c.metadata.product))
    return QualityGate(c,p,anchor='2500',anchor_ns=NOW_NS-20*86400*NS,anchor_sha256=digest('reviewed independent anchor'))


def pipeline(product='GC'):
    c=contract(product)
    return ResearchPipeline({c.metadata.instrument_id:gate(c)},{c.metadata.instrument_id:calendar(c)},
        enabled_schemas=('definition','trades','mbp-1','mbp-10','ohlcv-1s','ohlcv-1m','ohlcv-1h','statistics')),c


def trade(c, *, t=NOW_NS-NS, price='2500', size=2, flags=0, action=dbn.Action.TRADE, side=dbn.Side.BID):
    return dbn.TradeMsg(publisher_id=c.metadata.publisher_id,instrument_id=c.metadata.instrument_id,
        ts_event=t,ts_recv=t+1,price=int(Decimal(price)*NS),size=size,action=action,side=side,depth=0,sequence=1,flags=flags)


def add(p,row,schema='trades',ordinal=0,stamp=NOW_NS):
    return p.ingest(row,schema=schema,archive_sha256=digest('synthetic source'),ordinal=ordinal,
        capture_ns=stamp,admission_ns=stamp,evidence_kind='ENGINEERING_SYNTHETIC')


@pytest.mark.parametrize('product',['GC','ES','NQ'])
def test_quote_free_native_context_and_indicators_reuse_real_engines(product):
    p,c=pipeline(product)
    # Native hourly bars in an independently declared engineering session.
    rows=synthetic_candles('1h')
    shift=NOW_NS//(3600*NS)*3600*NS-int(__import__('datetime').datetime.fromisoformat(rows[-1].timestamp).timestamp()*NS)-3600*NS
    tick=int(c.tick_size*NS)
    for i,b in enumerate(rows):
        stamp=int(__import__('datetime').datetime.fromisoformat(b.timestamp).timestamp()*NS)+shift
        vals=[round(v*NS/tick)*tick for v in (b.open,b.high,b.low,b.close)]
        r=dbn.OHLCVMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,ts_event=stamp,
            rtype=dbn.RType.OHLCV_1H,open=vals[0],high=vals[1],low=vals[2],close=vals[3],volume=int(b.volume))
        assert add(p,r,'ohlcv-1h',i)['accepted']
    assert add(p,trade(c),ordinal=1000)['accepted']
    result=p.analyse(c.metadata.instrument_id,now_ns=NOW_NS,requested=('mbp-1','GIL'))
    assert result['availability']=='PARTIAL_ANALYSIS'
    price=result['components']['price:1h']
    assert price['available'] and price['native_analysis']['available']
    assert 'fibonacci' in price['native_analysis']
    assert price['reference_price']>0 and not price['executable_quote']
    assert result['components']['trade_features']['result']['executed_contracts']==2
    assert result['basis_status']=='NOT_APPLICABLE' and result['analysis_instrument']==product+'Z6'
    assert result['decision']=='NO_TRADE' and not result['execution_eligible']
    assert result['qualification_status']=='NOT_EVALUATED' and not result['gil_enabled']
    # Historical context remains visible; expiry and source hash do not renew.
    later=p.analyse(c.metadata.instrument_id,now_ns=NOW_NS+4*3600*NS,requested=('price:1m',))
    assert later['availability']=='PARTIAL_ANALYSIS'
    old,new=price,later['components']['price:1h']
    assert 'original_expiry_ns' not in old and 'original_expiry_ns' not in new
    assert old['source_sha256']==new['source_sha256']
    assert not new['selector_applied'] and new['freshness']['age_ns']>old['freshness']['age_ns']


@pytest.mark.parametrize('product',['GC','ES','NQ'])
def test_outlier_is_quarantined_without_training_or_affecting_other_contracts(product):
    p,c=pipeline(product)
    for i in range(12): assert add(p,trade(c,t=NOW_NS-(20-i)*NS,price=str(2500+c.tick_size*(i%2))),ordinal=i)['accepted']
    g=p.gates[c.metadata.instrument_id]
    before=list(g.guards['trades'].changes)
    r=add(p,trade(c,price='250000'),ordinal=100)
    assert not r['accepted'] and 'discontinuity' in r['reason']
    assert list(g.guards['trades'].changes)==before
    assert len(g.quarantine)==1 and g.faults['trades']
    result=p.analyse(c.metadata.instrument_id,now_ns=NOW_NS,mandatory=('trade_features',))
    assert result['availability']=='UNAVAILABLE' and not result['components']['trade_features']['available']
    other,cc=pipeline('NQ' if product!='NQ' else 'GC')
    assert add(other,trade(cc))['accepted']
    assert other.analyse(cc.metadata.instrument_id,now_ns=NOW_NS,mandatory=('trade_features',))['components']['trade_features']['available']


@pytest.mark.parametrize('change', ['tick','negative','zero_size','correction','flags','order','schema'])
def test_invalid_native_records_are_rejected_with_provenance(change):
    p,c=pipeline();row=trade(c)
    assert add(p,row)['accepted']
    schema='trades'
    if change=='tick':row=trade(c,price='2500.01')
    if change=='negative':row=trade(c,price='-1')
    if change=='zero_size':row=trade(c,size=0)
    if change=='correction':row=trade(c,action=dbn.Action.CANCEL)
    if change=='flags':row=trade(c,flags=4)
    if change=='order':row=trade(c,t=NOW_NS-2*NS)
    if change=='schema':schema='mbo'
    r=add(p,row,schema,ordinal=1)
    assert not r['accepted'] and r['reason']
    assert p.quarantine or p.gates[c.metadata.instrument_id].quarantine


def test_duplicate_delivery_is_idempotent_but_identical_new_position_counts():
    p,c=pipeline();r=trade(c)
    assert add(p,r,ordinal=1)['accepted']
    assert add(p,r,ordinal=1)['duplicate']
    assert add(p,r,ordinal=2)['accepted']
    result=p.analyse(c.metadata.instrument_id,now_ns=NOW_NS,mandatory=('trade_features',))
    assert result['components']['trade_features']['result']['executed_contracts']==4
    assert not add(p,trade(c,price='2501'),ordinal=2)['accepted']


def test_feature_aware_freshness_requires_reviewed_tolerance_and_never_forgives_future_or_expiry():
    p=FreshnessPolicy('GCZ6','H1 context',10*NS,30*NS,'engineering delayed context evidence',digest('review'))
    def at(age,**kw):return p.assess(source_ns=NOW_NS-age,available_ns=NOW_NS-age+1,now_ns=NOW_NS,**kw)
    assert at(5*NS)['status']=='FRESH'
    assert at(20*NS)['status']=='ACCEPTABLE_DELAY' and at(20*NS)['synchronization']=='TOLERANT_SYNC'
    assert at(31*NS)['status']=='STALE'
    assert at(-NS)['reason']=='future_or_unavailable_at_cutoff'
    assert at(5*NS,expires_ns=NOW_NS)['reason']=='original_expiry_preserved'
    assert not at(5*NS,expires_ns=NOW_NS)['contextual_eligible']
    c=contract();q=inherited_policy(c,'options_pricing')
    assert not q.assess(source_ns=NOW_NS-5*NS,available_ns=NOW_NS-NS,now_ns=NOW_NS,paired_ns=NOW_NS-7*NS)['contextual_eligible']


def test_per_stream_health_preserves_unrelated_fresh_observations():
    state=FeedState(scope());populate(state)
    state.latest[('trades',10252)]=NOW_NS-20*NS
    state.latest.pop(('mbp-1',41271));state.quotes.pop(41271)
    h=state.health(NOW_NS)
    assert h['status']=='UNAVAILABLE'
    assert h['component_health']['ESZ6']['trades']['status']=='UNAVAILABLE'
    assert h['component_health']['GCZ6']['mbp-1']['status']=='UNAVAILABLE'
    assert h['component_health']['GCZ6']['trades']['status']=='CAPTURED_CONTEXT_FRESH'
    assert h['component_health']['NQZ6']['trades']['status']=='CAPTURED_CONTEXT_FRESH'


def test_continuous_all_timeframes_gap_no_imputation_and_late_retraction():
    p,c=pipeline();builder=p.trade_candles[c.metadata.instrument_id]
    start=NOW_NS//(14400*NS)*14400*NS-14400*NS
    for i in range(20):
        assert add(p,trade(c,t=start+i*NS,price=str(2500+Decimal('.1')*(i%3))),ordinal=i)['accepted']
    review=CoverageReview(start,start+14400*NS,NOW_NS,digest('capture coverage'),'ENGINEERING_WINDOW_REVIEW')
    for tf in WIDTHS:
        bars,q=builder.view(tf,review=review,now_ns=NOW_NS)
        assert bars and all(b.identity==c.metadata for b in bars)
        assert q['gap_fill_count']==0 and not q['complete_exchange_continuity']
    bars,q=builder.view('1s',review=review,now_ns=NOW_NS)
    assert len(bars)==20 and len(q['missing_or_no_trade_intervals'])==14380
    # New late native position taints, and retracts, the affected finalized bar.
    v=observation(trade(c,t=start+NS),schema='trades',contract=c,archive_sha256=digest('late'),ordinal=90,
        retrieval_ns=NOW_NS,admission_ns=NOW_NS,evidence_kind='ENGINEERING_SYNTHETIC',enabled_schemas=('trades',))
    builder.ingest(v)
    bars,q=builder.view('1s',review=review,now_ns=NOW_NS)
    assert len(bars)==19 and q['rejected'][0]['reason']=='LATE_EVENT_REQUIRES_REVIEW'
    with pytest.raises(ValueError,match='future'):builder.view('1s',review=replace(review,available_ns=NOW_NS+1),now_ns=NOW_NS)


def test_missing_child_bars_and_roll_do_not_aggregate():
    c=contract();cal=calendar(c);start=NOW_NS//(60*NS)*60*NS-60*NS
    def bar(t):return HistoricalBar(c.metadata,'1s',t,t+NS,(2500*NS,)*4,1,NOW_NS,(digest(str(t)),),'derived-ohlcv-v1','ENGINEERING_SYNTHETIC')
    rows=[bar(start+i*NS) for i in range(60)]
    out,rejected=aggregate_complete(rows,target='1m',calendar=cal)
    assert len(out)==1 and out[0].volume==60 and not rejected
    assert aggregate_complete(rows[:-1],target='1m',calendar=cal)[0]==()
    with pytest.raises(ValueError):aggregate_complete([*rows,rows[0]],target='1m',calendar=cal)
    with pytest.raises(ValueError):aggregate_complete([rows[0],replace(rows[1],identity=contract('ES').metadata)],target='1m',calendar=cal)


def test_native_legacy_adapter_explicit_opt_in_uses_actual_TRYOZ_feed_terms():
    row=native();policy=DatabentoPublisherPolicy(((1,'GLBX.MDP3','GLBX'),),NOW_NS-NS,digest('metadata'))
    result=legacy_definition(row,publishers=policy.mapping,now=instant(NOW_NS),cutoff_ns=NOW_NS,identity_policy=policy)
    assert result.tick==Decimal('.1') and result.multiplier==100
    with pytest.raises(ValueError):legacy_definition(row,publishers=policy.mapping,now=instant(NOW_NS))


def test_spool_restart_rebuild_is_idempotent_and_hash_verified(tmp_path):
    p,c=pipeline();spool=DurableSpool(tmp_path/'native.sqlite')
    row=trade(c)
    first=spool.append('trades',row,capture_ns=NOW_NS,delivery_id='original',evidence_kind='ENGINEERING_SYNTHETIC')
    assert first[2] and not spool.append('trades',row,capture_ns=NOW_NS,delivery_id='original',evidence_kind='ENGINEERING_SYNTHETIC')[2]
    # A verified gateway replay prefix remains raw evidence but is not volume.
    spool.append('trades',row,capture_ns=NOW_NS,delivery_id='prefix',evidence_kind='ENGINEERING_SYNTHETIC',admitted=False)
    assert len(spool.replay(p))==1
    a=p.analyse(c.metadata.instrument_id,now_ns=NOW_NS,mandatory=('trade_features',))
    fresh,cc=pipeline();assert len(spool.replay(fresh))==1
    assert fresh.analyse(cc.metadata.instrument_id,now_ns=NOW_NS,mandatory=('trade_features',))==a
    spool.checkpoint('cursor',{'event_ns':row.ts_event});assert spool.load('cursor')['event_ns']==row.ts_event
    spool.db.execute("UPDATE raw SET native=? WHERE id=1",(b'corrupt',));spool.db.commit()
    with pytest.raises(ValueError,match='hash_mismatch'):spool.replay(p)
    spool.close()


def test_clock_review_preserves_raw_clocks_and_removes_only_proven_offset_rejections(tmp_path):
    from tests.research.test_databento_live_preparation import clock_review
    p,c=pipeline();row=trade(c,t=NOW_NS+150_000_000)
    assert not add(p,row)['accepted']
    fresh,cc=pipeline();review=clock_review()
    result=fresh.ingest(row,schema='trades',archive_sha256=digest('clock raw'),ordinal=1,
        capture_ns=NOW_NS,admission_ns=NOW_NS,evidence_kind='ENGINEERING_SYNTHETIC',clock_review=review)
    assert result['accepted']
    value=fresh.gates[c.metadata.instrument_id].accepted[-1]
    assert value.event_ns==row.ts_event and value.receive_ns==row.ts_recv and value.source.retrieval_ns==NOW_NS
    r=fresh.analyse(c.metadata.instrument_id,now_ns=NOW_NS,mandatory=('trade_features',))
    timing=r['components']['trade_features']['health']['freshness']
    assert timing['contextual_eligible'] and timing['synchronization']=='TOLERANT_SYNC'
    assert timing['clock_review_sha256']==digest(review) and not r['execution_eligible']
    spool=DurableSpool(tmp_path/'clock.sqlite')
    spool.append('trades',row,capture_ns=NOW_NS,delivery_id='one',evidence_kind='ENGINEERING_SYNTHETIC',clock_review=review)
    recovered,ccc=pipeline();assert spool.replay(recovered)[0]['accepted'];spool.close()
    assert recovered.gates[ccc.metadata.instrument_id].accepted[-1].source.clock_review==review
    # An offset outside the reviewed interval is still rejected.
    future=trade(c,t=NOW_NS+500_000_000)
    assert not fresh.ingest(future,schema='trades',archive_sha256=digest('future raw'),ordinal=2,
        capture_ns=NOW_NS,admission_ns=NOW_NS,evidence_kind='ENGINEERING_SYNTHETIC',clock_review=review)['accepted']


def test_explicit_discontinuity_review_does_not_rewrite_or_requalify_rejected_prices():
    p,c=pipeline();g=p.gates[c.metadata.instrument_id]
    assert add(p,trade(c))['accepted']
    assert not add(p,trade(c,price='2600.1'),ordinal=1)['accepted']
    with pytest.raises(ValueError):g.review_recovery('trades',anchor='2600',anchor_ns=NOW_NS,
        anchor_sha256=digest('new anchor'),review_reference='review',expected_fault_sha256=digest('wrong'))
    g.review_recovery('trades',anchor='2600',anchor_ns=NOW_NS,
        anchor_sha256=digest('new independent anchor'),review_reference='engineering market discontinuity review',
        expected_fault_sha256=digest(g.faults['trades']))
    assert len(g.quarantine)==1 and not g.faults and 'trades' not in g.latest
    assert add(p,trade(c,price='2600',t=NOW_NS+NS),ordinal=2,stamp=NOW_NS+2*NS)['accepted']


def test_upstream_price_context_survives_downstream_engine_error(monkeypatch):
    from monatise.research.phase9.coordinator import price_components
    import monatise.research.phase9.coordinator as module
    c=contract();cal=calendar(c);start=NOW_NS//(3600*NS)*3600*NS-72*3600*NS
    rows=[]
    for i,b in enumerate(synthetic_candles('1h')):
        tick=int(c.tick_size*NS)
        rows.append(HistoricalBar(c.metadata,'1h',start+i*3600*NS,start+(i+1)*3600*NS,
            tuple(round(v*NS/tick)*tick for v in (b.open,b.high,b.low,b.close)),int(b.volume),NOW_NS,
            (digest(str(i)),),'ohlcv-1h','ENGINEERING_SYNTHETIC'))
    r=price_components(c,rows,now_ns=NOW_NS,calendar=cal)
    assert r['available'] and r['native_analysis']['available']
    assert not r['crypto_engines_used'] and 'engine_health' not in r
    assert r['session_statistics']['volume_contracts']>0


@pytest.mark.parametrize('fault',['crossed','spread','locked','one_sided'])
def test_book_quality_faults_do_not_erase_trade_features(fault):
    p,c=pipeline();assert add(p,trade(c))['accepted']
    bid=2500*NS;ask=2501*NS;size=2
    if fault=='crossed':ask=2499*NS
    if fault=='spread':ask=2520*NS
    if fault=='locked':ask=bid
    if fault=='one_sided':bid=2**63-1;size=0
    row=dbn.MBP1Msg(publisher_id=1,instrument_id=c.metadata.instrument_id,ts_event=NOW_NS-NS,ts_recv=NOW_NS-NS+1,
        price=2500*NS,size=1,side=dbn.Side.BID,action=dbn.Action.MODIFY,depth=0,sequence=1,flags=0,
        levels=dbn.BidAskPair(bid_px=bid,ask_px=ask,bid_sz=size,ask_sz=2,bid_ct=1,ask_ct=1))
    assert not add(p,row,'mbp-1',ordinal=1)['accepted']
    result=p.analyse(c.metadata.instrument_id,now_ns=NOW_NS,mandatory=('trade_features',),requested=('mbp-1',))
    assert result['availability']=='PARTIAL_ANALYSIS' and result['components']['trade_features']['available']
    assert not result['components']['mbp-1']['available']


def test_spool_capacity_and_metadata_corruption_fail_closed(tmp_path):
    p,c=pipeline();spool=DurableSpool(tmp_path/'bounded.sqlite',maximum_records=1)
    spool.append('trades',trade(c),capture_ns=NOW_NS,delivery_id='first',evidence_kind='ENGINEERING_SYNTHETIC')
    with pytest.raises(ValueError,match='capacity'):
        spool.append('trades',trade(c),capture_ns=NOW_NS,delivery_id='second',evidence_kind='ENGINEERING_SYNTHETIC')
    spool.db.execute("UPDATE raw SET schema='mbp-1'");spool.db.commit()
    with pytest.raises(ValueError,match='metadata_hash'):spool.replay(p)
    spool.close()


def test_forged_bar_cannot_borrow_valid_trade_provenance():
    from monatise.research.phase9.coordinator import NativeFuturesCoordinator
    p,c=pipeline();assert add(p,trade(c,t=NOW_NS-120*NS))['accepted']
    value=p.gates[c.metadata.instrument_id].accepted[-1]
    opened=value.event_ns//(60*NS)*60*NS
    forged=HistoricalBar(c.metadata,'1m',opened,opened+60*NS,(2600*NS,)*4,2,NOW_NS,
        (value.source.record_sha256,),'derived-ohlcv-v1','ENGINEERING_SYNTHETIC')
    r=NativeFuturesCoordinator().analyse(p.gates[c.metadata.instrument_id],bars_by_timeframe={'1m':(forged,)},
        calendar=calendar(c),now_ns=NOW_NS,mandatory=('price:1m',))
    assert not r['components']['price:1m']['available']
    assert r['components']['price:1m']['reason']=='bar_price_or_volume_lineage_mismatch'
