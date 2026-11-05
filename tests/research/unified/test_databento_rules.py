from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace
import pytest
from monatise.research.unified.databento_rules import record_quality, informational_flags,market_event_signature,EventOccurrences
from monatise.research.unified.models import (QuoteUnavailable,current_quote,Trade,Coverage,Bar,MINUTE)
from monatise.research.unified.eligibility import validate,final_revalidate
from monatise.research.unified.trade_bars import reconstruct_minutes
from .helpers import fixture,NOW


@pytest.mark.parametrize('flags',[32,128|32,64|32,128|64|32|16])
def test_snapshot_is_provenance_not_bad_data(flags):
    assert record_quality(flags)==()
    assert informational_flags(flags)==('NATIVE_REPLAY_SNAPSHOT',)


@pytest.mark.parametrize('flags,expected',[(8,('NATIVE_BAD_TS_RECV',)),(4,('NATIVE_MAYBE_BAD_BOOK',)),
    (32|8|4,('NATIVE_BAD_TS_RECV','NATIVE_MAYBE_BAD_BOOK'))])
def test_actual_timestamp_and_gap_flags_remain_rejections(flags,expected):
    assert record_quality(flags)==expected


def test_absent_native_bbo_invalidates_previous_good_quote_and_can_recover():
    snap,policy,frames,obs=fixture()
    q=replace(snap.quotes[0],sequence=1,native_ordinal=1)
    missing=QuoteUnavailable(q.contract,q.receive_ns,q.available_ns,'real-empty-native-book',sequence=2,native_ordinal=2)
    snap=replace(snap,quotes=(q,),quote_invalidations=(missing,))
    assert current_quote(snap) is None
    assert 'ENTRY_QUOTE_UNAVAILABLE' in validate(obs,snap,policy,frames).reasons
    recovered=replace(q,sequence=3,native_ordinal=3,source='later-real-two-sided-book')
    assert current_quote(replace(snap,quotes=(q,recovered)))==recovered


def archived(snap,*,trades,bars=()):
    return SimpleNamespace(instrument=snap.instrument,trades=trades,bars=bars,
        coverage=(Coverage('trades',NOW-MINUTE,NOW,NOW,'actual-source-proof'),),
        mode='AS_RECORDED',report={},manifest_hash='a'*64)


def test_receive_time_aggregation_preserves_native_tie_order_and_availability():
    # Use a real Archive shape, not provider data: these are engineering fixtures.
    from monatise.research.unified.archive import Archive
    snap,_,_,_=fixture();start=NOW-MINUTE
    rows=tuple(Trade(snap.instrument.key,start-1,start+1,NOW,D(p),1,'BUY',f's:{n}',
        sequence=n,native_ordinal=n) for n,p in [(2,'102'),(1,'101')])
    a=Archive(snap.instrument,(),rows,(),(Coverage('trades',start,NOW,NOW,'proof'),),
        snap.schedule,'a'*64,'AS_RECORDED',(),False,None,None,start,{},())
    result=reconstruct_minutes(a)
    assert len(result.bars)==1
    b=result.bars[0]
    assert (b.open,b.close,b.volume)==(D('101'),D('102'),2)
    assert b.open_ns==start and b.available_ns==NOW
    assert result.report['trade_aggregation']['forward_filled_bars']==0
    assert result.manifest_hash!=a.manifest_hash


def test_no_print_does_not_create_candles_and_disagreement_is_flagged():
    from monatise.research.unified.archive import Archive
    snap,_,_,_=fixture();start=NOW-MINUTE
    a=Archive(snap.instrument,(),(),(),(Coverage('trades',start,NOW,NOW,'proof'),),
        snap.schedule,'a'*64,'AS_RECORDED',(),False,None,None,start,{},())
    result=reconstruct_minutes(a)
    assert not result.bars and result.report['trade_aggregation']['reviewed_no_print_minutes']==1
    b=Bar(snap.instrument.key,'1m',start,NOW,NOW,D(100),D(101),D(99),D(100),1,'vendor')
    result=reconstruct_minutes(replace(a,bars=(b,)))
    assert 'TRADE_VENDOR_AGGREGATE_MISMATCH' in result.bars[0].quality


def test_latest_native_book_removal_is_rejected_at_final_revalidation():
    snap,policy,frames,obs=fixture()
    candidate=validate(obs,snap,policy,frames)
    assert candidate.eligible
    q=snap.quotes[0]
    invalid=QuoteUnavailable(q.contract,NOW,NOW,'native-no-two-sided-book',sequence=1,native_ordinal=1)
    assert 'FINAL_QUOTE_UNAVAILABLE_OR_STALE' in final_revalidate(candidate.plan,
        replace(snap,quote_invalidations=(invalid,)),policy)


def test_snapshot_never_admits_provider_receive_timestamp_from_future():
    from monatise.research.unified.archive import Archive
    snap,_,_,_=fixture()
    future=replace(snap.quotes[0],receive_ns=NOW+1,available_ns=NOW)
    a=Archive(snap.instrument,snap.bars,(),(future,),(),snap.schedule,'a'*64,'AS_RECORDED',
        (),False,None,None,NOW-1,{})
    assert not a.snapshot(NOW).quotes


def test_btc_readiness_refuses_another_product():
    from monatise.research.unified.archive import Archive
    from monatise.research.unified.readiness import btc_readiness
    snap,policy,_,_=fixture()
    a=Archive(snap.instrument,snap.bars,(),snap.quotes,(),snap.schedule,'a'*64,'AS_RECORDED',
        (),False,None,None,NOW-1,{})
    with pytest.raises(ValueError,match='BTC_ONLY_READINESS_SCOPE'):
        btc_readiness(a,policy,NOW)


def test_native_event_identity_excludes_capture_receive_clock_but_keeps_market_payload():
    row=dict(publisher_id=1,instrument_id=42316233,ts_event=123456,sequence=42,
        action='T',side='B',depth=0,price=78000*10**9,size=1,flags=0,ts_recv=123999,ts_in_delta=50)
    original=SimpleNamespace(**row)
    replay=SimpleNamespace(**dict(row,ts_recv=124049,ts_in_delta=100,flags=32))
    assert market_event_signature('trades',original)==market_event_signature('trades',replay)
    other_trade=SimpleNamespace(**dict(row,size=2))
    assert market_event_signature('trades',original)!=market_event_signature('trades',other_trade)


def test_overlap_occurrence_counts_preserve_repeated_identical_executions():
    r=SimpleNamespace(publisher_id=1,instrument_id=42316233,ts_event=123456,sequence=42,
        action='T',side='B',depth=0,price=78000*10**9,size=1,flags=0,ts_recv=123999)
    index=EventOccurrences()
    first=index.key('trades','source-a',0,r)
    second=index.key('trades','source-a',1,r)
    assert first!=second
    assert index.key('trades','source-b',0,r)==first
    assert index.key('trades','source-b',1,r)==second
    assert index.key('trades','source-a',0,r)==first


def test_reusing_source_ordinal_for_changed_payload_fails():
    r=SimpleNamespace(publisher_id=1,instrument_id=42316233,ts_event=123456,sequence=42,
        action='T',side='B',depth=0,price=78000*10**9,size=1,flags=0)
    index=EventOccurrences();index.key('trades','source',0,r)
    altered=SimpleNamespace(**dict(vars(r),size=2))
    with pytest.raises(ValueError,match='SOURCE_ORDINAL_PAYLOAD_CONFLICT'):
        index.key('trades','source',0,altered)
