"""Bounded manual terminal-export plans and offline import; no broker client."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import timedelta
from pathlib import Path

from monatise.application.hierarchy.policy import INTERVAL_SECONDS
from monatise.research.broker_xauusd.models import TIMEFRAMES, canonical, digest, expected_opens, instant


def acquisition_plan(identity, calendar, *, start, end, mapping_reference, page_bars=240):
    identity.validate_calendar(calendar)
    start, end = instant(start), instant(end)
    if not isinstance(mapping_reference, str) or not mapping_reference.strip():
        raise ValueError("reviewed native-symbol mapping reference required")
    if not calendar.start <= start < end <= calendar.end or end-start > timedelta(days=31):
        raise ValueError("reviewed bounded historical range required (maximum 31 days)")
    if type(page_bars) is not int or not 1 <= page_bars <= 240:
        raise ValueError("page size must be 1..240")
    pages = []
    for tf in TIMEFRAMES:
        opens = []
        chunk = start
        while chunk < end:
            until = min(chunk+timedelta(days=7), end)
            opens.extend(expected_opens(calendar, tf, chunk, until))
            chunk = until
        # Split at reviewed era changes before pagination. Never translate old
        # boundaries using today's offset, nor query through an offset transition.
        for era_start, era_end, offset in calendar.offsets:
            era_opens = [t for t in opens if era_start <= t < era_end]
            groups = [[t for t in era_opens if a <= t < b] for a,b in calendar.sessions]
            for selected in [g[i:i+page_bars] for g in groups for i in range(0,len(g),page_bars)]:
                utc_end = selected[-1]+timedelta(seconds=INTERVAL_SECONDS[tf])
                # Long closures can otherwise make a small page span many days.
                if utc_end-selected[0] > timedelta(days=7):
                    raise ValueError("page spans too many closed days; reduce page size")
                page = {"schema": "gold-mt5-historical-page-v1", "identity": identity.__dict__,
                    "mapping_reference": mapping_reference, "calendar_fingerprint": calendar.fingerprint,
                    "timeframe": tf, "start": selected[0].isoformat(), "end": utc_end.isoformat(),
                    "from_broker_epoch": int(selected[0].timestamp())+offset,
                    "until_broker_epoch_exclusive": int(utc_end.timestamp())+offset,
                    "expected_opens": [t.isoformat() for t in selected], "maximum_bars": page_bars,
                    "method": "MANUAL_MT5_SCRIPT_EXPORT", "connection_authorized": False}
                page["page_id"] = digest(page)
                pages.append(page)
    result = {"schema": "gold-mt5-historical-plan-v1", "start": start.isoformat(), "end": end.isoformat(),
              "identity": identity.__dict__, "pages": pages, "automatic_download": False,
              "connection_authorized": False, "execution_enabled": False}
    result["sha256"] = digest(result)
    return result


def validate_export(raw, page, archive):
    """Report defects without discarding the source or silently deduplicating."""
    if not isinstance(raw, dict):
        raise ValueError("export must be an object")
    tf = page["timeframe"]
    errors, warnings, seen, valid, duplicates, invalid = [], [], {}, [], [], []
    if page.get("page_id") != digest({k:v for k,v in page.items() if k != "page_id"}):
        raise ValueError("page plan integrity failure")
    if page["identity"] != archive.identity.__dict__ or page["calendar_fingerprint"] != archive.calendar.fingerprint:
        raise ValueError("page/archive identity mismatch")
    if raw.get("schema") != "gold-mt5-historical-export-v1" or raw.get("page_id") != page["page_id"]:
        errors.append("EXPORT_REQUEST_MISMATCH")
    if any(k not in raw for k in ("captured_at","broker_time_offset","point","tick_size","spread_price")):
        errors.append("EXPORT_METADATA_MISSING")
    if (str(raw.get("account_id")) != archive.identity.account_id or raw.get("server") != archive.identity.server
        or raw.get("symbol") != archive.identity.broker_symbol or raw.get("timeframe") != tf):
        errors.append("BROKER_IDENTITY_MISMATCH")
    for name, key in (("from_broker_epoch", "from_broker_epoch"), ("until_broker_epoch_exclusive", "until_broker_epoch_exclusive")):
        if type(raw.get(name)) is not int or raw.get(name) != page[key]:
            errors.append("EXPORT_RANGE_MISMATCH")
    rows = raw.get("rows")
    if not isinstance(rows, list) or len(rows) > page["maximum_bars"]:
        rows = []
        errors.append("EXPORT_ROW_LIMIT_OR_FORMAT")
    previous = None
    for ordinal, row in enumerate(rows):
        try:
            opened = archive.calendar.normalize_broker_epoch(row.get("t_broker"))
            if opened.isoformat() not in page["expected_opens"]:
                raise ValueError("OUTSIDE_EXPECTED_SESSION_GRID")
            if opened in seen:
                duplicates.append({"ordinal": ordinal, "opened_at": opened.isoformat(),
                                   "same_values": row == seen[opened]})
            if previous is not None and opened < previous:
                errors.append("UNORDERED_BROKER_BARS")
            previous = opened
            seen[opened] = row
            # Reuse authentic canonical finite geometry validation via archive,
            # after the receiver has attached actual local receive time.
            from math import isfinite
            from monatise.core.models import Candle
            vals = [row.get(k) for k in ("o", "h", "l", "c", "v")]
            if any(type(v) not in (int,float) or not isfinite(v) for v in vals):
                raise ValueError("INVALID_NUMERIC_OHLCV")
            Candle(opened.isoformat(), *vals).validate()
            if vals[2] <= 0 or vals[4] < 0:
                raise ValueError("INVALID_PRICE_OR_VOLUME")
            if "spread_points" in row and (type(row["spread_points"]) is not int or row["spread_points"] < 0):
                raise ValueError("INVALID_REPORTED_SPREAD")
            valid.append(opened.isoformat())
        except (ValueError, TypeError, OverflowError, AttributeError):
            invalid.append({"ordinal": ordinal, "reason": "INVALID_CANDLE_OR_TIMESTAMP"})
    missing = sorted(set(page["expected_opens"])-set(valid))
    if duplicates: errors.append("DUPLICATE_BROKER_BARS")
    if invalid: errors.append("INVALID_BROKER_BARS")
    if missing: warnings.append("PARTIAL_OR_MISSING_HISTORY")
    try:
        first_available = archive.calendar.normalize_broker_epoch(raw["series_first_broker_epoch"])
        if first_available > instant(page["start"]):
            warnings.append("BROKER_HISTORY_TRUNCATED_AT_START")
    except (KeyError, ValueError, TypeError, OverflowError):
        first_available = None
        warnings.append("BROKER_HISTORY_START_UNKNOWN")
    if raw.get("copied_count") != len(rows) or type(raw.get("copied_count")) is not int:
        errors.append("COPIED_COUNT_MISMATCH")
    if raw.get("last_error", 0) != 0:
        warnings.append("TERMINAL_REPORTED_ERROR")
    return {"schema": "gold-historical-page-quality-v1", "page_id": page["page_id"],
        "timeframe": tf, "expected": len(page["expected_opens"]), "returned": len(rows),
        "available_range": {"first": min(valid) if valid else None, "last": max(valid) if valid else None},
        "missing": missing, "duplicates": duplicates, "invalid": invalid, "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)), "session_gaps_filled": 0,
        "broker_history_start": first_available.isoformat() if first_available else None,
        "archive_eligible": not errors, "coverage_complete": not errors and not missing and not warnings}


async def import_export(archive, path, page, *, source_reference, capture_calendar_manifest=None, engineering=False):
    """Offline local export import; no authentication, connection or downloads.

    Receive time is actual local read completion. Terminal capture is untouched.
    Any failed/unknown source is retained in append-only quarantine, not normalized.
    """
    file = Path(path)
    if file.stat().st_size > 8_000_000:
        raise ValueError("export exceeds bounded local import size")
    wire = file.read_bytes()
    received = instant(archive.clock())
    try:
        raw = json.loads(wire)
        quality = validate_export(raw, page, archive)
    except (ValueError, TypeError, KeyError):
        raw = None
        quality = {"errors": ["INVALID_EXPORT_FORMAT"], "archive_eligible": False}
    quality["wire_sha256"] = hashlib.sha256(wire).hexdigest()
    quality["received_at"] = received.isoformat()
    if quality["archive_eligible"]:
        request_id = digest({"page_id": page["page_id"], "wire_sha256": quality["wire_sha256"]})
        payload = {"request_id": request_id, "account_id": raw["account_id"], "server": raw["server"],
            "symbol": raw["symbol"], "captured_at": raw["captured_at"], "received_at": received.isoformat(),
            "broker_time_offset": raw["broker_time_offset"], "timestamp_policy": "current_offset_uncertified_history",
            "point": raw["point"], "tick_size": raw["tick_size"], "spread_price": raw["spread_price"],
            "timeframes": {page["timeframe"]: raw["rows"]}, "original_export": raw,
            "wire_sha256": quality["wire_sha256"], "volume_kind": "tick_volume"}
        try:
            kind = "ENGINEERING_SYNTHETIC" if engineering else "RETROSPECTIVE_HISTORICAL_DOWNLOAD"
            batch_id = digest({"namespace":archive.namespace, "request_id":request_id})
            existing = await archive.store.get(archive.namespace,"batch:"+batch_id)
            if existing is not None:
                body = existing.value
                if (existing.version != 1 or body.get("body_sha256") != digest({k:v for k,v in body.items() if k != "body_sha256"})
                    or body.get("evidence_kind") != kind or body.get("source_reference") != source_reference
                    or body.get("raw_payload",{}).get("wire_sha256") != quality["wire_sha256"]
                    or body.get("raw_sha256") != digest(body["raw_payload"])):
                    raise ValueError("reimport identity or evidence-class conflict")
                # Exact bytes are one observation. Preserve first receive time;
                # retry an orphan admission without manufacturing a new capture.
                payload = body["raw_payload"]
            receipt = await archive.append(payload, evidence_kind=kind,
                source_reference=source_reference, window={"start":page["start"],"end":page["end"]},
                capture_calendar_manifest=capture_calendar_manifest)
            quality["receipt"] = receipt
        except (ValueError, KeyError, TypeError, OverflowError):
            quality.update(archive_eligible=False, errors=quality["errors"]+["ARCHIVE_PROVENANCE_OR_GEOMETRY_REJECTED"])
    evidence = {"schema": "gold-export-custody-v1", "evidence_kind": "ENGINEERING_SYNTHETIC" if engineering else "UNKNOWN_OR_UNVERIFIED",
        "wire_sha256": quality["wire_sha256"], "wire_base64": base64.b64encode(wire).decode(),
        "source_reference": source_reference, "received_at": received.isoformat(), "page_id": page["page_id"],
        "quality": quality, "capture_authenticity": "NOT_INDEPENDENTLY_VERIFIED", "execution_enabled": False}
    # Receive/custody records are distinct from normalized candle observations.
    key = "custody:"+digest(evidence)
    await archive._create(key, evidence)
    return quality
