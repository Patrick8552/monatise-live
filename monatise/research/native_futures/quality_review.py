"""Read-only native rejection attribution; corroboration is never admission.

The original capture, admission bit, price policies and fault latches are kept.
Only a completely accounted-for trade timestamp fault can be scoped to trades.
Unknown failures retain the broader instrument quarantine.
"""
import hashlib

from monatise.research.institutional.models import digest

NS = 10**9


def receive_timestamp_issue(record, contract, *, schema):
    """Identify the vendor flag without repairing, replacing or admitting a record."""
    import databento_dbn as dbn
    flags = int(getattr(record, 'flags', 0))
    if schema != 'trades' or not isinstance(record, dbn.TradeMsg) or not flags & 8:
        return None
    # A second, unrelated defect must not be hidden by the receive-time flag.
    tick = int(contract.tick_size * NS)
    if (flags & (4 | 32) or record.publisher_id != contract.metadata.publisher_id
            or record.instrument_id != contract.metadata.instrument_id
            or not contract.metadata.event_ns <= record.ts_event < contract.metadata.expiration_ns
            or not 0 < record.ts_recv < contract.metadata.expiration_ns
            or not 0 < record.price < 2**63-1 or record.price % tick
            or not 0 < record.size < 2**32-1
            or str(record.action) != 'T' or str(record.side) not in {'A', 'B', 'N'}):
        return None
    return dict(classification='PROVIDER_RECEIVE_TIMESTAMP_FLAG', flag='F_BAD_TS_RECV',
        flags=flags, event_ns=record.ts_event, receive_ns=record.ts_recv,
        receive_minus_event_ns=record.ts_recv-record.ts_event,
        record_sha256=hashlib.sha256(bytes(record)).hexdigest(),
        dependent_schema='trades', record_admitted=False, timestamp_repaired=False)


