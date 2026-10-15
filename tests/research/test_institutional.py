"""Credential-free native-shaped fixtures; no provider or broker requests."""
import asyncio
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys

import databento_dbn as dbn
import pytest

from monatise.research.institutional import VERSION
from monatise.research.institutional.fixtures import contract,quote,candle_evidence,positioning,NOW_NS,ENABLED
from monatise.research.institutional.models import Source,MarketObservation,SignalPreview,PreviewDecision,digest,encode
from monatise.research.institutional.normalize import observation,SECONDARY
from monatise.research.institutional.indicators import trade_indicators,book_indicator,volatility,open_interest_change
from monatise.research.institutional.mapping import ContextMapper,MappingPolicy,BrokerQuote
from monatise.research.institutional.options import OptionConvention,unsigned_european_sensitivity
from monatise.research.institutional.signals import broker_preview,crypto_preview
from monatise.research.institutional.worker import mapping_fixture,options_fixture,acquisition_proposals
from monatise.research.institutional.runner import run


def trade(*, product='GC',side=dbn.Side.BID,size=3,price=None,ordinal=0,flags=0,receive=None):
    c=contract(product)
    price=Decimal('2500') if price is None else Decimal(str(price))
    t=NOW_NS-10**9 if receive is None else receive
    row=dbn.TradeMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,
        ts_event=t-7,ts_recv=t,price=int(price*10**9),size=size,action=dbn.Action.TRADE,
        side=side,depth=0,sequence=1,flags=flags)
    return observation(row,schema='trades',contract=c,archive_sha256=digest('FIXTURE_TRADES'),ordinal=ordinal,
        retrieval_ns=NOW_NS,admission_ns=NOW_NS,evidence_kind='ENGINEERING_SYNTHETIC',enabled_schemas=ENABLED)


def metrics(values,**kwargs):
    return trade_indicators(values,start_ns=NOW_NS-2*10**9,end_ns=NOW_NS,
                            session_reference='ENGINEERING_SESSION',**kwargs)


@pytest.mark.parametrize('product,tick,multiplier',[('GC','.1','100'),('ES','.25','50'),('NQ','.25','20')])
def test_exact_contract_terms_and_native_observations(product,tick,multiplier):
    c=contract(product);t=trade(product=product)
    assert c.metadata.raw_symbol==product+'Z6' and c.tick_size==Decimal(tick) and c.multiplier==Decimal(multiplier)
    assert t.event_ns+7==t.receive_ns and t.source.admission_ns==NOW_NS
    assert t.source.evidence_kind=='ENGINEERING_SYNTHETIC' and t.contract.metadata.dataset=='GLBX.MDP3'
    assert t.payload==('2500',3,'BUY') and t.quality=='CAPTURED_NATIVE_CONTINUITY_UNCERTIFIED'


@pytest.mark.parametrize('flags',[4,8,32])
def test_gap_bad_receive_and_snapshot_trades_reject(flags):
    with pytest.raises(ValueError):trade(flags=flags)


def test_disabled_schema_and_secondary_descriptors():
    q=quote(contract())
    assert all(not v['enabled'] for v in SECONDARY.values())
    with pytest.raises(ValueError,match='disabled'):
        observation(None,schema='mbo',contract=q.contract,archive_sha256=digest('x'),ordinal=0,
            retrieval_ns=NOW_NS,admission_ns=NOW_NS,evidence_kind='ENGINEERING_SYNTHETIC')


def test_off_tick_and_unknown_aggressor():
    with pytest.raises(ValueError):trade(price='2500.01')
    result=metrics([trade(side=dbn.Side.NONE)])
    assert result['unknown_side_contracts']==3 and result['cvd'] is None
    assert result['known_side_delta']==0 and result['executed_contracts']==3


def test_source_ordinal_multiplicity_and_ingestion_idempotence():
    a,b=trade(ordinal=1),trade(ordinal=2)
    assert a.source.record_sha256==b.source.record_sha256
    result=metrics([a,a,b])
    assert result['executed_contracts']==6 and result['inputs']['count']==2
    assert result['vwap']=='2500' and result['cvd']==6
    assert not result['inputs']['complete_exchange_continuity']


