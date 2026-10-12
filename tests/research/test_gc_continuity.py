"""Engineering evidence only. No network, paid data or production credentials."""
from dataclasses import asdict, replace
from datetime import UTC, datetime
import copy
from pathlib import Path

import pytest

from monatise.research.gc_fib.candles import GCIdentity, MINUTE
from monatise.research.gc_fib.worker import parse_bar
from monatise.research.gc_qualification.adapter import CutoffAdapter, required_history
from monatise.research.gc_qualification.models import NativeContract
from monatise.research.gc_continuity.classification import classify
from monatise.research.gc_continuity.sessions import status_sessions, complete_minute_sessions, expectation, expected_opens, nominal_gc_state
from monatise.research.gc_continuity.recovery import NativeTrade, TradeContinuityReview, recover_minute
from monatise.research.gc_continuity.forensics import metric_counts
from monatise.research.gc_continuity.acquisition_plan import propose, metadata_only
from tests.research.gc_qualification_fixtures import fixture, NOW_NS

START = NOW_NS//MINUTE*MINUTE


def contract():
    data = fixture()["contract"]
    data['identity'] = GCIdentity(**data['identity'])
    data['native_terms'] = tuple(tuple(t) for t in data['native_terms'])
    return NativeContract(**data)


def trade(ordinal=0, **changes):
    args = dict(identity=GCIdentity(),event_ns=START+10*10**9,receive_ns=START+10*10**9+5,
        price_fixed=2500_000_000_000,size=2,sequence=10,flags=0,action="T",side="N",
        archive_sha256='a'*64,record_sha256='b'*64,ordinal=ordinal,
        retrieval_ns=START+86400*10**9,admission_ns=START+86400*10**9,evidence_kind="ENGINEERING_SYNTHETIC")
    return NativeTrade(**(args|changes))


def review(count=1,**changes):
    args = dict(identity=GCIdentity(),start_ns=START,end_ns=START+MINUTE,
        archive_sha256s=('a'*64,),request_sha256s=('c'*64,),reviewed_reference='engineering-independent-review',
        independent_evidence_sha256='d'*64,continuity_complete=True,corrections_reviewed=True,
        multiplicity_policy='PRESERVE_VERIFIED_NATIVE_SOURCE_POSITIONS',expected_interval_records=count,
        definition_sha256=contract().definition_sha256,evidence_kind="ENGINEERING_SYNTHETIC")
    return TradeContinuityReview(**(args|changes))


def recover(rows, proof=None, sessions=None):
    return recover_minute(rows,start_ns=START,review=proof or review(len(rows)),
        sessions=sessions if sessions is not None else ((START,START+MINUTE),),contract=contract())


@pytest.mark.parametrize('state,raw,admitted,count,complete,expected',[
    ('CLOSED',False,False,None,False,'A'),('FULLY_OPEN',False,False,0,True,'B'),
    ('FULLY_OPEN',False,False,2,False,'C'),('FULLY_OPEN',True,False,None,False,'D'),
    ('FULLY_OPEN',False,False,0,False,'E'),('FULLY_OPEN',False,False,None,False,'E'),
    ('PARTIAL_SESSION',True,False,2,False,'E'),('UNREVIEWED',False,False,0,True,'E')])
def test_classifications_require_correct_evidence(state,raw,admitted,count,complete,expected):
    result = classify(session_state=state,raw_present=raw,admitted_present=admitted,trade_count=count,
                      independently_complete_trades=complete)
    assert result['classification']==expected
    assert not result['synthetic_price_authorized']


def test_recovery_order_precision_volume_and_source_positions():
    rows = [trade(0),trade(1,price_fixed=2500_100_000_000,size=3,receive_ns=START+20*10**9),
            trade(2,price_fixed=2499_900_000_000,size=4,receive_ns=START+30*10**9)]
    result = recover(list(reversed(rows)))
    assert result['prices']==['2500','2500.1','2499.9','2499.9']
    assert result['volume']==9 and result['aggregation_clock']=='ts_recv'
    assert len(result['source_records'])==3 and result['event_clock_preserved']
    assert result['evidence_kind']=='ENGINEERING_SYNTHETIC' and not result['qualification_admitted']
    assert result==recover(rows)


