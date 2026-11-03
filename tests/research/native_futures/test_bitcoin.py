"""Native-shaped BTC fixtures; these tests do not establish live data access."""
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import databento_dbn as dn
import pytest

from monatise.engines.asset_scope import require_canonical_non_futures
from monatise.research.databento.live_models import native_definition
from monatise.research.databento.live_state import FeedState
from monatise.research.databento.advanced import AdvancedAdapters
from monatise.research.institutional.models import digest
from monatise.research.native_futures.bitcoin_calendar import BitcoinScheduleReview, bitcoin_calendar
from monatise.research.native_futures.information_gate import NativeInformationGate
from monatise.research.phase9.pipeline import ResearchPipeline
from monatise.research.phase10.access import AnalysisRequest
from monatise.research.phase10.market_info import FuturesMarketInfo
from monatise.research.phase10.requests import request_symbols, exact_symbols
from tests.research.phase9.test_pipeline import calendar, trade, add, NS, NOW_NS
from tests.research.test_databento_live_preparation import native, capability, contract, scope


def test_btc_exact_native_economics_and_live_scope():
    c = contract('BTC')
    assert c.metadata.namespace == 'CME:BTC:BTCZ6'
    assert (c.tick_size, c.multiplier, c.price_unit) == (Decimal(5), Decimal(5), 'USD_PER_BITCOIN')
    assert scope(contracts=(c,)).contracts == (c,)
    assert request_symbols('Analyse BTC using Databento') == ('BTC',)


def test_btc_capture_state_verifies_definition_and_native_trade_without_legacy_policy():
    c=contract('BTC');state=FeedState(scope(contracts=(c,)),native_information=True)
    for i,schema in enumerate(('definition','trades','mbp-1')):
        state.ingest(schema,dn.SystemMsg(ts_event=NOW_NS,msg='ENGINEERING_ACK',code=dn.SystemCode.SUBSCRIPTION_ACK),capture_ns=NOW_NS,ordinal=i*3)
    state.ingest('definition',native('BTC'),capture_ns=NOW_NS,ordinal=10)
    row=trade(c,price='50000')
    assert state.ingest('trades',row,capture_ns=NOW_NS,ordinal=11) is not None
    assert c.metadata.instrument_id in state.verified_definitions
    assert not state.quality_reasons and not state.component_reasons


