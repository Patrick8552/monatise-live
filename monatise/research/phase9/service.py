"""Persistent bounded research capture using existing SDK/permit/journal boundaries.

An explicit reviewed plan supplies every possible connection attempt in advance.
There is no unbounded retry, entitlement renewal, paid backfill or automatic roll.
Current short-lived permits intentionally limit reconnects: a stale entitlement
review requires a fresh operator receipt, never an invented renewal.
"""
import asyncio
from dataclasses import dataclass
from pathlib import Path
import time

from monatise.research.databento.live_feed import CMELiveCapture
from monatise.research.institutional.models import digest, hash_required
from . import SAFETY


@dataclass(frozen=True)
class CaptureStep:
    scope: object
    permit: object
    mode: str
    review_reference: str


@dataclass(frozen=True)
class CapturePlan:
    steps: tuple[CaptureStep,...]
    entitlement_receipt_sha256: str
    cost_receipt_sha256: str
    no_additional_charges_verified: bool
    review_reference: str
    retry_delay_seconds: float = 1

    def __post_init__(self):
        hash_required(self.entitlement_receipt_sha256);hash_required(self.cost_receipt_sha256)
        if (not isinstance(self.steps,tuple) or not 1<=len(self.steps)<=8 or not self.review_reference
                or self.no_additional_charges_verified is not True
                or not 0<=self.retry_delay_seconds<=30):
            raise ValueError('bounded_entitled_zero_incremental_cost_plan_required')
        ids=set()
        for i,step in enumerate(self.steps):
            if step.mode not in {'INITIAL','RECOVER','NEW_SESSION','REVIEWED_ROLL'} or not step.review_reference:
                raise ValueError('explicit_session_or_recovery_review_required')
            if (i==0) != (step.mode=='INITIAL'): raise ValueError('initial_step_order_invalid')
            if step.permit.permit_id in ids:raise ValueError('distinct_one_use_attempt_permits_required')
            ids.add(step.permit.permit_id)
            if i:
                old=self.steps[i-1].scope
                if step.mode=='RECOVER' and (step.scope.contracts!=old.contracts or step.scope.start_ns!=old.start_ns
                        or step.scope.schemas!=old.schemas):raise ValueError('recovery_scope_changed')
                if step.mode=='NEW_SESSION' and (step.scope.start_ns<old.session_end_ns or step.scope.contracts!=old.contracts):
                    raise ValueError('reviewed_nonoverlapping_new_session_required')
                if step.mode=='REVIEWED_ROLL':
                    if (step.scope.start_ns<old.start_ns or
                            {c.metadata.product for c in step.scope.contracts}!={c.metadata.product for c in old.contracts}
                            or step.scope.contracts==old.contracts):raise ValueError('explicit_same_product_new_contract_roll_required')

    @property
    def sha256(self): return digest(self)


def _retryable(report):
    reasons=report['quality']['reasons']
    return bool(reasons) and not report['quality'].get('component_rejections') and all(r.startswith(('provider_disconnected_','provider_disconnect_or_error_')) for r in reasons)


