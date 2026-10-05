"""Explicit broker schedule; no guessed timezone, holidays or exchange calendar.

A reviewed manifest contains UTC offset eras and UTC trading intervals from the
broker. Loading it does not certify its source or authorize order execution.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from monatise.application.hierarchy.policy import INTERVAL_SECONDS


def utc(value):
    result = datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        raise ValueError("broker schedule requires UTC-aware timestamps")
    return result.astimezone(UTC)


@dataclass(frozen=True)
class GoldSessionCalendar:
    account_id: str
    server: str
    symbol: str
    source: str
    version: str
    start: datetime
    end: datetime
    offsets: tuple[tuple[datetime, datetime, int], ...]
    sessions: tuple[tuple[datetime, datetime], ...]
    fingerprint: str

    @classmethod
    def from_manifest(cls, manifest):
        if manifest.get("schema") != "gold-broker-sessions-v1":
            raise ValueError("unsupported broker schedule schema")
        identity = [
            manifest.get(k)
            for k in ("account_id", "server", "symbol", "source", "version")
        ]
        if (
            not all(isinstance(v, str) and v.strip() for v in identity)
            or identity[2] != "XAU/USD"
        ):
            raise ValueError("broker schedule identity/source required")
        start, end = utc(manifest["valid_from"]), utc(manifest["valid_until"])
        if not timedelta(days=1) <= end - start <= timedelta(days=400):
            raise ValueError("bounded broker schedule validity required")
        offsets, sessions = [], []
        for row in manifest["offsets"]:
            a, b, seconds = utc(row["from"]), utc(row["until"]), row["seconds"]
            if (
                isinstance(seconds, bool)
                or not isinstance(seconds, int)
                or abs(seconds) > 14 * 3600
                or seconds % 60
            ):
                raise ValueError("invalid historical broker UTC offset")
            if a >= b or a < start or b > end or (offsets and a != offsets[-1][1]):
                raise ValueError("offset eras must cover validity contiguously")
            offsets.append((a, b, seconds))
        if not offsets or offsets[0][0] != start or offsets[-1][1] != end:
            raise ValueError("historical offset coverage incomplete")
        for row in manifest["sessions"]:
            a, b = utc(row["open"]), utc(row["close"])
            if (
                not start <= a < b <= end
                or b - a > timedelta(days=1)
                or (sessions and a < sessions[-1][1])
            ):
                raise ValueError("invalid broker session interval")
            sessions.append((a, b))
        if not sessions or len(sessions) > 2000 or len(offsets) > 100:
            raise ValueError("bounded broker schedule coverage required")
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return cls(*identity, start, end, tuple(offsets), tuple(sessions), digest)

    @classmethod
    def load(cls, path):
        file = Path(path)
        if file.stat().st_size > 1_000_000:
            raise ValueError("broker schedule manifest too large")
        return cls.from_manifest(json.loads(file.read_text()))

    def require_identity(self, account, server, symbol):
        if (
            str(account) != self.account_id
            or str(server).casefold() != self.server.casefold()
            or symbol != self.symbol
        ):
            raise ValueError("broker schedule identity mismatch")

    def offset(self, at):
        if at.tzinfo is None or not self.start <= at < self.end:
            raise ValueError("broker schedule outside reviewed coverage")
        return next(seconds for a, b, seconds in self.offsets if a <= at < b)

    def normalize_broker_epoch(self, wall_epoch):
        if isinstance(wall_epoch, bool) or not isinstance(wall_epoch, int):
            raise ValueError("raw broker timestamp required")  # noqa: TRY004
        candidates = [
            datetime.fromtimestamp(wall_epoch - seconds, UTC)
            for a, b, seconds in self.offsets
            if a.timestamp() <= wall_epoch - seconds < b.timestamp()
        ]
        if len(candidates) != 1:
            raise ValueError("broker timestamp ambiguous or outside offset coverage")
        return candidates[0]

    def session_close(self, now):
        self.offset(now)
        for a, b in self.sessions:
            if a <= now < b:
                return b
        raise ValueError("gold_broker_session_closed_or_break")

    def require_regular_session(self, now):
        self.session_close(now)

    def regular_bar(self, opened, timeframe):
        seconds = INTERVAL_SECONDS[timeframe]
        offset = self.offset(opened)
        if (int(opened.timestamp()) + offset) % seconds:
            return False
        close = opened + timedelta(seconds=seconds)
        if self.offset(close - timedelta(microseconds=1)) != offset:
            return False  # no fixed-duration bar through a clock transition
        return any(a <= opened and close <= b for a, b in self.sessions)

    def expected_closed_open(self, timeframe, now, *, grace_seconds=10):
        self.offset(now)
        seconds = INTERVAL_SECONDS[timeframe]
        latest = None
        for a, b in self.sessions:
            cutoff = min(b, now - timedelta(seconds=grace_seconds))
            if cutoff < a + timedelta(seconds=seconds):
                continue
            # Broker bars are anchored to broker midnight, not US equity hours.
            for era_a, era_b, offset in self.offsets:
                end = min(cutoff, era_b)
                epoch = (
                    (int(end.timestamp()) + offset) // seconds * seconds
                    - offset
                    - seconds
                )
                candidate = datetime.fromtimestamp(epoch, UTC)
                if (
                    candidate >= era_a
                    and candidate >= a
                    and self.regular_bar(candidate, timeframe)
                ):
                    latest = max(latest, candidate) if latest else candidate
        if latest is None:
            raise ValueError("expected broker closed bar unavailable")
        return latest
