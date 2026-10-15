"""Explicit read-only CME capture; no subscription purchase or engine activation.

One schema per SDK connection makes control-message attribution unambiguous.
No reconnect or retry is automatic: reviewed cursor recovery needs a new permit.
"""
import asyncio
from importlib.metadata import version
import json
from pathlib import Path
import threading
import time

from monatise.research.institutional.models import encode,digest
from .live_models import LiveScope,consume_permit,SAFETY
from .live_state import FeedState
from .live_journal import NativeJournal


def sdk_client(key,heartbeat_seconds):
    if version('databento')!='0.87.0' or version('databento-dbn')!='0.70.0':
        raise ValueError('reviewed_pinned_live_SDK_versions_required')
    import databento
    return databento.Live(key=key,heartbeat_interval_s=heartbeat_seconds,reconnect_policy='none')


class CMELiveCapture:
    def __init__(self,scope, *, client_factory=None,clock_ns=time.time_ns,queue_capacity=2048,journal_factory=None,clock_refresh=None):
        if not isinstance(scope,LiveScope) or type(queue_capacity) is not int or not 1<=queue_capacity<=2048:
            raise ValueError('prepared_bounded_live_capture_required')
        self.scope,self.factory,self.clock_ns=scope,client_factory or sdk_client,clock_ns
        self.queue_capacity=queue_capacity
        self.journal_factory,self.clock_refresh=journal_factory,clock_refresh

    async def run(self, *, api_key,permit,permit_ledger,output,checkpoints=None,recovery_review_reference=None,
                  evidence_kind='AUTHENTIC_LIVE_CAPTURE',record_sink=None,checkpoint_sink=None,rejection_sink=None,tick_sink=None):
        if not isinstance(api_key,str) or not api_key.strip():raise ValueError('private_live_key_required')
        if evidence_kind=='ENGINEERING_SYNTHETIC' and self.factory is sdk_client:
            raise ValueError('fixtures_cannot_open_real_live_client')
        state=FeedState(self.scope,checkpoints=checkpoints,recovery_review_reference=recovery_review_reference)
        self.state=state
        self.active_clock_review=state.clock_review
        clock_reviews=[]
        output=Path(output)
        if output.exists():raise ValueError('fresh_private_live_output_required')
        consume_permit(permit_ledger,permit,self.scope,self.clock_ns())
        output.mkdir(parents=True,exist_ok=False);output.chmod(0o700)
        journals={};clients=[];watchers=[];closing=False;overflow=threading.Event()
        queue=asyncio.Queue(maxsize=self.queue_capacity);loop=asyncio.get_running_loop()
        pending=threading.BoundedSemaphore(self.queue_capacity)
        manifests={}

        def callback(schema):
            def receive(record):
                if closing:return
                if not pending.acquire(blocking=False):overflow.set();return
                captured=self.clock_ns()
                def deliver():
                    try:queue.put_nowait((schema,record,captured))
                    except asyncio.QueueFull:overflow.set()
                    finally:pending.release()
                loop.call_soon_threadsafe(deliver)
            return receive

        def callback_failed(exc):overflow.set()

        async def watch(schema,client):
            try:
                await client.wait_for_close()
                if not closing:state.quarantine('provider_disconnected_'+schema)
            except Exception:
                if not closing:state.quarantine('provider_disconnect_or_error_'+schema)

        def deliver(schema,record,captured,ordinal):
            self.active_clock_review=state.review_at(captured)
            try:
                normalized=state.ingest(schema,record,capture_ns=captured,ordinal=ordinal)
            except (ValueError,TypeError,AttributeError,ArithmeticError) as exc:
                state.reject_component(schema,record,'native_record_or_recovery_validation_failed')
                if rejection_sink is not None:rejection_sink(schema,record,captured,ordinal,type(exc).__name__)
                return
            # Storage/sink failures are operational faults, not malformed feed
            # records, and must escape to the capture shutdown boundary.
            if record_sink is not None:record_sink(schema,record,captured,ordinal,normalized)
            if checkpoint_sink is not None:checkpoint_sink(state.checkpoint())

        failure=None
        try:
            for schema in self.scope.schemas:
                permit.validate(self.scope,self.clock_ns())
                if self.journal_factory is None:
                    journals[schema]=NativeJournal(output/schema,schema=schema,scope=self.scope,evidence_kind=evidence_kind)
                else:
                    journals[schema]=self.journal_factory(output/schema,schema=schema,scope=self.scope,
                        evidence_kind=evidence_kind,checkpoint=state.checkpoint)
                client=self.factory(api_key,self.scope.heartbeat_seconds);clients.append(client)
                client.add_callback(callback(schema),exception_callback=callback_failed)
                await asyncio.to_thread(client.subscribe,dataset='GLBX.MDP3',schema=schema,
                    symbols=[c.metadata.instrument_id for c in self.scope.contracts],stype_in='instrument_id',
                    start=state.replay_start(schema))
                state.started[schema]=self.clock_ns();client.start()
                watchers.append(asyncio.create_task(watch(schema,client)))
            end=loop.time()+self.scope.duration_seconds
            next_tick=loop.time()
            while loop.time()<end:
                if self.clock_refresh is not None and state.clock_review is not None and self.clock_ns()>=state.clock_review.expires_ns-60*10**9:
                    review=await asyncio.to_thread(self.clock_refresh)
                    review.bounds(self.clock_ns());state.update_clock_review(review)
                    clock_reviews.append(encode(review))
                if tick_sink is not None and loop.time()>=next_tick:
                    tick_sink(state,self.clock_ns());next_tick=loop.time()+1
                if overflow.is_set():state.quarantine('local_callback_or_queue_backpressure')
                health=state.health(self.clock_ns())
                if state.quality_reasons or health['stalled_connections']:break
                try:
                    schema,record,captured=await asyncio.wait_for(queue.get(),timeout=min(.1,max(.001,end-loop.time())))
                except TimeoutError:continue
                ordinal,_=journals[schema].append(record,capture_ns=captured)
                deliver(schema,record,captured,ordinal)
        except asyncio.CancelledError:
            state.quarantine('capture_cancelled');failure='CancelledError'
            raise
        except Exception as exc:
            state.quarantine('capture_transport_or_storage_failure');failure=type(exc).__name__
        finally:
            closing=True
            for client in clients:
                try:client.terminate()
                except Exception:state.quarantine('client_shutdown_failed')
            if watchers:
                try:await asyncio.wait_for(asyncio.gather(*watchers,return_exceptions=True),timeout=5)
                except TimeoutError:state.quarantine('client_shutdown_timeout')
            if overflow.is_set():state.quarantine('local_callback_or_queue_backpressure')
            # Do not silently drop records already queued at the deadline.
            while not queue.empty():
                schema,record,captured=queue.get_nowait()
                try:
                    ordinal,_=journals[schema].append(record,capture_ns=captured)
                    deliver(schema,record,captured,ordinal)
                except Exception:state.quarantine('drain_record_or_storage_failure')
            health=state.health(self.clock_ns())
            if tick_sink is not None:
                try:tick_sink(state,self.clock_ns())
                except Exception:state.quarantine('analytical_publication_failure')
            for schema,journal in journals.items():
                try:manifests[schema]=journal.close(quality=health,checkpoint=state.checkpoint())
                except Exception:state.quarantine('journal_seal_failed')
            health=state.health(self.clock_ns())
            report=dict(version='CME-live-capture-v1',scope=encode(self.scope),scope_sha256=self.scope.sha256,
                permit_sha256=digest(permit),quality=health,checkpoint=state.checkpoint(),journals=manifests,
                normalization_tail=state.normalized,failure_type=failure,
                runtime=dict(databento=version('databento'),databento_dbn=version('databento-dbn')),
                clock_reviews=clock_reviews,automatic_retries=0,connection_count=len(clients),evidence_kind=evidence_kind,**SAFETY)
            p=output/'report.json';p.write_text(json.dumps(encode(report),sort_keys=True,indent=2));p.chmod(0o600)
        return report