def test_identical_native_bytes_at_different_ordinals_are_not_duplicate_trades():
    rows = [trade(0),trade(1)]
    result = recover(rows)
    assert result['volume']==4 and len(result['source_records'])==2
    assert result['source_records'][0]['record_sha256']==result['source_records'][1]['record_sha256']


def test_reingestion_same_source_position_is_idempotent_revision_is_rejected():
    row=trade()
    assert recover([row,row],review(1))['volume']==2
    with pytest.raises(ValueError,match='conflicting_source_revision'):
        recover([row,replace(row,size=3)],review(1))


@pytest.mark.parametrize('changes',[
    {'continuity_complete':False},{'corrections_reviewed':False},{'expected_interval_records':2},
    {'start_ns':START-MINUTE},{'definition_sha256':'f'*64},{'archive_sha256s':('f'*64,)},
    {'evidence_kind':'AUTHENTIC_HISTORICAL_DOWNLOAD'}])
def test_recovery_refuses_unreviewed_incomplete_or_mismatched_evidence(changes):
    with pytest.raises(ValueError):recover([trade()],review(**changes))


@pytest.mark.parametrize('flags',[4,8,32,12])
def test_gap_bad_clock_or_snapshot_cannot_recover(flags):
    with pytest.raises(ValueError,match='trade_gap_clock_or_snapshot_flag'):recover([trade(flags=flags)])


def test_no_trade_review_never_creates_zero_volume_or_carried_price():
    result=recover([],review(0))
    assert result['classification']=='B' and result['candle'] is None
    assert not result['synthetic_price_created'] and not result['qualification_admitted']


def test_recovery_cannot_reorder_bad_native_receive_or_count_informational_fills():
    with pytest.raises(ValueError,match='native_receive_order_regressed'):
        recover([trade(0,receive_ns=START+20*10**9),trade(1,receive_ns=START+15*10**9)])
    with pytest.raises(ValueError,match='executed_trade_required'):
        trade(action='F')
    with pytest.raises(ValueError,match='session'):
        recover([trade()],sessions=((START,START+30*10**9),))


def test_vendor_receive_clock_minute_does_not_erase_original_event_time():
    row=trade(event_ns=START-5,receive_ns=START+5)
    result=recover([row]);assert result['open_ns']==START
    assert result['source_records'][0]['event_ns']==START-5
    with pytest.raises(ValueError,match='outside_receive_time_bucket'):
        recover([trade(receive_ns=START+MINUTE)])


def status(event,trading,receive=None,action='0'):
    return dict(ts_event=str(event),ts_recv=str(event if receive is None else receive),is_trading=trading,action=action)


def test_status_unknown_no_change_ordered_transitions_and_midnight_snapshots():
    rows=[status(START,'True'),status(START+10*10**9,'None'),
          status(START+30*10**9,'False',action='1'),status(START+40*10**9,'True',action='7'),
          status(START+40*10**9,'True',receive=START+86400*10**9)]
    sessions=status_sessions(rows,end_ns=START+120*10**9)
    assert sessions==((START,START+30*10**9),(START+40*10**9,START+120*10**9))
    assert expectation(START,START+MINUTE,sessions=sessions)=='PARTIAL_SESSION'
    assert complete_minute_sessions(sessions)==((START+MINUTE,START+2*MINUTE),)
    tied=[status(START,'False',receive=START+1,action='1'),status(START,'True',receive=START+2,action='7')]
    assert status_sessions(tied,end_ns=START+MINUTE)==((START,START+MINUTE),)
    with pytest.raises(ValueError,match='conflicting_status'):
        status_sessions([status(START,'True'),status(START,'False')],end_ns=START+MINUTE)
    with pytest.raises(ValueError,match='unknown'):
        status_sessions([status(START,'None',action='8')],end_ns=START+MINUTE)


