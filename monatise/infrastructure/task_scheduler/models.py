from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from math import isfinite
from typing import Any, Awaitable, Callable


class JobState(StrEnum):
    REGISTERED = "registered"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"
    TIMED_OUT = "timed_out"


class ScheduleType(StrEnum):
    ONCE = "once"
    INTERVAL = "interval"


class MisfirePolicy(StrEnum):
    SKIP = "skip"
    RUN_ONCE = "run_once"


@dataclass(frozen=True)
class RetryPolicy:
    maximum_attempts: int = 3
    delay_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    maximum_delay_seconds: float = 60.0

    def validate(self) -> None:
        if self.maximum_attempts < 1:
            raise ValueError("maximum_attempts must be positive")
        if not isfinite(self.delay_seconds) or self.delay_seconds < 0:
            raise ValueError("delay_seconds cannot be negative")
        if not isfinite(self.backoff_multiplier) or self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be at least 1")
        if (
            not isfinite(self.maximum_delay_seconds)
            or self.maximum_delay_seconds < self.delay_seconds
        ):
            raise ValueError(
                "maximum_delay_seconds must be >= delay_seconds"
            )


JobCallable = Callable[[], Awaitable[Any]]


@dataclass(frozen=True)
class JobDefinition:
    job_id: str
    name: str
    task: JobCallable
    schedule_type: ScheduleType
    run_at: datetime | None = None
    interval: timedelta | None = None
    timeout_seconds: float | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    misfire_policy: MisfirePolicy = MisfirePolicy.SKIP
    enabled: bool = True
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.job_id.strip():
            raise ValueError("job_id is required")
        if not self.name.strip():
            raise ValueError("job name is required")
        if not callable(self.task):
            raise ValueError("task must be callable")
        self.retry_policy.validate()

        if self.schedule_type is ScheduleType.ONCE:
            if self.run_at is None:
                raise ValueError("run_at is required for one-time jobs")
        elif self.schedule_type is ScheduleType.INTERVAL:
            if (
                self.interval is None
                or not isfinite(self.interval.total_seconds())
                or self.interval.total_seconds() <= 0
            ):
                raise ValueError(
                    "positive interval is required for interval jobs"
                )

        if self.timeout_seconds is not None and (
            not isfinite(self.timeout_seconds) or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")


@dataclass(frozen=True)
class JobResult:
    job_id: str
    state: JobState
    started_at: datetime | None
    finished_at: datetime | None
    attempt: int
    output: Any = None
    error: str | None = None
    next_run_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def successful(self) -> bool:
        return self.state is JobState.SUCCEEDED
