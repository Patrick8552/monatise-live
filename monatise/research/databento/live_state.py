"""CME native live state, exact cursor recovery and fail-closed quality gates."""
from collections import defaultdict
from dataclasses import dataclass,field
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

    def accept(self,event_ns,native_hash):
        timestamp_ns(event_ns)
        if self.event_ns is not None and event_ns<self.event_ns:
            if self.replay_prefix:return False
            raise ValueError('market_event_order_regressed')
        if self.event_ns==event_ns and self.skipped<len(self.replay_prefix):
            if native_hash!=self.replay_prefix[self.skipped]:
                raise ValueError('replay_equal_timestamp_prefix_mismatch')
            self.skipped+=1;return False
        if self.event_ns!=event_ns:
            if self.skipped<len(self.replay_prefix):raise ValueError('replay_missing_tied_records')
            self.event_ns=event_ns;self.hashes_at_event=[];self.replay_prefix=();self.skipped=0
        if len(self.hashes_at_event)>=10000:raise ValueError('cursor_tie_capacity_exceeded')
        self.hashes_at_event.append(native_hash)
        return True

    def snapshot(self):return dict(event_ns=self.event_ns,hashes_at_event=list(self.hashes_at_event))

    def finish_recovery(self):
        if self.skipped<len(self.replay_prefix):raise ValueError('replay_prefix_incomplete')
        self.replay_prefix=();self.skipped=0

    @classmethod
    def recover(cls,value):
        event=value['event_ns'];hashes=tuple(value['hashes_at_event'])
        if event is not None:timestamp_ns(event)
        if (len(hashes)>10000 or event is None and hashes or any(not isinstance(h,str) or len(h)!=64 for h in hashes)):
            raise ValueError('reviewed_native_cursor_required')
        for h in hashes:hash_required(h)
        return cls(event_ns=event,hashes_at_event=list(hashes),replay_prefix=hashes)


class FeedState:
    def __init__(self,scope, *, checkpoints=None,recovery_review_reference=None):
        self.scope=scope;self.contracts={c.metadata.instrument_id:c for c in scope.contracts}
        self.started={};self.completed=set();self.acknowledged=set();self.last_message={}
        self.latest={};self.quotes={};self.verified_definitions=set();self.quality_reasons=set();self.counts=defaultdict(int)
        self.cursors={};self.normalized=[]
        if checkpoints and not recovery_review_reference:raise ValueError('explicit_recovery_review_required')
        for schema in scope.schemas:
            for iid in self.contracts:
                key=f'{schema}:{iid}'
                self.cursors[key]=Cursor.recover(checkpoints[key]) if checkpoints and key in checkpoints else Cursor()

    def quarantine(self,reason):self.quality_reasons.add(reason)

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
        lower,upper=self.scope.clock_bounds(capture_ns)
        if (record.publisher_id!=contract.metadata.publisher_id or not event<=received<=capture_ns+upper
                or not (contract.metadata.event_ns if schema=='definition' else self.scope.start_ns)<=event<self.scope.session_end_ns
                or capture_ns+max(0,upper)>=self.scope.session_end_ns or int(getattr(record,'flags',0))&(4|8|32)):
            raise ValueError('live_record_identity_clocks_session_or_quality_rejected')
        key=f'{schema}:{iid}';previous=self.cursors[key]
        cursor=Cursor(previous.event_ns,list(previous.hashes_at_event),previous.replay_prefix,previous.skipped)
        if schema=='definition':
            value=native_definition(record,capability=self.scope.capability,
                publishers={p:(d,v) for p,d,v in self.scope.publishers},as_of_ns=capture_ns+max(0,upper))
            signature=lambda c:(c.identity,c.tick_size,c.multiplier,c.price_unit,c.metadata.native_terms)
            if signature(value)!=signature(contract):raise ValueError('contract_roll_or_definition_economics_changed')
            result=dict(contract=encode(value),record_sha256=native_hash)
        else:
            result=encode(AdvancedAdapters(identity=contract.metadata,enabled_schemas=(schema,)).normalize(schema,record))
        accepted=cursor.accept(event,native_hash)
        if schema=='definition':self.verified_definitions.add(iid)
        else:
            self.latest[(schema,iid)]=received
            if schema=='mbp-1':self.quotes[iid]=result['payload'][0]
        self.cursors[key]=cursor
        if not accepted:
            self.counts['replay_duplicates_skipped']+=1;return None
        self.counts[schema]+=1
        result=dict(result,capture_ns=capture_ns,native_ordinal=ordinal,
                    capture_utc_bounds_ns=(capture_ns+lower,capture_ns+upper),
                    clock_review_sha256=digest(self.scope.clock_review) if self.scope.clock_review else None,
                    availability_basis='ACTUAL_LOCAL_LIVE_CAPTURE',context_only=True,**SAFETY)
        self.normalized.append(result)
        if len(self.normalized)>2048:self.normalized.pop(0)
        return result

    def health(self,now_ns):
        timestamp_ns(now_ns)
        try:lower,upper=self.scope.clock_bounds(now_ns)
        except ValueError:
            self.quarantine('independent_clock_review_expired_or_invalid');lower=upper=0
        stalled=[s for s in self.scope.schemas if now_ns-self.last_message.get(s,self.started.get(s,now_ns))>
                 (self.scope.heartbeat_seconds+10)*10**9]
        stale=[f'{s}:{i}' for s in self.scope.schemas if s!='definition' for i in self.contracts
               if not 0<=now_ns+upper-self.latest.get((s,i),0)<=self.scope.maximum_market_age_ns]
        unusable_quotes=[i for i in self.contracts if 'mbp-1' in self.scope.schemas and (i not in self.quotes
            or self.quotes[i][0] is None or self.quotes[i][3] is None
            or self.quotes[i][0]==self.quotes[i][3] or min(self.quotes[i][1],self.quotes[i][4])<=0)]
        ready=(not self.quality_reasons and not stalled and not stale and not unusable_quotes
               and self.completed==set(self.scope.schemas) and self.verified_definitions==set(self.contracts)
               and now_ns+max(0,upper)<self.scope.session_end_ns)
        return dict(status='CAPTURED_CONTEXT_FRESH' if ready else 'UNAVAILABLE',
            quarantined=bool(self.quality_reasons or stalled or self.completed!=set(self.scope.schemas)
                             or self.verified_definitions!=set(self.contracts)),reasons=sorted(self.quality_reasons),
            stalled_connections=stalled,stale_market_inputs=stale,replay_completed=sorted(self.completed),
            unusable_quote_instruments=unusable_quotes,
            definitions_verified=sorted(self.verified_definitions),counts=dict(self.counts),
            local_clock_offset_bounds_ns=(lower,upper),
            clock_review_sha256=digest(self.scope.clock_review) if self.scope.clock_review else None,
            authenticated_clock_certified=False,
            complete_exchange_continuity_certified=False,context_only=True,**SAFETY)
