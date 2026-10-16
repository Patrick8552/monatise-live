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
import queue as thread_queue

from monatise.research.institutional.models import encode,digest
from .live_models import LiveScope,consume_permit,SAFETY
from .live_state import FeedState
from .live_journal import NativeJournal
from .semantics import VERSION as NORMALIZATION_VERSION


def sdk_client(key,heartbeat_seconds):
    if version('databento')!='0.87.0' or version('databento-dbn')!='0.70.0':
        raise ValueError('reviewed_pinned_live_SDK_versions_required')
    from .sdk_transport import OwnedSDKClient
    return OwnedSDKClient(key,heartbeat_seconds)


class CMELiveCapture:
    def __init__(self,scope, *, client_factory=None,clock_ns=time.time_ns,queue_capacity=2048,journal_factory=None,clock_refresh=None,liveness_clock_ns=time.perf_counter_ns):
        if not isinstance(scope,LiveScope) or type(queue_capacity) is not int or not 1<=queue_capacity<=2048:
            raise ValueError('prepared_bounded_live_capture_required')
        self.scope,self.factory,self.clock_ns=scope,client_factory or sdk_client,clock_ns
        self.liveness_clock_ns=liveness_clock_ns
        self.queue_capacity=queue_capacity
        self.journal_factory,self.clock_refresh=journal_factory,clock_refresh

    async def run(self, *, api_key,permit,permit_ledger,output,checkpoints=None,recovery_review_reference=None,
                  bootstrap_prefixes=None,evidence_kind='AUTHENTIC_LIVE_CAPTURE',record_sink=None,checkpoint_sink=None,rejection_sink=None,tick_sink=None,metrics_sink=None):
        if not isinstance(api_key,str) or not api_key.strip():raise ValueError('private_live_key_required')
        if evidence_kind=='ENGINEERING_SYNTHETIC' and self.factory is sdk_client:
            raise ValueError('fixtures_cannot_open_real_live_client')
        state=FeedState(self.scope,checkpoints=checkpoints,recovery_review_reference=recovery_review_reference,bootstrap_prefixes=bootstrap_prefixes,liveness_clock_ns=self.liveness_clock_ns)
        self.state=state
        self.active_clock_review=state.clock_review
        self.active_arrival_ns=None
        clock_reviews=[]
        output=Path(output)
        if output.exists():raise ValueError('fresh_private_live_output_required')
        consume_permit(permit_ledger,permit,self.scope,self.clock_ns())
        output.mkdir(parents=True,exist_ok=False);output.chmod(0o700)
        journals={};clients=[];watchers=[];closing=False;overflow=threading.Event()
        queue=thread_queue.Queue(maxsize=self.queue_capacity);loop=asyncio.get_running_loop()
        wake=asyncio.Event()
        manifests={};transport_events=[];transport_lock=threading.Lock()
        callback_last={};callback_counts={};max_queue_depth=0;max_delivery_lag_ns=0
        max_processing_ns=0;max_tick_ns=0;stop_evidence=None;client_diagnostics={}
        from .latency import Latencies
        latencies=Latencies();overflow_count=0;overflow_chain=digest([])
        # Public SDK iteration owns network backpressure. An application worker
        # can wait for this bounded queue; the networking loop never waits here.
        high=low=None
        transport_history=[];probe_task=None;next_probe=0

        def transport_event(schema,stage,exc=None):
            with transport_lock:
                if len(transport_events)<32:
                    transport_events.append(dict(schema=schema,stage=stage,observed_at_ns=self.clock_ns(),
                        error_type=type(exc).__name__ if exc is not None else None,
                        errno=getattr(exc,"errno",None) if type(getattr(exc,"errno",None)) is int else None))

        def callback(schema,blocking_delivery=False):
            def receive(record):
                nonlocal overflow_count,overflow_chain
                if closing and not blocking_delivery:return
                begin=time.perf_counter_ns()
                captured=self.clock_ns()
                with transport_lock:
                    callback_last[schema]=captured;callback_counts[schema]=callback_counts.get(schema,0)+1
                inserted=time.perf_counter_ns()
                item=(schema,record,captured,inserted)
                try:
                    if blocking_delivery:
                        while True:
                            try:queue.put(item,timeout=.1);break
                            except thread_queue.Full:
                                if closing:
                                    # Retain the SDK record already yielded at
                                    # shutdown; final drain frees the queue below.
                                    continue
                    else:queue.put_nowait(item)
                except thread_queue.Full:
                    import hashlib
                    with transport_lock:
                        overflow_count+=1;overflow_chain=digest([overflow_chain,schema,captured,hashlib.sha256(bytes(record)).hexdigest()])
                    overflow.set()
                finally:latencies.record('queue_insertion',time.perf_counter_ns()-inserted)
                loop.call_soon_threadsafe(wake.set)
                latencies.record('callback_execution',time.perf_counter_ns()-begin)
            return receive

        def callback_failed(schema,exc):
            transport_event(schema,'callback',exc);overflow.set()

        async def watch(schema,client):
            try:
                await client.wait_for_close()
                if not closing:
                    transport_event(schema,'unexpected_close')
                    state.quarantine('provider_disconnected_'+schema)
            except Exception as exc:
                if not closing:
                    transport_event(schema,'wait_for_close',exc)
                    state.quarantine('provider_disconnect_or_error_'+schema)

        def deliver(schema,record,captured,ordinal):
            self.active_clock_review=state.review_at(captured)
            try:
                normalized=state.ingest(schema,record,capture_ns=captured,ordinal=ordinal,arrival_ns=self.active_arrival_ns)
            except (ValueError,TypeError,AttributeError,ArithmeticError) as exc:
                state.reject_component(schema,record,'native_record_or_recovery_validation_failed')
                if rejection_sink is not None:rejection_sink(schema,record,captured,ordinal,type(exc).__name__)
                return
            # Storage/sink failures are operational faults, not malformed feed
            # records, and must escape to the capture shutdown boundary.
            if record_sink is not None:
                started=time.perf_counter_ns();record_sink(schema,record,captured,ordinal,normalized)
                latencies.record('record_sink',time.perf_counter_ns()-started)
            if checkpoint_sink is not None:
                started=time.perf_counter_ns();checkpoint_sink(state.checkpoint())
                latencies.record('checkpoint',time.perf_counter_ns()-started)

        failure=None;clock_refresh_task=None;failures=[]
        def failure_diagnostic(exc,stage,schema=None):
            import traceback
            # Only known local codes; arbitrary provider/OS exception text may
            # contain credentials even if it looks like a lowercase identifier.
            codes={'native_monotonic_arrival_order_required','live_journal_limit_or_clock_failure',
                'cross_segment_capture_clock_regression','full_session_native_storage_limit',
                'full_session_segment_limit','durable_spool_capacity_exceeded','durable_delivery_revision',
                'positive_monotonic_arrival_required','independent_clock_review_expired_or_not_yet_available',
                'capture_has_no_contemporaneous_clock_review'}
            code=str(exc)
            safe=code if isinstance(exc,ValueError) and code in codes else None
            return dict(stage=stage,schema=schema,error_type=type(exc).__name__,local_error_code=safe,
                frames=[dict(module=Path(f.filename).name,function=f.name,line=f.lineno) for f in traceback.extract_tb(exc.__traceback__)[-8:]],
                exception_text_omitted=safe is None)
        try:
            for schema in self.scope.schemas:
                permit.validate(self.scope,self.clock_ns())
                if self.journal_factory is None:
                    journals[schema]=NativeJournal(output/schema,schema=schema,scope=self.scope,evidence_kind=evidence_kind,arrival_order=True)
                else:
                    journals[schema]=self.journal_factory(output/schema,schema=schema,scope=self.scope,
                        evidence_kind=evidence_kind,checkpoint=state.checkpoint,arrival_order=True)
                client=self.factory(api_key,self.scope.heartbeat_seconds);clients.append(client)
                client.add_callback(callback(schema,getattr(client,"blocking_delivery",False)),exception_callback=lambda exc,schema=schema:callback_failed(schema,exc))
                await asyncio.to_thread(client.subscribe,dataset='GLBX.MDP3',schema=schema,
                    symbols=[c.metadata.instrument_id for c in self.scope.contracts],stype_in='instrument_id',
                    start=state.replay_start(schema))
                state.started[schema]=self.clock_ns()
                state.liveness_started[schema]=self.liveness_clock_ns()
                watchers.append(asyncio.create_task(watch(schema,client)))
            # Finish all subscriptions before any replay can fill the handoff.
            for client in clients:client.start()
            end=loop.time()+self.scope.duration_seconds
            next_tick=loop.time()
            while loop.time()<end:
                if probe_task is not None and probe_task.done():
                    transport_history.append(dict(observed_at_ns=self.clock_ns(),clients=probe_task.result()))
                    transport_history=transport_history[-8:];probe_task=None
                if probe_task is None and loop.time()>=next_probe:
                    async def probe():
                        async def one(schema,client):
                            diagnostic=getattr(client,'diagnostics',None)
                            if diagnostic is None:return schema,{'instrumentation_unavailable':True}
                            try:return schema,await asyncio.to_thread(diagnostic)
                            except Exception:return schema,{'diagnostic_failed':True}
                        return dict(await asyncio.gather(*(one(s,c) for s,c in zip(self.scope.schemas,clients))))
                    probe_task=asyncio.create_task(probe());next_probe=loop.time()+10
                if (self.clock_refresh is not None and state.clock_review is not None and clock_refresh_task is None
                        and self.clock_ns()>=state.clock_review.expires_ns-60*10**9):
                    clock_refresh_task=asyncio.create_task(asyncio.to_thread(self.clock_refresh))
                if clock_refresh_task is not None and clock_refresh_task.done():
                    review=clock_refresh_task.result();clock_refresh_task=None
                    review.bounds(self.clock_ns());state.update_clock_review(review)
                    clock_reviews.append(encode(review))
                if tick_sink is not None and loop.time()>=next_tick:
                    tick_started=time.perf_counter_ns()
                    tick_sink(state,self.clock_ns());next_tick=loop.time()+1
                    max_tick_ns=max(max_tick_ns,time.perf_counter_ns()-tick_started)
                if overflow.is_set():state.quarantine('local_callback_or_queue_backpressure')
                health=state.health(self.clock_ns())
                if state.quality_reasons or health['stalled_connections']:
                    if health['stalled_connections']:
                        with transport_lock:
                            stop_evidence=dict(observed_at_ns=self.clock_ns(),
                                stalled_connections=list(health['stalled_connections']),
                                last_processed_capture_ns=dict(state.last_message),
                                last_callback_capture_ns=dict(callback_last),queue_depth=queue.qsize())
                        # Final draining must never erase an observed liveness failure.
                        for schema in health['stalled_connections']:state.quarantine('connection_stalled_'+schema)
                    break
                try:
                    schema,record,captured,enqueued=queue.get_nowait()
                except thread_queue.Empty:
                    wake.clear()
                    if not queue.empty():continue
                    try:await asyncio.wait_for(wake.wait(),timeout=min(.1,max(.001,end-loop.time())))
                    except TimeoutError:pass
                    continue
                max_queue_depth=max(max_queue_depth,queue.qsize()+1)
                latencies.record('queue_residence',time.perf_counter_ns()-enqueued)
                max_delivery_lag_ns=max(max_delivery_lag_ns,max(0,self.clock_ns()-captured))
                processing_started=time.perf_counter_ns()
                self.active_arrival_ns=enqueued
                ordinal,_=journals[schema].append(record,capture_ns=captured,arrival_ns=enqueued)
                latencies.record('journal_append',time.perf_counter_ns()-processing_started)
                for metric,elapsed in getattr(journals[schema],'last_append_timings',{}).items():latencies.record(metric,elapsed)
                deliver(schema,record,captured,ordinal)
                max_processing_ns=max(max_processing_ns,time.perf_counter_ns()-processing_started)
                latencies.record('consumer_processing',time.perf_counter_ns()-processing_started)
                latencies.record('end_to_end_ingestion',time.perf_counter_ns()-enqueued)
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            state.quarantine('capture_cancelled');failure='CancelledError'
            raise
        except Exception as exc:
            state.quarantine('capture_transport_or_storage_failure');failure=type(exc).__name__;failures.append(failure_diagnostic(exc,'capture'))
        finally:
            closing=True
            if probe_task is not None:
                await asyncio.gather(probe_task,return_exceptions=True)
            # Capture loop/socket state before terminate destroys SDK state.
            # Diagnostics cannot reopen, resume or reconnect a subscription.
            for schema,client in zip(self.scope.schemas,clients):
                diagnostic=getattr(client,'diagnostics',None)
                if diagnostic is not None:
                    try:client_diagnostics[schema]=await asyncio.to_thread(diagnostic)
                    except Exception:client_diagnostics[schema]={'diagnostic_failed':True}
            if clock_refresh_task is not None:
                clock_refresh_task.cancel()
                await asyncio.gather(clock_refresh_task,return_exceptions=True)
            for client in clients:
                try:client.terminate()
                except Exception:state.quarantine('client_shutdown_failed')
            async def drain_pending():
                while True:
                    try:schema,record,captured,enqueued=queue.get_nowait()
                    except thread_queue.Empty:return
                    try:
                        self.active_arrival_ns=enqueued
                        ordinal,_=journals[schema].append(record,capture_ns=captured,arrival_ns=enqueued)
                        deliver(schema,record,captured,ordinal)
                    except Exception as exc:
                        state.quarantine('drain_record_or_storage_failure')
                        if len(failures)<32:failures.append(failure_diagnostic(exc,'drain',schema))
            if watchers:
                try:
                    until=loop.time()+5
                    while not all(t.done() for t in watchers) and loop.time()<until:
                        await drain_pending();await asyncio.sleep(.01)
                    if not all(t.done() for t in watchers):raise TimeoutError
                    await asyncio.gather(*watchers,return_exceptions=True)
                except TimeoutError:state.quarantine('client_shutdown_timeout')
            for client in clients:
                close=getattr(client,'close',None)
                if close is not None:
                    try:await asyncio.to_thread(close)
                    except Exception:state.quarantine('owned_SDK_loop_shutdown_failed')
            if overflow.is_set():state.quarantine('local_callback_or_queue_backpressure')
            # Do not silently drop records already queued at the deadline.
            await drain_pending()
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
                normalization_tail=state.normalized,failure_type=failure,failure_diagnostics=failures,transport_events=transport_events,
                capture_clock_semantics="ORIGINAL_UTC_WALL_AND_MONOTONIC_ARRIVAL_V2",
                bootstrap_clock_translations=state.bootstrap_clock_translations,
                runtime=dict(databento=version('databento'),databento_dbn=version('databento-dbn')),
                normalization_semantics=NORMALIZATION_VERSION,
                durable_spool_latency_distributions=metrics_sink() if metrics_sink is not None else {},
                delivery_diagnostics=dict(callback_counts=dict(callback_counts),last_callback_capture_ns=dict(callback_last),
                    latency_distributions=latencies.summary(),callback_queue_waiting=False,
                    application_iterator_handoff_waiting=any(getattr(c,"blocking_delivery",False) for c in clients),
                    liveness_clock="MONOTONIC_ARRIVAL",
                    unretained_overflow_records=overflow_count,unretained_overflow_hash_chain=overflow_chain,
                    queue_capacity=self.queue_capacity,pause_high_watermark=high,resume_low_watermark=low,
                    transport_history=transport_history,
                    max_queue_depth=max_queue_depth,max_delivery_lag_ns=max_delivery_lag_ns,
                    max_record_processing_ns=max_processing_ns,max_publication_tick_ns=max_tick_ns,
                    stop_evidence=stop_evidence,client_transports=client_diagnostics,thresholds_unchanged=True),
                clock_reviews=clock_reviews,automatic_retries=0,connection_count=len(clients),evidence_kind=evidence_kind,**SAFETY)
            p=output/'report.json';p.write_text(json.dumps(encode(report),sort_keys=True,indent=2));p.chmod(0o600)
        return report
