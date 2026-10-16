"""Canonical native normalization -> scoped quality -> candles -> read-only engines."""
from collections import deque
import hashlib

from monatise.research.institutional.normalize import observation
from monatise.research.institutional.models import digest
from monatise.research.databento.candles import normalize_candle, WIDTHS
from .candles import ContinuousCandles, aggregate_complete
from . import SAFETY


class ResearchPipeline:
    def __init__(self, gates, calendars, *, enabled_schemas, capacity=50000, rolling=False):
        if (not gates or len(gates)>64 or type(capacity) is not int or not 1<=capacity<=100000
                or set(gates)!=set(calendars)):
            raise ValueError('bounded_exact_contract_pipeline_required')
        self.gates, self.calendars = dict(gates), dict(calendars)
        self.enabled_schemas = tuple(enabled_schemas)
        self.bars = {iid:{} for iid in gates}
        self.trade_candles = {iid:ContinuousCandles(g.contract,calendars[iid],capacity=capacity) for iid,g in gates.items()}
        self.quarantine = deque(maxlen=256)
        self.capacity = capacity
        self.rolling=rolling

    def ingest(self, record, *, schema, archive_sha256, ordinal, capture_ns, admission_ns, evidence_kind, clock_review=None):
        iid = getattr(record,'instrument_id',None)
        gate = self.gates.get(iid)
        assessment=None
        try:
            if gate is None: raise ValueError('unrequested_contract')
            from monatise.research.databento.semantics import assess_native_record,transformation_provenance
            _,upper=clock_review.bounds(capture_ns) if clock_review else (0,0)
            if schema in {'trades','ohlcv-1s','ohlcv-1m','ohlcv-1h'}:
                assessment=assess_native_record(record,schema=schema,contract=gate.contract,capture_upper_ns=capture_ns+upper)
            value = observation(record,schema=schema,contract=gate.contract,archive_sha256=archive_sha256,
                ordinal=ordinal,retrieval_ns=capture_ns,admission_ns=admission_ns,
                evidence_kind=evidence_kind,enabled_schemas=self.enabled_schemas,clock_review=clock_review)
            result = gate.ingest(value,now_ns=admission_ns)
            result['mapping_provenance']=transformation_provenance(value)
            if hasattr(gate,'quality_mode'):
                result['mapping_provenance'].update(custom_price_anomaly_applied=False,excursion_measurement='NOT_APPLIED')
            if result['accepted']:
                if schema=='trades':
                    builder=self.trade_candles[iid]
                    if self.rolling and len(builder.rows)>=self.capacity:
                        old=builder.rows.pop(0);builder.positions.pop(old.source.position,None)
                    builder.ingest(value)
                elif schema.startswith('ohlcv-'):
                    bar = normalize_candle(record,schema=schema,identity=gate.contract.metadata,retrieval_ns=capture_ns,
                        evidence_kind='AUTHENTIC_HISTORICAL_DOWNLOAD' if evidence_kind=='AUTHENTIC_ARCHIVED_RECORD' else evidence_kind,clock_review=clock_review)
                    series = self.bars[iid].setdefault(bar.timeframe,{})
                    if bar.open_ns in series:
                        gate.transport_gap(schema,'duplicate_or_revised_candle');raise ValueError('duplicate_or_revised_candle')
                    if self.rolling and len(series)>=self.capacity:series.pop(min(series))
                    elif not self.rolling and sum(len(v) for v in self.bars[iid].values())>=self.capacity:raise ValueError('bar_capacity_exceeded')
                    series[bar.open_ns] = bar
            elif not result['duplicate'] and schema=='trades':
                # Rejecting an execution taints its bucket, not other instruments.
                for tf,w in WIDTHS.items():
                    self.trade_candles[iid].tainted.add((tf,value.event_ns//w*w))
            if assessment is not None:
                assessment['price_screening_accepted']=result['accepted']
                if hasattr(gate,'quality_mode'):
                    assessment.update(price_plausibility='CUSTOM_STATISTICAL_GATE_RETIRED',custom_price_anomaly_applied=False)
                if not result['accepted']:assessment['capabilities']={k:False for k in assessment['capabilities']}
                result['record_quality']=assessment
            return result
        except (ValueError,TypeError,AttributeError,ArithmeticError) as exc:
            if assessment is not None:
                assessment['canonical_mapping_accepted']=False
                assessment['capabilities']={k:False for k in assessment['capabilities']}
            if gate is not None: gate.transport_gap(schema,type(exc).__name__,event_ns=getattr(record,'ts_event',None))
            self.quarantine.append(dict(schema=schema,instrument_id=iid,ordinal=ordinal,capture_ns=capture_ns,
                archive_sha256=archive_sha256,native_sha256=hashlib.sha256(bytes(record)).hexdigest(),
                error_type=type(exc).__name__,reason=str(exc),record_quality=assessment))
            return dict(accepted=False,duplicate=False,reason=str(exc),record_quality=assessment,**SAFETY)

    def analyse(self, iid, *, now_ns, mandatory=('price:1h',), requested=(), coverage_review=None):
        frames = {tf:tuple(series[k] for k in sorted(series)
            if series[k].close_ns+10*10**9<=now_ns and series[k].retrieval_ns<=now_ns)
            for tf,series in self.bars[iid].items()}
        diagnostics = {tf:dict(forming_or_not_yet_available=len(series)-len(frames[tf]))
            for tf,series in self.bars[iid].items()}
        if coverage_review is not None:
            for tf in ('1s','5s','1m','5m','15m','1h','4h'):
                values,quality = self.trade_candles[iid].view(tf,review=coverage_review,now_ns=now_ns)
                diagnostics[tf] = quality
                if values and tf not in frames: frames[tf] = values
        frames={tf:rows for tf,rows in frames.items() if rows}
        # Only aggregate a fully represented smaller timeframe; no filling gaps.
        for tf in ('5s','1m','5m','15m','1h','4h'):
            if tf in frames: continue
            sources = [s for s in frames if WIDTHS[s]<WIDTHS[tf] and WIDTHS[tf]%WIDTHS[s]==0]
            if sources:
                source = max(sources,key=lambda s:WIDTHS[s])
                values,rejected = aggregate_complete(frames[source],target=tf,calendar=self.calendars[iid])
                diagnostics[tf] = dict(aggregation_rejections=rejected)
                if values: frames[tf] = values
        from .coordinator import NativeFuturesCoordinator
        result = NativeFuturesCoordinator().analyse(self.gates[iid],bars_by_timeframe=frames,
            calendar=self.calendars[iid],now_ns=now_ns,mandatory=mandatory,requested=requested)
        result['candle_quality'] = diagnostics
        result['reproducibility_sha256'] = digest({k:v for k,v in result.items() if k!='reproducibility_sha256'})
        return result