class NativeQualityReview:
    """Bounded raw cross-stream comparison, independent of the price guard.

    Aggregates structurally valid source-admitted prints even when price screening
    rejects them, solely to explain the rejection. These aggregates are never
    passed to indicators, published as candles or used to fit a policy.
    """
    def __init__(self, maximum_buckets=20000):
        if type(maximum_buckets) is not int or not 1<=maximum_buckets<=100000:
            raise ValueError('bounded_native_quality_comparison_required')
        self.maximum_buckets = maximum_buckets
        self.trades, self.bars, self.first_prices = {}, {}, {}
        self.rejections = {}
        self.exhausted = False

    def rejection(self, schema, record, contract, *, original_reason, context_valid=True):
        key = schema+':'+str(contract.metadata.instrument_id)
        entry = self.rejections.setdefault(key, dict(count=0, typed_count=0,
            record_hash_chain=digest([]), reasons=set(), examples=[]))
        entry['count'] += 1
        sha = hashlib.sha256(bytes(record)).hexdigest()
        entry['record_hash_chain'] = digest([entry['record_hash_chain'], sha])
        entry['reasons'].add(original_reason)
        issue = receive_timestamp_issue(record, contract, schema=schema)
        if issue and context_valid:
            entry['typed_count'] += 1
            if len(entry['examples']) < 8:
                entry['examples'].append(issue)

    def observe(self, schema, record, contract, *, admitted, gate):
        import databento_dbn as dbn
        if not admitted:
            return
        fault = gate.fault_details.get(schema, {})
        sha = hashlib.sha256(bytes(record)).hexdigest()
        if fault.get('record_sha256') == sha and sha not in self.first_prices:
            self.first_prices[sha] = record
        if schema == 'trades' and isinstance(record, dbn.TradeMsg):
            from monatise.research.databento.advanced import AdvancedAdapters
            try:
                AdvancedAdapters(identity=contract.metadata, enabled_schemas=('trades',)).normalize('trades', record)
                if record.flags & (4 | 8 | 32):
                    return
            except (ValueError, TypeError, AttributeError):
                return
            for width in (NS, 60*NS):
                key = (record.instrument_id, width, record.ts_recv//width*width)
                if key not in self.trades:
                    if len(self.trades) >= self.maximum_buckets:
                        self.exhausted = True
                        continue
                    self.trades[key] = dict(ohlc=[record.price]*4, volume=0, count=0,
                        last_receive_ns=record.ts_recv, ordered=True, hash_chain=digest([]))
                bucket = self.trades[key]
                bucket['ordered'] &= record.ts_recv >= bucket['last_receive_ns']
                bucket['last_receive_ns'] = record.ts_recv
                prices = bucket['ohlc']
                prices[1], prices[2], prices[3] = max(prices[1],record.price), min(prices[2],record.price), record.price
                bucket['volume'] += record.size
                bucket['count'] += 1
                bucket['hash_chain'] = digest([bucket['hash_chain'], sha])
        elif schema in {'ohlcv-1s', 'ohlcv-1m'} and isinstance(record, dbn.OHLCVMsg):
            width = NS if schema == 'ohlcv-1s' else 60*NS
            key = (record.instrument_id,width,record.ts_event)
            if key in self.bars or len(self.bars) < self.maximum_buckets:
                values=self.bars.setdefault(key, [])
                if len(values)<2:values.append(record)
            else:
                self.exhausted = True

    def typed_rejections(self, *, complete_for_reported_prefix):
        result = {}
        for key, entry in self.rejections.items():
            result[key] = dict(count=entry['count'], typed_count=entry['typed_count'],
                record_hash_chain=entry['record_hash_chain'], examples=entry['examples'],
                original_rejection_reasons=sorted(entry['reasons']),
                verified_trade_timestamp_scope=bool(complete_for_reported_prefix
                    and entry['count'] == entry['typed_count'] and entry['count'] > 0
                    and entry['reasons'] <= {'ValueError'}),
                prefix_accounted_for=complete_for_reported_prefix,
                rejected_records_readmitted=False)
        return result

    def price_faults(self, gate):
        result = {}
        for schema, detail in gate.fault_details.items():
            if detail['reason'] != 'suspicious_price_discontinuity_requires_review':
                continue
            record = self.first_prices.get(detail['record_sha256'])
            evidence = dict(classification='PLAUSIBILITY_THRESHOLD_EXCEEDED',
                policy_sha256=detail['policy_sha256'], record_sha256=detail['record_sha256'],
                bound_ticks=detail['bound_ticks'], excursion_ticks=detail['excursion_ticks'],
                status='INSUFFICIENT_CORROBORATION', diagnostic_only=True,
                corroboration_is_independent_exchange_truth=False,
                policy_changed=False, fault_cleared=False, record_readmitted=False,
                comparison_budget_exhausted=self.exhausted)
            if record is not None and not self.exhausted:
                width = NS
                start = (record.ts_recv//NS*NS if schema == 'trades' else record.ts_event)
                key = (record.instrument_id,width,start)
                bucket, bars = self.trades.get(key), self.bars.get(key, ())
                if bucket and len(bars) == 1 and bucket['ordered']:
                    bar = bars[0]
                    exact = tuple(bucket['ohlc']) == (bar.open,bar.high,bar.low,bar.close) and bucket['volume'] == bar.volume
                    evidence.update(native_second_bar_sha256=hashlib.sha256(bytes(bar)).hexdigest(),
                        trade_count=bucket['count'], trade_hash_chain=bucket['hash_chain'],
                        native_OHLCV_matches_captured_trades=exact,
                        rejected_price_inside_native_bar=(schema != 'trades' or bar.low <= record.price <= bar.high),
                        comparison_clock='DATABENTO_TRADE_TS_RECV',
                        status='CROSS_STREAM_CORROBORATED_POLICY_REVIEW_REQUIRED' if exact else 'CROSS_STREAM_MISMATCH_REQUIRES_REVIEW')
            result[schema] = evidence
        return result
