"""Read-only default-behavior fingerprint, runnable against either source checkout.

No research modules are imported. INPUT is an artificial observation archive.
"""
import json
import sys
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import Enum

from monatise.application.gold_analysis import GoldLayerEvaluator, GoldPolicy
from monatise.application.hierarchy.candles import CandleBoundaryNormalizer
from monatise.application.hierarchy.coordinator import HierarchyConfiguration, TimeframeSnapshot
from monatise.application.hierarchy.models import Provenance
from monatise.application.hierarchy.risk import StructuralRiskInputBuilder
from monatise.application.target_evidence import crypto_layer_candidates
from monatise.core.models import Candle
from monatise.engines.fibonacci_liquidity import FibonacciLiquidityEngine, FibonacciRequest


def encode(x):
    if is_dataclass(x): return encode(asdict(x))
    if isinstance(x, datetime): return x.isoformat()
    if isinstance(x,Decimal): return str(x)
    if isinstance(x,Enum): return x.value
    if isinstance(x,dict): return {str(k):encode(v) for k,v in x.items()}
    if isinstance(x,(tuple,list)): return [encode(v) for v in x]
    return x


archive=json.load(open(sys.argv[1]))
normalizer=CandleBoundaryNormalizer()
hashes={}; known={}; snapshots={}
provenance=Provenance('ftmo_mt5_archive',archive['calendar']['server'],'XAU/USD',archive['source_version'],'hierarchy-candle-v1')
evaluator=GoldLayerEvaluator(configuration=HierarchyConfiguration(strategy_version=GoldPolicy().strategy),asset_route='gold')
evaluator.broker_units=archive['broker_units']
canonical=[];fib=[];candidates=[]
for obs in archive['observations']:
    now=datetime.fromisoformat(obs['at'])
    current={}
    for tf, raw in obs['candles'].items():
        series=normalizer.normalize_series([Candle(**r) for r in raw],symbol='XAU/USD',timeframe=tf,received_at=now,provenance=provenance,previous_hashes=hashes.get(tf,{}))
        hashes[tf]={c.candle_id:c.content_hash for c in series}
        rows=[]
        for c in series:
            if c.is_final:
                key=(c.candle_id,c.content_hash);known.setdefault(key,now)
                c=replace(c,received_at=known[key])
            rows.append(c)
        final=[c for c in rows if c.is_final]
        if final: current[tf]=TimeframeSnapshot('XAU/USD',tf,now,tuple(rows[-evaluator.configuration.candle_limit:]),final[-1])
    if obs.get('warmup_only'): continue
    result=evaluator.evaluate('XAU/USD',current,evaluated_at=now,macro_degraded=False)
    canonical.append(result)
    state=evaluator._state['XAU/USD']
    for tf,snap in state.snapshots.items():
        layer=evaluator._analyse_structure(snap,state.regime_assessment)
        fib.append(FibonacciLiquidityEngine().assess(FibonacciRequest(layer.market,layer.structure,liquidity=layer.liquidity,zones=layer.zones,reclaim=layer.reclaim)))
        candidates.append(crypto_layer_candidates(layer,timeframe=tf,observed=snap.latest_finalized.scheduled_close_time))
risks=[]
for side in ('long','short'):
    for atr in (0,.4,2):
        risks.append(StructuralRiskInputBuilder().build(direction=side,entry_zone_low=2499,entry_zone_high=2501,structural_invalidation=2490 if side=='long' else 2510,target_liquidity=2520 if side=='long' else 2480,atr=atr,movement_tolerance_pct=.002,expires_at=now))
print(json.dumps(encode({'canonical':canonical,'default_fibonacci':fib,'default_candidates':candidates,'risk':risks}),sort_keys=True,separators=(',',':'),allow_nan=False))