def test_reviewed_holiday_maintenance_and_partial_buckets_are_not_missing_prices():
    day=int(datetime(2026,9,7,tzinfo=UTC).timestamp())*10**9
    holiday=((day,day+18*3600*10**9+30*MINUTE),)
    assert expectation(day+19*3600*10**9,day+20*3600*10**9,sessions=holiday)=='CLOSED'
    assert expectation(day+16*3600*10**9,day+20*3600*10**9,sessions=holiday)=='PARTIAL_SESSION'
    opens=expected_opens(holiday,width_ns=4*3600*10**9,start_ns=day,end_ns=day+24*3600*10**9)
    assert day+16*3600*10**9 not in opens
    assert expectation(day,day+MINUTE,sessions=holiday,reviewed=False)=='UNREVIEWED'


@pytest.mark.parametrize('utc,state',[
    ('2026-03-01T22:30:00+00:00','CLOSED_WEEKEND'),('2026-03-01T23:30:00+00:00','REGULAR_OPEN_SUBJECT_TO_HOLIDAY_AND_STATUS'),
    ('2026-03-08T22:30:00+00:00','REGULAR_OPEN_SUBJECT_TO_HOLIDAY_AND_STATUS'),
    ('2026-11-01T22:30:00+00:00','CLOSED_WEEKEND'),('2026-11-01T23:30:00+00:00','REGULAR_OPEN_SUBJECT_TO_HOLIDAY_AND_STATUS'),
    ('2026-10-05T21:30:00+00:00','MAINTENANCE')])
def test_chicago_dst_regular_calendar_crosscheck(utc,state):
    ns=int(datetime.fromisoformat(utc).timestamp())*10**9
    assert nominal_gc_state(ns)==state


def test_h4_true_engine_warmup_51_does_not_shorten_200_history_or_change_others():
    assert required_history('4h')==51 and required_history('1h')==50
    v=fixture();bars=[parse_bar(b) for b in v['bars']]
    h4=sorted([b for b in bars if b.timeframe=='4h'],key=lambda b:b.open_ns)[-50:]
    bars=[b for b in bars if b.timeframe!='4h']+h4
    frames,reasons,_=CutoffAdapter(bars,v['sessions']).frames(NOW_NS)
    assert '4h:canonical_history_insufficient' in reasons and '4h' not in frames
    assert all(tf in frames for tf in ('1h','15m','5m','1m'))


def test_corrected_metrics_distinguish_quotes_candles_closures_and_overlaps():
    records=[{'rejection_reasons':['4h:canonical_source_stale','15m:canonical_source_stale','4h:missing_or_no_trade_bar']},
             {'rejection_reasons':['quote_stale']},{'rejection_reasons':['exchange_closed_or_unreviewed_session']}]
    counts=metric_counts(records)
    assert counts['candle_transport_freshness_rejected']==1
    assert counts['quote_freshness_rejected']==1 and counts['closed_session_rejected']==1
    assert counts['continuity_rejected']==1


def test_missing_evidence_proposals_do_not_rebuy_cache_raise_budget_or_call_download():
    class Ledger:
        def plan(self,*args,**kwargs):return dict(new_download_required=True,incremental_cost_usd=None)
        def report(self):return dict(approved_budget_usd='0')
    report={'missing_minutes':[dict(trade_requests=[],classification='E',start_ns=START,end_ns=START+MINUTE,
                    utc='2026-09-21T04:37:00+00:00'),dict(trade_requests=[{}],classification='E')]}
    result=propose(report,ledger=Ledger(),archive=object())
    assert len(result['requests'])==1 and result['approved_new_budget_usd']=='0'
    assert not result['concrete_nonzero_budget_approved'] and result['downloads_attempted']==0
    from monatise.research.databento.acquisition import DownloadPreflight
    class MetadataOnly:
        def preflight(self,r,now_ns):
            return DownloadPreflight(r.sha256,now_ns,r.start_ns,r.end_ns,'0.000001',True,True,'d'*64)
        def download(self,*args,**kwargs):raise AssertionError('must never acquire')
    quoted=metadata_only(result,MetadataOnly(),now_ns=NOW_NS)
    assert quoted['requests'][0]['estimated_usd']=='0.000001'
    assert not quoted['requests'][0]['download_authorized']
