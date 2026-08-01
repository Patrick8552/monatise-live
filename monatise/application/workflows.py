"""OpenClaw scheduling and Telegram delivery workflows (analysis-only)."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import datetime, timezone
from datetime import timedelta
from typing import Any, Awaitable, Callable, Protocol

from monatise.application.models import AnalysisRun, PipelineResult
from monatise.application.orchestrator import PipelineOrchestrator
from monatise.infrastructure.state_manager import StateKey
from monatise.infrastructure.task_scheduler import JobDefinition, RetryPolicy, ScheduleType


class TelegramTransport(Protocol):
    async def send_message(self, chat_id: str, text: str) -> Any: ...


class TelegramNotifier:
    def __init__(self, transport: TelegramTransport, chat_id: str) -> None:
        if not isinstance(chat_id, str) or not chat_id.strip():
            raise ValueError("Telegram chat_id is required")
        self._transport, self._chat_id = transport, chat_id

    async def deliver(self, result: PipelineResult) -> Any:
        text = self.format(result)
        return await self._transport.send_message(self._chat_id, text)

    async def deliver_safely(self, result: PipelineResult) -> bool:
        try:
            await self.deliver(result)
            return True
        except Exception:
            return False

    async def governance_alert(self, message: str) -> Any:
        return await self._alert("GOVERNANCE", message)

    async def health_alert(self, message: str) -> Any:
        return await self._alert("HEALTH", message)

    async def audit_notification(self, message: str) -> Any:
        return await self._alert("AUDIT", message)

    async def _alert(self, category: str, message: str) -> Any:
        if not message.strip():
            raise ValueError("notification message is required")
        return await self._transport.send_message(self._chat_id, f"Monatise {category}: {message}")

    @staticmethod
    def format(result: PipelineResult) -> str:
        suffix = f" | blocked by {result.blocked_by}" if result.blocked_by else ""
        return f"Monatise crypto analysis: {result.symbol} | {result.status.value} | stages {result.statistics.completed_stages}/20{suffix} | run {result.run_id}"

    @property
    def execution_enabled(self) -> bool:
        return False


@dataclass(frozen=True)
class OpenClawWorkflow:
    orchestrator: PipelineOrchestrator
    run_factory: Callable[[], AnalysisRun | Awaitable[AnalysisRun]]
    notifier: TelegramNotifier | None = None
    maximum_request_age_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.maximum_request_age_seconds <= 0:
            raise ValueError("maximum_request_age_seconds must be positive")
        if not callable(self.run_factory):
            raise ValueError("run_factory must be callable")

    async def schedule(self, scheduler: Any, *, job_id: str, interval_seconds: float, state: Any | None = None) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")

        async def task() -> PipelineResult:
            if state is not None:
                await state.set(StateKey("openclaw_workflows", job_id), {"status": "running", "updated_at": datetime.now(timezone.utc).isoformat()})
            try:
                result = await self.execute()
            except Exception:
                if state is not None:
                    await state.set(StateKey("openclaw_workflows", job_id), {"status": "failed", "updated_at": datetime.now(timezone.utc).isoformat()})
                raise
            if state is not None:
                await state.set(StateKey("openclaw_workflows", job_id), {"status": result.status.value, "run_id": result.run_id, "updated_at": datetime.now(timezone.utc).isoformat()})
            return result

        await scheduler.register(JobDefinition(job_id, f"OpenClaw crypto analysis {job_id}", task, ScheduleType.INTERVAL, interval=timedelta(seconds=interval_seconds), retry_policy=RetryPolicy(maximum_attempts=3), tags=("openclaw", "crypto", "analysis"), metadata={"execution_enabled": False}))

    async def execute(self) -> PipelineResult:
        candidate = self.run_factory()
        run = await candidate if inspect.isawaitable(candidate) else candidate
        if not isinstance(run, AnalysisRun):
            raise TypeError("run_factory must return AnalysisRun")
        age = (datetime.now(timezone.utc) - run.requested_at).total_seconds()
        if age < -60:
            raise ValueError("scheduled analysis request is in the future")
        if age > self.maximum_request_age_seconds:
            raise ValueError("scheduled analysis request is stale")
        result = await self.orchestrator.run(run)
        if self.notifier is not None:
            await self.notifier.deliver_safely(result)
        return result

    @property
    def execution_enabled(self) -> bool:
        return False
