"""Short local eligibility leases, separate from the approved broker expiry."""
from datetime import datetime, timedelta
from decimal import Decimal

from monatise.application.entry_policy import PENDING_LEASE_SECONDS
from monatise.application.hierarchy.approval import requires_shared_hierarchy, validate_shared_evidence
from monatise.application.market_session import classify_market_session, session_allows_execution
from monatise.application.take_profit import TakeProfitPlan, route_for


async def pending_entry_leases(master, snapshot, now):
    repository = master.repository
    readiness = await master.status(now=now)
    proposals = {str(p.get("command_id"))[:16]: p for p in await repository.proposals() if p.get("command_id")}
    leases = []
    revocations = "ftmo_pending_entry_revocations_v1"
    for order in snapshot.get("orders") or ():
        comment = str(order.get("comment") or "")
        if not comment.startswith("MNP:"):
            continue
        proposal = proposals.get(comment[4:])
        if proposal is None:
            continue  # Unrecognized ownership is never granted a lease.
        reason = None
        try:
            if await repository.store.get(revocations, proposal["command_id"]):
                raise ValueError("pending entry lease was permanently revoked")
            if (not proposal.get("entry_policy") or not proposal.get("automatic_pending_cancellation")
                    or not proposal.get("approved_by") or not proposal.get("approval_id")
                    or proposal.get("status") not in {"command_created", "reconciled", "reconciliation_required"}
                    or proposal.get("pending_cancellation_reason") or proposal.get("superseded_by_signal_id")):
                raise ValueError("pending setup is no longer approved or eligible")
            if not readiness.get("execution_ready"):
                raise ValueError("execution eligibility lost: " + ", ".join(master.execution_blockers(readiness)))
            expires = datetime.fromisoformat(proposal["expires_at"])
            if now >= expires:
                raise ValueError("setup expired")
            stored_command = await repository.command(proposal["command_id"])
            command = stored_command[0] if stored_command else None
            if (not command or command.get("approval_id") != proposal["approval_id"]
                    or command.get("expected_account_id") != snapshot["account_id"]
                    or command.get("expected_server", "").casefold() != snapshot["server"].casefold()
                    or command.get("status") not in {"delivered", "reconciled", "broker_uncertain"}):
                raise ValueError("pending order has no matching approved command")
            native_deadline = datetime.fromtimestamp(int(command["payload"]["pending_native_expires_epoch"]), tz=now.tzinfo)
            expires = min(expires, native_deadline)
            if now >= expires:
                raise ValueError("approved pending order expired")
            native_expiration = int(order["expiration_epoch"])
            if native_expiration <= int(now.timestamp()) or native_expiration > int(native_deadline.timestamp()):
                raise ValueError("broker pending expiry differs from the approved deadline")
            for field in ("symbol", "side", "order_type", "entry", "stop_loss", "take_profit", "volume", "entry_zone_low", "entry_zone_high", "setup_invalidation_price"):
                if str(command["payload"].get(field)) != str(proposal.get(field)):
                    raise ValueError("pending proposal differs from signed approval")
            if master._symbol_key(order["symbol"]) != master._symbol_key(proposal["symbol"]):
                raise ValueError("pending symbol differs from approved order")
            expected_type = {("buy", "limit"): 2, ("sell", "limit"): 3, ("buy", "stop"): 4, ("sell", "stop"): 5}
            if int(order["type"]) != expected_type[(proposal["side"], proposal["order_type"])]:
                raise ValueError("pending order type changed")
            for field, approved in (("price_open", "entry"), ("sl", "stop_loss"), ("tp", "take_profit")):
                if Decimal(str(order[field])) != Decimal(str(proposal[approved])):
                    raise ValueError("pending price or protection differs from approved order")
            volume = Decimal(str(order["volume"]))
            if not 0 < volume <= Decimal(proposal["volume"]):
                raise ValueError("pending volume exceeds approved size")
            instrument = master._verified_instrument_mapping(proposal["symbol"])
            if requires_shared_hierarchy(instrument):
                proof = await validate_shared_evidence(repository.store, instrument, proposal.get("evidence_bundle"), now)
                expires = min(expires, datetime.fromisoformat(proof["expires_at"]))
            if proposal.get("replacement_for_proposal_id"):
                await master._validate_limit_replacement_origin(proposal, now=now)
            expires = min(expires, await master._validate_entry_source(proposal, now))
            if readiness.get("execution_session_expiry"):
                expires = min(expires, datetime.fromisoformat(readiness["execution_session_expiry"]))
            quote = master._quote_match(snapshot, proposal["symbol"])[1]
            master._require_pending_capability(snapshot, quote)
            master._validate_entry_thesis(proposal["side"], quote, proposal.get("setup_invalidation_price") or proposal["stop_loss"], proposal["take_profit"])
            if not session_allows_execution(classify_market_session(now, instrument=instrument, trade_mode=quote.get("trade_mode"))):
                raise ValueError("market session no longer permits execution")
            if proposal.get("take_profit_plan"):
                plan = TakeProfitPlan.from_dict(proposal["take_profit_plan"])
                if (not master.configuration.multi_tp.permits(route_for(instrument)) or snapshot.get("multi_tp_version") != 1
                        or now >= plan.expires_at or plan.minimum_rr < master.configuration.multi_tp.minimum_rr
                        or plan.minimum_increment_r < master.configuration.multi_tp.minimum_increment_r
                        or (plan.management_mode == "APPROVED_PLAN" and not master.configuration.multi_tp.auto_partial_close)
                        or (plan.breakeven_policy != "NONE" and not master.configuration.multi_tp.auto_breakeven)
                        or (plan.trail_policy != "OFF" and not master.configuration.multi_tp.auto_trailing)):
                    raise ValueError("target management eligibility lost")
            fields = await master._validated_open_fields(symbol=proposal["symbol"], side=proposal["side"], order_type=proposal["order_type"],
                entry=proposal["entry"], stop_loss=proposal["stop_loss"], take_profit=proposal["take_profit"], now=now,
                entry_zone_low=proposal["entry_zone_low"], entry_zone_high=proposal["entry_zone_high"],
                **(await master._confidence_risk_inputs(proposal, now))[0], exclude_pending_ticket=str(order["ticket"]),
                defer_entry_placement=True)  # A working order may approach/touch entry without becoming invalid.
            risk = Decimal(fields["risk_amount"]) * volume / Decimal(fields["volume"])
            if volume > Decimal(fields["volume"]) or risk > Decimal(proposal["risk_amount"]):
                raise ValueError("pending order exceeds current or approved risk capacity")
            leases.append(f"{int(order['ticket'])}|{int(min(expires, now + timedelta(seconds=PENDING_LEASE_SECONDS)).timestamp())}|{int(expires.timestamp())}")
        except (ValueError, RuntimeError, ArithmeticError, KeyError, TypeError) as exc:
            reason = str(exc)
        if reason:
            try:
                await repository.store.put(revocations, proposal["command_id"],
                    {"reason": reason, "revoked_at": now.isoformat(), "ticket": str(order["ticket"])}, expected_version=0)
            except RuntimeError:
                pass  # Existing revocation is immutable.
        if reason and not proposal.get("pending_cancellation_reason"):
            stored = await repository.proposal(proposal["proposal_id"])
            if stored:
                value, version = stored
                value.update(pending_cancellation_reason=reason, pending_cancellation_requested_at=now.isoformat(),
                             pending_entry_state="CANCELLATION_REQUIRED")
                try:
                    await repository.update_proposal(value["proposal_id"], value, version)
                    await repository.audit("pending_entry_cancellation_required", value["proposal_id"], {"ticket": order["ticket"], "reason": reason})
                except RuntimeError:
                    pass  # A concurrent update must never restore a revoked lease.
    return ";".join(leases)
