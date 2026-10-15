from dataclasses import replace
import hashlib
import json

import databento_dbn as dbn
import pytest

from monatise.research.native_futures.quality_review import NativeQualityReview, receive_timestamp_issue
from monatise.research.phase10.market_info import FuturesMarketInfo, quarantine_scope
from monatise.research.phase10.access import AnalysisRequest
from monatise.research.phase10.source import load_capture
from monatise.research.phase9.rotation import RotatingSpool, RotationPolicy
from monatise.research.institutional.models import digest
from tests.research.phase9.test_pipeline import pipeline, add, trade, NOW_NS, NS
from tests.research.phase10.test_workflow import bar
from tests.research.phase10.test_source import capture, hashes


def bad_receive(c, *, flags=8, price=2500*NS):
    return dbn.TradeMsg(publisher_id=c.metadata.publisher_id,instrument_id=c.metadata.instrument_id,
        ts_event=NOW_NS-NS,ts_recv=NOW_NS-NS-14000000,price=price,size=2,
        action=dbn.Action.TRADE,side=dbn.Side.BID,depth=0,sequence=123,flags=flags)


def test_bad_receive_is_attributed_without_clock_repair_or_admission():
    p,c=pipeline();row=bad_receive(c);before=bytes(row)
    issue=receive_timestamp_issue(row,c,schema='trades')
    assert issue['flag']=='F_BAD_TS_RECV' and issue['receive_minus_event_ns']==-14000000
    assert not issue['record_admitted'] and not issue['timestamp_repaired']
    assert bytes(row)==before and not add(p,row)['accepted']


@pytest.mark.parametrize('flags,price',[(8|4,2500*NS),(8|32,2500*NS),(8,1),(0,2500*NS)])
def test_other_quality_defects_do_not_become_trade_timestamp_only(flags,price):
    p,c=pipeline()
    assert receive_timestamp_issue(bad_receive(c,flags=flags,price=price),c,schema='trades') is None


def test_typed_trade_fault_preserves_native_candles_and_blocks_all_trade_features():
    p,c=pipeline();iid=c.metadata.instrument_id
    assert add(p,bar(c,NOW_NS//(60*NS)*60*NS-120*NS),'ohlcv-1m')['accepted']
    assert add(p,trade(c),ordinal=1)['accepted']
    review=NativeQualityReview();review.rejection('trades',bad_receive(c),c,original_reason='ValueError')
    h=dict(quarantined=True,reasons=[],component_rejections={'trades:'+str(iid):['native_record_or_recovery_validation_failed']},
        native_rejection_reviews=review.typed_rejections(complete_for_reported_prefix=True))
    report=FuturesMarketInfo(p,source_health=lambda now:h).analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))
    value=report['instruments'][c.metadata.raw_symbol]
    assert value['availability']=='PARTIAL_MARKET_INFORMATION'
    assert value['components']['price:1m']['available']
    assert not value['components']['trade_features']['available']  # Even a clean prefix is not full flow.
    assert value['capture_health']['quarantined']
    assert value['validation']['source_quarantine_scope']=='COMPONENT_SOURCE_QUARANTINE'
    h['reasons']=['connection_stalled_trades']
    assert quarantine_scope(h,iid)=='GLOBAL_SOURCE_QUARANTINE'
    h['reasons']=[];h['native_rejection_reviews']=review.typed_rejections(complete_for_reported_prefix=False)
    assert quarantine_scope(h,iid)=='INSTRUMENT_SOURCE_QUARANTINE'


def test_exact_cross_stream_corroboration_explains_but_never_overrides_price_rejection():
    p,c=pipeline('ES');g=p.gates[c.metadata.instrument_id]
    g.schema_policies['trades']=replace(g.policy,floor_ticks=1)
    row=trade(c,t=NOW_NS-2*NS,price='2501');review=NativeQualityReview()
    assert not add(p,row)['accepted']
    before=list(g.guards['trades'].changes)
    review.observe('trades',row,c,admitted=True,gate=g)
    candle=bar(c,row.ts_recv//NS*NS,schema='ohlcv-1s',price='2501',volume=2)
    review.observe('ohlcv-1s',candle,c,admitted=True,gate=g)
    evidence=review.price_faults(g)['trades']
    assert evidence['status']=='CROSS_STREAM_CORROBORATED_POLICY_REVIEW_REQUIRED'
    assert evidence['native_OHLCV_matches_captured_trades'] and evidence['rejected_price_inside_native_bar']
    assert not evidence['record_readmitted'] and not evidence['policy_changed']
    assert g.faults['trades'] and list(g.guards['trades'].changes)==before
    # A second bar is ambiguous; a volume mismatch is not corroboration.
    review.bars[(c.metadata.instrument_id,NS,candle.ts_event)][0]=bar(c,candle.ts_event,schema='ohlcv-1s',price='2501',volume=3)
    assert review.price_faults(g)['trades']['status']=='CROSS_STREAM_MISMATCH_REQUIRES_REVIEW'


def test_unaccounted_or_unknown_rejection_never_gets_narrow_scope():
    p,c=pipeline();review=NativeQualityReview();review.rejection('trades',bad_receive(c),c,original_reason='ValueError')
    review.rejection('trades',trade(c),c,original_reason='ValueError')
    assert not review.typed_rejections(complete_for_reported_prefix=True)['trades:'+str(c.metadata.instrument_id)]['verified_trade_timestamp_scope']


def test_rejection_attribution_uses_verified_readonly_native_bytes(capture):
    root,c=capture;auth=json.loads((root/'authorization.json').read_text())
    spool=RotatingSpool(root/'spool',policy=RotationPolicy(records_per_segment=2,bytes_per_segment=4096,maximum_segments=10,maximum_total_bytes=65536))
    row=bad_receive(c)
    spool.append('trades',row,capture_ns=NOW_NS,delivery_id=digest(auth['plan'])+':0:trades:4',
        evidence_kind='ENGINEERING_SYNTHETIC',admitted=False,rejection_reason='ValueError')
    spool.checkpoint('feed_cursor',dict(spool_records=spool.count,cursors={}))
    spool.close()
    final=root/'capture/attempt-00/report.json';d=json.loads(final.read_text())
    d['quality'].update(quarantined=True,component_rejections={'trades:'+str(c.metadata.instrument_id):['native_record_or_recovery_validation_failed']})
    final.write_text(json.dumps(d));(root/'progress.json').write_text(json.dumps(dict(spool_records=5)))
    before=hashes(root)
    value=load_capture(root,cutoff_ns=NOW_NS).analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))['instruments'][c.metadata.raw_symbol]
    details=value['validation']['source_record_reviews']['trades:'+str(c.metadata.instrument_id)]
    assert details['count']==details['typed_count']==1 and details['verified_trade_timestamp_scope']
    assert details['examples'][0]['record_sha256']==hashlib.sha256(bytes(row)).hexdigest()
    assert not value['components']['trade_features']['available']
    assert hashes(root)==before
