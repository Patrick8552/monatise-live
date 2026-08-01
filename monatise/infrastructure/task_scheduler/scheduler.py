from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any

from monatise.infrastructure.task_scheduler.models import (
    JobDefinition,
    JobResult,
    JobState,
    MisfirePolicy,
    ScheduleType,
)


class TaskScheduler:
    """Async scheduler for infrastructure and analysis jobs.

    The scheduler coordinates tasks only. It contains no trading logic and
    cannot submit orders or bypass governance.
    """

    def __init__(
        self,
        *,
        maximum_concurrency: int = 4,
        poll_interval_seconds: float = 0.25,
        misfire_grace_seconds: float = 1.0,
        maximum_history_per_job: int = 1_000,
    ) -> None:
        if maximum_concurrency < 1:
            raise ValueError("maximum_concurrency must be positive")
        if not isfinite(poll_interval_seconds) or poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if not isfinite(misfire_grace_seconds) or misfire_grace_seconds < 0:
            raise ValueError("misfire_grace_seconds cannot be negative")
        if maximum_history_per_job < 1:
            raise ValueError("maximum_history_per_job must be positive")

        self._jobs: dict[str, JobDefinition] = {}
        self._states: dict[str, JobState] = {}
        self._next_run: dict[str, datetime | None] = {}
        self._history: list[JobResult] = []
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._semaphore = asyncio.Semaphore(maximum_concurrency)
        self._poll_interval_seconds = poll_interval_seconds
        self._misfire_grace_seconds = misfire_grace_seconds
        self._maximum_history_per_job = maximum_history_per_job
        self._loop_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._lock = asyncio.Lock()

    async def register(self, definition: JobDefinition) -> None:
        definition.validate()
        definition = replace(
            definition,
            metadata=deepcopy(definition.metadata),
            tags=tuple(definition.tags),
        )

        async with self._lock:
            if definition.job_id in self._jobs:
                raise ValueError(
                    f"job already registered: {definition.job_id}"
                )
            self._jobs[definition.job_id] = definition
            self._states[definition.job_id] = (
                JobState.SCHEDULED
                if definition.enabled
                else JobState.PAUSED
            )
            self._next_run[definition.job_id] = self._initial_next_run(
                definition
            )

    async def unregister(self, job_id: str) -> None:
        await self.cancel(job_id)
        async with self._lock:
            self._jobs.pop(job_id, None)
            self._states.pop(job_id, None)
            self._next_run.pop(job_id, None)

    async def pause(self, job_id: str) -> None:
        async with self._lock:
            self._require(job_id)
            if job_id in self._running_tasks:
                raise ValueError(f"job cannot pause while running: {job_id}")
            if self._states[job_id] is not JobState.SCHEDULED:
                raise ValueError(
                    f"job cannot pause from state {self._states[job_id].value}"
                )
            self._states[job_id] = JobState.PAUSED

    async def resume(self, job_id: str) -> None:
        async with self._lock:
            definition = self._require(job_id)
            if self._states[job_id] is not JobState.PAUSED:
                raise ValueError(
                    f"job cannot resume from state {self._states[job_id].value}"
                )
            self._states[job_id] = JobState.SCHEDULED
            self._next_run[job_id] = self._initial_next_run(definition)

    async def run_now(self, job_id: str) -> JobResult:
        async with self._lock:
            definition = self._require(job_id)
            if job_id in self._running_tasks:
                raise ValueError(f"job is already running: {job_id}")
            if self._states[job_id] is JobState.CANCELLED:
                raise ValueError(f"job is cancelled: {job_id}")
            runner = asyncio.current_task()
            if runner is None:
                raise RuntimeError("run_now requires an asyncio task")
            self._running_tasks[job_id] = runner

        try:
            result = await self._execute(definition)
            async with self._lock:
                if (
                    definition.schedule_type is ScheduleType.INTERVAL
                    and self._states[job_id] is result.state
                ):
                    self._states[job_id] = JobState.SCHEDULED
            return result
        finally:
            async with self._lock:
                if self._running_tasks.get(job_id) is runner:
                    self._running_tasks.pop(job_id, None)

    async def cancel(self, job_id: str) -> None:
        async with self._lock:
            self._require(job_id)
            task = self._running_tasks.get(job_id)
        if task is not None and not task.done():
            task.cancel()
            if task is not asyncio.current_task():
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        async with self._lock:
            if job_id in self._states:
                self._states[job_id] = JobState.CANCELLED
            if self._running_tasks.get(job_id) is task:
                self._running_tasks.pop(job_id, None)

    async def start(self) -> None:
        if self._loop_task is not None and not self._loop_task.done():
            return
        self._stop_event.clear()
        self._loop_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._loop_task is not None:
            await self._loop_task
        self._loop_task = None
        running = tuple(
            (job_id, task)
            for job_id, task in self._running_tasks.items()
            if not task.done()
        )
        for _, task in running:
            if not task.done():
                task.cancel()
        if running:
            await asyncio.gather(
                *(task for _, task in running),
                return_exceptions=True,
            )
        async with self._lock:
            for job_id, _ in running:
                definition = self._jobs.get(job_id)
                if definition is None or not definition.enabled:
                    continue
                self._states[job_id] = JobState.SCHEDULED
                if definition.schedule_type is ScheduleType.INTERVAL:
                    self._next_run[job_id] = (
                        datetime.now(timezone.utc) + definition.interval
                    )
        self._running_tasks.clear()

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            now = datetime.now(timezone.utc)
            due: list[JobDefinition] = []

            async with self._lock:
                for job_id, definition in self._jobs.items():
                    if self._states[job_id] is not JobState.SCHEDULED:
                        continue
                    next_run = self._next_run[job_id]
                    if next_run is not None and next_run <= now:
                        lateness = (now - next_run).total_seconds()
                        if (
                            lateness > self._misfire_grace_seconds
                            and definition.misfire_policy is MisfirePolicy.SKIP
                        ):
                            if definition.schedule_type is ScheduleType.ONCE:
                                self._states[job_id] = JobState.CANCELLED
                                self._next_run[job_id] = None
                                self._append_history_unlocked(JobResult(
                                    job_id=job_id,
                                    state=JobState.CANCELLED,
                                    started_at=None,
                                    finished_at=now,
                                    attempt=0,
                                    error="scheduled run skipped after misfire",
                                    metadata={"misfire": True},
                                ))
                            else:
                                self._next_run[job_id] = now + definition.interval
                            continue
                        due.append(definition)
                for definition in due:
                    if definition.job_id in self._running_tasks:
                        continue
                    task = asyncio.create_task(
                        self._execute_and_reschedule(definition)
                    )
                    self._running_tasks[definition.job_id] = task
                    task.add_done_callback(
                        lambda completed, job_id=definition.job_id:
                        self._discard_running(job_id, completed)
                    )

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._poll_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass

    async def _execute_and_reschedule(
        self,
        definition: JobDefinition,
    ) -> JobResult:
        result = await self._execute(definition)

        async with self._lock:
            if definition.schedule_type is ScheduleType.ONCE:
                self._states[definition.job_id] = result.state
                self._next_run[definition.job_id] = None
            else:
                self._states[definition.job_id] = JobState.SCHEDULED
                self._next_run[definition.job_id] = (
                    datetime.now(timezone.utc) + definition.interval
                )

        return result

    async def _execute(
        self,
        definition: JobDefinition,
    ) -> JobResult:
        requested_at = datetime.now(timezone.utc)
        try:
            return await self._execute_attempts(definition)
        except asyncio.CancelledError:
            result = JobResult(
                job_id=definition.job_id,
                state=JobState.CANCELLED,
                started_at=requested_at,
                finished_at=datetime.now(timezone.utc),
                attempt=0,
                error="job cancelled",
            )
            async with self._lock:
                self._append_history_unlocked(result)
                self._states[definition.job_id] = result.state
            raise

    async def _execute_attempts(
        self,
        definition: JobDefinition,
    ) -> JobResult:
        async with self._semaphore:
            started_at = datetime.now(timezone.utc)
            state = JobState.RUNNING

            async with self._lock:
                self._states[definition.job_id] = state

            last_error: Exception | None = None
            output: Any = None

            for attempt in range(
                1,
                definition.retry_policy.maximum_attempts + 1,
            ):
                try:
                    coroutine = definition.task()
                    if definition.timeout_seconds is None:
                        output = await coroutine
                    else:
                        output = await asyncio.wait_for(
                            coroutine,
                            timeout=definition.timeout_seconds,
                        )

                    result = JobResult(
                        job_id=definition.job_id,
                        state=JobState.SUCCEEDED,
                        started_at=started_at,
                        finished_at=datetime.now(timezone.utc),
                        attempt=attempt,
                        output=output,
                        next_run_at=self._preview_next_run(definition),
                    )
                    async with self._lock:
                        self._append_history_unlocked(result)
                        self._states[definition.job_id] = result.state
                    return result

                except asyncio.TimeoutError as exc:
                    last_error = exc
                    if attempt >= definition.retry_policy.maximum_attempts:
                        final_state = JobState.TIMED_OUT
                        break
                except Exception as exc:
                    last_error = exc
                    if attempt >= definition.retry_policy.maximum_attempts:
                        final_state = JobState.FAILED
                        break

                delay = min(
                    definition.retry_policy.maximum_delay_seconds,
                    definition.retry_policy.delay_seconds
                    * (
                        definition.retry_policy.backoff_multiplier
                        ** (attempt - 1)
                    ),
                )
                if delay:
                    await asyncio.sleep(delay)

            result = JobResult(
                job_id=definition.job_id,
                state=final_state,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                attempt=definition.retry_policy.maximum_attempts,
                error=(
                    f"{type(last_error).__name__}: {last_error}"
                    if last_error is not None
                    else "unknown job failure"
                ),
                next_run_at=self._preview_next_run(definition),
            )
            async with self._lock:
                self._append_history_unlocked(result)
                self._states[definition.job_id] = result.state
            return result

    def _append_history_unlocked(self, result: JobResult) -> None:
        self._history.append(result)
        matching = [
            index
            for index, item in enumerate(self._history)
            if item.job_id == result.job_id
        ]
        excess = len(matching) - self._maximum_history_per_job
        for index in reversed(matching[:max(0, excess)]):
            self._history.pop(index)

    @staticmethod
    def _initial_next_run(
        definition: JobDefinition,
    ) -> datetime | None:
        if not definition.enabled:
            return None
        if definition.schedule_type is ScheduleType.ONCE:
            return TaskScheduler._as_utc(definition.run_at)
        return datetime.now(timezone.utc) + definition.interval

    @staticmethod
    def _preview_next_run(
        definition: JobDefinition,
    ) -> datetime | None:
        if definition.schedule_type is ScheduleType.ONCE:
            return None
        return datetime.now(timezone.utc) + definition.interval

    @staticmethod
    def _as_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _require(self, job_id: str) -> JobDefinition:
        definition = self._jobs.get(job_id)
        if definition is None:
            raise KeyError(f"job is not registered: {job_id}")
        return definition

    def _discard_running(
        self,
        job_id: str,
        completed: asyncio.Task,
    ) -> None:
        if self._running_tasks.get(job_id) is completed:
            self._running_tasks.pop(job_id, None)

    async def state_of(self, job_id: str) -> JobState:
        async with self._lock:
            self._require(job_id)
            return self._states[job_id]

    async def history(
        self,
        job_id: str | None = None,
    ) -> tuple[JobResult, ...]:
        async with self._lock:
            if job_id is None:
                return tuple(self._history)
            return tuple(
                item for item in self._history
                if item.job_id == job_id
            )

    async def next_run_at(self, job_id: str) -> datetime | None:
        async with self._lock:
            self._require(job_id)
            return self._next_run[job_id]

    async def definitions(self) -> tuple[JobDefinition, ...]:
        async with self._lock:
            return tuple(
                replace(
                    definition,
                    metadata=deepcopy(definition.metadata),
                )
                for definition in self._jobs.values()
            )

    @property
    def execution_enabled(self) -> bool:
        return False
