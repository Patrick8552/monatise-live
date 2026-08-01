import asyncio
from datetime import datetime, timedelta, timezone

from monatise.infrastructure.task_scheduler import (
    JobDefinition,
    JobState,
    MisfirePolicy,
    RetryPolicy,
    ScheduleType,
    TaskScheduler,
)


def test_run_now_success() -> None:
    async def run() -> None:
        scheduler = TaskScheduler()

        async def task():
            return 42

        await scheduler.register(
            JobDefinition(
                job_id="one",
                name="One",
                task=task,
                schedule_type=ScheduleType.ONCE,
                run_at=datetime.now(timezone.utc),
            )
        )

        result = await scheduler.run_now("one")
        assert result.successful is True
        assert result.output == 42

    asyncio.run(run())


def test_retry_then_success() -> None:
    async def run() -> None:
        scheduler = TaskScheduler()
        attempts = 0

        async def flaky():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RuntimeError("temporary")
            return "ok"

        await scheduler.register(
            JobDefinition(
                job_id="retry",
                name="Retry",
                task=flaky,
                schedule_type=ScheduleType.ONCE,
                run_at=datetime.now(timezone.utc),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    delay_seconds=0,
                ),
            )
        )

        result = await scheduler.run_now("retry")
        assert result.state is JobState.SUCCEEDED
        assert result.attempt == 3

    asyncio.run(run())


def test_timeout() -> None:
    async def run() -> None:
        scheduler = TaskScheduler()

        async def slow():
            await asyncio.sleep(0.05)

        await scheduler.register(
            JobDefinition(
                job_id="timeout",
                name="Timeout",
                task=slow,
                schedule_type=ScheduleType.ONCE,
                run_at=datetime.now(timezone.utc),
                timeout_seconds=0.001,
                retry_policy=RetryPolicy(
                    maximum_attempts=1,
                    delay_seconds=0,
                ),
            )
        )

        result = await scheduler.run_now("timeout")
        assert result.state is JobState.TIMED_OUT

    asyncio.run(run())


def test_pause_and_resume() -> None:
    async def run() -> None:
        scheduler = TaskScheduler()

        async def task():
            return None

        await scheduler.register(
            JobDefinition(
                job_id="interval",
                name="Interval",
                task=task,
                schedule_type=ScheduleType.INTERVAL,
                interval=timedelta(seconds=1),
            )
        )

        await scheduler.pause("interval")
        assert await scheduler.state_of("interval") is JobState.PAUSED

        await scheduler.resume("interval")
        assert await scheduler.state_of("interval") is JobState.SCHEDULED

    asyncio.run(run())


def test_cancel_running_job() -> None:
    async def run() -> None:
        scheduler = TaskScheduler()

        async def long_running():
            await asyncio.sleep(10)

        await scheduler.register(
            JobDefinition(
                job_id="cancel",
                name="Cancel",
                task=long_running,
                schedule_type=ScheduleType.ONCE,
                run_at=datetime.now(timezone.utc),
            )
        )

        runner = asyncio.create_task(scheduler.run_now("cancel"))
        await asyncio.sleep(0)
        await scheduler.cancel("cancel")
        await asyncio.gather(runner, return_exceptions=True)

        assert await scheduler.state_of("cancel") is JobState.CANCELLED
        history = await scheduler.history("cancel")
        assert history[-1].state is JobState.CANCELLED

    asyncio.run(run())


def test_same_job_cannot_run_concurrently() -> None:
    async def run() -> None:
        scheduler = TaskScheduler()
        release = asyncio.Event()

        async def blocked():
            await release.wait()

        await scheduler.register(
            JobDefinition(
                job_id="single",
                name="Single",
                task=blocked,
                schedule_type=ScheduleType.ONCE,
                run_at=datetime.now(timezone.utc),
            )
        )
        first = asyncio.create_task(scheduler.run_now("single"))
        await asyncio.sleep(0)
        try:
            await scheduler.run_now("single")
        except ValueError as exc:
            assert "already running" in str(exc)
        else:
            raise AssertionError("expected duplicate-run failure")
        release.set()
        await first

    asyncio.run(run())


def test_manual_interval_run_remains_scheduled() -> None:
    async def run() -> None:
        scheduler = TaskScheduler()

        async def task():
            return "ok"

        await scheduler.register(
            JobDefinition(
                job_id="interval-manual",
                name="Interval manual",
                task=task,
                schedule_type=ScheduleType.INTERVAL,
                interval=timedelta(seconds=10),
            )
        )
        result = await scheduler.run_now("interval-manual")
        assert result.state is JobState.SUCCEEDED
        assert await scheduler.state_of("interval-manual") is JobState.SCHEDULED

    asyncio.run(run())


