"""Bounded, fail-closed scanner pipeline for the canonical FTMO universe."""

from __future__ import annotations

import asyncio
import inspect
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable, Mapping

from monatise.application.ftmo_registry import FTMOAssetClass, FTMOInstrument, FTMOInstrumentRegistry
from monatise.application.market_session import classify_market_session


ObservationProvider = Callable[[FTMOInstrument], Mapping[str, Any] | None | Awaitable[Mapping[str, Any] | None]]
AnalysisProvider = Callable[["FTMOScannerCandidate"], Mapping[str, Any] | Awaitable[Mapping[str, Any]]]
Publisher = Callable[[FTMOInstrument, Mapping[str, Any]], Any | Awaitable[Any]]


@dataclass(frozen=True)
class FTMOScannerConfiguration:
    candidate_limit: int = 20
    deep_analysis_limit: int = 10
    maximum_concurrency: int = 4
    minimum_score: float = 0.5

    def __post_init__(self) -> None:
        if self.candidate_limit < 1 or self.deep_analysis_limit < 1:
            raise ValueError("FTMO scanner candidate limits must be positive")
        if not 1 <= self.maximum_concurrency <= 16:
            raise ValueError("FTMO scanner concurrency must be between 1 and 16")


@dataclass(frozen=True)
class FTMOScannerCandidate:
    instrument: FTMOInstrument
    score: float
    direction: str
    observation: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ftmo_symbol": self.instrument.ftmo_symbol,
            "underlying_symbol": self.instrument.underlying_symbol,
            "asset_class": self.instrument.asset_class.value,
            "score": self.score,
            "direction": self.direction,
            "observation": dict(self.observation),
        }


@dataclass(frozen=True)
class FTMOScannerResult:
    asset_class: FTMOAssetClass
    universe_size: int
    qualified: int
    shortlisted: int
    analyzed: int
    published: int
    suppressed: int
    provider_failures: int
    execution_enabled: bool = False


def rank_ftmo_observations(
    registry: FTMOInstrumentRegistry,
    asset_class: FTMOAssetClass,
    observations: Iterable[Mapping[str, Any]],
    *,
    limit: int = 20,
    minimum_score: float = 0.5,
) -> tuple[FTMOScannerCandidate, ...]:
    """Rank observations only when they resolve to an enabled FTMO instrument."""
    instruments = registry.for_asset_class(asset_class)
    aliases: dict[str, FTMOInstrument] = {}
    for instrument in instruments:
        for value in (instrument.ftmo_symbol, instrument.underlying_symbol, instrument.provider_symbol):
            if value:
                aliases[str(value).strip().casefold()] = instrument
    ranked: dict[str, FTMOScannerCandidate] = {}
    for observation in observations:
        raw_symbol = observation.get("ftmo_symbol") or observation.get("symbol") or observation.get("provider_symbol")
        instrument = aliases.get(str(raw_symbol or "").strip().casefold())
        if instrument is None:
            continue
        score = _finite_number(observation.get("score"))
        if score is None:
            score = _derived_score(observation)
        if score < minimum_score:
            continue
        direction = str(observation.get("direction") or "none").strip().casefold()
        if direction not in {"long", "short"}:
            continue
        candidate = FTMOScannerCandidate(instrument, round(score, 4), direction, observation)
        previous = ranked.get(instrument.ftmo_symbol.casefold())
        if previous is None or candidate.score > previous.score:
            ranked[instrument.ftmo_symbol.casefold()] = candidate
    return tuple(sorted(ranked.values(), key=lambda item: (-item.score, item.instrument.ftmo_symbol))[:limit])


