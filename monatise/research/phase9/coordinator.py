"""Native GC/ES/NQ context using existing pure analytical engines; no CFD transport."""
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
import logging
from math import log, sqrt

from monatise.core.models import Candle
from monatise.engines.market_data import MarketSnapshot, DataQuality, DataStatus
from monatise.engines.regime import RegimeEngine, RegimeRequest
from monatise.engines.liquidity import LiquidityEngine, LiquidityRequest
from monatise.engines.liquidity_sweep import LiquiditySweepEngine, SweepRequest
from monatise.engines.supply_demand import SupplyDemandEngine, ZoneRequest
from monatise.engines.reclaim import ReclaimEngine, ReclaimRequest
from monatise.engines.market_structure import MarketStructureEngine, MarketStructureRequest
from monatise.engines.fibonacci_liquidity import FibonacciLiquidityEngine, FibonacciRequest
from monatise.research.databento.candles import WIDTHS
from monatise.research.institutional.indicators import trade_indicators, book_indicator, open_interest_change
from monatise.research.institutional.models import digest, encode
from .availability import envelope, inherited_policy
from . import SAFETY

LOGGER = logging.getLogger(__name__)


def instant(ns):
    seconds,nanos = divmod(ns,10**9)
    return datetime.fromtimestamp(seconds,UTC).replace(microsecond=nanos//1000)


def price_components(contract, bars, *, now_ns, calendar, policy=None, reviewed_history=False):
    rows = tuple(bars)
    if not rows: raise ValueError('no_validated_candles')
    tf = rows[0].timeframe; width = WIDTHS[tf]
    policy = policy or inherited_policy(contract,'candles',timeframe_ns=width)
    categories={b.evidence_kind for b in rows}
    authentic={'AUTHENTIC_HISTORICAL_DOWNLOAD','AUTHENTIC_LIVE_CAPTURE','MIXED_AUTHENTIC_HISTORY_AND_LIVE'}
    if len(categories)>1 and not (reviewed_history and categories<=authentic):
        raise ValueError('mixed_evidence_categories')
    omitted=[]
    for i,b in enumerate(rows):
        if (b.identity != contract.metadata or b.timeframe != tf or
                b.retrieval_ns > now_ns or b.close_ns+10*10**9 > now_ns):
            raise ValueError('mixed_revised_future_forming_or_noncontiguous_bars')
        if i and rows[i-1].close_ns!=b.open_ns:
            previous=rows[i-1].close_ns
            if not reviewed_history or previous>b.open_ns or (b.open_ns-previous)//width>10000:
                raise ValueError('mixed_revised_future_forming_or_noncontiguous_bars')
            for start in range(previous,b.open_ns,width):
                if calendar.contains(start,start+width):
                    raise ValueError('missing_bar_in_reviewed_trading_interval')
                omitted.append(dict(open_ns=start,reason='REVIEWED_CLOSED_OR_PARTIAL_SESSION_BUCKET'))
        if not calendar.contains(b.open_ns,b.close_ns): raise ValueError('bar_outside_reviewed_session')
    timing = policy.assess(source_ns=rows[-1].close_ns,available_ns=max(b.retrieval_ns for b in rows),
        now_ns=now_ns,expires_ns=contract.metadata.expiration_ns)
    cs = tuple(Candle(instant(b.open_ns).isoformat(),*(p/10**9 for p in b.prices_fixed),b.volume) for b in rows)
    market = MarketSnapshot(contract.metadata.raw_symbol,tf,cs[-1].close,cs,
        DataQuality(DataStatus.READY,'Databento_native_research',instant(now_ns),instant(rows[-1].close_ns),
                    (now_ns-rows[-1].close_ns)/10**9),metadata=dict(price_type='reference',executable_quote=False))
    # Execute the existing graph in dependency order. An unavailable downstream
    # component cannot erase already calculated upstream context.
    outputs,engine_health={},{}
    stages=(('regime',(),lambda:RegimeEngine().assess(RegimeRequest(market))),
        ('liquidity',('regime',),lambda:LiquidityEngine().assess(LiquidityRequest(market,outputs['regime']))),
        ('sweep',('liquidity','regime'),lambda:LiquiditySweepEngine().assess(SweepRequest(market,outputs['liquidity'],outputs['regime']))),
        ('zones',('regime','liquidity'),lambda:SupplyDemandEngine().assess(ZoneRequest(market,outputs['regime'],outputs['liquidity']))),
        ('reclaim',('sweep','regime','zones'),lambda:ReclaimEngine().assess(ReclaimRequest(market,outputs['sweep'],outputs['regime'],outputs['zones']))),
        ('structure',('regime','liquidity','sweep','reclaim','zones'),lambda:MarketStructureEngine().assess(MarketStructureRequest(
            market,outputs['regime'],outputs['liquidity'],outputs['sweep'],outputs['reclaim'],outputs['zones']))),
        ('fibonacci',('structure','liquidity','zones','reclaim'),lambda:FibonacciLiquidityEngine().assess(FibonacciRequest(
            market,outputs['structure'],outputs['liquidity'],outputs['zones'],outputs['reclaim']))))
    for name,dependencies,calculate in stages:
        missing=[d for d in dependencies if d not in outputs]
        if missing:
            engine_health[name]=dict(available=False,reason='upstream_component_unavailable',dependencies=missing)
            continue
        try:
            outputs[name]=calculate();engine_health[name]=dict(available=True)
        except Exception as exc:
            unexpected=not isinstance(exc,(ValueError,TypeError,ArithmeticError))
            if unexpected:LOGGER.error('Native analytical engine defect',extra={'engine':name,'error_type':type(exc).__name__},exc_info=False)
            engine_health[name]=dict(available=False,error_type=type(exc).__name__,unexpected_error=unexpected,reason='analytical_engine_defect' if unexpected else str(exc)[:160])
    prices = [c.close for c in cs]
    returns = [log(b/a) for a,b in zip(prices,prices[1:])]
    mean = sum(returns)/len(returns) if returns else None
    volatility = sqrt(sum((x-mean)**2 for x in returns)/(len(returns)-1)) if len(returns)>1 else None
    return dict(available=True, freshness=timing, historical_only=not timing['contextual_eligible'],
        schema=rows[-1].schema,timeframe=tf,event_ns=rows[-1].open_ns,close_ns=rows[-1].close_ns,
        capture_ns=max(b.retrieval_ns for b in rows),
        coverage='REVIEWED_COMPLETE_SESSION_BUCKETS_ONLY' if reviewed_history else 'CONTIGUOUS_CAPTURED_BARS_ONLY',
        validated_candle_count=len(rows),evidence_categories=sorted(categories),omitted_session_buckets=omitted,
        source_sha256=digest(rows),source_hashes=[h for b in rows for h in b.source_hashes],
        **{k:encode(v) for k,v in outputs.items()},engine_health=engine_health,
        analysis_partial=any(not v['available'] for v in engine_health.values()),
        session_statistics=dict(open=cs[0].open,high=max(c.high for c in cs),low=min(c.low for c in cs),
            close=cs[-1].close,volume_contracts=sum(c.volume for c in cs),
            scope='VALIDATED_HISTORY_AND_LIVE_SESSION_BUCKETS' if reviewed_history else 'CAPTURED_CONTIGUOUS_BARS'),
        volatility=dict(value=volatility,method='sample-stdev-log-close-returns',annualized=False),
        reference_price=market.price, executable_quote=False, original_expiry_ns=rows[-1].close_ns+2*width,
        frozen_H1_parent_qualified=False, **SAFETY)


from .lineage import verify_bar_lineage


class NativeFuturesCoordinator:
    def analyse(self, gate, *, bars_by_timeframe, calendar, now_ns, mandatory=('price:1h',), requested=(), reviewed_history=False):
        c = gate.contract
        if c.asset_class != 'futures' or c.metadata.product not in {'GC','ES','NQ'}:
            raise ValueError('reviewed_native_futures_contract_required')
        components = {}
        for tf, bars in bars_by_timeframe.items():
            try:
                # Bars must originate in the caller's validated gate. Historical
                # imports use ResearchPipeline.import_bars, which screens prices.
                verify_bar_lineage(gate,bars,reviewed_history=reviewed_history)
                known = {v.source.record_sha256 for v in gate.lineage_observations()}
                if any(h not in known for b in bars for h in b.source_hashes):
                    raise ValueError('bar_sources_not_admitted_by_quality_gate')
                bar_hashes = {h for b in bars for h in b.source_hashes}
                schema_faults = {v.schema for v in gate.lineage_observations() if v.source.record_sha256 in bar_hashes}
                if any(s in gate.faults and any(b.close_ns>gate.fault_event_ns.get(s,0) for b in bars) for s in schema_faults):
                    raise ValueError('source_schema_requires_quality_review')
                components['price:'+tf] = price_components(c,bars,now_ns=now_ns,calendar=calendar,reviewed_history=reviewed_history)
            except (ValueError,TypeError,ArithmeticError) as exc:
                components['price:'+tf] = dict(available=False,reason=str(exc),error_type=type(exc).__name__)
        policies = {s:inherited_policy(c,'book' if s.startswith('mbp-') else 'open_interest' if s=='statistics' else 'trades')
                    for s in ('trades','mbp-1','mbp-10','statistics')}
        health = gate.health(now_ns=now_ns,policies=policies,schemas=tuple(policies))
        for schema in ('trades','mbp-1','mbp-10','statistics'):
            key = 'trade_features' if schema=='trades' else 'oi_change' if schema=='statistics' else schema
            if not health[schema]['available']:
                components[key] = dict(health[schema]);continue
            values = [v for v in gate.accepted if v.schema==schema and v.source.admission_ns <= now_ns]
            try:
                if schema=='trades':
                    start,end = min(v.receive_ns for v in values),max(v.receive_ns for v in values)+1
                    result = trade_indicators(values,start_ns=start,end_ns=end,session_reference=calendar.sha256)
                elif schema=='statistics':
                    if len(values)<2: raise ValueError('two_distinct_published_OI_periods_required')
                    result = open_interest_change(values[-2],values[-1],cutoff_ns=now_ns)
                else: result = book_indicator(values[-1])
                components[key] = dict(available=True,result=result,health=health[schema])
            except (ValueError,TypeError,ArithmeticError) as exc:
                components[key] = dict(available=False,reason=str(exc),error_type=type(exc).__name__)
        contextual_scope = any(components.get(k,{}).get('historical_only') or components.get(k,{}).get('analysis_partial') for k in mandatory)
        result = envelope(c,components,mandatory=mandatory,requested=requested,now_ns=now_ns,context_only=contextual_scope)
        result.update(basis_status='NOT_APPLICABLE',analysis_instrument=c.metadata.raw_symbol,
            price_namespace=c.metadata.namespace,positioning_qualification='NOT_EVALUATED',
            GIL_qualification='UNAVAILABLE_SEPARATE_PROVIDER_HIERARCHY', quote_is_optional_for_price_context=True,
            source_health=health, frozen_selector_modified=False)
        result['reproducibility_sha256'] = digest({k:v for k,v in result.items() if k!='reproducibility_sha256'})
        return result

    def scan(self, requests):
        """Every request is isolated; unexpected errors are explicit and logged."""
        result = []
        for request in requests:
            try: result.append(self.analyse(**request))
            except Exception as exc:
                LOGGER.exception('Phase 9 analytical instrument failed')
                result.append(dict(availability='UNAVAILABLE',instrument=request['gate'].contract.metadata.raw_symbol,
                    error_type=type(exc).__name__,unexpected_error=not isinstance(exc,(OSError,ValueError,TypeError,ArithmeticError)),
                    decision='NO_TRADE',qualification_status='FAILED',**SAFETY))
        return result
