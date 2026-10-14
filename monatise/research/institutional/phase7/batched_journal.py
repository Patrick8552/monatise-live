"""Bounded batching over the unchanged Phase 6 native journal format.

No cursor advances until the whole batch has been flushed and fsynced. A
failed/interrupted write stays unsealed; existing verification rejects it.
This is a research transport helper, never a production ingestion change.
"""
import os
from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.databento.live_journal import NativeJournal, FRAME


class BatchedNativeJournal(NativeJournal):
    def append_batch(self, records):
        if self.closed:
            raise ValueError('closed_native_journal')
        batch = tuple(records)
        if not 1 <= len(batch) <= 512:
            raise ValueError('bounded_native_batch_required')
        previous = self.last_capture
        parts = []
        for capture_ns, native in batch:
            timestamp_ns(capture_ns)
            payload = bytes(native)
            if capture_ns < previous or not 1 <= len(payload) <= 65536:
                raise ValueError('invalid_native_batch_frame')
            parts.extend((FRAME.pack(capture_ns, len(payload)), payload))
            previous = capture_ns
        payload = b''.join(parts)
        if (self.count + len(batch) > self.scope.maximum_records
                or self.bytes + len(payload) > self.scope.maximum_bytes):
            raise ValueError('native_batch_capacity_exceeded')
        written = self.file.write(payload)
        if written != len(payload):
            raise OSError('incomplete_native_batch_write')
        self.file.flush()
        os.fsync(self.file.fileno())
        self.count += len(batch)
        self.bytes += len(payload)
        self.last_capture = previous
