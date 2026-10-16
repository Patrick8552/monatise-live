from dataclasses import replace
from decimal import Decimal
import pytest
import databento_dbn as dn

from monatise.research.native_futures.analysis import analyse_frame
from monatise.research.databento.candles import ExchangeCalendar
from monatise.research.phase10.market_info import FuturesMarketInfo
from monatise.research.phase10.access import AnalysisRequest
from tests.research.native_futures.test_analysis import bars
from tests.research.phase9.test_pipeline import pipeline, add, trade, NOW_NS, NS
from tests.research.phase9.test_options_service import quote
from monatise.research.institutional.models import digest


def test_closed_calendar_buckets_do_not_erase_structure_but_unknown_gaps_do():
    rows=bars([2500,2501,2505,2502,2501,2498,2501,2504,2508,2504,2503,2500,2503,2505,2510,2506,2505])
    a,b=rows[7],rows[9];identity=a.identity
    cal=ExchangeCalendar('GLBX.MDP3',identity.exchange,'ENGINEERING_CLOSURE',digest('closure'),'v1',
        rows[0].open_ns,rows[-1].close_ns,((rows[0].open_ns,a.close_ns),(b.open_ns,rows[-1].close_ns)))
    kept=rows[:8]+rows[9:]
    r=analyse_frame(kept,tick_size='.1',cutoff_ns=NOW_NS,calendar=cal)
    assert r['available'] and len(r['omitted_session_buckets'])==1 and r['gap_fill_count']==0
    assert r['omitted_older_bars']==0 and type(r['omitted_older_bars']) is int
    assert not analyse_frame(kept,tick_size='.1',cutoff_ns=NOW_NS)['available']
    open_cal=replace(cal,intervals=((cal.valid_from_ns,cal.valid_to_ns),))
    assert analyse_frame(kept,tick_size='.1',cutoff_ns=NOW_NS,calendar=open_cal)['reason']=='missing_bar_in_reviewed_trading_interval'
    assert not analyse_frame(kept+(kept[-1],),tick_size='.1',cutoff_ns=NOW_NS,calendar=cal)['available']


def test_native_quote_component_exposes_only_admitted_fresh_book_without_legacy(monkeypatch):
    p,c=pipeline();add(p,trade(c),ordinal=1)
    assert add(p,quote(c,2500),'mbp-1',2)['accepted']
    monkeypatch.setattr(p,'analyse',lambda *a,**k:pytest.fail('legacy graph'))
    service=FuturesMarketInfo(p,source_health=lambda now:{})
    req=AnalysisRequest((c.metadata.raw_symbol,),NOW_NS)
    x=service.analyse(req)['instruments'][c.metadata.raw_symbol]['components']['mbp-1']
    assert x['available'] and x['quote']['spread']=='0.2' and not x['quote']['executable_quote']
    stale=service.analyse(replace(req,cutoff_ns=NOW_NS+11*NS))['instruments'][c.metadata.raw_symbol]
    assert not stale['components']['mbp-1']['available']
    p.gates[c.metadata.instrument_id].transport_gap('mbp-1','ENGINEERING_MISSING_BOOK')
    x=service.analyse(req)['instruments'][c.metadata.raw_symbol]
    assert not x['components']['mbp-1']['available'] and x['components']['trade_features']['available']


def test_OI_revisions_same_reference_do_not_become_day_changes():
    p,c=pipeline()
    for i,(days,qty) in enumerate(((2,100),(1,110),(1,115))):
        at=NOW_NS-(3-i)*NS
        row=dn.StatMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,
            ts_event=at-1,ts_recv=at,ts_ref=NOW_NS-days*86400*NS,quantity=qty,
            price=2**63-1,stat_type=dn.StatType.OPEN_INTEREST,
            update_action=dn.StatUpdateAction.NEW,channel_id=1,sequence=i)
        assert add(p,row,'statistics',i)['accepted']
    x=FuturesMarketInfo(p,source_health=lambda now:{}).analyse(
        AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))['instruments'][c.metadata.raw_symbol]['components']
    assert x['open_interest']['contracts']==115
    assert x['oi_change']['result']['change_contracts']==15
    assert x['open_interest']['signed_dealer_position'] is None


def test_SDK_book_streams_explicitly_warn_instead_of_silently_skipping():
    from monatise.research.databento.sdk_transport import OwnedSDKClient
    from tests.research.phase10.test_sdk_transport import SDK
    received={}
    def builder(**kw):
        received.update(kw);return SDK(**kw)
    c=OwnedSDKClient('ENGINEERING_ONLY',5,builder=builder)
    try:assert received['slow_reader_behavior']=='warn' and received['reconnect_policy']=='none'
    finally:c.close()


def test_frame_history_limit_is_a_count_separate_from_session_omissions():
    rows=bars([2500,2501,2505,2502,2501,2498,2501,2504,2508,2504,2503,2500,2503,2505,2510,2506,2505])
    result=analyse_frame(rows,tick_size='.1',cutoff_ns=NOW_NS,maximum_bars=16)
    assert result['omitted_older_bars']==1 and result['omitted_session_buckets']==[]


@pytest.mark.parametrize('sign,expected',[(1,'100'),(-1,'0'),(0,'50')])
def test_standard_indicators_have_explicit_wilder_and_sma_seeds(sign,expected):
    from monatise.research.native_futures.technicals import close_indicators
    rows=tuple((2500+sign*i)*10**9 for i in range(40))
    r=close_indicators(rows)
    assert r['rsi14']['value']==expected
    assert r['ema20']['available'] and r['rsi14_sma14']['value']==expected
    assert r['rsi_cross_above_sma_within_4_bars']['observed'] is False
    assert not r['trade_signal']
    short=close_indicators(rows[:14]);assert not short['rsi14']['available']
    assert not close_indicators(rows[:31])['rsi_cross_above_sma_within_4_bars']['available']
    assert close_indicators(rows[:32])['rsi_cross_above_sma_within_4_bars']['available']


def test_wilder_rsi_known_mixed_close_reference():
    from monatise.research.native_futures.technicals import close_indicators
    # Mixed gains/losses: initial 14-change averages are hand-verifiable.
    values=[100,102,101,104,102,103,105,104,107,106,108,107,109,108,110]
    result=close_indicators(tuple(v*10**9 for v in values))
    gain=Decimal(17)/14;loss=Decimal(7)/14
    assert abs(Decimal(result['rsi14']['value'])-(100-100/(1+gain/loss)))<Decimal('1e-24')


def test_ema20_uses_sma_seed_then_two_over_twenty_one():
    from monatise.research.native_futures.technicals import close_indicators
    result=close_indicators(tuple((2500+i)*10**9 for i in range(21)))
    assert Decimal(result['ema20']['value'])==Decimal('2510.5')
