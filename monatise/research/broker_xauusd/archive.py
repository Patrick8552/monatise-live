"""One-shot local import, immutable PostgreSQL batches and admission receipts.

No broker/network/credential client exists here. POINT_IN_TIME_OBSERVATION is
reserved for separately reviewed captured-response imports; a proof reference
is recorded, not magically authenticated by this module. Historical downloads
are never relabelled as point-in-time, even after repeated downloads.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from math import isfinite

from monatise.application.gold_sessions import GoldSessionCalendar
from monatise.application.hierarchy.candles import CandleBoundaryNormalizer
from monatise.application.hierarchy.models import Provenance
from monatise.application.persistence import PostgresDocumentStore
from monatise.core.models import Candle
from monatise.research.broker_xauusd import BASELINE, SCHEMA
from monatise.research.broker_xauusd.models import KINDS, TIMEFRAMES, canonical, digest, instant

TABLE = "monatise_research_broker_documents"


class BrokerObservationArchive:
    def __init__(self, store, *, identity, calendar_manifest, clock=None, engineering_store=False):
        if not engineering_store and (not isinstance(store, PostgresDocumentStore) or store._table != TABLE):
            raise ValueError("isolated research PostgreSQL table required")
        self.store, self.identity = store, identity
        self._calendar_json = canonical(calendar_manifest)
        self.calendar = GoldSessionCalendar.from_manifest(self.calendar_manifest)
        identity.validate_calendar(self.calendar)
        self.namespace = identity.namespace + ":" + self.calendar.fingerprint
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.engineering_store = engineering_store

    @property
    def calendar_manifest(self):
        return json.loads(self._calendar_json)

    def prepare(self, payload, *, evidence_kind, source_reference, capture_proof_reference=None, window=None, capture_calendar_manifest=None):
        """Validate without writes; retain unmodified response as received.

        `t_broker` is the original broker wall epoch; `t` is preserved as a
        provider assertion, never trusted as historical UTC. Broker schedule
        normalization is authoritative. No candles are resampled or fabricated.
        """
        raw = json.loads(canonical(payload))
        if len(canonical(raw).encode()) > 8_000_000:
            raise ValueError("bounded payload exceeds eight MB")
        if evidence_kind not in KINDS or not isinstance(source_reference, str) or not source_reference.strip() or len(source_reference) > 2048:
            raise ValueError("explicit evidence kind and source reference required")
        if self.engineering_store and evidence_kind != "ENGINEERING_SYNTHETIC":
            raise ValueError("engineering store cannot admit real evidence")
        if evidence_kind == "POINT_IN_TIME_OBSERVATION" and (not isinstance(capture_proof_reference, str) or not capture_proof_reference.strip() or len(capture_proof_reference) > 2048):
            raise ValueError("reviewed capture proof reference required")
        if (str(raw.get("account_id")) != self.identity.account_id or
            str(raw.get("server", "")).casefold() != self.identity.server.casefold() or
            raw.get("symbol") != self.identity.broker_symbol):
            raise ValueError("broker response identity mismatch")
        request_id = raw.get("request_id")
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise ValueError("bounded observation request identity required")
        captured, received = instant(raw["captured_at"]), instant(raw["received_at"])
        ingestion = instant(self.clock())
        if not captured <= received <= ingestion:
            raise ValueError("capture/receive/ingestion clock ordering invalid")
        units = {k: raw.get(k) for k in ("point", "tick_size", "spread_price")}
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not isfinite(v) for v in units.values()):
            raise ValueError("finite broker units required")
        if units["point"] <= 0 or units["tick_size"] <= 0 or units["spread_price"] < 0:
            raise ValueError("invalid broker units")
        if raw.get("timestamp_policy") not in {"current_offset_uncertified_history", "reviewed_broker_schedule_v1"}:
            raise ValueError("original timestamp policy required")
        if raw.get("volume_kind", "tick_volume") != "tick_volume":
            raise ValueError("broker tick-volume contract required")
        offset = raw.get("broker_time_offset")
        capture_calendar = self.calendar
        if capture_calendar_manifest is not None:
            if evidence_kind != "RETROSPECTIVE_HISTORICAL_DOWNLOAD":
                raise ValueError("separate capture calendar reserved for retrospective downloads")
            capture_calendar = GoldSessionCalendar.from_manifest(capture_calendar_manifest)
            self.identity.validate_calendar(capture_calendar)
        if isinstance(offset, bool) or not isinstance(offset, int) or offset != capture_calendar.offset(captured):
            raise ValueError("capture broker offset disagrees with reviewed schedule")
        if evidence_kind == "POINT_IN_TIME_OBSERVATION":
            self.calendar.require_regular_session(captured)
            if raw.get("session_open") is not True or instant(raw["session_close"]) != self.calendar.session_close(captured):
                raise ValueError("capture session evidence mismatch")
        if window is not None:
            start, end = instant(window["start"]), instant(window["end"])
            if not self.calendar.start <= start < end <= self.calendar.end:
                raise ValueError("download window outside reviewed calendar")
        else:
            start = end = None
        frames = raw.get("timeframes")
        if not isinstance(frames, dict) or not frames or not set(frames) <= set(TIMEFRAMES):
            raise ValueError("supported broker timeframes required")
        provenance = Provenance("broker_xauusd_archive", self.identity.server, "XAU/USD", source_reference, "hierarchy-candle-v1")
        normalizer, rows = CandleBoundaryNormalizer(), []
        for tf in TIMEFRAMES:
            if tf not in frames:
                continue
            series = frames[tf]
            if not isinstance(series, list) or len(series) > 5000:
                raise ValueError("bounded candle list required")
            prior = None
            for row in series:
                opened = self.calendar.normalize_broker_epoch(row.get("t_broker"))
                if prior is not None and opened <= prior:
                    raise ValueError("duplicate or unordered candle timestamps")
                prior = opened
                if opened > captured or not self.calendar.regular_bar(opened, tf):
                    raise ValueError("future or inconsistent session candle boundary")
                if start is not None and not start <= opened < end:
                    raise ValueError("candle outside declared download window")
                values = [row.get(k) for k in ("o", "h", "l", "c", "v")]
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v) for v in values):
                    raise ValueError("finite numeric broker OHLCV required")
                c = Candle(opened.isoformat(), *values)
                if c.low <= 0 or c.volume < 0:
                    raise ValueError("positive prices and nonnegative tick volume required")
                n = normalizer.normalize(c, symbol="XAU/USD", timeframe=tf, received_at=captured, provenance=provenance)
                rows.append({"timeframe": tf, "opened_at": opened.isoformat(),
                    "scheduled_close_at": n.scheduled_close_time.isoformat(),
                    "content_hash": n.content_hash, "value_sha256": digest(asdict(c)), "candle": asdict(c),
                    "original": row, "clock_closed_at_capture": captured >= n.scheduled_close_time,
                    "is_final": False})
        body = {"schema": SCHEMA, "baseline": BASELINE, "broker_identity": asdict(self.identity),
            "namespace": self.namespace, "calendar": self.calendar_manifest,
            "calendar_fingerprint": self.calendar.fingerprint, "raw_payload": raw,
            "raw_sha256": digest(raw), "evidence_kind": evidence_kind,
            "source_reference": source_reference, "capture_proof_reference": capture_proof_reference,
            "capture_proof_verified_by_archive": False, "window": window, "rows": rows,
            "capture_calendar": capture_calendar_manifest or self.calendar_manifest,
            "capture_calendar_fingerprint": capture_calendar.fingerprint,
            "volume_kind": "tick_volume", "execution_enabled": False}
        body["batch_id"] = digest({"namespace": self.namespace, "request_id": request_id})
        body["body_sha256"] = digest(body)
        return json.loads(canonical(body))

    async def _create(self, key, value):
        previous = await self.store.get(self.namespace, key)
        if previous is not None:
            if previous.value != value or previous.version != 1:
                raise ValueError("immutable archive identity conflict")
            return previous.value
        try:
            return (await self.store.put(self.namespace, key, value, expected_version=0)).value
        except RuntimeError:
            previous = await self.store.get(self.namespace, key)
            if previous is None or previous.version != 1 or previous.value != value:
                raise ValueError("immutable archive identity conflict") from None
            return previous.value

    async def append(self, payload, **metadata):
        body = self.prepare(payload, **metadata)
        await self._create("batch:" + body["batch_id"], body)
        # Only after the batch write has completed can its availability be claimed.
        # If admission fails, the orphan remains immutable and is excluded by reads.
        key = "admission:" + body["batch_id"]
        previous = await self.store.get(self.namespace, key)
        if previous is not None:
            return previous.value
        admitted = instant(self.clock())
        if admitted < instant(payload["received_at"]):
            raise ValueError("admission clock moved backwards")
        receipt = {"schema": "broker-xauusd-admission-v1", "batch_id": body["batch_id"],
                   "body_sha256": body["body_sha256"], "ingested_and_available_at": admitted.isoformat()}
        receipt["sha256"] = digest(receipt)
        try:
            return await self._create(key, receipt)
        except ValueError:
            # Concurrent identical import: retain the first committed admission.
            winner = await self.store.get(self.namespace, key)
            if winner is None or winner.value.get("body_sha256") != body["body_sha256"]:
                raise
            return winner.value

    async def batches(self, *, cutoff):
        cutoff = instant(cutoff)
        documents = await self.store.list_namespace(self.namespace)
        receipts = {}
        for d in documents:
            key = d.key.decode("utf-8") if isinstance(d.key, bytes) else d.key
            if key.startswith("admission:"):
                if d.version != 1 or digest({k: v for k, v in d.value.items() if k != "sha256"}) != d.value.get("sha256"):
                    raise ValueError("admission integrity failure")
                if key != "admission:" + d.value["batch_id"]:
                    raise ValueError("admission identity failure")
                receipts[d.value["batch_id"]] = d.value
        result = []
        for document in documents:
            key = document.key.decode("utf-8") if isinstance(document.key, bytes) else document.key
            if not key.startswith("batch:"):
                continue
            body = document.value
            unhashed = {k: v for k, v in body.items() if k != "body_sha256"}
            if document.version != 1 or digest(unhashed) != body["body_sha256"] or digest(body["raw_payload"]) != body["raw_sha256"]:
                raise ValueError("archive integrity failure")
            if key != "batch:" + body["batch_id"] or body["namespace"] != self.namespace:
                raise ValueError("archive identity failure")
            receipt = receipts.get(body["batch_id"])
            if receipt is None:
                continue
            available = instant(receipt["ingested_and_available_at"])
            if receipt["body_sha256"] != body["body_sha256"] or available < instant(body["raw_payload"]["received_at"]):
                raise ValueError("admission integrity failure")
            if available <= cutoff:
                result.append({**body, "availability_at": available.isoformat()})
        return tuple(sorted(result, key=lambda b: (b["availability_at"], b["batch_id"])))
