"""Native GC/ES/NQ context; canonical engines and frozen selector deleted."""
from datetime import UTC, datetime
from decimal import Decimal
import logging

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
    categories={b.evidence_kind for b in rows}
    authentic={'AUTHENTIC_HISTORICAL_DOWNLOAD','AUTHENTIC_LIVE_CAPTURE','MIXED_AUTHENTIC_HISTORY_AND_LIVE'}
    if len(categories)>1 and not (reviewed_history and categories<=authentic):
        raise ValueError('mixed_evidence_categories')
    omitted=[]
    for i,b in enumerate(rows):
        if (b.identity != contract.metadata or b.timeframe != tf or
                b.retrieval_ns > now_ns or b.close_ns > now_ns):
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
    timing=dict(source_ns=rows[-1].close_ns,available_ns=max(b.retrieval_ns for b in rows),
        age_ns=now_ns-rows[-1].close_ns,contextual_eligible=True,
        local_freshness_cutoff_applied=False,original_expiry_ns=None)
    from monatise.research.native_futures.analysis import analyse_frame
    native=analyse_frame(rows,tick_size=contract.tick_size,cutoff_ns=now_ns,calendar=calendar)
    scale=Decimal(10**9)
    return dict(available=True,freshness=timing,historical_only=not timing['contextual_eligible'],
        schema=rows[-1].schema,timeframe=tf,event_ns=rows[-1].open_ns,close_ns=rows[-1].close_ns,
        capture_ns=max(b.retrieval_ns for b in rows),validated_candle_count=len(rows),
        evidence_categories=sorted(categories),omitted_session_buckets=omitted,
        source_sha256=digest(rows),source_hashes=[h for b in rows for h in b.source_hashes],
        native_analysis=native,crypto_engines_used=False,selector_applied=False,
        session_statistics=dict(open=rows[0].prices_fixed[0]/scale,
            high=max(b.prices_fixed[1] for b in rows)/scale,low=min(b.prices_fixed[2] for b in rows)/scale,
            close=rows[-1].prices_fixed[3]/scale,volume_contracts=sum(b.volume for b in rows)),
        reference_price=rows[-1].prices_fixed[3]/scale,executable_quote=False,
        analysis_partial=not native['available'],**SAFETY)


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
            quote_is_optional_for_price_context=True,source_health=health,
            crypto_engines_used=False,frozen_H1_selector_used=False,GIL_rules_used=False)
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
