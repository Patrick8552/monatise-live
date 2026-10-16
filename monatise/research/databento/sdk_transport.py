"""Owned SDK network loops; bounded, price-free failure diagnostics.

The pinned SDK's synchronous subscribe waits on its network loop, so it must
remain off that loop. Startup and cleanup mutate asyncio tasks and belong on it.
There is no recovery, retry, timeout relaxation, or transport resume here.
"""
import asyncio
from concurrent.futures import Future, TimeoutError as FutureTimeout
import threading
import time


class OwnedSDKClient:
    def __init__(self, key, heartbeat_seconds, *, builder=None):
        if builder is None:
            from databento import Live
            builder = Live
        self._loop = asyncio.new_event_loop()
        self._lock = threading.Lock()
        self._events = []
        self._pulse_ns = 0
        self._closed = False
        self._transport = None
        self._reading_requested = True
        self._wire_bytes=0;self._wire_updates=0;self._wire_last_ns=0;self._wire_max_processing_ns=0
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
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._loop.close()

    def _pulse(self):
        self._pulse_ns = time.monotonic_ns()
        self._loop.call_later(.25, self._pulse)

    def _loop_error(self, loop, context):
        # Exception text, repr, task names and transport objects can hold secrets.
        exc = context.get('exception')
        with self._lock:
            if len(self._events) < 32:
                self._events.append({'error_type': type(exc).__name__ if exc else None,
                    'observed_at_ns': time.time_ns(), 'exception_text_omitted': True})

    def _call(self, fn, timeout=2):
        if self._closed:
            raise ValueError('closed_owned_SDK_transport')
        if threading.current_thread() is self._thread:
            return fn()
        future = Future()
        def invoke():
            if not future.set_running_or_notify_cancel():
                return
            try:
                future.set_result(fn())
            except BaseException as exc:
                future.set_exception(exc)
        self._loop.call_soon_threadsafe(invoke)
        try:
            return future.result(timeout)
        except FutureTimeout:
            future.cancel()
            raise TimeoutError('owned_SDK_loop_unresponsive') from None

    def add_callback(self, *args, **kwargs):
        return self._call(lambda: self._client.add_callback(*args, **kwargs))

    def subscribe(self, *args, **kwargs):
        if self._closed:
            raise ValueError('closed_owned_SDK_transport')
        if threading.current_thread() is self._thread:
            raise ValueError('blocking_SDK_subscribe_must_run_off_network_loop')
        result = self._client.subscribe(*args, **kwargs)
        # SDK wait_for_close can clear its transport reference on timeout before
        # the capture watcher runs. Retain ownership so shutdown still aborts it.
        def capture_transport():
            session=self._client._session
            protocol=session._protocol
            if protocol is not None and hasattr(protocol,'buffer_updated'):
                # Bound one SDK decode/dispatch turn as well as the handoff.
                # A socket pause cannot interrupt an already decoded batch.
                # DBN supports partial records; only the exposed receive view
                # is shortened, never the original bytes or decoder semantics.
                get_buffer=protocol.get_buffer
                protocol.get_buffer=lambda sizehint:memoryview(get_buffer(sizehint))[:2048]
                original=protocol.buffer_updated
                def observed(nbytes):
                    begin=time.monotonic_ns()
                    self._wire_bytes+=nbytes;self._wire_updates+=1;self._wire_last_ns=begin
                    try:return original(nbytes)
                    finally:self._wire_max_processing_ns=max(self._wire_max_processing_ns,time.monotonic_ns()-begin)
                protocol.buffer_updated=observed
            return session._transport
        self._transport = self._call(capture_transport)
        return result

    def start(self):
        return self._call(self._client.start)

    def set_reading(self,enabled):
        """Nonblocking watermarks on the owning loop; never resume a failed run.

        pause_reading cannot interrupt the SDK's current decoded batch. A batch
        exceeding the bounded reserve still fails explicitly at the handoff.
        """
        if type(enabled) is not bool:raise ValueError('boolean_reading_state_required')
        if self._closed:return
        self._reading_requested=enabled
        def apply():
            transport=self._transport
            if transport is not None and not transport.is_closing():
                # A queued consumer resume may run after a newer pause applied
                # inline by this network thread. Apply the latest requested
                # state, not the obsolete state captured by the queued closure.
                (transport.resume_reading if self._reading_requested else transport.pause_reading)()
        if threading.current_thread() is self._thread:apply()
        else:self._loop.call_soon_threadsafe(apply)

    def terminate(self):
        if not self._closed and self._client is not None:
            def stop():
                if self._transport is not None:
                    self._transport.abort()
                return self._client.terminate()
            return self._call(stop)

    async def wait_for_close(self):
        # SDK wait_for_close marshals its coroutine to the supplied network loop.
        try:
            return await self._client.wait_for_close()
        except Exception as exc:
            with self._lock:
                if len(self._events) < 32:
                    self._events.append({'error_type': type(exc).__name__,
                        'stage': 'wait_for_close', 'observed_at_ns': time.time_ns(),
                        'exception_text_omitted': True})
            raise

    def diagnostics(self):
        def snapshot():
            # Private attributes are read only, bound to the exact SDK versions
            # enforced by sdk_client. Never return IDs, symbols or record values.
            session = self._client._session
            protocol = session._protocol
            transport = self._transport or session._transport
            socket_error=None
            if transport is not None and hasattr(transport,'get_extra_info'):
                import socket
                sock=transport.get_extra_info('socket')
                if sock is not None:
                    try:socket_error=sock.getsockopt(socket.SOL_SOCKET,socket.SO_ERROR)
                    except OSError:socket_error=None
            return {'network_loop_responsive': True,
                'socket_pending_error':socket_error,
                'wire_bytes':self._wire_bytes,'wire_updates':self._wire_updates,
                'wire_last_receive_age_seconds':max(0,(time.monotonic_ns()-self._wire_last_ns)/1e9) if self._wire_last_ns else None,
                'wire_max_decode_dispatch_ns':self._wire_max_processing_ns,
                'transport_reading': transport.is_reading() if transport else None,
                'transport_closing': transport.is_closing() if transport else None,
                'reading_requested':self._reading_requested,
                'iteration_queue_enabled': session._dbn_queue.is_enabled(),
                'iteration_queue_depth': session._dbn_queue.qsize(),
                'sdk_last_message_age_seconds': max(0, self._loop.time()-getattr(protocol,'_last_msg_loop_time',float('inf')))
                    if protocol and getattr(protocol,'_last_msg_loop_time',float('inf')) != float('inf') else None}
        try:
            result = self._call(snapshot, timeout=.2)
        except (TimeoutError, ValueError, AttributeError):
            result = {'network_loop_responsive': False}
        with self._lock:
            events = list(self._events)
        result.update(network_loop_thread_alive=self._thread.is_alive(),
            network_loop_pulse_age_seconds=max(0,(time.monotonic_ns()-self._pulse_ns)/1e9),
            loop_errors=events, isolated_network_loop=True, automatic_retries=0)
        return result

    def close(self):
        if self._closed:
            return
        try:
            self.terminate()
        finally:
            self._closed = True
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=2)
        if self._thread.is_alive():
            raise TimeoutError('owned_SDK_loop_shutdown_incomplete')
