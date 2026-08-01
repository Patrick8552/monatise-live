from __future__ import annotations

from hashlib import sha256
from json import dumps
from uuid import uuid4

from monatise.engines.integration.models import (
    IntegrationAction,
    IntegrationChannel,
    IntegrationEvent,
    IntegrationRequest,
    IntegrationResult,
    IntegrationStatus,
)


class IntegrationEngine:
    """Builds integration events for approved external boundaries.

    The engine may publish, store, schedule, validate, and ingest metadata.
    It must never submit orders or expose exchange execution capability.
    """

    def build(self, request: IntegrationRequest) -> IntegrationResult:
        request.validate()

        events: list[IntegrationEvent] = []
        blocked: list[IntegrationChannel] = []
        reasons: list[str] = []

        for channel in dict.fromkeys(request.requested_channels):
            if not self._enabled(channel, request):
                blocked.append(channel)
                reasons.append(f"{channel.value} integration is disabled")
                continue

            event = self._event_for(channel, request)
            if event is None:
                blocked.append(channel)
                reasons.append(f"{channel.value} has no supported integration action")
                continue

            events.append(event)

        if not events and blocked:
            status = IntegrationStatus.BLOCKED
        elif events and blocked:
            status = IntegrationStatus.PARTIAL
        elif events:
            status = IntegrationStatus.READY
        else:
            status = IntegrationStatus.FAILED

        if events:
            reasons.append(f"{len(events)} integration event(s) prepared")

        return IntegrationResult(
            symbol=request.report.symbol,
            status=status,
            events=tuple(events),
            blocked_channels=tuple(dict.fromkeys(blocked)),
            reasons=tuple(reasons),
            metadata={
                "engine_scope": "crypto_only",
                "execution_adapter_enabled": False,
                "adapter_submission_enabled": False,
                "openclaw_execution_allowed": False,
                "telegram_execution_allowed": False,
                "idempotency_enforced": True,
            },
        )

    def _event_for(
        self,
        channel: IntegrationChannel,
        request: IntegrationRequest,
    ) -> IntegrationEvent | None:
        payload = self._payload(channel, request)
        if payload is None:
            return None

        action = {
            IntegrationChannel.COINGLASS: IntegrationAction.INGEST,
            IntegrationChannel.TELEGRAM: IntegrationAction.PUBLISH,
            IntegrationChannel.OPENCLAW: IntegrationAction.SCHEDULE,
            IntegrationChannel.DATABASE: IntegrationAction.STORE,
            IntegrationChannel.DASHBOARD: IntegrationAction.PUBLISH,
            IntegrationChannel.AUDIT_LOG: IntegrationAction.STORE,
        }[channel]

        correlation_id = self._correlation_id(request)
        idempotency_key = self._idempotency_key(
            channel=channel,
            action=action,
            symbol=request.report.symbol,
            correlation_id=correlation_id,
            payload=payload,
        )

        event = IntegrationEvent(
            event_id=str(uuid4()),
            channel=channel,
            action=action,
            payload=payload,
            created_at=request.generated_at,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            metadata={
                "execution_allowed": False,
                "source_engine": "integration",
            },
        )
        event.validate()
        return event

    @staticmethod
    def _enabled(
        channel: IntegrationChannel,
        request: IntegrationRequest,
    ) -> bool:
        mapping = {
            IntegrationChannel.COINGLASS: request.enable_coinglass,
            IntegrationChannel.TELEGRAM: request.enable_telegram,
            IntegrationChannel.OPENCLAW: request.enable_openclaw,
            IntegrationChannel.DATABASE: request.enable_database,
            IntegrationChannel.DASHBOARD: request.enable_dashboard,
            IntegrationChannel.AUDIT_LOG: request.enable_audit_log,
        }
        return mapping[channel]

    @staticmethod
    def _payload(
        channel: IntegrationChannel,
        request: IntegrationRequest,
    ) -> dict | None:
        if channel is IntegrationChannel.COINGLASS:
            return {
                "symbol": request.report.symbol,
                "operation": "request_market_context",
                "required_fields": (
                    "open_interest",
                    "funding",
                    "liquidations",
                    "cvd",
                    "order_book",
                ),
                "execution_allowed": False,
            }

        if channel is IntegrationChannel.TELEGRAM:
            return {
                "symbol": request.report.symbol,
                "headline": request.report.headline,
                "summary": request.report.summary,
                "severity": request.report.severity.value,
                "blockers": request.report.blockers,
                "warnings": request.report.warnings,
                "execution_allowed": False,
            }

        if channel is IntegrationChannel.OPENCLAW:
            return {
                "symbol": request.report.symbol,
                "allowed_tasks": (
                    "schedule_analysis",
                    "validate_freshness",
                    "format_report",
                    "log_result",
                    "deliver_notification",
                ),
                "forbidden_tasks": (
                    "place_order",
                    "cancel_order",
                    "modify_position",
                    "change_risk_limits",
                ),
                "execution_allowed": False,
            }

        if channel is IntegrationChannel.DATABASE:
            return {
                "symbol": request.report.symbol,
                "record_type": "analysis_report",
                "payload": request.report.payload,
                "decision_trace": request.report.decision_trace,
                "execution_allowed": False,
            }

        if channel is IntegrationChannel.DASHBOARD:
            return {
                "symbol": request.report.symbol,
                "headline": request.report.headline,
                "severity": request.report.severity.value,
                "sections": request.report.payload.get("sections", ()),
                "execution_allowed": False,
            }

        if channel is IntegrationChannel.AUDIT_LOG:
            return {
                "symbol": request.report.symbol,
                "decision": request.execution_policy.decision.value,
                "mode": request.execution_policy.mode.value,
                "blockers": request.execution_policy.blockers,
                "warnings": request.execution_policy.warnings,
                "execution_allowed": False,
            }

        return None

    @staticmethod
    def _correlation_id(request: IntegrationRequest) -> str:
        raw = (
            f"{request.report.symbol}|"
            f"{request.generated_at.isoformat()}|"
            f"{request.report.channel.value}"
        )
        return sha256(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _idempotency_key(
        *,
        channel: IntegrationChannel,
        action: IntegrationAction,
        symbol: str,
        correlation_id: str,
        payload: dict,
    ) -> str:
        raw = dumps(
            {
                "channel": channel.value,
                "action": action.value,
                "symbol": symbol,
                "correlation_id": correlation_id,
                "payload": payload,
            },
            sort_keys=True,
            default=str,
        )
        return sha256(raw.encode("utf-8")).hexdigest()
