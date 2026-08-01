"""Immutable contracts for a complete Monatise analysis run."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4


def _frozen_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(deepcopy(dict(value or {})))


class PipelineStage(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class PipelineExecutionMetadata:
    actor_id: str = "monatise-application"
    source: str = "monatise.application"
    maximum_attempts: int = 2
    retry_delay_seconds: float = 0.1
    tags: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.actor_id.strip() or not self.source.strip():
            raise ValueError("actor_id and source are required")
        if self.maximum_attempts < 1 or self.retry_delay_seconds < 0:
            raise ValueError("invalid retry policy")
        object.__setattr__(self, "tags", _frozen_mapping(self.tags))


@dataclass(frozen=True)
class AnalysisRun:
    symbol: str
    stage_inputs: Mapping[str, Any]
    run_id: str = field(default_factory=lambda: str(uuid4()))
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: PipelineExecutionMetadata = field(default_factory=PipelineExecutionMetadata)

    def __post_init__(self) -> None:
        normalized = self.symbol.strip().upper()
        if not normalized or "/" in normalized or normalized.isdigit():
            raise ValueError("a crypto asset symbol is required")
        if len(normalized) == 6 and normalized[:3] in {"USD", "EUR", "GBP", "JPY", "CHF"}:
            raise ValueError("forex markets are not supported")
        if self.requested_at.tzinfo is None:
            raise ValueError("requested_at must be timezone-aware")
        object.__setattr__(self, "symbol", normalized)
        object.__setattr__(self, "stage_inputs", _frozen_mapping(self.stage_inputs))


@dataclass(frozen=True)
class PipelineContext:
    run: AnalysisRun
    outputs: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "outputs", _frozen_mapping(self.outputs))

    def with_output(self, name: str, output: Any) -> "PipelineContext":
        values = dict(self.outputs)
        values[name] = output
        return PipelineContext(run=self.run, outputs=values)


@dataclass(frozen=True)
class PipelineFailure:
    engine: str
    code: str
    message: str
    retryable: bool
    attempt: int


@dataclass(frozen=True)
class PipelineStatistics:
    total_duration_ms: float
    stage_durations_ms: Mapping[str, float]
    attempts: Mapping[str, int]
    completed_stages: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage_durations_ms", _frozen_mapping(self.stage_durations_ms))
        object.__setattr__(self, "attempts", _frozen_mapping(self.attempts))


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    correlation_id: str
    symbol: str
    status: PipelineStage
    context: PipelineContext
    statistics: PipelineStatistics
    failure: PipelineFailure | None
    blocked_by: str | None
    started_at: datetime
    finished_at: datetime

    @property
    def successful(self) -> bool:
        return self.status is PipelineStage.COMPLETED

    @property
    def execution_enabled(self) -> bool:
        return False
