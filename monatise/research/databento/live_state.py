"""CME native live state, exact cursor recovery and fail-closed quality gates."""
from collections import defaultdict
from dataclasses import dataclass,field,replace
import hashlib

from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.institutional.models import encode,hash_required,digest
from monatise.research.databento.advanced import AdvancedAdapters
from .live_models import native_definition,SAFETY


@dataclass
class Cursor:
    event_ns: int|None=None
    hashes_at_event: list=field(default_factory=list)
    replay_prefix: tuple=()
    skipped: int=0
    index_ns: int|None=None
    event_order_regressed: bool=False

    def accept(self,event_ns,native_hash, *, index_ns=None):
        timestamp_ns(event_ns)
        if index_ns is not None:
            timestamp_ns(index_ns)
            if self.index_ns is not None and index_ns<self.index_ns and not self.replay_prefix:
                raise ValueError('provider_index_order_regressed')
        if self.event_ns is not None and event_ns<self.event_ns:
            if self.replay_prefix:return False
            if index_ns is None:raise ValueError('market_event_order_regressed')
            self.event_order_regressed=True
        if self.event_ns==event_ns and self.skipped<len(self.replay_prefix):
            if native_hash!=self.replay_prefix[self.skipped]:
                raise ValueError('replay_equal_timestamp_prefix_mismatch')
            self.skipped+=1;return False
        if self.event_ns!=event_ns:
            if self.skipped<len(self.replay_prefix):raise ValueError('replay_missing_tied_records')
            self.event_ns=event_ns;self.hashes_at_event=[];self.replay_prefix=();self.skipped=0
        if len(self.hashes_at_event)>=10000:raise ValueError('cursor_tie_capacity_exceeded')
        self.hashes_at_event.append(native_hash)
        if index_ns is not None:self.index_ns=index_ns
        return True

    def snapshot(self):
        result=dict(event_ns=self.event_ns,hashes_at_event=list(self.hashes_at_event))
        if self.index_ns is not None:result.update(index_ns=self.index_ns,event_order_regressed=self.event_order_regressed)
        return result

    def finish_recovery(self):
        if self.skipped<len(self.replay_prefix):raise ValueError('replay_prefix_incomplete')
        self.replay_prefix=();self.skipped=0

    @classmethod
    def recover(cls,value):
        # Live replay start uses exchange time, unlike historical index order.
        # A regressed exchange clock needs an explicitly reviewed overlap and
        # source-prefix reconciliation, never an unsafe automatic last-event seek.
        if value.get('event_order_regressed'):raise ValueError('nonmonotonic_event_recovery_requires_overlap_review')
        event=value['event_ns'];hashes=tuple(value['hashes_at_event'])
        index=value.get('index_ns')
        if index is not None:timestamp_ns(index)
        if event is not None:timestamp_ns(event)
        if (len(hashes)>10000 or event is None and hashes or any(not isinstance(h,str) or len(h)!=64 for h in hashes)):
            raise ValueError('reviewed_native_cursor_required')
        for h in hashes:hash_required(h)
        return cls(event_ns=event,hashes_at_event=list(hashes),replay_prefix=hashes,index_ns=index)


