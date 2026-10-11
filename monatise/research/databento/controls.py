"""Durable local research manifests, overlap checks and spending reservations.

SQLite is a local control plane, not a tick database or production dependency.
Credit is reported separately. Unsettled usage retains the approved reservation;
estimates cannot enforce a provider-side charge cap. No automatic retries.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from monatise.application.persistence import DurableRecord
from monatise.research.databento.acquisition import HistoricalMetadata, NAMESPACE, _reference, _usd


@contextmanager
def connect(path):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30, isolation_level=None)
    db.execute("PRAGMA synchronous=FULL")
    try:
        yield db
    finally:
        db.close()


class LocalHistoricalMetadata(HistoricalMetadata):
    """Same async CAS seam as existing PostgreSQL manifests; no external DSN."""
    def __init__(self, path):
        self.path = Path(path)
        with connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS documents (key TEXT PRIMARY KEY, value TEXT NOT NULL, version INTEGER NOT NULL)")

    async def get(self, key):
        with connect(self.path) as db:
            row = db.execute("SELECT value,version FROM documents WHERE key=?", (key,)).fetchone()
        return DurableRecord(NAMESPACE, key, json.loads(row[0]), row[1]) if row else None

    def _put(self, key, value, expected):
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT version FROM documents WHERE key=?", (key,)).fetchone()
            version = row[0] if row else 0
            if version != expected:
                raise RuntimeError("durable state version conflict")
            db.execute("INSERT INTO documents VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,version=excluded.version",
                       (key, payload, version+1))
            db.execute("COMMIT")
        return DurableRecord(NAMESPACE, key, json.loads(payload), version+1)

    async def create(self, key, value):
        return self._put(key, value, 0)

    async def replace(self, previous, value):
        return self._put(previous.key, value, previous.version)

    async def checkpoint(self, replay_id, value):
        _reference(replay_id)
        key = "checkpoint:"+replay_id
        current = await self.get(key)
        if current and (current.value["config_sha256"] != value["config_sha256"]
                        or current.value["archive_sha256"] != value["archive_sha256"]
                        or current.value["record_ordinal"] > value["record_ordinal"]):
            raise ValueError("checkpoint incompatible or moving backwards")
        return self._put(key, value, current.version if current else 0)


class ResearchLedger:
    """Atomic cross-process budget/overlap gate; defaults to zero spending.

    One shared ledger must be used by all researchers sharing an archive/budget.
    Budget configuration and settlement are trusted reviewed operator inputs.
    Failed/uncertain attempts retain reservations until reviewed billing settles.
    """
    def __init__(self, path):
        self.path = Path(path)
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS budget (id INTEGER PRIMARY KEY CHECK(id=1), limit_usd TEXT, credit_usd TEXT, review TEXT)")
            db.execute("INSERT OR IGNORE INTO budget VALUES (1,'0',NULL,'default-zero-budget')")
            db.execute("CREATE TABLE IF NOT EXISTS reservations (approval_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, scope TEXT NOT NULL, reserved_usd TEXT NOT NULL, billed_usd TEXT, credit_used_usd TEXT, billing_review TEXT, manifest TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS historical_cache (request_hash TEXT PRIMARY KEY, scope TEXT NOT NULL, manifest TEXT NOT NULL, review TEXT NOT NULL)")
            if "transport_started" not in {r[1] for r in db.execute("PRAGMA table_info(reservations)")}:
                db.execute("ALTER TABLE reservations ADD COLUMN transport_started INTEGER NOT NULL DEFAULT 0")
            db.execute("COMMIT")

    def configure(self, *, approved_budget_usd, review_reference, historical_credit_usd=None):
        _reference(review_reference)
        limit = _usd(approved_budget_usd)
        credit = None if historical_credit_usd is None else str(_usd(historical_credit_usd))
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            committed = self._committed(db)
            if committed > limit:
                raise ValueError("budget below committed spending")
            db.execute("UPDATE budget SET limit_usd=?,credit_usd=?,review=? WHERE id=1",
                       (str(limit), credit, review_reference))
            db.execute("COMMIT")

    @staticmethod
    def _committed(db):
        return sum((_usd(billed if billed is not None else reserved) for reserved,billed in
                    db.execute("SELECT reserved_usd,billed_usd FROM reservations")), _usd(0))

    def reserve(self, request, preflight, approval):
        """Reserve approved upper estimate, not available signup credit."""
        from dataclasses import asdict
        amount = _usd(approval.max_estimated_usd)
        if _usd(preflight.estimated_usd) > amount:
            raise ValueError("estimate exceeds approval")
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM reservations WHERE approval_id=?", (approval.approval_id,)).fetchone():
                raise ValueError("one-use budget receipt already reserved")
            rows = list(db.execute("SELECT request_hash,scope,billed_usd,manifest FROM reservations"))
            rows += [(h,s,None,m) for h,s,m in db.execute("SELECT request_hash,scope,manifest FROM historical_cache")]
            for old_hash, scope, billed, manifest in rows:
                old = json.loads(scope)
                shared = {tuple(c) for c in old["contracts"]} & set(request.contracts)
                overlap = old["start_ns"] < request.end_ns and request.start_ns < old["end_ns"]
                if old["dataset"] == request.dataset and old["schema"] == request.schema and shared and overlap:
                    # A reviewed retry of the same failed request can proceed only
                    # after reconciliation; successful ranges should be reused.
                    failed = manifest and json.loads(manifest).get("status") == "QUARANTINED"
                    if not (old_hash == request.sha256 and billed is not None and failed):
                        raise ValueError("overlapping download; reuse cache or review quarantined range")
            limit = _usd(db.execute("SELECT limit_usd FROM budget WHERE id=1").fetchone()[0])
            if self._committed(db)+amount > limit:
                raise ValueError("approved research budget exceeded")
            db.execute("INSERT INTO reservations (approval_id,request_hash,scope,reserved_usd) VALUES (?,?,?,?)",
                       (approval.approval_id, request.sha256, json.dumps(asdict(request), sort_keys=True), str(amount)))
            db.execute("COMMIT")

    def authorize_transport(self, request, preflight, approval):
        """Lowest billable boundary consumes a persistent one-attempt permit."""
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT request_hash,reserved_usd,transport_started FROM reservations WHERE approval_id=?",
                             (approval.approval_id,)).fetchone()
            if (not row or row[0] != request.sha256 or row[2]
                    or _usd(row[1]) != _usd(approval.max_estimated_usd)
                    or _usd(preflight.estimated_usd) > _usd(row[1])):
                raise ValueError("matching unused budget permit required before transport")
            db.execute("UPDATE reservations SET transport_started=1 WHERE approval_id=?", (approval.approval_id,))
            db.execute("COMMIT")

    def record_manifest(self, approval_id, manifest):
        with connect(self.path) as db:
            changed = db.execute("UPDATE reservations SET manifest=? WHERE approval_id=?",
                (json.dumps(manifest, sort_keys=True, allow_nan=False), approval_id)).rowcount
            if changed != 1:
                raise ValueError("budget reservation missing")

    def register_existing(self, request, manifest, *, archive, provenance_review_reference):
        """Index previously authorized complete data without new provider usage.

        Preserve the saved bill/credit state; unknown historical usage is never
        reported as zero spending. No raw data or old credentials are copied.
        """
        from dataclasses import asdict
        from monatise.research.databento.acquisition import inspect_request_archive
        _reference(provenance_review_reference)
        if (manifest.get("status") != "ARCHIVED" or manifest.get("request_sha256") != request.sha256
                or not manifest.get("coverage",{}).get("transport_complete")
                or manifest.get("evidence_kind") != "AUTHENTIC_HISTORICAL_DOWNLOAD"):
            raise ValueError("complete authentic historical manifest required; quarantine cannot be reused")
        if inspect_request_archive(archive.verify(manifest["archive_sha256"]),request) != manifest["coverage"]:
            raise ValueError("existing manifest contradicts native archive")
        value = {**manifest,"cache_archive_root":str(archive.root)}
        payload = json.dumps(value,sort_keys=True,allow_nan=False)
        scope = json.dumps(asdict(request),sort_keys=True)
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT manifest FROM historical_cache WHERE request_hash=?",(request.sha256,)).fetchone()
            if old and old[0] != payload:
                raise ValueError("historical cache provenance conflict")
            db.execute("INSERT OR IGNORE INTO historical_cache VALUES (?,?,?,?)",
                       (request.sha256,scope,payload,provenance_review_reference))
            db.execute("COMMIT")

    def settle(self, approval_id, *, actual_billed_usd, credit_used_usd, billing_review_reference):
        _reference(billing_review_reference)
        billed, credit = _usd(actual_billed_usd), _usd(credit_used_usd)
        if credit > billed:
            raise ValueError("credit used exceeds actual API usage")
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT billed_usd FROM reservations WHERE approval_id=?", (approval_id,)).fetchone()
            if not previous or previous[0] is not None:
                raise ValueError("missing or already settled reservation")
            db.execute("UPDATE reservations SET billed_usd=?,credit_used_usd=?,billing_review=? WHERE approval_id=?",
                       (str(billed), str(credit), billing_review_reference, approval_id))
            db.execute("COMMIT")

    def plan(self, request, *, archive):
        """Find complete covering artifacts and every partial overlap locally.

        Does not estimate/download. Caller slices/revalidates a covering archive;
        ranges are never silently merged or billed again. Quarantine is excluded.
        """
        covering, overlaps, reusable = [], [], []
        with connect(self.path) as db:
            rows = db.execute("SELECT request_hash,scope,manifest FROM reservations").fetchall()
            rows += db.execute("SELECT request_hash,scope,manifest FROM historical_cache").fetchall()
        for digest, scope, raw in rows:
            old = json.loads(scope)
            if (old["dataset"], old["schema"]) != (request.dataset, request.schema):
                continue
            shared = {tuple(c) for c in old["contracts"]} & set(request.contracts)
            if not shared or old["start_ns"] >= request.end_ns or request.start_ns >= old["end_ns"]:
                continue
            overlaps.append(digest)
            manifest = json.loads(raw) if raw else None
            if (manifest and manifest["status"] == "ARCHIVED"
                    and manifest["coverage"]["transport_complete"]):
                if manifest.get("cache_archive_root"):
                    from monatise.research.databento.archive import NativeDBNArchive
                    NativeDBNArchive.open_existing(manifest["cache_archive_root"]).verify(manifest["archive_sha256"])
                else:
                    archive.verify(manifest["archive_sha256"])
                reusable.append((old,manifest))
                if (set(request.contracts) <= {tuple(c) for c in old["contracts"]}
                        and old["start_ns"] <= request.start_ns < request.end_ns <= old["end_ns"]):
                    covering.append(manifest)
        uncovered = []
        for contract in request.contracts:
            cursor = request.start_ns
            spans = sorted((max(request.start_ns,old["start_ns"]),min(request.end_ns,old["end_ns"]))
                for old,_ in reusable if contract in {tuple(c) for c in old["contracts"]})
            for start,end in spans:
                if start > cursor:
                    uncovered.append({"contract":contract,"start_ns":cursor,"end_ns":start})
                cursor = max(cursor,end)
            if cursor < request.end_ns:
                uncovered.append({"contract":contract,"start_ns":cursor,"end_ns":request.end_ns})
        return {"covering_manifests": covering, "overlapping_request_hashes": sorted(set(overlaps)),
                "reusable_manifests":[m for _,m in reusable],"uncovered_ranges":uncovered,
                "new_download_required": bool(uncovered), "incremental_cost_usd": "0" if not uncovered else None}

    def report(self):
        with connect(self.path) as db:
            limit, credit, review = db.execute("SELECT limit_usd,credit_usd,review FROM budget WHERE id=1").fetchone()
            rows = db.execute("SELECT reserved_usd,billed_usd,credit_used_usd FROM reservations").fetchall()
            cached = [json.loads(m) for (m,) in db.execute("SELECT manifest FROM historical_cache")]
            committed = self._committed(db)
        billed = sum((_usd(b) for _,b,_ in rows if b is not None), _usd(0))
        used = sum((_usd(c) for _,_,c in rows if c is not None), _usd(0))
        return {"approved_budget_usd": limit, "budget_review_reference": review,
                "committed_usage_usd": str(committed), "remaining_budget_usd": str(_usd(limit)-committed),
                "settled_api_usage_usd": str(billed), "credit_used_usd": str(used),
                "settled_cash_usd": str(billed-used), "historical_credit_usd": credit,
                "unreconciled_attempts": sum(b is None for _,b,_ in rows),
                "previously_acquired_cache_count":len(cached),
                "historical_cache_unknown_billing_count":sum(m.get("actual_billed_usd") is None for m in cached),
                "provider_charge_cap": False, "trading_enabled": False}
