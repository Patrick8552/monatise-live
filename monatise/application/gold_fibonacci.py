"""Gold-only user-selected TradingView default ratios; no chart-anchor parity.

The visible Auto Fib settings supply ratios, not qualified structural anchors.
Prices retain Monatise's directional retracement/continuation conventions.
"""
from dataclasses import replace

from monatise.application.target_evidence import candidate, crypto_layer_candidates
from monatise.engines.fibonacci_liquidity import FibonacciLiquidityEngine, FibonacciRequest


POLICY_ID = "gold-tradingview-default-ratios-v1"
RETRACEMENTS = (0.236, 0.382, 0.5, 0.618, 0.786)
EXTENSIONS = (1.0, 1.618, 2.618, 3.618, 4.236)
ENABLED_CHART_LEVELS = (0.0, *RETRACEMENTS, *EXTENSIONS)
PROFILE = {
    "policy_id": POLICY_ID,
    "source": "Safari TradingView built-in Auto fib retracement defaults, observed 2026-10-14",
    "retracement_ratios": RETRACEMENTS,
    "extension_ratios": EXTENSIONS,
    "enabled_chart_levels": ENABLED_CHART_LEVELS,
    "chart_settings": {"deviation": 3, "depth": 10, "reverse": False},
    "price_geometry": "Monatise structural retracement and directional continuation",
    "exact_TradingView_prices_or_ZigZag_parity": False,
    "anchor_timeframe": "1h",
    "targets_require_confluence_and_existing_plan_checks": True,
}


def _gold_symbol(symbol):
    return symbol.upper().replace("/", "") in {"XAUUSD", "FX:XAUUSD"}


def assess_gold_fibonacci(layer, *, require_h1=True):
    if not _gold_symbol(layer.market.symbol) or (require_h1 and layer.market.interval != "1h"):
        raise ValueError("Gold Fibonacci requires an XAUUSD H1 structural layer")
    assessment = FibonacciLiquidityEngine().assess(FibonacciRequest(
        layer.market, layer.structure, liquidity=layer.liquidity, zones=layer.zones,
        reclaim=layer.reclaim, retracement_ratios=RETRACEMENTS,
        extension_ratios=EXTENSIONS, deep_retracement_ratio=0.786,
    ))
    return replace(assessment, metadata={**assessment.metadata, "gold_profile": PROFILE,
        "assessment_timeframe": layer.market.interval,
        "target_anchor_eligible_timeframe": layer.market.interval == "1h"})


def gold_layer_candidates(layer, *, timeframe, observed, provider="monatise_gold"):
    """Keep nearer technical objectives; only H1 supplies Gold Fib candidates.

The existing TP builder decides direction, distance, freshness, RR, merging and
allocation. Larger ratios are never granted new confluence solely by this policy.
"""
    if not _gold_symbol(layer.market.symbol):
        raise ValueError("Gold target policy requires XAUUSD")
    result = crypto_layer_candidates(layer, timeframe=timeframe, observed=observed,
                                     provider=provider, include_fibonacci=False)
    if timeframe != "1h":
        return result
    fib = assess_gold_fibonacci(layer)
    if not fib.has_valid_anchor:
        return result
    for category, levels in (("RETRACE", fib.retracement_levels), ("EXT", fib.extension_levels)):
        for level in levels:
            if not (level.liquidity_confluence or level.zone_confluence or level.structure_confluence):
                continue
            result.append(candidate(level.price, provider=provider,
                kind="GOLD_TV_FIB_" + category + "_" + str(level.ratio).replace(".", "_"),
                timeframe=timeframe, observed=observed,
                confidence=str(min(1, fib.primary_anchor.structure_confidence))))
    return result
