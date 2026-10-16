"""Native futures facts from validated data; no crypto engines or qualification.

One-hour bars are ordinary data. No frozen selector, two-hour selector lifetime,
GIL, gamma, dealer positioning, signal, or order decision is evaluated here.
"""
from decimal import Decimal

from monatise.research.databento.candles import WIDTHS
from monatise.research.institutional.indicators import trade_indicators,book_indicator,open_interest_change,encode_source
from monatise.research.institutional.models import digest, encode
from monatise.research.phase9.availability import inherited_policy
from monatise.research.phase9.candles import aggregate_complete
from monatise.research.phase9.lineage import verify_bar_lineage
from .access import AnalysisRequest
from monatise.research.native_futures.analysis import analyse_frame, alignment
from .diagnostics import second_intervals
from monatise.research.databento.semantics import VERSION as NORMALIZATION_VERSION

SAFETY = dict(execution_eligible=False, orders_placed=0, production_registered=False, XAUUSD_signal_router_used=False)


def quarantine_scope(health, iid):
    """Keep global integrity failures global and typed component faults local."""
    if health.get('stale_checkpoint') or health.get('reasons') or health.get('stalled_connections'):
        return 'GLOBAL_SOURCE_QUARANTINE'
    scoped=dict(health.get('component_rejections',{}))
    for key in health.get('native_rejection_reviews',{}):
        scoped.setdefault(key,['native_record_or_recovery_validation_failed'])
    if health.get('quarantined') and not scoped:return 'GLOBAL_SOURCE_QUARANTINE'
    relevant=[]
    for key in scoped:
        schema,instrument=key.rsplit(':',1)
        if int(instrument)==iid:relevant.append(key)
    if relevant:
        reviews=health.get('native_rejection_reviews',{})
        if all(key.startswith('trades:') and reviews.get(key,{}).get('verified_trade_timestamp_scope')
                and set(scoped[key]) <= {'native_record_or_recovery_validation_failed'} for key in relevant):
            return 'COMPONENT_SOURCE_QUARANTINE'
        return 'INSTRUMENT_SOURCE_QUARANTINE'
    return 'NONE'


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
                parents, _ = aggregate_complete(frames[max(smaller, key=lambda s:WIDTHS[s])], target=tf, calendar=calendar,
                    coverage_reviews=tuple(getattr(gate,'coverage_reviews',{}).values()))
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
                    sparse_coverage_proofs={r.sha256:encode(r) for b in rows for r in getattr(b,'coverage_reviews',())},
                    synthetic_bar_count=0,
                    source_sha256=digest(rows), selector_applied=False, fixed_selector_expiry_applied=False,
                    native_analysis=analyse_frame(rows,tick_size=c.tick_size,cutoff_ns=request.cutoff_ns,calendar=calendar))
            except (ValueError,TypeError,ArithmeticError) as exc:
                parts['price:'+tf] = dict(available=False,reason=str(exc))
        policy = inherited_policy(c,'trades')
        trade_health = gate.health(now_ns=request.cutoff_ns,policies={'trades':policy},schemas=('trades',))['trades']
        if trade_health['available']:
            values = [v for v in getattr(gate,'trade_sources',gate.accepted) if v.schema == 'trades' and v.source.admission_ns <= request.cutoff_ns]
            metrics = trade_indicators(values,start_ns=min(v.receive_ns for v in values),
                end_ns=max(v.receive_ns for v in values)+1, session_reference=calendar.sha256)
            parts['trade_features'] = dict(available=True,result=metrics,health=trade_health)
        else:
            parts['trade_features'] = dict(trade_health)
        # Only observations already admitted by the exact source/price gate can
        # supply quotes or published OI. No subscriptions or legacy graph here.
        policies={s:inherited_policy(c,'open_interest' if s=='statistics' else 'book')
                  for s in ('mbp-1','mbp-10','statistics')}
        health_by_schema=gate.health(now_ns=request.cutoff_ns,policies=policies,schemas=tuple(policies))
        for schema in ('mbp-1','mbp-10'):
            h=health_by_schema[schema]
            values=[v for v in gate.accepted if v.schema==schema and v.source.admission_ns<=request.cutoff_ns]
            if not h['available'] or not values:
                parts[schema]=dict(available=False,reason=h.get('reason') or 'not_captured_or_not_validated',health=h)
            else:
                latest=values[-1];top=latest.payload[0]
                if top[0] is None or top[3] is None or min(top[1],top[4])<=0 or Decimal(top[0])>=Decimal(top[3]):
                    parts[schema]=dict(available=False,reason='one_sided_locked_or_empty_book',native_record_retained=True);continue
                parts[schema]=dict(available=True,health=h,result=book_indicator(latest),
                    quote=dict(bid=top[0],ask=top[3],bid_contracts=top[1],ask_contracts=top[4],
                        spread=str(Decimal(top[3])-Decimal(top[0])),receive_ns=latest.receive_ns,
                        available_ns=latest.source.admission_ns,book_basis='DIRECT_DISPLAYED_BOOK',
                        source_sha256=latest.source.record_sha256,executable_quote=False))
        h=health_by_schema['statistics']
        oi={}
        for v in getattr(gate,'statistics_sources',gate.accepted):
            if v.schema=='statistics' and v.source.admission_ns<=request.cutoff_ns:
                oi[v.payload[2]]=v  # Latest admitted publication for each reference date.
        periods=sorted(oi)
        if h['available'] and periods:
            latest=oi[periods[-1]]
            parts['open_interest']=dict(available=True,contracts=latest.payload[1],reference_ns=latest.payload[2],
                publication_ns=latest.receive_ns,available_ns=latest.source.admission_ns,
                health=h,source=encode_source(latest),signed_dealer_position=None)
            if len(periods)>=2:
                try:parts['oi_change']=dict(available=True,result=open_interest_change(oi[periods[-2]],latest,cutoff_ns=request.cutoff_ns))
                except ValueError as exc:parts['oi_change']=dict(available=False,reason=str(exc))
            else:parts['oi_change']=dict(available=False,reason='two_distinct_published_OI_periods_required')
        else:
            parts['open_interest']=dict(available=False,reason=h.get('reason') or 'not_captured_or_not_validated')
            parts['oi_change']=dict(parts['open_interest'])
        for v in parts.values():
            if v.get('available') and 'result' in v and 'vwap' in v['result']:
                v['result']['window_scope']='RETAINED_VALIDATED_EXECUTIONS_NOT_FULL_SESSION'
        available = [k for k,v in parts.items() if v['available']]
        state = 'PARTIAL_MARKET_INFORMATION' if available else 'UNAVAILABLE'
        source_scope=quarantine_scope(health,iid)
        if source_scope in {'GLOBAL_SOURCE_QUARANTINE','INSTRUMENT_SOURCE_QUARANTINE'}:state='UNAVAILABLE'
        elif source_scope=='COMPONENT_SOURCE_QUARANTINE':
            # Native OHLCV has its own source lineage and price gate. Never use
            # rejected trades to supply its candles, flow, VWAP or profile.
            parts['trade_features']=dict(available=False,reason='provider_receive_timestamp_quality_requires_review')
            state='PARTIAL_MARKET_INFORMATION' if any(v['available'] for v in parts.values()) else 'UNAVAILABLE'
        result = dict(instrument=c.metadata.raw_symbol, availability=state,components=parts,
            capture_health=health,analysis_access='READ_ONLY',live_analysis_certified=False,
            validation=dict(source_quarantine_scope=source_scope,faults=dict(gate.faults),first_fault_details=dict(getattr(gate,'fault_details',{})),
                source_record_reviews={k:v for k,v in health.get('native_rejection_reviews',{}).items() if k.endswith(':'+str(iid))},
                price_fault_reviews=health.get('reader_price_fault_reviews',{}).get(c.metadata.raw_symbol,{}),
                thresholds_relaxed=False,rejected_records_readmitted=False,quality_mode=getattr(gate,'quality_mode','LEGACY_STATISTICAL_V2'),custom_price_anomaly_applied=not hasattr(gate,'quality_mode')),
            multi_timeframe=alignment({tf:parts['price:'+tf].get('native_analysis',{}) for tf in request.timeframes}),
            information_scope='RETAINED_VALIDATED_CAPTURE_WINDOW',
            participant_identity='UNAVAILABLE_ANONYMOUS_EXCHANGE_DATA',
            crypto_engines_used=False, frozen_H1_selector_used=False, GIL_rules_used=False,
            trade_signal_produced=False, complete_exchange_continuity_certified=False, **SAFETY)
        if history is not None:
            result['history_warmup'] = history
        result['seconds_bar_diagnostics'] = second_intervals(p.gates[iid],cutoff_ns=request.cutoff_ns,
            watermark_ns=health.get('interval_watermarks',{}).get('ohlcv-1s'),
            source_unreliable=source_scope!='NONE')
        from monatise.research.native_futures.intervals import native_intervals
        for tf in ('1s','1m'):
            native=tuple(b for _,b in sorted(p.bars[iid].get(tf,{}).items()) if b.close_ns<=request.cutoff_ns)
            if not native:continue
            end=native[-1].close_ns;start=max(native[0].open_ns,end-60*WIDTHS[tf])
            state=native_intervals(gate,native,schema='ohlcv-'+tf,start_ns=start,end_ns=end,cutoff_ns=request.cutoff_ns,
                source_unreliable=source_scope in {'GLOBAL_SOURCE_QUARANTINE','INSTRUMENT_SOURCE_QUARANTINE'})
            result.setdefault('native_interval_classification',{})[tf]=state
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
            normalization_semantics=NORMALIZATION_VERSION,
            analysis_access='READ_ONLY',crypto_engines_used=False,frozen_H1_selector_used=False,GIL_rules_used=False,
            trade_signal_produced=False, **SAFETY)
        result['reproducibility_sha256'] = digest(result)
        return result
