from datetime import datetime, timezone

from monatise.engines.execution_policy.models import (
    ExecutionDecision,
    ExecutionMode,
    ExecutionPolicyResult,
)
from monatise.engines.integration.engine import IntegrationEngine
from monatise.engines.integration.models import (
    IntegrationChannel,
    IntegrationRequest,
    IntegrationStatus,
)
from monatise.engines.reporting_intelligence.models import (
    ReportChannel,
    ReportResult,
    ReportSeverity,
)


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def report() -> ReportResult:
    return ReportResult(
        symbol="BTCUSDT",
        channel=ReportChannel.API,
        headline="BTCUSDT: TREND LONG",
        severity=ReportSeverity.APPROVED,
        summary="Approved analytical report",
        sections=(),
        decision_trace=("decision:trend", "risk:approved"),
        blockers=(),
        warnings=(),
        payload={"symbol": "BTCUSDT", "sections": ()},
        generated_at=NOW,
    )


def execution_policy() -> ExecutionPolicyResult:
    return ExecutionPolicyResult(
        symbol="BTCUSDT",
        mode=ExecutionMode.PAPER,
        decision=ExecutionDecision.PAPER_READY,
        proposal=None,
        blockers=(),
        warnings=(),
        reasons=(),
    )


def test_prepares_multiple_integration_events() -> None:
    result = IntegrationEngine().build(
        IntegrationRequest(
            report=report(),
            execution_policy=execution_policy(),
            requested_channels=(
                IntegrationChannel.TELEGRAM,
                IntegrationChannel.OPENCLAW,
                IntegrationChannel.DATABASE,
                IntegrationChannel.AUDIT_LOG,
            ),
            generated_at=NOW,
        )
    )

    assert result.status is IntegrationStatus.READY
    assert len(result.events) == 4
    assert all(event.idempotency_key for event in result.events)


def test_disabled_channel_returns_partial() -> None:
    result = IntegrationEngine().build(
        IntegrationRequest(
            report=report(),
            execution_policy=execution_policy(),
            requested_channels=(
                IntegrationChannel.TELEGRAM,
                IntegrationChannel.DATABASE,
            ),
            generated_at=NOW,
            enable_telegram=False,
        )
    )

    assert result.status is IntegrationStatus.PARTIAL
    assert IntegrationChannel.TELEGRAM in result.blocked_channels


def test_openclaw_payload_forbids_execution() -> None:
    result = IntegrationEngine().build(
        IntegrationRequest(
            report=report(),
            execution_policy=execution_policy(),
            requested_channels=(IntegrationChannel.OPENCLAW,),
            generated_at=NOW,
        )
    )

    event = result.events[0]
    assert "place_order" in event.payload["forbidden_tasks"]
    assert event.payload["execution_allowed"] is False


def test_execution_adapter_request_is_rejected() -> None:
    try:
        IntegrationEngine().build(
            IntegrationRequest(
                report=report(),
                execution_policy=execution_policy(),
                requested_channels=(IntegrationChannel.DATABASE,),
                generated_at=NOW,
                allow_execution_adapter=True,
            )
        )
    except ValueError as exc:
        assert "outside Integration Engine scope" in str(exc)
    else:
        raise AssertionError("expected execution-adapter rejection")


def test_engine_cannot_enable_execution_adapter() -> None:
    result = IntegrationEngine().build(
        IntegrationRequest(
            report=report(),
            execution_policy=execution_policy(),
            requested_channels=(IntegrationChannel.AUDIT_LOG,),
            generated_at=NOW,
        )
    )

    assert result.execution_adapter_enabled is False
    assert result.metadata["telegram_execution_allowed"] is False
    assert result.metadata["openclaw_execution_allowed"] is False


def test_coinglass_can_be_disabled_per_channel() -> None:
    result = IntegrationEngine().build(
        IntegrationRequest(
            report=report(),
            execution_policy=execution_policy(),
            requested_channels=(
                IntegrationChannel.COINGLASS,
                IntegrationChannel.AUDIT_LOG,
            ),
            generated_at=NOW,
            enable_coinglass=False,
        )
    )

    assert result.status is IntegrationStatus.PARTIAL
    assert IntegrationChannel.COINGLASS in result.blocked_channels


def test_duplicate_channels_produce_one_idempotent_event() -> None:
    result = IntegrationEngine().build(
        IntegrationRequest(
            report=report(),
            execution_policy=execution_policy(),
            requested_channels=(
                IntegrationChannel.DATABASE,
                IntegrationChannel.DATABASE,
            ),
            generated_at=NOW,
        )
    )

    assert result.status is IntegrationStatus.READY
    assert len(result.events) == 1
