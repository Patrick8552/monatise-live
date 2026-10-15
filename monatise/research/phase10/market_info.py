"""Native futures facts from validated data; no crypto engines or qualification.

One-hour bars are ordinary data. No frozen selector, two-hour selector lifetime,
GIL, gamma, dealer positioning, signal, or order decision is evaluated here.
"""
from decimal import Decimal

from monatise.research.databento.candles import WIDTHS
from monatise.research.institutional.indicators import trade_indicators
from monatise.research.institutional.models import digest, encode
from monatise.research.phase9.availability import inherited_policy
from monatise.research.phase9.candles import aggregate_complete
from monatise.research.phase9.lineage import verify_bar_lineage
from .access import AnalysisRequest
from .diagnostics import second_intervals

SAFETY = dict(execution_eligible=False, orders_placed=0, production_registered=False)


class FuturesMarketInfo:
    def __init__(self, pipeline, *, source_health):
        self.pipeline, self.source_health = pipeline, source_health

    def _frames(self, iid, now):
        # Warm-up joins retain their independent quality checks and provenance.
        wrapped = self.pipeline
        p = getattr(wrapped, 'pipeline', wrapped)
        gate = p.gates[iid]
        frames = {tf: tuple(b for _, b in sorted(rows.items())
            if b.close_ns+10*10**9 <= now and b.retrieval_ns <= now)
            for tf, rows in p.bars[iid].items()}
        calendar = p.calendars[iid]
        history_status = None
        if hasattr(wrapped, 'history'):
            from .history import join_minutes, complete_parents, _CombinedGate
            h = wrapped.history
            historical = h['gates'][iid]
            history_status = dict(status='REJECTED_OR_NOT_AVAILABLE', faults=dict(historical.faults),
                live_soak_gap_repaired=False)
            if not historical.faults and now >= h['available_ns']:
                minutes = join_minutes(h['bars'][iid], frames.get('1m', ()))
                frames['1m'] = tuple(b for b in minutes if b.close_ns+10*10**9 <= now and b.retrieval_ns <= now)
                calendar = h['calendars'][iid]
                gate = _CombinedGate(gate, historical)
                for tf in ('5m','15m','1h','4h'):
                    frames[tf], _ = complete_parents(frames['1m'], tf, calendar)
                history_status = dict(status='VERIFIED_SEPARATE_ANALYTICAL_HISTORY', live_soak_gap_repaired=False)
        frames = {tf: rows for tf, rows in frames.items() if rows}
        for tf in ('5s','1m','5m','15m','1h','4h'):
            if tf in frames:
                continue
            smaller = [s for s in frames if WIDTHS[s] < WIDTHS[tf] and WIDTHS[tf] % WIDTHS[s] == 0]
            if smaller:
                parents, _ = aggregate_complete(frames[max(smaller, key=lambda s:WIDTHS[s])], target=tf, calendar=calendar)
                if parents:
                    frames[tf] = parents
        return p, gate, frames, calendar, history_status

    def _instrument(self, iid, request, health):
        p, gate, frames, calendar, history = self._frames(iid, request.cutoff_ns)
        c = gate.contract
        if c.asset_class != 'futures' or c.metadata.product not in {'GC','ES','NQ'}:
            raise ValueError('reviewed_native_futures_contract_required')
        parts = {}
        for tf in request.timeframes:
            rows = frames.get(tf, ())
            try:
                if not rows:
                    raise ValueError('insufficient_validated_history')
                verify_bar_lineage(gate, rows, reviewed_history=history is not None)
                if any(not calendar.contains(b.open_ns,b.close_ns) for b in rows):
                    raise ValueError('bar_outside_reviewed_session')
                hashes = {h for b in rows for h in b.source_hashes}
                schemas = {v.schema for v in gate.lineage_observations() if v.source.record_sha256 in hashes}
                if any(s in gate.faults for s in schemas):
                    raise ValueError('source_schema_requires_quality_review')
                gaps = sum(a.close_ns != b.open_ns for a,b in zip(rows,rows[1:]))
                scale = Decimal(10**9)
                parts['price:'+tf] = dict(available=True, timeframe=tf, validated_candle_count=len(rows),
                    session_statistics=dict(open=str(Decimal(rows[0].prices_fixed[0])/scale),
                        high=str(Decimal(max(b.prices_fixed[1] for b in rows))/scale),
                        low=str(Decimal(min(b.prices_fixed[2] for b in rows))/scale),
                        close=str(Decimal(rows[-1].prices_fixed[3])/scale),
                        volume_contracts=sum(b.volume for b in rows)),
                    start_ns=rows[0].open_ns,end_ns=rows[-1].close_ns,
                    age_ns=request.cutoff_ns-rows[-1].close_ns,
                    gaps_between_observed_buckets=gaps, coverage='OBSERVED_VALIDATED_BUCKETS; NO_GAP_FILLING',
                    source_sha256=digest(rows), selector_applied=False, fixed_selector_expiry_applied=False)
            except (ValueError,TypeError,ArithmeticError) as exc:
                parts['price:'+tf] = dict(available=False,reason=str(exc))
        policy = inherited_policy(c,'trades')
        trade_health = gate.health(now_ns=request.cutoff_ns,policies={'trades':policy},schemas=('trades',))['trades']
        if trade_health['available']:
            values = [v for v in gate.accepted if v.schema == 'trades' and v.source.admission_ns <= request.cutoff_ns]
            metrics = trade_indicators(values,start_ns=min(v.receive_ns for v in values),
                end_ns=max(v.receive_ns for v in values)+1, session_reference=calendar.sha256)
            parts['trade_features'] = dict(available=True,result=metrics,health=trade_health)
        else:
            parts['trade_features'] = dict(trade_health)
        parts.update({k:dict(available=False,reason='not_captured_or_not_validated') for k in ('mbp-1','mbp-10','oi_change')})
        available = [k for k,v in parts.items() if v['available']]
        state = 'PARTIAL_MARKET_INFORMATION' if available else 'UNAVAILABLE'
        if health.get('quarantined') or health.get('stale_checkpoint'):
            state = 'UNAVAILABLE'
        result = dict(instrument=c.metadata.raw_symbol, availability=state,components=parts,
            capture_health=health,analysis_access='READ_ONLY',live_analysis_certified=False,
            information_scope='RETAINED_VALIDATED_CAPTURE_WINDOW',
            participant_identity='UNAVAILABLE_ANONYMOUS_EXCHANGE_DATA',
            crypto_engines_used=False, frozen_H1_selector_used=False, GIL_rules_used=False,
            trade_signal_produced=False, complete_exchange_continuity_certified=False, **SAFETY)
        if history is not None:
            result['history_warmup'] = history
        result['seconds_bar_diagnostics'] = second_intervals(p.gates[iid],cutoff_ns=request.cutoff_ns,
            watermark_ns=health.get('interval_watermarks',{}).get('ohlcv-1s'),
            source_unreliable=bool(health.get('quarantined') or health.get('stale_checkpoint')))
        result['reproducibility_sha256'] = digest(result)
        return result

    def analyse(self, request):
        if not isinstance(request,AnalysisRequest):
            raise ValueError('typed_analysis_request_required')
        health = self.source_health(request.cutoff_ns)
        known = {g.contract.metadata.raw_symbol:i for i,g in self.pipeline.gates.items()}
        outputs = {}
        for symbol in request.symbols:
            if symbol not in known:
                outputs[symbol] = dict(availability='UNAVAILABLE',reason='exact_contract_not_loaded',**SAFETY)
                continue
            try:
                outputs[symbol] = self._instrument(known[symbol],request,health)
            except (ValueError,TypeError,KeyError,ArithmeticError) as exc:
                outputs[symbol] = dict(availability='UNAVAILABLE',reason=str(exc),**SAFETY)
        result = dict(version='native-futures-market-information-v1',request=encode(request),instruments=outputs,
            analysis_access='READ_ONLY',crypto_engines_used=False,frozen_H1_selector_used=False,GIL_rules_used=False,
            trade_signal_produced=False, **SAFETY)
        result['reproducibility_sha256'] = digest(result)
        return result
