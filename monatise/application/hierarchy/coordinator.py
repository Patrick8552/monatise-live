from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Protocol
import os

from monatise.application.hierarchy.candles import CandleBoundaryNormalizer
from monatise.application.hierarchy.candles import next_boundary
from monatise.application.hierarchy.lifecycle import HierarchyRepository
from monatise.application.hierarchy.models import EvidenceBundle, EvidenceContext, NormalizedCandle, Provenance, RiskProposal
from monatise.core.models import Candle


class CandleProvider(Protocol):
    def candles(self, symbol: str, limit: int, interval: str = "1h") -> list[Candle]: ...


@dataclass(frozen=True)
class HierarchyConfiguration:
    enabled: bool = False
    telegram_publish_enabled: bool = False
    strategy_version: str = "hierarchy-shadow-v1"
    candle_limit: int = 200
    provider_grace_seconds: int = 10
    macro_refresh_seconds: int = 900
    regime_refresh_seconds: int = 900
    strategy_refresh_seconds: int = 900
    setup_refresh_seconds: int = 300
    trigger_poll_seconds: int = 60
    maximum_provider_requests_per_cycle: int = 4
    confirmation_retry_seconds: int = 5

    def __post_init__(self) -> None:
        values = (self.candle_limit, self.macro_refresh_seconds, self.regime_refresh_seconds, self.strategy_refresh_seconds, self.setup_refresh_seconds, self.trigger_poll_seconds, self.maximum_provider_requests_per_cycle, self.confirmation_retry_seconds)
        if any(value <= 0 for value in values):
            raise ValueError("hierarchy configuration values must be positive")
        if self.provider_grace_seconds < 0 or not self.strategy_version:
            raise ValueError("hierarchy grace and strategy version are invalid")
        if self.maximum_provider_requests_per_cycle < 4:
            raise ValueError("provider budget must permit all four timeframe snapshots")

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> "HierarchyConfiguration":
        values = os.environ if environment is None else environment
        truthy = {"1", "true", "yes", "on", "enabled"}
        enabled = values.get("MONATISE_HIERARCHICAL_SHADOW_ENABLED", "false").strip().casefold() in truthy
        publish = values.get("MONATISE_HIERARCHICAL_TELEGRAM_PUBLISH_ENABLED", "false").strip().casefold() in truthy
        return cls(
            enabled=enabled,
            telegram_publish_enabled=publish,
            strategy_version=values.get("MONATISE_HIERARCHICAL_STRATEGY_VERSION", "hierarchy-shadow-v1").strip(),
            candle_limit=int(values.get("MONATISE_HIERARCHICAL_CANDLE_LIMIT", "200")),
            provider_grace_seconds=int(values.get("MONATISE_HIERARCHICAL_PROVIDER_GRACE_SECONDS", "10")),
            maximum_provider_requests_per_cycle=int(values.get("MONATISE_HIERARCHICAL_MAX_REQUESTS_PER_CYCLE", "4")),
            confirmation_retry_seconds=int(values.get("MONATISE_HIERARCHICAL_CONFIRMATION_RETRY_SECONDS", "5")),
        )


@dataclass(frozen=True)
class TimeframeSnapshot:
    symbol: str
    timeframe: str
    observed_at: datetime
    candles: tuple[NormalizedCandle, ...]
    latest_finalized: NormalizedCandle | None
    revisions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShadowComparison:
    symbol: str
    observed_at: datetime
    legacy_outcome: str
    hierarchical_outcome: str
    entry_delay_seconds: float | None = None
    initial_reward_to_risk: float | None = None
    maximum_favorable_excursion: float | None = None
    maximum_adverse_excursion: float | None = None
    stale_parent_blocked: bool = False
    forming_candle_blocked: bool = False
    duplicate_blocked: bool = False
    execution_enabled: bool = False


