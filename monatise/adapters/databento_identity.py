"""Explicit research identity policy. No I/O, client construction or activation.

GLBX is the feed venue; XCEC is the GC/OG definition's economic exchange.
Metadata provenance is an audit reference, not a market-data certification.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

UNDEF_TIMESTAMP = (1 << 64) - 1


def timestamp_ns(value, *, optional=False):
    if optional and (value is None or value == UNDEF_TIMESTAMP):
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < UNDEF_TIMESTAMP:
        raise ValueError("invalid integer nanosecond timestamp")
    return value


def datetime_ns(value):
    """Clock presentation bridge only; does not reconstruct discarded nanos."""
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("aware UTC-compatible clock required")
    delta = value.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


def broker_xauusd_namespace(broker_id):
    """Caller supplies a reviewed opaque broker reference, never credentials."""
    if not isinstance(broker_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", broker_id):
        raise ValueError("reviewed opaque broker identifier required")
    return "BROKER:XAUUSD:" + broker_id


@dataclass(frozen=True)
class DatabentoPublisherPolicy:
    publishers: tuple[tuple[int, str, str], ...]
    observed_at_ns: int
    source_sha256: str
    policy_version: str = "databento-gc-identity-research-v1"

    def __post_init__(self):
        timestamp_ns(self.observed_at_ns)
        if self.policy_version != "databento-gc-identity-research-v1":
            raise ValueError("unknown identity policy")
        if not isinstance(self.publishers, tuple) or not self.publishers or len(self.publishers) > 2048:
            raise ValueError("bounded publisher catalog required")
        ids = []
        for entry in self.publishers:
            if not isinstance(entry, tuple) or len(entry) != 3:
                raise ValueError("immutable publisher entries required")
            pid, dataset, venue = entry
            if isinstance(pid, bool) or not isinstance(pid, int) or not 0 < pid < 65536:
                raise ValueError("invalid publisher identifier")
            if not isinstance(dataset, str) or not isinstance(venue, str):
                raise ValueError("invalid publisher identity")
            if len(dataset) > 32 or len(venue) > 16 or not dataset or not venue:
                raise ValueError("invalid publisher identity")
            ids.append(pid)
        if len(set(ids)) != len(ids) or ids != sorted(ids):
            raise ValueError("duplicate or unordered publisher metadata")
        if not isinstance(self.source_sha256, str) or len(self.source_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.source_sha256):
            raise ValueError("metadata source hash required")
        if not any((dataset, venue) == ("GLBX.MDP3", "GLBX") for _, dataset, venue in self.publishers):
            raise ValueError("GLBX.MDP3/GLBX publisher absent")

    @classmethod
    def from_metadata(cls, rows, *, observed_at_ns, source_sha256):
        rows = tuple(rows)
        if len(rows) > 2048:
            raise ValueError("publisher metadata capacity exceeded")
        try:
            entries = tuple(sorted((r["publisher_id"], r["dataset"], r["venue"]) for r in rows))
        except (KeyError, TypeError):
            raise ValueError("invalid publisher metadata schema") from None
        return cls(entries, observed_at_ns, source_sha256)

    @property
    def mapping(self):
        return {pid: (dataset, venue) for pid, dataset, venue in self.publishers}

    @property
    def sha256(self):
        payload = (self.policy_version, self.publishers, self.observed_at_ns, self.source_sha256)
        return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()

    def validate(self, record, *, publishers, now, cutoff_ns=None):
        clock = datetime_ns(now)
        cutoff = clock if cutoff_ns is None else timestamp_ns(cutoff_ns)
        if cutoff_ns is not None and cutoff // 1000 * 1000 != clock:
            raise ValueError("nanosecond cutoff contradicts presentation clock")
        if self.observed_at_ns > cutoff:
            raise ValueError("publisher metadata unavailable at assessment")
        pid = record.publisher_id
        if isinstance(pid, bool) or not isinstance(pid, int):
            raise ValueError("invalid record publisher")
        expected = self.mapping.get(pid)
        if expected != ("GLBX.MDP3", "GLBX") or publishers.get(pid) != expected:
            raise ValueError("unknown or contradictory GC feed publisher")
        if str(getattr(record, "exchange", "")) != "XCEC":
            raise ValueError("unknown or contradictory GC economic exchange")
        event, received, expiration = (
            timestamp_ns(record.ts_event), timestamp_ns(record.ts_recv),
            timestamp_ns(record.expiration),
        )
        if not event <= received <= cutoff < expiration:
            raise ValueError("definition unavailable at nanosecond cutoff")
        if str(record.instrument_class) == "F":
            match = re.fullmatch(r"GC([FGHJKMNQUVXZ])(\d{1,2})", str(record.raw_symbol))
            year, month = record.maturity_year, record.maturity_month
            if (match is None or isinstance(year, bool) or not isinstance(year, int)
                    or not 1900 <= year <= 2200 or isinstance(month, bool)
                    or not isinstance(month, int) or month != "FGHJKMNQUVXZ".index(match[1]) + 1
                    or year % (10 ** len(match[2])) != int(match[2])):
                raise ValueError("GC symbol/maturity contradiction")
        elif str(record.instrument_class) in {"C", "P"}:
            if (str(record.asset) != "OG" or str(record.security_type) != "OOF"
                    or not str(record.raw_symbol).startswith("OG")):
                raise ValueError("unsupported standard OG identity")
        else:
            raise ValueError("unsupported GC/OG contract class")
