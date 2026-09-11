"""One fail-closed publication boundary for every FTMO proposal producer."""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping

CONTEXT_ONLY = "CONTEXT ONLY — NOT AN EXECUTABLE TRADE"
LOGGER = logging.getLogger("uvicorn.error.monatise.trade_lifecycle")


def failure_code(reason: str) -> str:
    value = reason.casefold()
    for fragments, code in (
        (("stale",), "STALE_MT5_QUOTE"),
        (("timestamp", "clock_skew"), "INVALID_QUOTE_TIMESTAMP"),
        (("no current quote", "quote unavailable", "no quote"), "MT5_QUOTE_UNAVAILABLE"),
        (("symbol", "mapping"), "MT5_SYMBOL_MAPPING_FAILED"),
        (("superseded",), "SIGNAL_SUPERSEDED"),
        (("expired", "expiry"), "PROPOSAL_EXPIRED"),
        (("risk", "volume", "spread", "exposure", "loss capacity", "levels"), "RISK_VALIDATION_FAILED"),
        (("execution", "gate", "session", "kill switch"), "EXECUTION_GATES_BLOCKED"),
        (("persist", "durable", "identity collision"), "NO_DURABLE_PROPOSAL"),
        (("transport", "keyboard"), "APPROVAL_TRANSPORT_UNAVAILABLE"),
        (("quote", "bridge", "heartbeat"), "MT5_QUOTE_UNAVAILABLE"),
    ):
        if any(fragment in value for fragment in fragments):
            return code
    return "PROPOSAL_NOT_APPROVABLE"


def lifecycle_log(proposal: Mapping[str, Any], **changes: Any) -> dict[str, Any]:
    fields = {
        "analysis_id": proposal.get("analysis_id"), "signal_id": proposal.get("signal_id"),
        "proposal_id": proposal.get("proposal_id"), "symbol": proposal.get("symbol") or proposal.get("ftmo_symbol"),
        "mapped_mt5_symbol": (proposal.get("mapping") or {}).get("ftmo_execution_symbol"),
        "analysis_status": proposal.get("analysis_state"), "signal_status": proposal.get("confirmation_status"),
        "quote_status": "validated" if proposal.get("quote_bid") else "unavailable",
        "quote_age_ms": proposal.get("quote_age_ms"),
        "risk_status": "validated" if proposal.get("risk_amount") else "not_validated",
        "proposal_status": proposal.get("status"), "telegram_publish_status": "not_published",
        "approval_keyboard_attached": False, "telegram_message_id": proposal.get("telegram_message_id"),
        "execution_gate_status": "not_checked", "failure_reason": None,
        "approval_controls_omitted_reason": None,
        **changes,
    }
    LOGGER.info("trade_lifecycle %s", json.dumps(fields, sort_keys=True, default=str))
    return fields


def context_message(message: str, reason: str = "ANALYSIS_ONLY") -> str:
    if message.startswith(CONTEXT_ONLY):
        return message
    return f"{CONTEXT_ONLY}\napproval_controls_omitted_reason={reason}\n{message}"


async def publish_proposal(transport: Any, chat_id: str, service: Any, proposal_id: str) -> int:
    # Never trust caller-supplied message text or reconstruct a missing proposal.
    from monatise.application.ftmo_master import FTMOMasterError, format_proposal

    if service is None:
        raise FTMOMasterError("durable proposal publication service is unavailable")
    repository = service.repository
    stored = await repository.proposal(proposal_id)
    if stored is None:
        lifecycle_log({"proposal_id": proposal_id}, failure_reason="proposal missing",
                      approval_controls_omitted_reason="NO_DURABLE_PROPOSAL")
        raise FTMOMasterError("no durable proposal; executable publication refused")
    proposal, version = stored
    previous = proposal.get("telegram_message_id")
    if previous is not None:
        if str(proposal.get("telegram_chat_id")) != str(chat_id):
            raise FTMOMasterError("proposal belongs to another Telegram chat")
        return previous
    # A send timeout/crash has an unknown outcome. Never blindly create another
    # live approval message; an operator must reconcile the durable send intent.
    if proposal.get("telegram_publish_status") in {"sending", "reconciliation_required"}:
        raise FTMOMasterError("Telegram publication requires reconciliation")
    try:
        await service.validate_proposal_publication(proposal)
        if not callable(getattr(transport, "send_trade_proposal", None)):
            raise FTMOMasterError("approval keyboard transport is unavailable")
    except (FTMOMasterError, ValueError) as exc:
        reason = failure_code(str(exc))
        proposal.update({"telegram_publish_status": "context_only", "approval_keyboard_attached": False,
                         "approval_controls_omitted_reason": reason, "blocking_reason": str(exc),
                         "telegram_chat_id": str(chat_id)})
        await repository.update_proposal(proposal_id, proposal, version)
        fields = lifecycle_log(proposal, failure_reason=str(exc), approval_controls_omitted_reason=reason,
                               execution_gate_status="blocked", telegram_publish_status="context_only")
        await repository.audit("telegram_proposal_withheld", proposal_id, fields)
        # No actionable formatting, levels or approval command can leak here.
        return await transport.send_message(chat_id, context_message(
            f"Instrument: {proposal.get('symbol') or 'unknown'}\nProposal: {proposal_id}\nReason: {exc}\nNo order was sent.", reason,
        ))
    proposal.update({
        "telegram_chat_id": str(chat_id), "telegram_publish_status": "sending",
        "approval_controls_required": True, "approval_keyboard_attached": False,
    })
    await repository.update_proposal(proposal_id, proposal, version)
    fields = lifecycle_log(proposal, telegram_publish_status="sending", execution_gate_status="ready")
    await repository.audit("telegram_proposal_send_intent", proposal_id, fields)
    message_id = None
    try:
        message_id = await transport.send_trade_proposal(chat_id, format_proposal(proposal), proposal_id)
        await repository.attach_proposal_telegram_message(proposal_id, message_id)
        fields = lifecycle_log(proposal, telegram_publish_status="published", approval_keyboard_attached=True,
                               telegram_message_id=message_id, execution_gate_status="ready")
        await repository.audit("telegram_approval_controls_attached", proposal_id, fields)
        return message_id
    except Exception as exc:
        # Callback and bridge validation both require the completed publication
        # record. Remove controls if Telegram succeeded but persistence failed.
        if message_id is not None:
            try:
                await transport.update_trade_proposal(chat_id, message_id, context_message(
                    f"Proposal: {proposal_id}\nPublication could not be persisted. No order was sent.",
                    "PUBLICATION_PERSISTENCE_FAILED",
                ))
            except Exception:
                LOGGER.exception("failed to retract unpersisted Telegram approval controls")
        try:
            current = await repository.proposal(proposal_id)
            if current is not None:
                value, version = current
                value.update({"telegram_publish_status": "reconciliation_required", "approval_keyboard_attached": False,
                              "approval_controls_omitted_reason": "TELEGRAM_PUBLICATION_FAILED",
                              "publication_error_type": type(exc).__name__})
                await repository.update_proposal(proposal_id, value, version)
        except Exception:
            LOGGER.exception("failed to persist Telegram publication reconciliation state")
        lifecycle_log(proposal, telegram_publish_status="reconciliation_required", telegram_message_id=message_id,
                      failure_reason=type(exc).__name__, approval_controls_omitted_reason="TELEGRAM_PUBLICATION_FAILED")
        raise
