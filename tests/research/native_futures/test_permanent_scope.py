"""Permanent futures routing/retirement; no network, broker or source mutation."""
import asyncio,ast,importlib
from pathlib import Path
from types import SimpleNamespace
import pytest
from monatise.engines.asset_scope import require_canonical_non_futures


@pytest.mark.parametrize('symbol',['GC','ES','NQ','GCZ6','ESZ2026','NQH7','ES.v.0','GC.FUT','CME_MINI:ESZ2026','COMEX:GC1!','NQ=F'])
def test_canonical_scope_rejects_futures_symbols(symbol):
    with pytest.raises(ValueError,match='dedicated_native'):require_canonical_non_futures(symbol)


@pytest.mark.parametrize('symbol',['BTCUSDT','ETH','SOL','AAPL','XAU/USD'])
def test_other_asset_routes_are_not_reclassified(symbol):
    require_canonical_non_futures(symbol)


@pytest.mark.parametrize('package,klass',[
 ('regime','RegimeEngine'),('liquidity','LiquidityEngine'),('liquidity_sweep','LiquiditySweepEngine'),
 ('supply_demand','SupplyDemandEngine'),('reclaim','ReclaimEngine'),('market_structure','MarketStructureEngine'),
 ('fibonacci_liquidity','FibonacciLiquidityEngine')])
def test_every_canonical_candle_engine_rejects_futures_before_calculation(package,klass):
    engine=getattr(importlib.import_module('monatise.engines.'+package),klass)()
    with pytest.raises(ValueError,match='dedicated_native'):
        engine.assess(SimpleNamespace(validate=lambda:None,market=SimpleNamespace(symbol='ESZ6')))


@pytest.mark.parametrize('asset,symbol',[('GC','XAU/USD'),('ES','US500.cash'),('NQ','US100.cash')])
def test_legacy_broker_preview_reports_retired_without_touching_candles(asset,symbol):
    from monatise.research.institutional.signals import broker_preview
    class Never:
        def rows(self,**kwargs):pytest.fail('retired canonical data/engine path called')
    output=asyncio.run(broker_preview(asset=asset,instrument=symbol,now_ns=1792125366000000000,
        evidence=Never(),include_canonical=True))
    assert output['canonical'] is None and output['preview']['canonical_path']=='RETIRED_FUTURES_ROUTE'


def test_selector_executables_and_gil_rule_module_are_deleted():
    root=Path(__file__).resolve().parents[3]
    paths=('monatise/research/institutional/phase7/gil.py','monatise/research/gc_qualification/worker.py',
        'monatise/research/gc_qualification/bootstrap.py','monatise/research/gc_fib/bootstrap.py',
        'monatise/research/institutional/phase8/spot_worker.py','monatise/research/institutional/phase8/spot_bootstrap.py')
    assert all(not (root/name).exists() for name in paths)
    for p in (root/'monatise').rglob('*.py'):
        text=p.read_text()
        assert 'GoldH1StructuralLegSelector' not in text and 'H1StructuralEpisodeAdapter' not in text
        assert 'from .gil import' not in text


def test_default_and_compatibility_native_modules_have_no_canonical_engine_imports():
    root=Path(__file__).resolve().parents[3]
    for relative in ('monatise/research/phase9/coordinator.py','monatise/research/phase10/market_info.py','monatise/research/native_futures/analysis.py'):
        tree=ast.parse((root/relative).read_text())
        assert not [n for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and (n.module or '').startswith('monatise.engines.')]


@pytest.mark.parametrize('product',['GC','ES','NQ'])
def test_native_request_never_calls_any_canonical_candle_engine(monkeypatch,product):
    from tests.research.phase9.test_pipeline import pipeline,trade,add,NOW_NS
    from monatise.research.phase10.market_info import FuturesMarketInfo
    from monatise.research.phase10.access import AnalysisRequest
    for package,klass in [('regime','RegimeEngine'),('liquidity','LiquidityEngine'),
        ('liquidity_sweep','LiquiditySweepEngine'),('supply_demand','SupplyDemandEngine'),
        ('reclaim','ReclaimEngine'),('market_structure','MarketStructureEngine'),
        ('fibonacci_liquidity','FibonacciLiquidityEngine')]:
        engine=getattr(importlib.import_module('monatise.engines.'+package),klass)
        monkeypatch.setattr(engine,'assess',lambda *a,**kw:pytest.fail('canonical engine called'))
    p,c=pipeline(product);assert add(p,trade(c))['accepted']
    result=FuturesMarketInfo(p,source_health=lambda now:{}).analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))
    assert result['instruments'][c.metadata.raw_symbol]['components']['trade_features']['available']
    assert not result['crypto_engines_used'] and not result['GIL_rules_used'] and not result['frozen_H1_selector_used']