class PersistentResearchService:
    def __init__(self, plan, spool, pipeline, *, client_factory=None, clock_ns=time.time_ns, rotation_policy=None, publisher=None, clock_refresh=None, bootstrap_review=None):
        self.plan,self.spool,self.pipeline = plan,spool,pipeline
        self.factory,self.clock_ns = client_factory,clock_ns
        self.rotation_policy,self.publisher,self.clock_refresh=rotation_policy,publisher,clock_refresh
        self.bootstrap_review=bootstrap_review

    async def run(self, *, api_key, output, permit_ledger, evidence_kind='AUTHENTIC_LIVE_CAPTURE'):
        output=Path(output)
        output.mkdir(parents=True,exist_ok=True);output.chmod(0o700)
        previous=self.spool.load('service')
        if previous is not None and previous['plan_sha256']!=self.plan.sha256:
            raise ValueError('new_plan_requires_separate_reviewed_spool')
        if previous and previous.get('terminated'):return dict(attempts=0,status='PLAN_TERMINATED_REVIEW_REQUIRED',**SAFETY)
        cursor_state=self.spool.load('feed_cursor')
        if previous and cursor_state and cursor_state['spool_records']!=self.spool.count:
            raise ValueError('interrupted_raw_cursor_boundary_requires_review')
        start=previous['next_step'] if previous else 0
        self.spool.replay(self.pipeline)
        reports=[]
        for index in range(start,len(self.plan.steps)):
            step=self.plan.steps[index]
            if (set(c.metadata.instrument_id for c in step.scope.contracts)-set(self.pipeline.gates)
                    or any(self.pipeline.gates[c.metadata.instrument_id].contract!=c for c in step.scope.contracts)):
                raise ValueError('preloaded_reviewed_pipeline_contract_required')
            # Reserve the attempt durably before connecting. An interrupted
            # attempt is never silently reused after restart.
            self.spool.checkpoint('service',dict(plan_sha256=self.plan.sha256,next_step=index+1,in_flight=True))
            checkpoints=(self.spool.load('feed_cursor') or {}).get('cursors') if step.mode=='RECOVER' else None
            if step.mode=='RECOVER' and checkpoints is None:raise ValueError('durable_recovery_cursor_required')
            if index==0 and self.bootstrap_review is not None:
                from monatise.research.native_futures.bootstrap import BootstrapReview
                if previous is not None or self.spool.count or not isinstance(self.bootstrap_review,BootstrapReview):
                    raise ValueError('bootstrap_requires_fresh_initial_attempt')
                checkpoints=self.bootstrap_review.checkpoints(self.pipeline,step.scope)
                self.spool.checkpoint('bootstrap',dict(review_sha256=self.bootstrap_review.sha256,
                    scope_sha256=step.scope.sha256,cursors=checkpoints,source_root=self.bootstrap_review.source_root))
            step.permit.validate(step.scope,self.clock_ns())
            def sink(schema,record,captured,ordinal,normalized):
                admitted=normalized is not None and schema!='definition'
                position,sha,_=self.spool.append(schema,record,capture_ns=captured,
                    delivery_id=f'{self.plan.sha256}:{index}:{schema}:{ordinal}',evidence_kind=evidence_kind,
                    admitted=admitted,clock_review=capture.active_clock_review)
                # Native control and verified replay-prefix duplicates do not
                # become market volume. The source bytes remain in both journals.
                # Definitions are independently verified against exact native
                # identity/economics by FeedState and retained raw. Equivalent
                # subscription snapshots need not share the pinned raw hash.
                if admitted:
                    self.pipeline.ingest(record,schema=schema,archive_sha256=sha,ordinal=position,
                        capture_ns=captured,admission_ns=captured,evidence_kind=evidence_kind,clock_review=capture.active_clock_review)
            def reject(schema,record,captured,ordinal,error_type):
                self.spool.append(schema,record,capture_ns=captured,
                    delivery_id=f'{self.plan.sha256}:{index}:{schema}:{ordinal}',evidence_kind=evidence_kind,
                    admitted=False,rejection_reason=error_type,clock_review=capture.active_clock_review)
                iid=getattr(record,'instrument_id',None)
                if iid in self.pipeline.gates:self.pipeline.gates[iid].transport_gap(schema,error_type,event_ns=getattr(record,'ts_event',None))
            journal_factory=None
            if self.rotation_policy is not None:
                from .rotation import RotatingNativeJournal
                journal_factory=lambda *a,**kw:RotatingNativeJournal(*a,policy=self.rotation_policy,**kw)
            capture=CMELiveCapture(step.scope,client_factory=self.factory,clock_ns=self.clock_ns,
                journal_factory=journal_factory,clock_refresh=self.clock_refresh)
            self.capture=capture
            def tick(state,now):
                if self.publisher is None:return
                lower,_=state.clock_review.bounds(now) if state.clock_review else (0,0)
                health=state.health(now)
                ready={(schema,iid) for schema in state.completed for iid in state.verified_definitions
                    if not state.quality_reasons and schema not in health['stalled_connections']}
                self.publisher.advance(self.pipeline,now_ns=now+min(0,lower),replay_ready=ready,
                    source_reference=f'{self.plan.sha256}:{index}:verified-native-replay',interval_watermarks=state.interval_watermarks)
            report=await capture.run(api_key=api_key,permit=step.permit,permit_ledger=permit_ledger,
                output=output/f'attempt-{index:02d}',checkpoints=checkpoints,
                recovery_review_reference=step.review_reference if checkpoints else None,
                bootstrap_prefixes=self.bootstrap_review.prefix_reviews() if index==0 and self.bootstrap_review else None,
                evidence_kind=evidence_kind,record_sink=sink,rejection_sink=reject,tick_sink=tick,
                checkpoint_sink=lambda value:self.spool.checkpoint('feed_cursor',dict(cursors=value,spool_records=self.spool.count)))
            reports.append(report)
            self.spool.checkpoint('service',dict(plan_sha256=self.plan.sha256,next_step=index+1,
                in_flight=False,last_report_sha256=digest(report)))
            if index+1>=len(self.plan.steps):break
            mode=self.plan.steps[index+1].mode
            if mode=='RECOVER':
                if not _retryable(report):
                    self.spool.checkpoint('service',dict(plan_sha256=self.plan.sha256,next_step=index+1,
                        terminated=True,reason='non_retryable_capture_outcome'))
                    break
                await asyncio.sleep(self.plan.retry_delay_seconds)
            elif report['quality']['quarantined']:
                self.spool.checkpoint('service',dict(plan_sha256=self.plan.sha256,next_step=index+1,
                    terminated=True,reason='quarantined_capture_outcome'))
                break
        return dict(version='phase9-persistent-research-v1',plan_sha256=self.plan.sha256,
            attempts=len(reports),reports=reports,spool_records=self.spool.count,
            analytical_publication=self.publisher.summary() if self.publisher else None,
            complete_exchange_continuity=False,fresh_live_operation_verified=False,**SAFETY)
