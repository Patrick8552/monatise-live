"""Explicitly authorized, one-attempt historical acquisition. Not wired to runtime.

    Cost estimates are not provider-enforced charge caps. Credit balance and
    entitlement verification are operator attestations, not inferred from API
    authentication. No automatic retries after a request could have been billed.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import warnings
from dataclasses import asdict, dataclass
from decimal import Decimal

from monatise.adapters.databento_identity import timestamp_ns
from monatise.application.persistence import PostgresDocumentStore
from monatise.research.databento.archive import NativeDBNArchive, dbn_records

SCHEMAS = {"trades", "mbp-1", "definition", "statistics", "status",
           "ohlcv-1s", "ohlcv-1m", "ohlcv-1h", "ohlcv-1d"}
NAMESPACE = "databento-historical-acquisitions-v1"


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def json_document(value):
    """Identical representation before/after a PostgreSQL JSONB round trip."""
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _usd(value):
    try:
        d = Decimal(str(value))
    except Exception:
        raise ValueError("non-negative finite USD amount required") from None
    if not d.is_finite() or d < 0:
        raise ValueError("non-negative finite USD amount required")
    return d


def _reference(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
        raise ValueError("opaque audit reference required")
    return value


@dataclass(frozen=True)
class HistoricalRequest:
    dataset: str
    schema: str
    # Exact publisher/instrument/raw contract tuple, never a continuous or parent symbol.
    contracts: tuple[tuple[int, int, str], ...]
    start_ns: int
    end_ns: int
    record_limit: int = 1_000_000
    wire_byte_limit: int = 256 * 1024**2

    def __post_init__(self):
        timestamp_ns(self.start_ns)
        timestamp_ns(self.end_ns)
        if self.dataset != "GLBX.MDP3" or self.schema not in SCHEMAS:
            raise ValueError("unreviewed dataset/schema")
        if not 0 < self.end_ns - self.start_ns <= 7 * 86400 * 10**9:
            raise ValueError("explicit historical window of at most seven days required")
        if not isinstance(self.contracts, tuple) or not 1 <= len(self.contracts) <= 8:
            raise ValueError("bounded immutable explicit contract selection required")
        for item in self.contracts:
            if not isinstance(item, tuple) or len(item) != 3:
                raise ValueError("immutable contract identity required")
            pid, iid, symbol = item
            if (type(pid) is not int or not 0 < pid < 65536 or type(iid) is not int
                    or not 0 < iid < 2**32 or not isinstance(symbol, str)
                    or not re.fullmatch(r"(?:(?:GC|ES|NQ|CL)[FGHJKMNQUVXZ]\d{1,2}|OG[A-Za-z0-9 .+-]{1,60})", symbol)):
                raise ValueError("explicit reviewed CME contract identity required")
        if (len(set(self.contracts)) != len(self.contracts)
                or len({c[2] for c in self.contracts}) != len(self.contracts)
                or len({c[:2] for c in self.contracts}) != len(self.contracts)):
            raise ValueError("duplicate contract selection")
        if type(self.record_limit) is not int or not 1 <= self.record_limit <= 1_000_000:
            raise ValueError("bounded record limit required")
        if type(self.wire_byte_limit) is not int or not 1024 <= self.wire_byte_limit <= 256 * 1024**2:
            raise ValueError("bounded wire byte limit required")

    @property
    def sha256(self):
        return canonical_hash(asdict(self))

    def api_parameters(self):
        return dict(dataset=self.dataset, schema=self.schema, start=self.start_ns,
                    end=self.end_ns, symbols=[c[2] for c in self.contracts],
                    stype_in="raw_symbol", limit=self.record_limit)


@dataclass(frozen=True)
class DownloadPreflight:
    request_sha256: str
    observed_at_ns: int
    available_from_ns: int
    available_to_ns: int
    estimated_usd: str
    schema_available: bool
    identities_verified: bool
    metadata_sha256: str
    # Free metadata success does NOT prove data entitlements.
    entitlement: str = "UNKNOWN"

    def __post_init__(self):
        for value in (self.observed_at_ns, self.available_from_ns, self.available_to_ns):
            timestamp_ns(value)
        _usd(self.estimated_usd)
        for value in (self.request_sha256, self.metadata_sha256):
            if not re.fullmatch(r"[a-f0-9]{64}", value):
                raise ValueError("preflight audit digest required")
        if self.entitlement not in {"UNKNOWN", "VERIFIED_OPERATOR", "DENIED"}:
            raise ValueError("unknown entitlement state")

    @property
    def sha256(self):
        return canonical_hash(asdict(self))


@dataclass(frozen=True)
class ApprovedDownload:
    """Trusted caller constructs ONLY from a specific recorded human approval.

    Python objects cannot authenticate a human. The review reference and
    external billing controls must be verified by the calling operator.
    One receipt authorizes one network attempt; a retry needs a new receipt.
    """
    approval_id: str
    review_reference: str
    request_sha256: str
    preflight_sha256: str
    approved_at_ns: int
    expires_at_ns: int
    max_estimated_usd: str
    entitlement_reference: str
    estimate_is_not_charge_cap_acknowledged: bool
    credits_only: bool = True
    verified_credit_usd: str | None = None
    credit_checked_at_ns: int | None = None
    credit_expires_at_ns: int | None = None
    credit_balance_reference: str | None = None

    def validate(self, request, preflight, now):
        for clock in (now, self.approved_at_ns, self.expires_at_ns):
            timestamp_ns(clock)
        if self.expires_at_ns - self.approved_at_ns > 300 * 10**9:
            raise ValueError("bounded five-minute download authorization required")
        for ref in (self.approval_id, self.review_reference, self.entitlement_reference):
            _reference(ref)
        if (self.request_sha256 != request.sha256 or self.preflight_sha256 != preflight.sha256
                or preflight.request_sha256 != request.sha256):
            raise ValueError("approval does not bind exact request/preflight")
        if not preflight.observed_at_ns <= self.approved_at_ns <= now < self.expires_at_ns:
            raise ValueError("approval expired or unavailable")
        if not 0 <= now - preflight.observed_at_ns <= 300 * 10**9:
            raise ValueError("preflight stale")
        if preflight.entitlement != "VERIFIED_OPERATOR":
            raise ValueError("data entitlement must be independently verified")
        if (not preflight.schema_available or not preflight.identities_verified
                or not preflight.available_from_ns <= request.start_ns < request.end_ns <= preflight.available_to_ns):
            raise ValueError("requested data identity/availability not verified")
        if self.estimate_is_not_charge_cap_acknowledged is not True:
            raise ValueError("estimated cost is not a hard billing cap")
        if _usd(preflight.estimated_usd) > _usd(self.max_estimated_usd):
            raise ValueError("estimate exceeds authorized limit")
        if type(self.credits_only) is not bool:
            raise ValueError("explicit credits-only policy required")
        if self.credits_only:
            if (self.verified_credit_usd is None or self.credit_checked_at_ns is None
                    or self.credit_expires_at_ns is None or self.credit_balance_reference is None):
                raise ValueError("verified available unexpired credit required")
            _reference(self.credit_balance_reference)
            if (not 0 <= now - timestamp_ns(self.credit_checked_at_ns) <= 300 * 10**9
                    or now >= timestamp_ns(self.credit_expires_at_ns)
                    or _usd(self.verified_credit_usd) < _usd(self.max_estimated_usd)):
                raise ValueError("credit balance stale, expired or insufficient")


class HistoricalMetadata:
    """Reuse PostgreSQL's existing document table for metadata, never raw ticks."""
    def __init__(self, store):
        if not isinstance(store, PostgresDocumentStore):
            raise ValueError("PostgresDocumentStore required for durable manifests")
        self.store = store

    async def get(self, key):
        return await self.store.get(NAMESPACE, key)

    async def create(self, key, value):
        return await self.store.put(NAMESPACE, key, value, expected_version=0)

    async def replace(self, previous, value):
        return await self.store.put(NAMESPACE, previous.key, value, expected_version=previous.version)

    async def checkpoint(self, replay_id, value):
        _reference(replay_id)
        key = "checkpoint:" + replay_id
        current = await self.get(key)
        if current and (current.value["config_sha256"] != value["config_sha256"]
                        or current.value["archive_sha256"] != value["archive_sha256"]
                        or current.value["record_ordinal"] > value["record_ordinal"]):
            raise ValueError("checkpoint incompatible or moving backwards")
        return await self.store.put(NAMESPACE, key, value, expected_version=current.version if current else 0)


