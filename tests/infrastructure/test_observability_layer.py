import asyncio
from math import nan

from monatise.infrastructure.observability import (
    HealthStatus,
    LogLevel,
    MetricType,
    ObservabilityManager,
)


def test_structured_logging() -> None:
    async def run() -> None:
        manager = ObservabilityManager()

        await manager.log(
            LogLevel.INFO,
            "analysis completed",
            source="decision_engine",
            correlation_id="corr-1",
            symbol="BTCUSDT",
            fields={"classification": "trend"},
        )

        logs = await manager.logs(correlation_id="corr-1")
        assert len(logs) == 1
        assert logs[0].fields["classification"] == "trend"

    asyncio.run(run())


def test_metric_recording() -> None:
    async def run() -> None:
        manager = ObservabilityManager()

        await manager.counter(
            "engine.runs_total",
            labels={"engine": "regime"},
        )
        await manager.gauge(
            "scheduler.queue_depth",
            3,
        )
        await manager.histogram(
            "engine.latency_ms",
            12.5,
        )

        metrics = await manager.metrics()
        assert len(metrics) == 3
        assert metrics[0].metric_type is MetricType.COUNTER

    asyncio.run(run())


def test_trace_success_records_latency() -> None:
    async def run() -> None:
        manager = ObservabilityManager()

        async with manager.trace(
            "decision.assess",
            source="decision_engine",
            correlation_id="corr-1",
        ) as context:
            assert context["trace_id"]
            assert context["span_id"]

        spans = await manager.spans()
        assert len(spans) == 1
        assert spans[0].success is True
        assert spans[0].duration_ms >= 0

        latency = await manager.metrics(
            name="operation.duration_ms",
        )
        assert len(latency) == 1

    asyncio.run(run())


def test_trace_failure_records_error_counter() -> None:
    async def run() -> None:
        manager = ObservabilityManager()

        try:
            async with manager.trace(
                "engine.failure",
                source="test_engine",
            ):
                raise RuntimeError("boom")
        except RuntimeError:
            pass

        spans = await manager.spans()
        assert spans[0].success is False
        assert "RuntimeError" in spans[0].error

        errors = await manager.metrics(
            name="operation.errors_total",
        )
        assert len(errors) == 1

    asyncio.run(run())


def test_health_checks() -> None:
    async def run() -> None:
        manager = ObservabilityManager()

        async def healthy():
            return HealthStatus.HEALTHY, "ok"

        async def broken():
            raise RuntimeError("unavailable")

        manager.register_health_check("database", healthy)
        manager.register_health_check("coinglass", broken)

        results = await manager.run_health_checks()
        by_name = {item.name: item for item in results}

        assert by_name["database"].status is HealthStatus.HEALTHY
        assert by_name["coinglass"].status is HealthStatus.UNHEALTHY

    asyncio.run(run())


def test_snapshot_is_read_only_metadata() -> None:
    async def run() -> None:
        manager = ObservabilityManager()
        snapshot = await manager.snapshot()

        assert snapshot["metadata"]["read_only_snapshot"] is True
        assert snapshot["metadata"]["execution_enabled"] is False

    asyncio.run(run())


def test_manager_is_non_executable() -> None:
    manager = ObservabilityManager()

    assert manager.execution_enabled is False
    assert not hasattr(manager, "place_order")
    assert not hasattr(manager, "submit_trade")


def test_cancelled_trace_is_recorded_as_failure() -> None:
    async def run() -> None:
        manager = ObservabilityManager()

        async def worker():
            async with manager.trace("cancelled", source="scheduler"):
                await asyncio.sleep(10)

        task = asyncio.create_task(worker())
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        spans = await manager.spans()
        assert spans[0].success is False
        assert "CancelledError" in spans[0].error
        assert len(await manager.metrics(name="operation.errors_total")) == 1

    asyncio.run(run())