def test_source_position_conflict_rejects():
    with pytest.raises(ValueError,match='revision'):
        metrics([trade(ordinal=1),trade(price='2501',ordinal=1)])


def test_indicator_scope_order_capacity_and_mixed_contracts():
    with pytest.raises(ValueError,match='mixed_contract'):metrics([trade(),trade(product='ES',ordinal=1)])
    with pytest.raises(ValueError,match='unordered'):metrics([trade(receive=NOW_NS-10**8),trade(ordinal=1)])
    with pytest.raises(ValueError,match='capacity'):metrics([trade(),trade(ordinal=1)],capacity=1)
    with pytest.raises(ValueError,match='outside'):metrics([trade(receive=NOW_NS-3*10**9)])
    assert metrics([])['status']=='UNAVAILABLE'


def test_profile_poc_tie_and_executed_vwap():
    result=metrics([trade(price='2500',size=2),trade(price='2502',size=2,side=dbn.Side.ASK,ordinal=1)])
    assert result['vwap']=='2501' and result['point_of_control']=='2500'
    assert result['cvd']==0 and result['buy_contracts']==result['sell_contracts']==2


def test_book_metrics_never_become_executions():
    q=quote(contract())
    result=book_indicator(q)
    assert result['executed_volume'] is None and result['institutional_intent'] is None
    assert result['visible_bid_quantity']==10 and result['visible_ask_quantity']==12
    with pytest.raises(ValueError):replace(q,payload=(('2519.2',10,1,'2519.0',12,1),))
    with pytest.raises(ValueError):replace(q,payload=((None,10,1,'2519.2',12,1),))


def candles():
    c=contract();output=[]
    end=NOW_NS//(60*10**9)*(60*10**9)
    for i in range(3):
        t=end-(3-i)*60*10**9;p=(2500+i)*10**9
        row=dbn.OHLCVMsg(rtype=dbn.RType.OHLCV_1M,publisher_id=1,instrument_id=c.metadata.instrument_id,
            ts_event=t,open=p,high=p+10**9,low=p-10**9,close=p,volume=10)
        output.append(observation(row,schema='ohlcv-1m',contract=c,archive_sha256=digest('OHLCV'),ordinal=i,
            retrieval_ns=NOW_NS,admission_ns=NOW_NS,evidence_kind='ENGINEERING_SYNTHETIC',enabled_schemas=ENABLED))
    return output,end


def test_candle_precision_receive_null_and_contiguous_volatility():
    values,end=candles()
    assert values[0].receive_ns is None and values[0].payload[2]==2500*10**9
    result=volatility(values,start_ns=end-3*60*10**9,end_ns=end,session_reference='ENGINEERING_SESSION')
    assert result['status']=='PARTIAL' and not result['annualized']
    assert volatility([values[0],values[2]],start_ns=end-3*60*10**9,end_ns=end,
                      session_reference='ENGINEERING_SESSION')['status']=='UNAVAILABLE'


def oi(*,offset=0,quantity=100):
    c=contract();received=NOW_NS-(2-offset)*3600*10**9
    row=dbn.StatMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,ts_event=received-1,ts_recv=received,
        ts_ref=NOW_NS-(2-offset)*86400*10**9,price=2**63-1,quantity=quantity,
        stat_type=dbn.StatType.OPEN_INTEREST,sequence=1,update_action=dbn.StatUpdateAction.NEW,channel_id=1)
    return observation(row,schema='statistics',contract=c,archive_sha256=digest('OI'),ordinal=offset,
        retrieval_ns=NOW_NS,admission_ns=NOW_NS,evidence_kind='ENGINEERING_SYNTHETIC',enabled_schemas=ENABLED)