class SDKHistoricalSource:
    """Pinned SDK metadata/get_range parameter validation; bounded HTTP stream.

    SDK 0.87.0's stock file downloader has no wire limit and does not close
    its writer on stream failure. Override only that transport, with no retry
    or redirects. No key is stored in metadata, repr, error text or log output.
    """
    evidence_kind = "AUTHENTIC_HISTORICAL_DOWNLOAD"
    def __init__(self, *, key, clock_ns=time.time_ns):
        if not isinstance(key, str) or not key.strip():
            raise ValueError("explicit private Databento key required")
        import databento
        self._client = databento.Historical(key=key)
        self._clock_ns = clock_ns

    def preflight(self, request, *, now_ns):
        import pandas as pd
        try:
            metadata = self._client.metadata
            schemas = metadata.list_schemas(request.dataset)
            span = metadata.get_dataset_range(request.dataset)
            publishers = metadata.list_publishers()
            mapping = self._client.symbology.resolve(dataset=request.dataset,
                symbols=[c[2] for c in request.contracts], stype_in="raw_symbol",
                stype_out="instrument_id", start_date=pd.Timestamp(request.start_ns, tz="UTC").date(),
                end_date=(pd.Timestamp(request.end_ns-1, tz="UTC") + pd.Timedelta(days=1)).date())
            estimate = metadata.get_cost(**request.api_parameters())
        except Exception:
            raise RuntimeError("Databento metadata preflight failed; no data request made") from None
        catalog = {p["publisher_id"]: (p["dataset"], p["venue"]) for p in publishers}
        matched = (not mapping.get("partial") and not mapping.get("not_found")
                   and all(catalog.get(pid) == (request.dataset, "GLBX") for pid, _, _ in request.contracts))
        for _, iid, raw in request.contracts:
            intervals = mapping.get("result", {}).get(raw, [])
            start = pd.Timestamp(request.start_ns, tz="UTC").date()
            end = pd.Timestamp(request.end_ns-1, tz="UTC").date()
            cursor = start
            for item in sorted(intervals, key=lambda x: x["d0"]):
                left, right = pd.Timestamp(item["d0"]).date(), pd.Timestamp(item["d1"]).date()
                if right <= cursor:
                    continue
                if left > cursor or str(item["s"]) != str(iid):
                    matched = False
                    break
                cursor = right
            matched = matched and cursor > end
        selected_span = span.get("schema", {}).get(request.schema)
        # Dataset-wide availability is insufficient for a particular schema.
        if selected_span is None:
            raise RuntimeError("schema-specific historical availability unavailable")
        return DownloadPreflight(request.sha256, now_ns, pd.Timestamp(selected_span["start"]).value,
            pd.Timestamp(selected_span["end"]).value, str(estimate), request.schema in schemas,
            bool(matched), canonical_hash({"schemas": schemas, "range": span, "mapping": mapping, "publishers": publishers}))

    def download(self, request, path, *, preflight=None, approval=None, cost_control=None):
        # Recheck at the lowest billable boundary, including queue/worker delay.
        if not isinstance(preflight, DownloadPreflight) or not isinstance(approval, ApprovedDownload):
            raise ValueError("explicit approved request required before data transport")
        approval.validate(request, preflight, timestamp_ns(self._clock_ns()))
        from monatise.research.databento.controls import ResearchLedger
        if not isinstance(cost_control, ResearchLedger):
            raise ValueError("durable budget permit required before data transport")
        cost_control.authorize_transport(request, preflight, approval)
        from databento.historical.api.timeseries import TimeseriesHttpAPI
        import databento
        import requests

        key = self._client.key
        class BoundedTimeseries(TimeseriesHttpAPI):
            def _stream(self, url, data, basic_auth, path=None):
                if url != "https://hist.databento.com/v0/timeseries.get_range" or not basic_auth or path is None:
                    raise ValueError("unreviewed data transport")
                written = 0
                started = time.monotonic()
                with requests.post(url, data=data, auth=(key, ""), headers=self._headers,
                                   timeout=(30, 60), stream=True, allow_redirects=False) as response:
                    if response.status_code != 200 or any(k.lower().startswith("x-dbn-warning") for k in response.headers):
                        raise ValueError("data request denied or provider warning")
                    with open(path, "xb") as target:
                        for chunk in response.iter_content(chunk_size=65536):
                            if time.monotonic() - started > 120:
                                raise ValueError("bounded download duration exceeded")
                            written += len(chunk)
                            if written > request.wire_byte_limit:
                                raise ValueError("wire byte limit exceeded; partial request may have been billed")
                            target.write(chunk)
                return databento.DBNStore.from_file(path)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                BoundedTimeseries(key=key, gateway=self._client.gateway).get_range(
                    **request.api_parameters(), path=path)
        except Exception:
            raise RuntimeError("Databento download failed; reconcile usage before retry") from None