class FeedState:
    def __init__(self,scope, *, checkpoints=None,recovery_review_reference=None,bootstrap_prefixes=None):
        if bootstrap_prefixes and (not checkpoints or not recovery_review_reference):raise ValueError("reviewed_initial_prefix_requires_checkpoints")
        self.bootstrap_prefixes=bootstrap_prefixes or {}
        self.bootstrap_clock_translations=[]
        self.scope=scope;self.clock_review=scope.clock_review;self.clock_history=[scope.clock_review] if scope.clock_review else [];self.contracts={c.metadata.instrument_id:c for c in scope.contracts}
        self.interval_watermarks={};self.interval_receipts={};self.started={};self.completed=set();self.acknowledged=set();self.last_message={}
        self.latest={};self.quotes={};self.verified_definitions=set();self.quality_reasons=set();self.counts=defaultdict(int)
        self.cursors={};self.coverage_start_ns={};self.normalized=[];self.component_reasons=defaultdict(set)
        if checkpoints and not recovery_review_reference:raise ValueError('explicit_recovery_review_required')
        for schema in scope.schemas:
            for iid in self.contracts:
                key=f'{schema}:{iid}'
                self.cursors[key]=Cursor.recover(checkpoints[key]) if checkpoints and key in checkpoints else Cursor()
                if schema.startswith('ohlcv-'):
                    from .candles import WIDTHS
                    event=self.cursors[key].event_ns
                    self.coverage_start_ns[key]=max(scope.start_ns,event+WIDTHS[schema[6:]] if event is not None else scope.start_ns)

    def update_clock_review(self,review):
        from .live_models import ClockReview
        if (not isinstance(review,ClockReview) or len(self.clock_history)>=4096 or
                self.clock_review is not None and not self.clock_review.observed_at_ns<review.observed_at_ns<self.clock_review.expires_ns):
            raise ValueError('ordered_overlapping_clock_review_required')
        self.clock_history.append(review);self.clock_review=review

    def review_at(self,capture_ns):
        if not self.clock_history:return None
        for review in reversed(self.clock_history):
            if review.observed_at_ns<=capture_ns<review.expires_ns:return review
        raise ValueError('capture_has_no_contemporaneous_clock_review')

    def quarantine(self,reason):self.quality_reasons.add(reason)

    def reject_component(self,schema,record,reason):
        iid=getattr(record,'instrument_id',None)
        if iid in self.contracts:self.component_reasons[(schema,iid)].add(reason)
        else:self.quarantine(reason)

    def checkpoint(self):return {k:c.snapshot() for k,c in sorted(self.cursors.items())}

    def replay_start(self,schema):
        # A missing instrument cursor means replay from the original approved
        # start; never skip an instrument that had no records before disconnect.
        clocks=[self.cursors[f'{schema}:{i}'].event_ns or (0 if schema=='definition' else self.scope.start_ns) for i in self.contracts]
        return min(clocks)

    def ingest(self,schema,record, *, capture_ns,ordinal):
        import databento_dbn as dbn
        timestamp_ns(capture_ns)
        if schema not in self.scope.schemas:raise ValueError('unsubscribed_schema')
        self.last_message[schema]=capture_ns
        native_hash=hashlib.sha256(bytes(record)).hexdigest()
        if isinstance(record,dbn.ErrorMsg):
            self.quarantine('provider_error_code_'+str(int(record.code)));return None
        if isinstance(record,dbn.SystemMsg):
            code=int(record.code)
            if code==int(dbn.SystemCode.HEARTBEAT):return None
            if code==int(dbn.SystemCode.SUBSCRIPTION_ACK):self.acknowledged.add(schema);return None
            if code==int(dbn.SystemCode.END_OF_INTERVAL):
                from .candles import WIDTHS
                event=timestamp_ns(record.ts_event)
                review=self.review_at(capture_ns)
                _,upper=review.bounds(capture_ns) if review else (0,0)
                width=WIDTHS.get(schema[6:]) if schema.startswith('ohlcv-') else None
                if (width is None or schema not in self.acknowledged or event%width or
                        event<self.interval_watermarks.get(schema,0) or event>capture_ns+upper):
                    self.quarantine('invalid_native_interval_watermark');return None
                self.interval_watermarks[schema]=event
                self.interval_receipts[schema]=dict(event_ns=event,capture_ns=capture_ns,ordinal=ordinal,record_sha256=native_hash)
                self.counts['end_of_interval:'+schema]+=1
                return None
            if code==int(dbn.SystemCode.REPLAY_COMPLETED):
                if schema not in self.acknowledged or schema in self.completed:
                    self.quarantine('unexpected_replay_watermark');return None
                if any(c.skipped<len(c.replay_prefix) for k,c in self.cursors.items() if k.startswith(schema+':')):
                    self.quarantine('replay_prefix_incomplete');return None
                for key,cursor in self.cursors.items():
                    if key.startswith(schema+':'):cursor.finish_recovery()
                self.completed.add(schema);return None
            self.quarantine('slow_reader_or_unknown_control_code_'+str(code));return None
        if isinstance(record,dbn.SymbolMappingMsg):
            contract=self.contracts.get(record.instrument_id)
            # The live gateway maps numeric subscriptions back to raw exchange
            # symbols. Bind that output to the independently reviewed contract;
            # never accept a different expiry, parent or continuous symbol.
            output_matches=(contract is not None and (
                record.stype_out==dbn.SType.RAW_SYMBOL
                and str(record.stype_out_symbol)==contract.metadata.raw_symbol
                or record.stype_out==dbn.SType.INSTRUMENT_ID
                and str(record.stype_out_symbol)==str(record.instrument_id)))
            if (contract is None or not output_matches
                    or record.stype_in!=dbn.SType.INSTRUMENT_ID
                    or str(record.stype_in_symbol)!=str(record.instrument_id)
                    or record.start_ts>capture_ns or capture_ns>=record.end_ts):
                self.quarantine('symbol_mapping_conflicts_with_exact_native_selection')
            return None
        iid=getattr(record,'instrument_id',None);contract=self.contracts.get(iid)
        if contract is None:raise ValueError('unrequested_instrument')
        event=timestamp_ns(record.ts_event);received=timestamp_ns(getattr(record,'ts_recv',record.ts_event))
        review=self.review_at(capture_ns)
        lower,upper=review.bounds(capture_ns) if review else (0,0)
        if (record.publisher_id!=contract.metadata.publisher_id or max(event,received)>capture_ns+upper
                or not contract.metadata.event_ns<=received<contract.metadata.expiration_ns
                or not (contract.metadata.event_ns if schema=='definition' else self.scope.start_ns)<=event<self.scope.session_end_ns
                or capture_ns+max(0,upper)>=self.scope.session_end_ns+self.scope.session_drain_seconds*10**9 or int(getattr(record,'flags',0))&(4|8|32)):
            raise ValueError('live_record_identity_clocks_session_or_quality_rejected')
        if schema.startswith('ohlcv-'):
            from .candles import WIDTHS
            if event+WIDTHS[schema[6:]]<=self.interval_watermarks.get(schema,0):raise ValueError('bar_after_native_interval_watermark')
        key=f'{schema}:{iid}';previous=self.cursors[key]
        cursor=replace(previous,hashes_at_event=list(previous.hashes_at_event))
        if schema=='definition':
            value=native_definition(record,capability=self.scope.capability,
                publishers={p:(d,v) for p,d,v in self.scope.publishers},as_of_ns=capture_ns+max(0,upper))
            signature=lambda c:(c.identity,c.tick_size,c.multiplier,c.price_unit,c.metadata.native_terms)
            if signature(value)!=signature(contract):raise ValueError('contract_roll_or_definition_economics_changed')
            result=dict(contract=encode(value),record_sha256=native_hash)
        elif schema in {'trades','mbp-1','mbp-10'}:
            result=encode(AdvancedAdapters(identity=contract.metadata,enabled_schemas=(schema,)).normalize(schema,record))
        else:
            from monatise.research.institutional.normalize import observation
            if schema=='statistics' and isinstance(record,dbn.StatMsg) and record.stat_type!=dbn.StatType.OPEN_INTEREST:
                self.counts['unsupported_statistics_preserved_raw']+=1
                return None
            result=encode(observation(record,schema=schema,contract=contract,archive_sha256=native_hash,
                ordinal=ordinal,retrieval_ns=capture_ns,admission_ns=capture_ns,
                evidence_kind='AUTHENTIC_LIVE_CAPTURE',enabled_schemas=self.scope.schemas,clock_review=review))
        cursor_hash=native_hash
        prefix=self.bootstrap_prefixes.get(key)
        if prefix and cursor.replay_prefix and event==cursor.event_ns and cursor.skipped<len(cursor.replay_prefix):
            from monatise.research.native_futures.replay_identity import verified_prefix_hash
            if schema!='trades' or not prefix.get('review_reference') or len(prefix['expected'])!=len(cursor.replay_prefix):
                raise ValueError('reviewed_initial_trade_prefix_required')
            expected=prefix['expected'][cursor.skipped]
            if expected['record_sha256']!=cursor.replay_prefix[cursor.skipped]:raise ValueError('initial_prefix_source_hash_mismatch')
            cursor_hash=verified_prefix_hash(record,expected=expected,maximum_translation_ns=prefix['maximum_translation_ns'])
            if cursor_hash!=native_hash:
                self.bootstrap_clock_translations.append(dict(schema=schema,instrument_id=iid,event_ns=event,
                    original_anchor_sha256=cursor_hash,replayed_native_sha256=native_hash,
                    receive_time_difference_ns=record.ts_recv-expected['ts_recv'],review_reference=prefix['review_reference']))
        accepted=cursor.accept(event,cursor_hash,index_ns=received if hasattr(record,'ts_recv') else None)
        if schema=='definition':self.verified_definitions.add(iid)
        else:
            from .candles import WIDTHS
            self.latest[(schema,iid)]=event+WIDTHS[schema[6:]] if schema.startswith('ohlcv-') else received
            if schema=='mbp-1':self.quotes[iid]=result['payload'][0]
        self.cursors[key]=cursor
        if not accepted:
            self.counts['replay_duplicates_skipped']+=1;return None
        self.counts[schema]+=1
        result=dict(result,capture_ns=capture_ns,native_ordinal=ordinal,
                    capture_utc_bounds_ns=(capture_ns+lower,capture_ns+upper),
                    clock_review_sha256=digest(review) if review else None,
                    availability_basis='ACTUAL_LOCAL_LIVE_CAPTURE',context_only=True,**SAFETY)
        self.normalized.append(result)
        if len(self.normalized)>2048:self.normalized.pop(0)
        return result

    def health(self,now_ns):
        timestamp_ns(now_ns)
        try:lower,upper=self.clock_review.bounds(now_ns) if self.clock_review else (0,0)
        except ValueError:
            self.quarantine('independent_clock_review_expired_or_invalid');lower=upper=0
        stalled=[s for s in self.scope.schemas if now_ns-self.last_message.get(s,self.started.get(s,now_ns))>
                 (self.scope.heartbeat_seconds+10)*10**9]
        from .candles import WIDTHS
        def age_limit(schema):
            return max(self.scope.maximum_market_age_ns,2*WIDTHS[schema[6:]]) if schema.startswith('ohlcv-') else self.scope.maximum_market_age_ns
        stale=[f'{s}:{i}' for s in self.scope.schemas if s!='definition' for i in self.contracts
               if not 0<=now_ns+upper-self.latest.get((s,i),0)<=age_limit(s)]
        unusable_quotes=[i for i in self.contracts if 'mbp-1' in self.scope.schemas and (i not in self.quotes
            or self.quotes[i][0] is None or self.quotes[i][3] is None
            or self.quotes[i][0]==self.quotes[i][3] or min(self.quotes[i][1],self.quotes[i][4])<=0)]
        ready=(not self.component_reasons and not self.quality_reasons and not stalled and not stale and not unusable_quotes
               and self.completed==set(self.scope.schemas) and self.verified_definitions==set(self.contracts)
               and now_ns+max(0,upper)<self.scope.session_end_ns)
        components={}
        for iid,contract in self.contracts.items():
            streams={}
            for schema in self.scope.schemas:
                reasons=sorted(self.component_reasons.get((schema,iid),()))
                if schema in stalled:reasons.append('connection_stalled')
                if schema not in self.completed:reasons.append('replay_not_completed')
                if iid not in self.verified_definitions:reasons.append('definition_unverified')
                if f'{schema}:{iid}' in stale:reasons.append('stream_stale_or_missing')
                if schema=='mbp-1' and iid in unusable_quotes:reasons.append('quote_unusable')
                if now_ns+max(0,upper)>=self.scope.session_end_ns:reasons.append('session_ended')
                # An uncertain transport fault remains fail-closed. Simple
                # staleness/absence is independently attributed above.
                reasons.extend(sorted(self.quality_reasons))
                streams[schema]=dict(status='UNAVAILABLE' if reasons else 'CAPTURED_CONTEXT_FRESH',
                    reasons=reasons,event_ns=self.cursors[f'{schema}:{iid}'].event_ns,
                    provider_receive_ns=self.latest.get((schema,iid)),
                    complete_exchange_continuity_certified=False,**SAFETY)
            components[contract.metadata.raw_symbol]=streams
        return dict(status='CAPTURED_CONTEXT_FRESH' if ready else 'UNAVAILABLE',
            quarantined=bool(self.component_reasons or self.quality_reasons or stalled or self.completed!=set(self.scope.schemas)
                             or self.verified_definitions!=set(self.contracts)),reasons=sorted(self.quality_reasons),
            component_rejections={f'{s}:{i}':sorted(v) for (s,i),v in self.component_reasons.items()},
            stalled_connections=stalled,stale_market_inputs=stale,replay_completed=sorted(self.completed),interval_watermarks=dict(self.interval_watermarks),
            unusable_quote_instruments=unusable_quotes,component_health=components,
            definitions_verified=sorted(self.verified_definitions),counts=dict(self.counts),
            local_clock_offset_bounds_ns=(lower,upper),
            clock_review_sha256=digest(self.clock_review) if self.clock_review else None,
            authenticated_clock_certified=False,
            complete_exchange_continuity_certified=False,context_only=True,**SAFETY)