def test_published_oi_change_preserves_reference_publication_and_availability():
    first,second=oi(),oi(offset=1,quantity=110)
    result=open_interest_change(first,second,cutoff_ns=NOW_NS)
    assert result['change_contracts']==10 and result['signed_dealer_position'] is None
    with pytest.raises(ValueError):open_interest_change(first,second,cutoff_ns=NOW_NS-1)
    with pytest.raises(ValueError):open_interest_change(second,first,cutoff_ns=NOW_NS)


def mapper(product='GC'):
    c=contract(product)
    return ContextMapper(contract=c,broker_instrument={'GC':'XAU/USD','ES':'US500.cash','NQ':'US100.cash'}[product],
                         policy=MappingPolicy('ENGINEERING_REVIEWED_POLICY'))


def pair(m,ordinal=1,**kwargs):
    t=NOW_NS-(6-ordinal)*10**9
    q=quote(m.contract,receive_ns=t,ordinal=ordinal)
    midpoint=Decimal(q.payload[0][0])
    b=BrokerQuote(m.broker_instrument,'ENGINEERING_FIXTURE','USD',midpoint-1,midpoint-Decimal('.8'),
                  t,t,t+1,digest(ordinal),'ENGINEERING_SYNTHETIC',m.contract.price_unit)
    b=replace(b,**kwargs)
    return q,b


def add(m,q,b):
    m.add(q,b,now_ns=NOW_NS,session_start_ns=NOW_NS-3600*10**9,
          session_end_ns=NOW_NS+3600*10**9,session_reference='ENGINEERING_SESSION')


@pytest.mark.parametrize('product',['GC','ES','NQ'])
def test_context_mapping_with_explicit_economic_policy(product):
    m=mapper(product)
    assert m.estimate(now_ns=NOW_NS)['status']=='MAPPING_UNAVAILABLE'
    for i in range(1,6):add(m,*pair(m,i))
    result=m.estimate(now_ns=NOW_NS,futures_level=str(Decimal(pair(m)[0].payload[0][0])+5))
    assert result['status']=='MAPPING_CONTEXT_ESTIMATE' and result['stable']
    assert result['context_only'] and not result['execution_price_authority']
    assert Decimal(result['uncertainty'])>0 and result['expiration_ns']>NOW_NS
    assert m.estimate(now_ns=NOW_NS+31*10**9)['status']=='MAPPING_UNAVAILABLE'


@pytest.mark.parametrize('fault',['skew','unit','identity','duplicate','closed','future','mixed_kind','provider'])
def test_mapping_rejects_and_quarantines_prior_samples(fault):
    m=mapper()
    for i in range(1,6):add(m,*pair(m,i))
    q,b=pair(m,5)
    kwargs={}
    if fault=='skew':b=replace(b,event_ns=b.event_ns-2*10**9)
    if fault=='unit':b=replace(b,price_unit='INDEX_POINT')
    if fault=='identity':b=replace(b,instrument='US100.cash')
    if fault=='mixed_kind':b=replace(b,evidence_kind='AUTHENTIC_ARCHIVED_RECORD')
    if fault=='provider':b=replace(b,provider='DIFFERENT_BROKER_VENUE')
    if fault=='closed':kwargs['session_end_ns']=NOW_NS
    if fault=='future':kwargs['now_ns']=q.receive_ns-1
    parameters=dict(now_ns=NOW_NS,session_start_ns=NOW_NS-3600*10**9,
                    session_end_ns=NOW_NS+3600*10**9,session_reference='ENGINEERING_SESSION')
    parameters.update(kwargs)
    with pytest.raises(ValueError):m.add(q,b,**parameters)
    assert not m.sources and m.estimate(now_ns=NOW_NS)['status']=='MAPPING_UNAVAILABLE'


def test_mapping_contract_roll_never_reuses_an_old_basis():
    m=mapper()
    for i in range(1,6):add(m,*pair(m,i))
    q,b=pair(m,5)
    next_contract=replace(m.contract,metadata=replace(m.contract.metadata,raw_symbol='GCG7',
        instrument_id=50000,maturity_year=2027,maturity_month=2))
    q=replace(q,contract=next_contract)
    with pytest.raises(ValueError):add(m,q,b)
    assert m.estimate(now_ns=NOW_NS)['status']=='MAPPING_UNAVAILABLE'