def inspect_request_archive(path, request):
    import databento_dbn as dbn
    count, first, last, header, kinds = 0, None, None, None, set()
    expected = {c[:2] for c in request.contracts}
    expected_rtype = {"trades": dbn.RType.MBP_0, "mbp-1": dbn.RType.MBP_1,
        "definition": dbn.RType.INSTRUMENT_DEF, "statistics": dbn.RType.STATISTICS,
        "status": dbn.RType.STATUS, "ohlcv-1s": dbn.RType.OHLCV_1S,
        "ohlcv-1m": dbn.RType.OHLCV_1M, "ohlcv-1h": dbn.RType.OHLCV_1H,
        "ohlcv-1d": dbn.RType.OHLCV_1D}[request.schema]
    for record in dbn_records(path, max_records=request.record_limit):
        if isinstance(record, dbn.Metadata):
            header = record
            if (record.dataset != request.dataset or str(record.schema) != request.schema
                    or record.start != request.start_ns or record.end != request.end_ns
                    or str(record.stype_in) != "raw_symbol" or str(record.stype_out) != "instrument_id"
                    or set(record.symbols) != {c[2] for c in request.contracts}
                    or record.partial or record.not_found or record.limit != request.record_limit):
                raise ValueError("DBN metadata contradicts exact request")
            continue
        # System/error/control messages must not silently become market records.
        if (record.publisher_id, record.instrument_id) not in expected or record.rtype != expected_rtype:
            raise ValueError("unexpected contract/control record in archive")
        timestamp = timestamp_ns(getattr(record, "ts_recv", None), optional=True)
        if hasattr(record, "ts_recv") and timestamp is None:
            raise ValueError("required provider receive timestamp unavailable")
        timestamp = timestamp if timestamp is not None else timestamp_ns(record.ts_event)
        if not request.start_ns <= timestamp < request.end_ns or (last is not None and timestamp < last):
            raise ValueError("archive range/order mismatch")
        count += 1
        first = timestamp if first is None else first
        last = timestamp
        kinds.add(type(record).__name__)
    if header is None:
        raise ValueError("DBN metadata missing")
    return dict(record_count=count, first_record_ns=first, last_record_ns=last,
                native_version=header.version, record_types=sorted(kinds),
                requested_from_ns=request.start_ns, requested_to_ns=request.end_ns,
                transport_complete=count < request.record_limit,
                coverage_state="PARTIAL" if count == request.record_limit else "UNCERTIFIED",
                continuity_certified=False, completion_watermark_ns=request.end_ns if count < request.record_limit else None)


