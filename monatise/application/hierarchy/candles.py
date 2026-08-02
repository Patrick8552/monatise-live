from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Iterable, Mapping

from monatise.application.hierarchy.models import BoundaryStatus, NormalizedCandle, Provenance, deterministic_id
from monatise.core.models import Candle


INTERVAL_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400}


def interval_duration(interval: str) -> timedelta:
    try:
        return timedelta(seconds=INTERVAL_SECONDS[interval])
    except KeyError as exc:
        raise ValueError(f"unsupported hierarchical interval: {interval}") from exc


def next_boundary(now: datetime, interval: str, *, grace_seconds: int = 0) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    seconds = INTERVAL_SECONDS.get(interval)
    if seconds is None:
        raise ValueError(f"unsupported hierarchical interval: {interval}")
    epoch = now.astimezone(timezone.utc).timestamp()
    boundary = ceil(epoch / seconds) * seconds
    if boundary <= epoch:
        boundary += seconds
    return datetime.fromtimestamp(boundary + grace_seconds, timezone.utc)


def _timestamp(value: str) -> datetime:
    raw = value.strip()
    if raw.isdigit():
        epoch = int(raw)
        if epoch > 10_000_000_000:
            epoch //= 1000
        return datetime.fromtimestamp(epoch, timezone.utc)
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("provider candle timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


class CandleBoundaryNormalizer:
    """Conservatively derives closed candles without trusting a forming provider row."""

    def __init__(self, *, grace_seconds: int = 10, normalization_version: str = "hierarchy-candle-v1") -> None:
        if grace_seconds < 0:
            raise ValueError("grace_seconds cannot be negative")
        self.grace_seconds = grace_seconds
        self.normalization_version = normalization_version

    def normalize(self, candle: Candle, *, symbol: str, timeframe: str, received_at: datetime, provenance: Provenance, confirmation_observations: int = 1) -> NormalizedCandle:
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")
        candle.validate()
        open_time = _timestamp(candle.timestamp)
        close_time = open_time + interval_duration(timeframe)
        eligible_at = close_time + timedelta(seconds=self.grace_seconds)
        closed_by_clock = received_at.astimezone(timezone.utc) >= eligible_at
        is_final = closed_by_clock and confirmation_observations >= 2
        status = BoundaryStatus.FINALIZED if is_final else BoundaryStatus.FORMING
        values = f"{candle.open:.12g}|{candle.high:.12g}|{candle.low:.12g}|{candle.close:.12g}|{candle.volume:.12g}"
        content_hash = hashlib.sha256(values.encode()).hexdigest()
        candle_id = deterministic_id("candle", {"symbol": symbol.upper(), "timeframe": timeframe, "open_time": open_time.isoformat(), "provider": provenance.provider, "exchange": provenance.exchange})
        return NormalizedCandle(candle_id, symbol.upper(), timeframe, open_time, close_time, open_time, received_at, candle.open, candle.high, candle.low, candle.close, candle.volume, is_final, status, content_hash, provenance)

    def normalize_series(self, candles: Iterable[Candle], *, symbol: str, timeframe: str, received_at: datetime, provenance: Provenance, previous_hashes: Mapping[str, str] | None = None) -> tuple[NormalizedCandle, ...]:
        known = previous_hashes or {}
        normalized: list[NormalizedCandle] = []
        for candle in candles:
            preliminary = self.normalize(candle, symbol=symbol, timeframe=timeframe, received_at=received_at, provenance=provenance)
            observations = 2 if known.get(preliminary.candle_id) == preliminary.content_hash else 1
            normalized.append(self.normalize(candle, symbol=symbol, timeframe=timeframe, received_at=received_at, provenance=provenance, confirmation_observations=observations))
        return tuple(normalized)