@pytest.mark.parametrize('changes', [
    dict(min_price_increment=NS), dict(unit_of_measure_qty=NS//10),
    dict(min_price_increment_amount=5*NS), dict(display_factor=NS//100),
    dict(unit_of_measure='BTC'), dict(exchange='XCEC'), dict(currency='EUR'),
    dict(raw_symbol='BTCUSDT'), dict(raw_symbol='MBTZ6'), dict(maturity_month=11),
    dict(expiration=NOW_NS-1), dict(leg_count=2), dict(main_fraction=1),
])
def test_definition_contradictions_never_enable_btc(changes):
    with pytest.raises(ValueError):
        native_definition(native('BTC', **changes), capability=capability(),
            publishers={1:('GLBX.MDP3','GLBX')}, as_of_ns=NOW_NS)


@pytest.mark.parametrize('symbol', ['BTCZ6', 'BTCX26', 'CME:BTCZ2026', 'BTC.FUT', 'BTC.v.0', 'BTC1!', 'BTC=F', 'CME:BTC'])
def test_explicit_btc_futures_cannot_enter_canonical_crypto_engines(symbol):
    with pytest.raises(ValueError, match='dedicated_native'):
        require_canonical_non_futures(symbol)


@pytest.mark.parametrize('symbol', ['BTC', 'BTCUSDT', 'BTC/USD', 'BTC-PERP', 'ETH'])
def test_spot_and_perpetual_names_keep_their_existing_scope(symbol):
    require_canonical_non_futures(symbol)


@pytest.mark.parametrize('symbol', ['BTCUSDT', 'MBT', 'ETH'])
def test_unreviewed_products_cannot_expand_native_requests(symbol):
    with pytest.raises(ValueError):
        request_symbols(f'Analyse {symbol} using Databento')


def btc_pipeline():
    row = native('BTC', ts_event=NOW_NS-20*86400*NS, ts_recv=NOW_NS-20*86400*NS+1)
    c = native_definition(row, capability=capability(), publishers={1:('GLBX.MDP3','GLBX')}, as_of_ns=NOW_NS)
    gate = NativeInformationGate(c)
    return ResearchPipeline({c.metadata.instrument_id:gate}, {c.metadata.instrument_id:calendar(c)},
        enabled_schemas=('definition','trades','ohlcv-1m','mbp-1')), c


def test_btc_real_native_pipeline_structure_flow_and_replay(monkeypatch):
    for package, klass in [('market_structure','MarketStructureEngine'), ('fibonacci_liquidity','FibonacciLiquidityEngine')]:
        import importlib
        engine = getattr(importlib.import_module('monatise.engines.'+package), klass)
        monkeypatch.setattr(engine, 'assess', lambda *a,**kw:pytest.fail('canonical crypto engine called'))
    p,c = btc_pipeline()
    start = NOW_NS//(60*NS)*(60*NS)-31*60*NS
    prices = [50000,50005,50025,50010,50005,49990,50005,50020,50040,50020,50015,50000,50015,50025,50050,50030,50025]
    for i,price in enumerate(prices):
        row = dn.OHLCVMsg(publisher_id=1, instrument_id=c.metadata.instrument_id, ts_event=start+i*60*NS,
            rtype=dn.RType.OHLCV_1M, open=price*NS, high=(price+5)*NS, low=(price-5)*NS, close=price*NS, volume=2)
        assert add(p,row,'ohlcv-1m',i)['accepted']
    for i,side in enumerate((dn.Side.BID,dn.Side.ASK,dn.Side.NONE)):
        assert add(p,trade(c,t=NOW_NS-(3-i)*NS,price='50000',size=i+1,side=side),ordinal=100+i)['accepted']
    assert exact_symbols(('BTC',),p) == ('BTCZ6',)
    health = {'replay_completed':['definition','trades','ohlcv-1m','mbp-1']}
    result = FuturesMarketInfo(p,source_health=lambda at:health).analyse(AnalysisRequest(('BTCZ6',),NOW_NS))
    r = result['instruments']['BTCZ6']
    assert r['availability'] != 'UNAVAILABLE'
    frame = r['components']['price:1m']['native_analysis']
    assert frame['structure']['state'] == 'HIGHER_HIGHS_AND_LOWS'
    assert frame['fibonacci']['available'] and not frame['fibonacci']['signal_qualification']
    flow = r['components']['trade_features']['result']
    assert flow['executed_contracts'] == 6 and Decimal(flow['vwap']) == 50000
    assert r['components']['recent_trade_flow']['windows']['5m']['known_side_delta'] == -1
    assert r['components']['recent_trade_flow']['windows']['5m']['unknown_side_contracts'] == 3
    assert not result['crypto_engines_used'] and not result['execution_eligible']
    health['replay_completed'].remove('ohlcv-1m')
    r = FuturesMarketInfo(p,source_health=lambda at:health).analyse(AnalysisRequest(('BTCZ6',),NOW_NS))
    assert r['instruments']['BTCZ6']['availability'] == 'UNAVAILABLE'


@pytest.mark.parametrize('price', ['0', '-5', '50001'])
def test_btc_off_tick_or_nonpositive_trade_never_enters_features(price):
    p,c = btc_pipeline()
    assert not add(p,trade(c,price=price))['accepted']
    assert p.gates[c.metadata.instrument_id].faults


def stamp(text):
    return int(datetime.fromisoformat(text).timestamp())*NS


def reviewed(start='2026-10-26T00:00:00+00:00', end='2026-11-09T00:00:00+00:00', **kwargs):
    return BitcoinScheduleReview(stamp(start),stamp(end),'ENGINEERING_DATED_CME_SCHEDULE',digest('schedule'),**kwargs)


def test_calendar_uses_weekday_breaks_and_chicago_dst_without_weekend_closure():
    review=reviewed();cal=bitcoin_calendar(review.valid_from_ns,review.valid_to_ns,review=review)
    for point in ('2026-10-30T21:00:00+00:00','2026-11-02T22:01:00+00:00','2026-10-31T07:30:00+00:00','2026-11-07T09:00:00+00:00'):
        t=stamp(point);assert not cal.contains(t,t+60*NS)
    for point in ('2026-10-30T21:02:00+00:00','2026-11-02T22:02:00+00:00','2026-10-31T09:00:00+00:00','2026-11-01T08:00:00+00:00','2026-11-07T10:00:00+00:00'):
        t=stamp(point);assert cal.contains(t,t+60*NS)


def test_calendar_keeps_explicit_exceptions_and_rejects_unreviewed_dates():
    t=stamp('2026-11-03T14:00:00+00:00')
    review=reviewed(additional_closures=((t,t+10*60*NS),))
    cal=bitcoin_calendar(review.valid_from_ns,review.valid_to_ns,review=review)
    assert not cal.contains(t,t+60*NS)
    with pytest.raises(ValueError,match='reviewed_bitcoin_calendar'):
        bitcoin_calendar(review.valid_from_ns-60*NS,review.valid_to_ns,review=review)
    with pytest.raises(ValueError,match='dated_bitcoin'):
        reviewed(start='2026-01-01T00:00:00+00:00')