class FTMOScannerPipeline:
    """Staged scanner that never lets a ranking score become a publication."""

    def __init__(self, registry: FTMOInstrumentRegistry, configuration: FTMOScannerConfiguration | None = None) -> None:
        self.registry = registry
        self.configuration = configuration or FTMOScannerConfiguration()

    async def run(
        self,
        asset_class: FTMOAssetClass,
        *,
        observe: ObservationProvider,
        analyze: AnalysisProvider,
        publish: Publisher,
    ) -> FTMOScannerResult:
        universe = self.registry.for_asset_class(asset_class)
        observations, provider_failures = await _bounded_collect(
            universe,
            observe,
            maximum_concurrency=self.configuration.maximum_concurrency,
        )
        ranked = rank_ftmo_observations(
            self.registry,
            asset_class,
            observations,
            limit=self.configuration.candidate_limit,
            minimum_score=self.configuration.minimum_score,
        )
        shortlist = ranked[: self.configuration.deep_analysis_limit]
        async def analyze_candidate(candidate: FTMOScannerCandidate) -> Mapping[str, Any]:
            result = analyze(candidate)
            if inspect.isawaitable(result):
                result = await result
            value = dict(result)
            value.setdefault("ftmo_symbol", candidate.instrument.ftmo_symbol)
            value.setdefault("asset_class", candidate.instrument.asset_class.value)
            # Every analysis gets a new clock-derived session snapshot. Never
            # inherit session state from an observation or prior scanner run.
            session = classify_market_session(datetime.now(timezone.utc), instrument=candidate.instrument)
            value.update(session.to_dict())
            value["session_context"] = session.to_dict()
            return value

        analyses, analysis_failures = await _bounded_collect(
            shortlist,
            analyze_candidate,
            maximum_concurrency=self.configuration.maximum_concurrency,
        )
        by_symbol = {candidate.instrument.ftmo_symbol: candidate for candidate in shortlist}
        published = suppressed = 0
        for analysis in analyses:
            ftmo_symbol = str(analysis.get("ftmo_symbol") or "")
            candidate = by_symbol.get(ftmo_symbol)
            if candidate is None:
                suppressed += 1
                continue
            if not publication_allowed(analysis):
                suppressed += 1
                continue
            result = publish(candidate.instrument, analysis)
            if inspect.isawaitable(result):
                await result
            published += 1
        suppressed += analysis_failures
        return FTMOScannerResult(
            asset_class,
            len(universe),
            len(observations),
            len(shortlist),
            len(analyses),
            published,
            suppressed,
            provider_failures + analysis_failures,
        )


def publication_allowed(analysis: Mapping[str, Any]) -> bool:
    """Final publication gate shared by all FTMO scanner domains."""
    decision = str(analysis.get("decision") or "NO_TRADE").upper()
    status = str(analysis.get("setup_status") or "").casefold()
    freshness = str(analysis.get("freshness") or analysis.get("data_status") or "fresh").casefold()
    execution = analysis.get("execution") or {}
    return (
        decision in {"BUY_WATCH", "SELL_WATCH"}
        and status == "confirmed"
        and freshness not in {"stale", "expired", "invalid"}
        and analysis.get("publication_valid", True) is True
        and not bool(execution.get("enabled", False))
        and int(execution.get("orders_placed", 0) or 0) == 0
    )


async def _bounded_collect(items: Iterable[Any], callback: Callable[[Any], Any], *, maximum_concurrency: int) -> tuple[list[Any], int]:
    queue: asyncio.Queue[Any] = asyncio.Queue()
    for item in items:
        queue.put_nowait(item)
    results: list[Any] = []
    failures = 0

    async def worker() -> None:
        nonlocal failures
        while True:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                result = callback(item)
                if inspect.isawaitable(result):
                    result = await result
                if result is not None:
                    results.append(result)
            except Exception:
                failures += 1
            finally:
                queue.task_done()

    workers = tuple(asyncio.create_task(worker()) for _ in range(min(maximum_concurrency, queue.qsize())))
    if workers:
        await asyncio.gather(*workers)
    return results, failures


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _derived_score(observation: Mapping[str, Any]) -> float:
    changes = [
        abs(_finite_number(observation.get(key)) or 0.0)
        for key in ("change_5m", "change_15m", "change_1h", "relative_volume", "volatility")
    ]
    return sum(changes)