def test_american_options_iv_is_not_gamma_or_signed_dealer_gex():
    result=options_fixture()
    assert .1<result['iv']<.3 and result['greeks'] is None and result['unsigned_gamma_1pct'] is None
    assert result['signed_dealer_gex'] is None and result['gamma_flip'] is None
    assert result['evidence_kind']=='ENGINEERING_SYNTHETIC' and not result['gil_enabled']


def test_unsigned_european_gamma_is_a_model_benchmark_with_declared_units():
    params=dict(future=5000,strike=5000,years=30/365,rate=.04,volatility=.2,
        open_interest=100,multiplier=50,convention_reference='ENGINEERING_EUROPEAN',input_sha256=digest('model'))
    call=unsigned_european_sensitivity(kind='C',**params)
    put=unsigned_european_sensitivity(kind='P',**params)
    assert Decimal(call['unsigned_gamma_1pct'])>0 and call['unsigned_gamma_1pct']==put['unsigned_gamma_1pct']
    assert call['gamma_flip'] is None and not call['complete_chain'] and not call['gil_enabled']
    with pytest.raises(ValueError):OptionConvention('OG','European',digest('x'),'wrong_style')


@pytest.mark.parametrize('short,decision',[(False,'LONG'),(True,'SHORT')])
def test_actual_gold_fixture_path_remains_non_executable(short,decision):
    e=candle_evidence(short=short)
    result=asyncio.run(broker_preview(asset='GC',instrument='XAU/USD',now_ns=NOW_NS,evidence=e))
    assert result.decision==decision and 'GoldLayerEvaluator' in result.canonical_path
    assert result.reward_risk and result.structural_stop and result.expiration_ns>NOW_NS
    assert result.evidence_kind=='ENGINEERING_SYNTHETIC'
    assert not any((result.execution_eligible,result.publication_eligible,result.approval_eligible,result.gil_enabled))


@pytest.mark.parametrize('asset,instrument',[('ES','US500.cash'),('NQ','US100.cash')])
def test_index_fixture_uses_index_hierarchy_and_required_positioning(asset,instrument):
    e=candle_evidence(asset)
    result=asyncio.run(broker_preview(asset=asset,instrument=instrument,now_ns=NOW_NS,evidence=e,positioning=positioning(asset)))
    assert 'AssetHierarchyAnalysis/HierarchyLayerEvaluator' in result.canonical_path
    assert 'GoldLayerEvaluator' not in result.canonical_path and not result.execution_eligible
    missing=asyncio.run(broker_preview(asset=asset,instrument=instrument,now_ns=NOW_NS,evidence=e))
    assert missing.decision=='INSUFFICIENT_MARKET_DATA'


@pytest.mark.parametrize('fault',['missing','stale','wrong_identity','future_confirmation'])
def test_gold_input_rejections(fault):
    e=candle_evidence()
    if fault=='missing':e=replace(e,timeframes_json='{}')
    if fault=='stale':
        frames=json.loads(e.timeframes_json)
        frames['4h']=frames['4h'][:-2]  # Beyond canonical five-hour context lifetime.
        e=replace(e,timeframes_json=json.dumps(frames))
    if fault=='wrong_identity':e=replace(e,instrument='GCZ6')
    if fault=='future_confirmation':e=replace(e,confirmation_ns=NOW_NS+1)
    result=asyncio.run(broker_preview(asset='GC',instrument='XAU/USD',now_ns=NOW_NS,evidence=e))
    assert result.decision not in {'LONG','SHORT'} and result.rejection_reasons


