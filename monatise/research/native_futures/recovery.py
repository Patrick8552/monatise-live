"""Bounded native Live API recovery using Databento's event-time/count recipe.

This is application orchestration of documented subscribe(start=...), not the
SDK's resume-at-now reconnect policy. Provider errors never cause blind retries.
Original failed attempts remain sealed and are not relabelled healthy.
"""
from dataclasses import dataclass
from monatise.research.institutional.models import digest

VERSION='DATABENTO_EVENT_TIME_COUNT_V1'


@dataclass(frozen=True)
class RecoveryPolicy:
    maximum_attempts: int=3
    total_seconds: int=900
    delay_seconds: float=1
    version: str=VERSION

    def __post_init__(self):
        if (self.version!=VERSION or type(self.maximum_attempts) is not int or
                not 1<=self.maximum_attempts<=3 or type(self.total_seconds) is not int or
                not 1<=self.total_seconds<=900 or not 1<=self.delay_seconds<=30):
            raise ValueError('finite_native_recovery_policy_required')


def recoverable(report):
    quality=report['quality']
    reasons=set(quality['reasons'])|{'connection_stalled_'+s for s in quality.get('stalled_connections',())}
    return bool(reasons) and not quality.get('component_rejections') and all(
        r.startswith(('connection_stalled_','provider_disconnected_','provider_disconnect_or_error_')) for r in reasons)


def validate_recovery_scope(original,current,remaining):
    """Fresh entitlement/clock receipts may change; symbols/schemas cannot."""
    from monatise.research.institutional.models import encode
    old,new=encode(original),encode(current)
    allowed={'capability','clock_review','duration_seconds'}
    if (any(new[k]!=v for k,v in old.items() if k not in allowed) or
            not 1<=current.duration_seconds<=remaining or
            current.capability.dataset!=original.capability.dataset or
            current.capability.schemas!=original.capability.schemas):
        raise ValueError('recovery_must_preserve_original_data_scope')


def decode_scope(value):
    from monatise.research.databento.live_models import LiveScope,ClockReview
    from monatise.research.databento.datasets import DatasetCapability
    from monatise.research.phase10.source import decode_contract
    v=dict(value);v['contracts']=tuple(decode_contract(c) for c in v['contracts'])
    cap=dict(v['capability']);cap['schemas']=tuple(cap['schemas']);v['capability']=DatasetCapability(**cap)
    v['clock_review']=ClockReview(**v['clock_review']) if v['clock_review'] else None
    for key in ('publishers','initial_schema_starts'):v[key]=tuple(tuple(x) for x in v[key])
    v['schemas']=tuple(v['schemas'])
    return LiveScope(**v)


class ReplayAudit:
    """Recompute admission and counted overlap from hash-verified native rows.

    No collector assertion alone can make a replay duplicate disappear from
    the reader. Each attempt must start at the previous committed cursor.
    """
    def __init__(self,original,receipts):
        self.original=original;self.receipts=receipts;self.index=-1;self.state=None
        self.duplicates=0

    def ingest(self,index,schema,record,*,at,ordinal,arrival,clock,admitted,rejection,position):
        import databento_dbn as dn
        from monatise.research.databento.live_state import FeedState
        if index!=self.index:
            if index!=self.index+1 or index>=len(self.receipts):raise ValueError('source_recovery_attempt_order')
            receipt=self.receipts[index]
            if receipt['index']!=index or receipt['spool_records_before']!=position-1:
                raise ValueError('source_recovery_prefix_boundary')
            scope=decode_scope(receipt['step']['scope'])
            validate_recovery_scope(self.original,scope,self.original.duration_seconds)
            from monatise.research.databento.live_models import LivePermit
            LivePermit(**receipt['step']['permit']).validate(scope,receipt['prepared_at_ns'])
            if receipt['step']['mode']!=('RECOVER' if index else 'INITIAL'):
                raise ValueError('source_recovery_step_mode')
            checkpoints=self.state.checkpoint() if self.state else None
            if digest(checkpoints)!=digest(receipt['checkpoints']):raise ValueError('source_recovery_cursor_mismatch')
            self.state=FeedState(scope,checkpoints=checkpoints,
                recovery_review_reference='verified-source-bound-recovery' if index else None,
                native_information=True,count_recovery=bool(index))
            self.index=index
        # Every spool row binds its contemporaneous review. The read-only audit
        # must use that receipt, including after the collector renews it; retaining
        # only the attempt's initial clock would falsely reject a long capture.
        self.state.clock_review=clock
        self.state.clock_history=[clock] if clock is not None else []
        try:
            normalized=self.state.ingest(schema,record,capture_ns=at,ordinal=ordinal,arrival_ns=arrival)
        except (ValueError,TypeError,AttributeError,ArithmeticError):
            if not rejection or admitted:raise ValueError('source_recovery_unreported_record_rejection') from None
            return
        expected=normalized is not None and schema!='definition'
        if expected!=bool(admitted) or rejection:raise ValueError('source_recovery_admission_mismatch')
        if not admitted and not isinstance(record,(dn.SystemMsg,dn.SymbolMappingMsg,dn.ErrorMsg,dn.InstrumentDefMsg)):
            self.duplicates+=1