def test_background_loop_runs_one_time_job() -> None:
    async def run() -> None:
        scheduler = TaskScheduler(poll_interval_seconds=0.001)
        completed = asyncio.Event()

        async def task():
            completed.set()

        await scheduler.register(
            JobDefinition(
                job_id="background",
                name="Background",
                task=task,
                schedule_type=ScheduleType.ONCE,
                run_at=datetime.now(timezone.utc),
            )
        )
        await scheduler.start()
        await asyncio.wait_for(completed.wait(), timeout=0.1)
        await scheduler.stop()

        assert await scheduler.state_of("background") is JobState.SUCCEEDED

    asyncio.run(run())


def test_global_concurrency_limit_is_enforced() -> None:
    async def run() -> None:
        scheduler = TaskScheduler(maximum_concurrency=1)
        active = 0
        peak = 0

        async def task():
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0)
            active -= 1

        for job_id in ("first", "second"):
            await scheduler.register(
                JobDefinition(
                    job_id=job_id,
                    name=job_id,
                    task=task,
                    schedule_type=ScheduleType.ONCE,
                    run_at=datetime.now(timezone.utc),
                )
            )

        await asyncio.gather(
            scheduler.run_now("first"),
            scheduler.run_now("second"),
        )
        assert peak == 1

    asyncio.run(run())


def test_queued_job_can_be_cancelled_with_history() -> None:
    async def run() -> None:
        scheduler = TaskScheduler(maximum_concurrency=1)
        release = asyncio.Event()

        async def blocked():
            await release.wait()

        for job_id in ("active", "queued"):
            await scheduler.register(JobDefinition(
                job_id=job_id,
                name=job_id,
                task=blocked,
                schedule_type=ScheduleType.ONCE,
                run_at=datetime.now(timezone.utc),
            ))

        active = asyncio.create_task(scheduler.run_now("active"))
        await asyncio.sleep(0)
        queued = asyncio.create_task(scheduler.run_now("queued"))
        await asyncio.sleep(0)
        await scheduler.cancel("queued")
        await asyncio.gather(queued, return_exceptions=True)
        release.set()
        await active

        history = await scheduler.history("queued")
        assert history[-1].state is JobState.CANCELLED
        assert history[-1].attempt == 0

    asyncio.run(run())


def test_queued_job_cannot_be_paused_and_then_execute() -> None:
    async def run() -> None:
        scheduler = TaskScheduler(maximum_concurrency=1)
        release = asyncio.Event()

        async def blocked():
            await release.wait()

        for job_id in ("active-pause", "queued-pause"):
            await scheduler.register(JobDefinition(
                job_id=job_id,
                name=job_id,
                task=blocked,
                schedule_type=ScheduleType.ONCE,
                run_at=datetime.now(timezone.utc),
            ))
        active = asyncio.create_task(scheduler.run_now("active-pause"))
        await asyncio.sleep(0)
        queued = asyncio.create_task(scheduler.run_now("queued-pause"))
        await asyncio.sleep(0)
        try:
            await scheduler.pause("queued-pause")
        except ValueError as exc:
            assert "while running" in str(exc)
        else:
            raise AssertionError("expected queued-job pause rejection")
        await scheduler.cancel("queued-pause")
        await asyncio.gather(queued, return_exceptions=True)
        release.set()
        await active

    asyncio.run(run())


def test_misfire_skip_and_run_once_policies() -> None:
    async def run() -> None:
        calls: list[str] = []
        scheduler = TaskScheduler(
            poll_interval_seconds=0.001,
            misfire_grace_seconds=0,
        )

        async def skipped():
            calls.append("skipped")

        async def caught_up():
            calls.append("caught-up")

        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        await scheduler.register(JobDefinition(
            job_id="skip",
            name="Skip",
            task=skipped,
            schedule_type=ScheduleType.ONCE,
            run_at=past,
            misfire_policy=MisfirePolicy.SKIP,
        ))
        await scheduler.register(JobDefinition(
            job_id="catch-up",
            name="Catch up",
            task=caught_up,
            schedule_type=ScheduleType.ONCE,
            run_at=past,
            misfire_policy=MisfirePolicy.RUN_ONCE,
        ))
        await scheduler.start()
        await asyncio.sleep(0.01)
        await scheduler.stop()

        assert calls == ["caught-up"]
        skipped_history = await scheduler.history("skip")
        assert skipped_history[-1].metadata["misfire"] is True

    asyncio.run(run())


def test_history_retention_is_bounded_per_job() -> None:
    async def run() -> None:
        scheduler = TaskScheduler(maximum_history_per_job=2)

        async def task():
            return "ok"

        await scheduler.register(JobDefinition(
            job_id="bounded",
            name="Bounded",
            task=task,
            schedule_type=ScheduleType.ONCE,
            run_at=datetime.now(timezone.utc),
        ))
        for _ in range(3):
            await scheduler.run_now("bounded")

        assert len(await scheduler.history("bounded")) == 2

    asyncio.run(run())


def test_scheduler_has_no_execution_capability() -> None:
    scheduler = TaskScheduler()

    assert scheduler.execution_enabled is False
    assert not hasattr(scheduler, "place_order")
    assert not hasattr(scheduler, "submit_trade")