def test_health_checks_run_concurrently_and_time_out() -> None:
    async def run() -> None:
        manager = ObservabilityManager(health_check_timeout_seconds=0.001)

        async def hanging():
            await asyncio.sleep(10)
            return HealthStatus.HEALTHY, "late"

        async def healthy():
            return HealthStatus.HEALTHY, "ok"

        manager.register_health_check("hanging", hanging)
        manager.register_health_check("healthy", healthy)
        results = await manager.run_health_checks()
        by_name = {item.name: item for item in results}
        assert by_name["hanging"].status is HealthStatus.UNHEALTHY
        assert "TimeoutError" in by_name["hanging"].message
        assert by_name["healthy"].status is HealthStatus.HEALTHY

    asyncio.run(run())


def test_non_finite_metrics_are_rejected() -> None:
    async def run() -> None:
        manager = ObservabilityManager()
        for method in (manager.counter, manager.gauge, manager.histogram):
            try:
                await method("invalid", nan)
            except ValueError as exc:
                assert "finite" in str(exc)
            else:
                raise AssertionError("expected non-finite metric rejection")

    asyncio.run(run())


def test_retention_is_bounded_and_fields_are_redacted() -> None:
    async def run() -> None:
        manager = ObservabilityManager(maximum_records_per_type=2)
        for index in range(3):
            await manager.log(
                LogLevel.INFO,
                f"message-{index}",
                source="test",
                fields={"client_secret": "plaintext", "index": index},
            )

        logs = await manager.logs()
        assert [item.message for item in logs] == ["message-1", "message-2"]
        assert logs[0].fields["client_secret"] == "***REDACTED***"
        try:
            logs[0].fields["index"] = 999
        except TypeError:
            pass
        else:
            raise AssertionError("expected immutable structured fields")

    asyncio.run(run())


def test_snapshot_is_deeply_immutable() -> None:
    async def run() -> None:
        manager = ObservabilityManager()
        snapshot = await manager.snapshot()
        try:
            snapshot["metadata"] = {}
        except TypeError:
            pass
        else:
            raise AssertionError("expected immutable snapshot")

    asyncio.run(run())


def test_metric_summary_aggregates_matching_series() -> None:
    async def run() -> None:
        manager = ObservabilityManager()
        await manager.counter("requests", 1, labels={"service": "api"})
        await manager.counter("requests", 2, labels={"service": "api"})
        await manager.counter("requests", 10, labels={"service": "worker"})

        summary = await manager.metric_summary(
            "requests",
            labels={"service": "api"},
        )
        assert summary is not None
        assert summary.count == 2
        assert summary.total == 3
        assert summary.minimum == 1
        assert summary.maximum == 2
        assert summary.latest == 2

    asyncio.run(run())


def test_metric_name_cannot_change_type() -> None:
    async def run() -> None:
        manager = ObservabilityManager()
        await manager.counter("stable_type")
        try:
            await manager.gauge("stable_type", 1)
        except ValueError as exc:
            assert "different type" in str(exc)
        else:
            raise AssertionError("expected metric-type conflict")

    asyncio.run(run())


def test_exporters_are_replaceable_and_failure_isolated() -> None:
    async def run() -> None:
        manager = ObservabilityManager()
        received = []

        async def successful(snapshot):
            received.append(snapshot)

        async def broken(snapshot):
            raise RuntimeError("export failed with secret")

        manager.register_exporter("successful", successful)
        manager.register_exporter("broken", broken)
        results = await manager.export()
        by_name = {item.exporter_name: item for item in results}

        assert by_name["successful"].success is True
        assert by_name["broken"].success is False
        assert by_name["broken"].error == "RuntimeError"
        assert len(received) == 1
        try:
            received[0]["logs"] = ()
        except TypeError:
            pass
        else:
            raise AssertionError("expected immutable exporter snapshot")

    asyncio.run(run())


def test_latest_health_results_are_in_snapshot() -> None:
    async def run() -> None:
        manager = ObservabilityManager()

        async def healthy():
            return HealthStatus.HEALTHY, "ok"

        manager.register_health_check("database", healthy)
        await manager.run_health_checks()
        snapshot = await manager.snapshot()
        assert snapshot["health_checks"][0].name == "database"
        assert snapshot["health_checks"][0].status is HealthStatus.HEALTHY

    asyncio.run(run())
