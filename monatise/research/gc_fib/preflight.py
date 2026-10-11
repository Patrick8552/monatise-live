"""Metadata ONLY. No acquisition command or approval-receipt constructor."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import time
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path

from monatise.research.databento.acquisition import HistoricalRequest, SDKHistoricalSource
from monatise.research.gc_fib import BASELINE, H1_RESEARCH, ISOLATION, POLICY

START_NS = 1791158400 * 10**9  # 2026-10-05T00:00:00Z
END_NS = 1791590400 * 10**9    # 2026-10-10T00:00:00Z, exclusive
SCHEMAS = ("definition", "status", "ohlcv-1m", "trades", "mbp-1")


def requests():
    return tuple(HistoricalRequest("GLBX.MDP3", schema, ((1, 41271, "GCZ6"),),
                                   START_NS, END_NS) for schema in SCHEMAS)


def prepare(*, archive_root, scopes=None):
    return {"schema": "monatise-gc-research-proposal-v1", "baseline": BASELINE,
            "h1_research": H1_RESEARCH, "selector": POLICY, **ISOLATION,
            "billable_download_authorized": False, "data_downloaded": False,
            "credit": {"status": "UNVERIFIED"}, "entitlement": "UNKNOWN",
            "requests": [{"request": asdict(r), "request_sha256": r.sha256,
                          "archive_root":str(Path(archive_root).resolve()),
                          "staging_destination":str(Path(archive_root).resolve()/"staging"/(r.sha256+".dbn.part")),
                          "archive_destination_template":str(Path(archive_root).resolve()/"objects"/"{native_sha256}.dbn")}
                         for r in (scopes or requests())]}


def partition_scopes(source):
    """Free metadata bisects oversized scopes; never retries a paid request.

    Uncompressed billable size is used conservatively with 50% wire headroom;
    it does not certify compressed transport size. Actual transport stays capped.
    """
    output, pending = [], list(requests())
    while pending:
        request = pending.pop(0)
        params = request.api_parameters(); params.pop("limit")
        count = source._client.metadata.get_record_count(**params)
        size = source._client.metadata.get_billable_size(**params)
        if count < request.record_limit and size < request.wire_byte_limit // 2:
            output.append(request)
        else:
            midpoint = ((request.start_ns + request.end_ns) // 2) // (60*10**9) * (60*10**9)
            if (not request.start_ns < midpoint < request.end_ns
                    or len(output)+len(pending) >= 63):
                raise ValueError("scope cannot fit existing limits; no acquisition attempted")
            pending[0:0] = [replace(request,end_ns=midpoint),replace(request,start_ns=midpoint)]
    return tuple(output)


def assess_metadata(source, *, archive_root, partition=False):
    """Existing Phase 2 preflight + free size/count estimates. No data endpoints."""
    scopes = partition_scopes(source) if partition else requests()
    value = prepare(archive_root=archive_root, scopes=scopes)
    for item, request in zip(value["requests"], scopes):
        proof = source.preflight(request, now_ns=time.time_ns())
        item.update(preflight=asdict(proof), preflight_sha256=proof.sha256)
        params = request.api_parameters()
        # A capped cost is not evidence that the full five-day window fits.
        params.pop("limit")
        try:
            count = source._client.metadata.get_record_count(**params)
            size = source._client.metadata.get_billable_size(**params)
        except Exception:
            item.update(full_record_count=None, full_billable_bytes=None,
                        completeness_preflight="UNVERIFIED")
            continue
        item.update(full_record_count=count, full_billable_bytes=size,
                    # Billable size is uncompressed DBN, not compressed wire size.
                    wire_size_verified=False,
                    completeness_preflight="FITS_RECORD_LIMIT" if count < request.record_limit
                        else "PARTITION_REQUIRED_NO_DOWNLOAD")
        print("Metadata complete:", request.schema, request.start_ns, request.end_ns,
              count, "records; estimate USD", proof.estimated_usd, flush=True)
    value["estimated_usd"] = str(sum(Decimal(i["preflight"]["estimated_usd"])
                                     for i in value["requests"]))
    value["estimates_are_not_charge_caps"] = True
    value["acquisition_ready"] = False  # Requires separate credit/entitlement review + human receipt.
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archive-root", required=True)
    parser.add_argument("--metadata", action="store_true")
    parser.add_argument("--partition", action="store_true", help="free size/count checks, then bounded scope quotes")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("fresh immutable metadata output required")
    value = prepare(archive_root=args.archive_root)
    if args.metadata:
        key = os.environ.get("DATABENTO_API_KEY") or getpass.getpass("Databento key (metadata only, not saved): ")
        value = assess_metadata(SDKHistoricalSource(key=key), archive_root=args.archive_root, partition=args.partition)
    # Exclusive creation; never overwrite previous estimates or receipts.
    with args.output.open("x") as output:
        json.dump(value, output, sort_keys=True, indent=2)
    print("Metadata proposal saved. No data downloaded; billable approval still required.")


if __name__ == "__main__":
    main()
