"""Synthetic policy/route tests; no market-data or order authority."""
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from monatise.application.gold_analysis import GoldLayerEvaluator
from monatise.application.gold_fibonacci import (
    RETRACEMENTS, EXTENSIONS, POLICY_ID, assess_gold_fibonacci, gold_layer_candidates,
)
from monatise.application.hierarchy.evaluator import HierarchyLayerEvaluator
from monatise.application.target_evidence import crypto_layer_candidates
from monatise.application.take_profit import MultiTPConfiguration, build_plan
from monatise.engines.fibonacci_liquidity import FibonacciRequest
from monatise.engines.market_structure.models import StructureBias, StructureState
from tests.engines.test_fibonacci_liquidity_engine import NOW, make_market, bullish_structure


def layer(*, timeframe="1h", symbol="XAU/USD", confidence=.85, confluence=True, short=False):
    zone=SimpleNamespace(lower_bound=90,upper_bound=300)
    obj=SimpleNamespace(market=replace(make_market(),symbol=symbol,interval=timeframe),
        structure=replace(bullish_structure(),symbol=symbol,confidence=confidence),
        liquidity=SimpleNamespace(buy_side_levels=(),sell_side_levels=()),
        zones=SimpleNamespace(supply_zones=(zone,) if confluence else (),demand_zones=()),reclaim=None)
    if short:
        obj.market=replace(obj.market,price=220-obj.market.price,candles=tuple(
            replace(c,open=220-c.open,high=220-c.low,low=220-c.high,close=220-c.close)
            for c in obj.market.candles))
        obj.structure=replace(obj.structure,bias=StructureBias.BEARISH,state=StructureState.BEARISH_CONTINUATION,
            swing_highs=tuple((i,220-p) for i,p in bullish_structure().swing_lows),
            swing_lows=tuple((i,220-p) for i,p in bullish_structure().swing_highs))
    return obj


def test_gold_profile_uses_enabled_default_levels_and_retains_anchor_gates():
    result=assess_gold_fibonacci(layer())
    assert result.has_valid_anchor
    assert {x.ratio for x in result.retracement_levels}=={.236,.382,.5,.618,.786}
    assert {x.ratio for x in result.extension_levels}=={1,1.618,2.618,3.618,4.236}
    assert result.metadata['gold_profile']['policy_id']==POLICY_ID
    assert not assess_gold_fibonacci(layer(confidence=.1)).has_valid_anchor


@pytest.mark.parametrize('short,a,b,retrace_price,extension_price',[
    (False,98,122,116.336,160.832),(True,122,98,103.664,59.168)])
def test_directional_prices_are_not_relabelled_as_exact_tradingview_chart_prices(short,a,b,retrace_price,extension_price):
    result=assess_gold_fibonacci(layer(short=short))
    anchor=result.primary_anchor
    assert anchor.start_price==a and anchor.end_price==b
    retrace=next(x for x in result.retracement_levels if x.ratio==.236)
    extended=next(x for x in result.extension_levels if x.ratio==2.618)
    assert retrace.price==pytest.approx(retrace_price)
    assert extended.price==pytest.approx(extension_price)
    assert not result.metadata['gold_profile']['exact_TradingView_prices_or_ZigZag_parity']


def test_gold_dispatch_and_h1_only_candidates_preserve_technical_obstacles():
    obj=layer();kwargs=dict(timeframe="1h",observed=NOW,provider="monatise_gold")
    gold=GoldLayerEvaluator(asset_route="gold")._target_candidates(obj,**kwargs)
    assert gold==gold_layer_candidates(obj,**kwargs)
    assert any(c.evidence_type=='GOLD_TV_FIB_EXT_2_618' for c in gold)
    assert any(c.evidence_type=='SUPPLY_ZONE' for c in gold)
    lower=GoldLayerEvaluator(asset_route="gold")._target_candidates(layer(timeframe="5m"),**{**kwargs,'timeframe':'5m'})
    assert lower and not any('FIB' in c.evidence_type for c in lower)


def test_new_distant_ratios_are_not_automatically_promoted_without_confluence():
    candidates=gold_layer_candidates(layer(confluence=False),timeframe="1h",observed=NOW)
    assert not any('GOLD_TV_FIB' in c.evidence_type for c in candidates)
    candidates=gold_layer_candidates(layer(confidence=.1),timeframe="1h",observed=NOW)
    assert not any('GOLD_TV_FIB' in c.evidence_type for c in candidates)


def test_non_gold_routes_and_shared_request_defaults_keep_existing_behavior():
    obj=layer(symbol="BTCUSDT");kwargs=dict(timeframe="1h",observed=NOW)
    assert HierarchyLayerEvaluator()._target_candidates(obj,**kwargs)==crypto_layer_candidates(obj,**kwargs)
    old=FibonacciRequest(obj.market,obj.structure)
    assert old.retracement_ratios==(.382,.5,.618,.705,.786,.886)
    assert old.extension_ratios==(1,1.272,1.414,1.618,2)
    with pytest.raises(ValueError,match='XAUUSD'):assess_gold_fibonacci(obj)
    with pytest.raises(ValueError,match='H1'):assess_gold_fibonacci(layer(timeframe="15m"))


def test_gold_advisory_assessments_use_same_ratios_without_lower_frame_target_authority():
    assessment=GoldLayerEvaluator(asset_route='gold')._fibonacci_assessment(layer(timeframe='15m'))
    assert {x.ratio for x in assessment.retracement_levels}==set(RETRACEMENTS)
    assert {x.ratio for x in assessment.extension_levels}==set(EXTENSIONS)
    assert not assessment.metadata['target_anchor_eligible_timeframe']


def test_far_default_extensions_cannot_hide_bad_nearest_objective_rr():
    candidates=gold_layer_candidates(layer(),timeframe='1h',observed=NOW)
    assert any(c.evidence_type=='GOLD_TV_FIB_EXT_2_618' for c in candidates)
    with pytest.raises(ValueError,match='cannot skip first objective'):
        build_plan(candidates=candidates,direction='long',entry=121.9,stop=120,
                   now=NOW,expires_at=NOW+timedelta(minutes=5),config=MultiTPConfiguration(enabled=True))
