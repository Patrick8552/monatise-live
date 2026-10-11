"""Bounded synthetic JSONB archive measurements; no market/provider benchmark."""
from __future__ import annotations

from datetime import timedelta
from statistics import median
from time import perf_counter

from monatise.research.broker_xauusd.models import canonical


async def measure_reads(archive, *, cutoff, samples=3):
    if type(samples) is not int or not 1 <= samples <= 5:
        raise ValueError("bounded benchmark sample count required")
    times, size, count = [],0,0
    for _ in range(samples):
        before = perf_counter()
        batches = await archive.batches(cutoff=cutoff)
        times.append(perf_counter()-before)
        count = len(batches)
        size = sum(len(canonical(b).encode()) for b in batches)
    return {"samples":samples,"selected_batches":count,"selected_json_bytes":size,
        "median_read_seconds":median(times),"min_read_seconds":min(times),"max_read_seconds":max(times),
        "evidence_kind":"ENGINEERING_SYNTHETIC", "interpretation":"Local isolated PostgreSQL JSONB workload; no indefinite-archive or broker throughput claim."}
