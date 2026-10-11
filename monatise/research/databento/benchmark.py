"""Offline synthetic DBN throughput/memory probe; never downloads market data.

    python -m monatise.research.databento.benchmark --records 100000
"""
import argparse
import json
import resource
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

from monatise.adapters.databento_identity import DatabentoPublisherPolicy
from monatise.research.databento.acquisition import HistoricalRequest, inspect_request_archive
from monatise.research.databento.archive import NativeDBNArchive
from monatise.research.databento.replay import HistoricalGCReference, ReplayConfig, replay_archive


def benchmark(count):
    import databento_dbn as dbn
    if not 1 <= count < 1_000_000:
        raise ValueError("benchmark requires 1..999999 synthetic records")
    now = 1791727200000000000
    start, end = now-86400*10**9, now-86400*10**9+10**9
    request = HistoricalRequest("GLBX.MDP3", "trades", ((1, 41271, "GCZ6"),), start, end, count+1)
    catalog = DatabentoPublisherPolicy(((1, "GLBX.MDP3", "GLBX"),), now, "a"*64)
    record = dbn.InstrumentDefMsg(publisher_id=1, instrument_id=41271,
        ts_event=start-100, ts_recv=start-99, min_price_increment=100_000_000,
        display_factor=10**9, raw_symbol="GCZ6", asset="GC", security_type="FUT",
        instrument_class=dbn.InstrumentClass.FUTURE, security_update_action=dbn.SecurityUpdateAction.ADD,
        expiration=now+60*86400*10**9, currency="USD", unit_of_measure="oz",
        unit_of_measure_qty=100*10**9, exchange="XCEC", maturity_year=2026, maturity_month=12,
        user_defined_instrument=dbn.UserDefinedInstrument.NO)
    reference = HistoricalGCReference.reconstruct(record, identity_policy=catalog, retrieval_ns=now)
    config = ReplayConfig(start, end, start, end, "ENGINEERING_SYNTHETIC_SESSION")
    with tempfile.TemporaryDirectory(prefix="mon-history-bench-") as root:
        archive = NativeDBNArchive(root)
        header = dbn.Metadata(dataset=request.dataset, start=start, end=end, schema=dbn.Schema.TRADES,
            stype_in=dbn.SType.RAW_SYMBOL, stype_out=dbn.SType.INSTRUMENT_ID,
            symbols=["GCZ6"], limit=count+1, version=3)
        with archive.staging(request.sha256).open("xb") as stream:
            stream.write(header.encode())
            for i in range(count):
                stream.write(bytes(dbn.TradeMsg(publisher_id=1, instrument_id=41271,
                    ts_event=start+i+1, ts_recv=start+i+2, price=2500*10**9+(i%128)*100_000_000,
                    size=1, action=dbn.Action.TRADE, side=dbn.Side.BID, depth=0, sequence=i, flags=0)))
        digest = archive.seal(request.sha256)
        manifest = dict(status="ARCHIVED", archive_sha256=digest, request_sha256=request.sha256,
            coverage=inspect_request_archive(archive.verify(digest), request),
            availability_ns=now, retrieval_ns=now, evidence_kind="ENGINEERING_SYNTHETIC")
        rss_scale = 1 if sys.platform == "darwin" else 1024
        prior_peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * rss_scale
        tracemalloc.start()
        started = time.perf_counter()
        result = replay_archive(archive=archive, manifest=manifest, request=request, reference=reference,
            config=config, assessed_at_ns=end).result()
        seconds = time.perf_counter()-started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert result["accepted"] == count and result["volume"] == count and not result["gaps"]
        return dict(records=count, seconds=round(seconds, 3), records_per_second=round(count/seconds, 1),
            python_tracemalloc_peak_bytes=peak, archive_bytes=Path(archive.verify(digest)).stat().st_size,
            process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * rss_scale,
            process_peak_rss_before_replay_bytes=prior_peak_rss,
            dedup_entries=len(result["recent_record_hashes"]), profile_entries=len(result["profile"]),
            coverage_state=result["coverage_state"], evidence_kind="ENGINEERING_SYNTHETIC",
            methodology="includes integrity hash, archive validation and replay; tracemalloc enabled",
            performance_scope="engineering only; no trading-performance or live-throughput claim")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, default=100000)
    print(json.dumps(benchmark(parser.parse_args().records), sort_keys=True))