def test_native_crypto_pipeline_preserves_derivatives_and_decision_policy():
    result=crypto_preview(asset='BTC',now_ns=NOW_NS,evidence=candle_evidence('BTC'),
        derivatives={'cvd_delta':123.,'funding_rate':.0001,'open_interest_change_pct':2.,'order_book_imbalance':.1})
    assert 'decision' in result['analytical_stages'] and 'order_flow' in result['analytical_stages']
    assert result['preview']['canonical_path']=='build_production_analysis_run/canonical_registrations/DecisionEngine'
    assert 'CoinGlass' not in result['preview']['broker_instrument'] and result['preview']['broker_instrument']=='BTC'
    assert not result['execution_eligible'] and result['preview']['decision']=='NO_TRADE'
    assert result['price_kind']=='reference'
    wrong=crypto_preview(asset='BTC',now_ns=NOW_NS,evidence=candle_evidence('GC'))
    assert wrong['preview']['decision']=='INSUFFICIENT_MARKET_DATA'


def test_unavailable_results_are_explicit_and_not_fake_broker_prices():
    for asset,symbol in [('GC','XAU/USD'),('ES','US500.cash'),('NQ','US100.cash')]:
        result=asyncio.run(broker_preview(asset=asset,instrument=symbol,now_ns=NOW_NS))
        assert result.decision=='INSUFFICIENT_MARKET_DATA' and result.proposed_entry is None
        assert result.mapping_status=='NOT_EVALUATED'
        assert 'verified_broker_candles_unavailable' in result.rejection_reasons
    assert crypto_preview(asset='BTC',now_ns=NOW_NS)['preview']['decision']=='INSUFFICIENT_MARKET_DATA'


def test_preview_cannot_claim_execution_or_expired_qualification():
    e=candle_evidence()
    result=asyncio.run(broker_preview(asset='GC',instrument='XAU/USD',now_ns=NOW_NS,evidence=e))
    with pytest.raises(ValueError):replace(result,execution_eligible=True)
    with pytest.raises(ValueError):replace(result,publication_eligible=True)
    with pytest.raises(ValueError):replace(result,expiration_ns=NOW_NS)


def test_numeric_credit_ceiling_receipts_and_exact_identity_remain_required():
    plan=acquisition_proposals()
    assert plan['numeric_credit_only_ceiling'] is None and not plan['acquisition_enabled']
    assert not plan['cash_authorized'] and plan['provider_estimates'] is None
    assert all(r['instrument_id'] is None and r['publisher_id'] is None for r in plan['requests'])


def test_guard_denies_network_process_credentials_execution_and_publishing(tmp_path):
    root=Path(__file__).resolve().parents[2]
    secret=tmp_path/'private.key';secret.write_text('fixture-only-secret')
    script="""
import sys, pathlib, json
sys.path.insert(0,sys.argv[1])
from monatise.research.institutional.isolation import install_guard
install_guard(read_roots=(pathlib.Path(sys.argv[1]),pathlib.Path(sys.prefix),pathlib.Path(sys.base_prefix),pathlib.Path(sys.argv[2])),output=pathlib.Path(sys.argv[2])/'output.json')
import socket,subprocess,importlib
checks={}
for name,action in [('network',lambda:socket.socket()),('process',lambda:subprocess.run(['true'])),('secret',lambda:open(pathlib.Path(sys.argv[2])/'private.key')),('broker',lambda:importlib.import_module('monatise.application.ftmo_master')),('telegram',lambda:importlib.import_module('monatise.application.trade_publication'))]:
 try:action();checks[name]=False
 except PermissionError:checks[name]=True
print(json.dumps(checks,sort_keys=True))
"""
    completed=subprocess.run([sys.executable,'-I','-c',script,str(root),str(tmp_path)],capture_output=True,text=True,check=True)
    assert all(json.loads(completed.stdout).values())


def test_isolated_repeat_and_environment_stripping(tmp_path,monkeypatch):
    monkeypatch.setenv('DATABENTO_API_KEY','fixture-secret-never-read')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','fixture-publisher-secret')
    summary=run(output=tmp_path/'repeat')
    assert summary['repeat_equal'] and summary['actual_downloads']==0
    assert summary['engineering_preview_status']['GC']=='LONG'
    text=(tmp_path/'repeat/preview-01.json').read_text()
    assert 'fixture-secret' not in text and 'fixture-publisher-secret' not in text
    assert not summary['execution_eligible'] and not summary['production_registration']