class HistoricalAcquisition:
    def __init__(self, *, metadata, archive, source, clock_ns=time.time_ns, cost_control=None):
        self.metadata, self.archive, self.source, self.clock_ns = metadata, archive, source, clock_ns
        if not isinstance(metadata, HistoricalMetadata) or not isinstance(archive, NativeDBNArchive):
            raise ValueError("durable archive and PostgreSQL metadata required")
        if getattr(source, "evidence_kind", None) not in {"AUTHENTIC_HISTORICAL_DOWNLOAD", "ENGINEERING_SYNTHETIC"}:
            raise ValueError("explicit source evidence classification required")
        from monatise.research.databento.controls import ResearchLedger
        self.cost_control = cost_control or ResearchLedger(archive.root / "research-ledger.sqlite")
        if not isinstance(self.cost_control, ResearchLedger):
            raise ValueError("durable research cost controls required")

    async def acquire(self, request, preflight, approval):
        """CAS reserve BEFORE network. Failure/uncertainty never retries automatically."""
        now = timestamp_ns(self.clock_ns())
        key = "request:" + request.sha256
        old = await self.metadata.get(key)
        if old:
            if old.value["status"] == "ARCHIVED":
                coverage = inspect_request_archive(self.archive.verify(old.value["archive_sha256"]),request)
                if coverage != old.value["coverage"] or not coverage["transport_complete"]:
                    raise ValueError("cached archive provenance or completeness mismatch")
                return old.value
            raise RuntimeError("existing acquisition requires local reconciliation, not another download")
        plan = self.cost_control.plan(request, archive=self.archive)
        if not plan["new_download_required"]:
            return {"status": "CACHE_AVAILABLE", "plan": plan, "trading_eligible": False}
        approval.validate(request, preflight, now)
        self.cost_control.reserve(request, preflight, approval)
        # A receipt is one-use globally, even if a buggy caller changes request scope.
        await self.metadata.create("approval:" + approval.approval_id, dict(approval=asdict(approval), reserved_at_ns=now))
        value = dict(request=asdict(request), request_sha256=request.sha256, preflight=asdict(preflight),
            authorization=asdict(approval), status="RESERVED", reserved_at_ns=now,
            archive_sha256=None, actual_billed_usd=None, actual_cost_status="UNKNOWN",
            evidence_kind=self.source.evidence_kind, observation_basis="LOCAL_ARCHIVE_ADMISSION",
            trading_eligible=False, download_attempts=1)
        current = await self.metadata.create(key, value)
        return await self._perform(request, current, value)

    async def retry(self, request, preflight, approval, *, previous_billed_usd, billing_review_reference):
        """Explicitly approved retry AFTER usage reconciliation and old attempt expiry.

        Trusted operator must confirm the prior process has stopped and the
        previous billed usage is final. A new balance check and one-use receipt
        are required. All previous manifest revisions and partial files remain.
        """
        now = timestamp_ns(self.clock_ns())
        approval.validate(request, preflight, now)
        _reference(billing_review_reference)
        billed = str(_usd(previous_billed_usd))
        previous = await self.metadata.get("request:" + request.sha256)
        if previous is None or previous.value["status"] != "QUARANTINED":
            raise ValueError("retry requires reconciled quarantined acquisition")
        old = previous.value
        if (now <= max(old["authorization"]["expires_at_ns"], old["reserved_at_ns"] + 180 * 10**9)
                or old["download_attempts"] >= 3):
            raise ValueError("prior attempt not settled or bounded retry count exhausted")
        # Reviewed actual usage is recorded separately from credit, without
        # guessing which part of the old charge consumed account credits.
        self.cost_control.reserve(request, preflight, approval)
        await self.metadata.create("approval:" + approval.approval_id, dict(approval=asdict(approval), reserved_at_ns=now))
        await self.metadata.create("history:" + request.sha256 + ":" + str(previous.version),
            {**old, "reconciled_billed_usd": billed, "billing_review_reference": billing_review_reference})
        value = {**old, "preflight": asdict(preflight), "authorization": asdict(approval),
                 "status": "RESERVED", "reserved_at_ns": now, "archive_sha256": None,
                 "actual_billed_usd": None, "actual_cost_status": "UNKNOWN",
                 "previous_billed_usd": billed, "billing_review_reference": billing_review_reference,
                 "download_attempts": old["download_attempts"] + 1}
        current = await self.metadata.replace(previous, value)
        return await self._perform(request, current, value)

    async def _perform(self, request, current, value):
        if self.archive.staging(request.sha256).exists():
            raise RuntimeError("unexpected staged artifact; reconcile before download")
        # Blocking network in worker thread; CAS ownership already held durably.
        import asyncio
        try:
            await asyncio.to_thread(self.source.download, request, self.archive.staging(request.sha256),
                preflight=DownloadPreflight(**value["preflight"]),
                approval=ApprovedDownload(**value["authorization"]), cost_control=self.cost_control)
            retrieved = timestamp_ns(self.clock_ns())
            coverage = inspect_request_archive(self.archive.staging(request.sha256), request)
            if not coverage["transport_complete"]:
                raise ValueError("record limit reached; partial archive quarantined")
            digest = self.archive.seal(request.sha256)
            admitted = timestamp_ns(self.clock_ns())
            if admitted < retrieved:
                raise ValueError("local clock moved backwards")
        except Exception:
            quarantined = self.archive.quarantine(request.sha256)
            failed = {**value, "status": "QUARANTINED", "quarantine_sha256": quarantined,
                      "failure": "download_or_integrity_failed", "actual_cost_status": "RECONCILIATION_REQUIRED"}
            await self.metadata.replace(current, failed)
            self.cost_control.record_manifest(value["authorization"]["approval_id"], failed)
            raise RuntimeError("historical acquisition quarantined; no automatic paid retry") from None
        # Archive is durable before metadata. DB failure here leaves RESERVED;
        # reconcile sealed objects locally rather than issuing another data call.
        result = {**value, "status": "ARCHIVED", "archive_sha256": digest, "coverage": coverage,
                  "retrieval_ns": retrieved, "availability_ns": admitted,
                  "ingestion_ns": admitted, "ingestion_basis": "BULK_ARCHIVE_ADMISSION",
                  "archive_bytes": self.archive.verify(digest).stat().st_size}
        result = json_document(result)
        await self.metadata.replace(current, result)
        self.cost_control.record_manifest(value["authorization"]["approval_id"], result)
        return result

    async def reconcile(self, request, *, archive_sha256=None, confirmed_transport_complete=False):
        """Local-only recovery; uncertainty is quarantined, never a new API request.

        Sealed orphan recovery requires the known digest and operator confirmation
        of the completed transport. A partial staged file is never auto-promoted.
        """
        previous = await self.metadata.get("request:" + request.sha256)
        if previous is None or previous.value["request_sha256"] != request.sha256:
            raise ValueError("acquisition reservation missing")
        if previous.value["status"] == "ARCHIVED":
            self.archive.verify(previous.value["archive_sha256"])
            return previous.value
        if archive_sha256 is not None and confirmed_transport_complete is True:
            coverage = inspect_request_archive(self.archive.verify(archive_sha256), request)
            if not coverage["transport_complete"]:
                raise ValueError("partial orphan cannot be promoted")
            now = timestamp_ns(self.clock_ns())
            value = {**previous.value, "status": "ARCHIVED", "archive_sha256": archive_sha256,
                     "coverage": coverage, "retrieval_ns": None, "ingestion_ns": now,
                     "availability_ns": now, "recovered_at_ns": now,
                     "actual_cost_status": "RECONCILIATION_REQUIRED"}
        else:
            value = {**previous.value, "status": "QUARANTINED",
                     "quarantine_sha256": self.archive.quarantine(request.sha256),
                     "failure": "uncertain_transport_or_restart", "actual_cost_status": "RECONCILIATION_REQUIRED"}
        await self.metadata.replace(previous, value)
        if value.get("authorization"):
            self.cost_control.record_manifest(value["authorization"]["approval_id"], value)
        return value
