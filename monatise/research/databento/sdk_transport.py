"""Public SDK async iteration on an owned loop, with bounded application handoff.

Only documented Live construction, subscribe, async iteration and terminate are
used. The SDK owns buffering/backpressure. No private session, protocol, socket,
queue or buffer is inspected or changed. No automatic reconnect/retry.
"""
import asyncio
from concurrent.futures import Future, TimeoutError as FutureTimeout
import threading
import time


class OwnedSDKClient:
    # The application handoff may wait on a worker thread, never the SDK loop.
    blocking_delivery = True

    def __init__(self, key, heartbeat_seconds, *, builder=None):
        if builder is None:
            from databento import Live
            builder = Live
        self._loop = asyncio.new_event_loop()
        self._lock = threading.Lock()
        self._events = []
        self._pulse_ns = 0
        self._closed = False
        self._stopping = threading.Event()
        self._callbacks = []
        self._pump = None
        self._delivered = 0
        self._last_delivery_ns = 0
        self._done = Future()
        self._thread = threading.Thread(target=self._serve, name='monatise-databento-network', daemon=True)
        self._thread.start()
        self._client = None
        try:
            self._client = self._call(lambda: builder(key=key, heartbeat_interval_s=heartbeat_seconds,
                reconnect_policy='none', slow_reader_behavior='warn', loop=self._loop))
        except BaseException:
            self.close()
            raise

    def _serve(self):
        asyncio.set_event_loop(self._loop)
        self._loop.set_exception_handler(self._loop_error)
        self._pulse()
        try:
            self._loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:task.cancel()
            if pending:self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._loop.run_until_complete(self._loop.shutdown_default_executor())
            self._loop.close()

    def _pulse(self):
        self._pulse_ns = time.monotonic_ns()
        self._loop.call_later(.25, self._pulse)

    def _loop_error(self, loop, context):
        self._error(context.get('exception'), 'event_loop')

    def _error(self, exc, stage):
        # Never serialize exception text, task/transport repr or native payload.
        with self._lock:
            if len(self._events)<32:self._events.append(dict(error_type=type(exc).__name__ if exc else None,
                stage=stage,observed_at_ns=time.time_ns(),exception_text_omitted=True))

    def _call(self, fn, timeout=2):
        if self._closed:raise ValueError('closed_owned_SDK_transport')
        if threading.current_thread() is self._thread:return fn()
        future=Future()
        def invoke():
            if not future.set_running_or_notify_cancel():return
            try:future.set_result(fn())
            except BaseException as exc:future.set_exception(exc)
        self._loop.call_soon_threadsafe(invoke)
        try:return future.result(timeout)
        except FutureTimeout:
            future.cancel();raise TimeoutError('owned_SDK_loop_unresponsive') from None

    def add_callback(self, fn, *, exception_callback=None):
        """Application consumer, not a blocking SDK record callback."""
        self._call(lambda:self._callbacks.append((fn,exception_callback)))

    def subscribe(self, *args, **kwargs):
        if self._closed:raise ValueError('closed_owned_SDK_transport')
        if threading.current_thread() is self._thread:
            raise ValueError('blocking_SDK_subscribe_must_run_off_network_loop')
        return self._client.subscribe(*args,**kwargs)

    def _dispatch(self,record):
        for fn,failed in self._callbacks:
            try:fn(record)
            except Exception as exc:
                if failed is not None:failed(exc)
                raise

    async def _consume(self):
        try:
            # Documented iteration starts the session itself. Never call start
            # first. One in-flight record per connection bounds our handoff.
            async for record in self._client:
                await asyncio.to_thread(self._dispatch,record)
                self._delivered+=1;self._last_delivery_ns=time.monotonic_ns()
                if self._stopping.is_set():break
            if not self._done.done():self._done.set_result(None)
        except asyncio.CancelledError:
            if not self._done.done():self._done.set_result(None)
            raise
        except Exception as exc:
            self._error(exc,'public_async_iteration')
            if not self._done.done():self._done.set_exception(exc)

    def start(self):
        def begin():
            if self._pump is not None:raise ValueError('public_iterator_already_started')
            self._pump=self._loop.create_task(self._consume())
        return self._call(begin)

    def terminate(self):
        self._stopping.set()
        if not self._closed and self._client is not None:
            def stop():
                self._client.terminate()
                if self._pump is None and not self._done.done():self._done.set_result(None)
            return self._call(stop)

    async def wait_for_close(self):
        # Wait for the iterator to drain/close. No competing SDK waiter can clear
        # session state while the iterator is still consuming it.
        await asyncio.shield(asyncio.wrap_future(self._done))

    def diagnostics(self):
        try:responsive=self._call(lambda:True,timeout=.2)
        except (TimeoutError,ValueError):responsive=False
        with self._lock:events=list(self._events)
        return dict(network_loop_responsive=responsive,network_loop_thread_alive=self._thread.is_alive(),
            network_loop_pulse_age_seconds=max(0,(time.monotonic_ns()-self._pulse_ns)/1e9),
            application_records_delivered=self._delivered,
            application_last_delivery_age_seconds=max(0,(time.monotonic_ns()-self._last_delivery_ns)/1e9) if self._last_delivery_ns else None,
            streaming_method='Live.__aiter__',sdk_private_instrumentation=False,
            sdk_buffering_and_backpressure='SDK_MANAGED_NOT_INSPECTED',
            loop_errors=events,isolated_network_loop=True,automatic_retries=0)

    def close(self):
        if self._closed:return
        try:self.terminate()
        finally:
            self._closed=True
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
        if self._thread.is_alive():raise TimeoutError('owned_SDK_loop_shutdown_incomplete')