class ShadowHierarchyCoordinator:
    """Collects and versions evidence without granting execution capability."""

    TIMEFRAMES = ("4h", "1h", "15m", "5m")

    def __init__(self, provider: CandleProvider, repository: HierarchyRepository, *, configuration: HierarchyConfiguration | None = None, provenance: Provenance | None = None) -> None:
        self.provider = provider
        self.repository = repository
        self.configuration = configuration or HierarchyConfiguration()
        self.provenance = provenance or Provenance("unknown", "unknown", "unknown", "unknown", "hierarchy-candle-v1")
        self.normalizer = CandleBoundaryNormalizer(grace_seconds=self.configuration.provider_grace_seconds, normalization_version=self.provenance.normalization_version)
        self._observed_hashes: dict[tuple[str, str], dict[str, str]] = {}
        self._next_due: dict[tuple[str, str], datetime] = {}

    async def collect(self, symbol: str, *, observed_at: datetime | None = None) -> Mapping[str, TimeframeSnapshot]:
        if not self.configuration.enabled:
            raise RuntimeError("hierarchical shadow coordinator is disabled")
        now = observed_at or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        snapshots: dict[str, TimeframeSnapshot] = {}
        for timeframe in self.TIMEFRAMES:
            snapshots[timeframe] = await self._collect_timeframe(symbol, timeframe, now)
        return snapshots

    async def collect_due(self, symbol: str, *, watching: bool, observed_at: datetime | None = None) -> Mapping[str, TimeframeSnapshot]:
        """Fetch only boundary-due layers; 5m stays dormant until a setup is watched."""
        if not self.configuration.enabled:
            raise RuntimeError("hierarchical shadow coordinator is disabled")
        now = observed_at or datetime.now(timezone.utc)
        candidates = ("4h", "1h", "15m") + (("5m",) if watching else ())
        due = [timeframe for timeframe in candidates if now >= self._next_due.get((symbol.upper(), timeframe), datetime.min.replace(tzinfo=timezone.utc))]
        if len(due) > self.configuration.maximum_provider_requests_per_cycle:
            raise RuntimeError("hierarchy provider request budget exceeded")
        snapshots: dict[str, TimeframeSnapshot] = {}
        for timeframe in due:
            snapshots[timeframe] = await self._collect_timeframe(symbol, timeframe, now)
            self._next_due[(symbol.upper(), timeframe)] = (
                next_boundary(now, timeframe, grace_seconds=self.configuration.provider_grace_seconds)
                if snapshots[timeframe].latest_finalized is not None
                else now + timedelta(seconds=self.configuration.confirmation_retry_seconds)
            )
        return snapshots

    async def _collect_timeframe(self, symbol: str, timeframe: str, now: datetime) -> TimeframeSnapshot:
        key = (symbol.upper(), timeframe)
        previous = self._observed_hashes.get(key, {})
        raw = await asyncio.to_thread(
            self.provider.candles,
            symbol.upper(),
            self.configuration.candle_limit,
            timeframe,
        )
        provenance = replace(self.provenance, instrument=f"{symbol.upper()}USDT") if self.provenance.instrument == "dynamic-crypto-usdt" else self.provenance
        normalized = self.normalizer.normalize_series(raw, symbol=symbol, timeframe=timeframe, received_at=now, provenance=provenance, previous_hashes=previous)
        revisions: list[str] = []
        current = {candle.candle_id: candle.content_hash for candle in normalized}
        for candle in normalized:
            old_hash = previous.get(candle.candle_id)
            if old_hash is not None and old_hash != candle.content_hash:
                revisions.append(candle.candle_id)
                await self.repository.record_candle_revision(symbol=symbol, candle_id=candle.candle_id, previous_hash=old_hash, replacement_hash=candle.content_hash, occurred_at=now)
        self._observed_hashes[key] = current
        finalized = tuple(candle for candle in normalized if candle.is_final)
        return TimeframeSnapshot(symbol.upper(), timeframe, now, normalized, finalized[-1] if finalized else None, tuple(revisions))

    async def record_comparison(self, comparison: ShadowComparison) -> None:
        await self.repository.record_shadow_comparison(asdict(comparison))

    async def claim_closed_trigger(self, *, trigger: EvidenceContext, setup_id: str, trigger_type: str) -> tuple[bool, str]:
        if trigger.identity.source_timeframe != "5m":
            raise ValueError("trigger evidence must use 5m")
        if trigger.source_close_time is None:
            raise ValueError("trigger evidence requires a source close time")
        return await self.repository.claim_trigger(
            symbol=trigger.identity.symbol,
            candle_close_time=trigger.source_close_time,
            setup_id=setup_id,
            direction=trigger.direction,
            trigger_type=trigger_type,
            strategy_version=trigger.identity.strategy_version,
            occurred_at=trigger.evaluated_at,
        )

    def consolidate(self, *, symbol: str, created_at: datetime, macro_context: EvidenceContext, regime_4h: EvidenceContext, strategy_1h: EvidenceContext, setup_15m: EvidenceContext, trigger_5m: EvidenceContext, risk_inputs: RiskProposal) -> EvidenceBundle:
        if not self.configuration.enabled:
            raise RuntimeError("hierarchical shadow coordinator is disabled")
        return EvidenceBundle.create(
            symbol=symbol, created_at=created_at, macro_context=macro_context, regime_4h=regime_4h,
            strategy_1h=strategy_1h, setup_15m=setup_15m, trigger_5m=trigger_5m,
            risk_inputs=risk_inputs, strategy_version=self.configuration.strategy_version,
        )

    @property
    def execution_enabled(self) -> bool:
        return False
