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
        self._thread = threading.Thread(target=self._serve, name='monatise-databento-network', daemon=True)
        self._thread.start()
        self._client = None
        try:
            self._client = self._call(lambda: builder(key=key, heartbeat_interval_s=heartbeat_seconds,
                reconnect_policy='none', loop=self._loop))
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
        self._transport = self._call(lambda: self._client._session._transport)
        return result

    def start(self):
        return self._call(self._client.start)

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
            return {'network_loop_responsive': True,
                'transport_reading': transport.is_reading() if transport else None,
                'transport_closing': transport.is_closing() if transport else None,
                'iteration_queue_enabled': session._dbn_queue.is_enabled(),
                'iteration_queue_depth': session._dbn_queue.qsize(),
                'sdk_last_message_age_seconds': max(0, self._loop.time()-protocol._last_msg_loop_time)
                    if protocol and protocol._last_msg_loop_time != float('inf') else None}
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
