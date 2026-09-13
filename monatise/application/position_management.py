"""Durable management of a single MT5 position, using approved signed commands.

Broker deal IDs are the accounting source of truth. A price crossing creates a
pending exit, never a filled target. Uncertain submissions are not retried under
a different command ID. Redis and process-local state are not used for recovery.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping

from monatise.application.take_profit import (
    TakeProfitPlan,
    ZERO,
    decimal,
    encode,
    format_targets,
    timestamp,
)

NAMESPACE = "ftmo_position_management_v1"
LOGGER = logging.getLogger("monatise.position_management")


@dataclass
class ManagedPosition:
    logical_trade_id: str
    ticket: str
    position_identifier: str
    plan: TakeProfitPlan
    original_plan: dict[str, Any]
    original_sl: Decimal
    current_sl: Decimal
    original_volume: Decimal
    remaining_volume: Decimal
    state: str = "OPEN"
    terminal_reason: str | None = None
    realized_pnl: Decimal = ZERO
    unrealized_pnl: Decimal = ZERO
    mfe_r: Decimal = ZERO
    mae_r: Decimal = ZERO
    seen_deals: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    pending_proposal_id: str | None = None
    pending_intent: dict[str, Any] | None = None
    entry: Decimal = ZERO
    stop_management_completed: list[str] = field(default_factory=list)
    original_risk_amount: Decimal = ZERO
    opening_costs: Decimal = ZERO

    def to_dict(self) -> dict[str, Any]:
        return encode(
            {
                **self.__dict__,
                "plan": self.plan.to_dict(),
                "pending_intent": self.pending_intent
                if self.pending_proposal_id
                else None,
            }
        )

    @property
    def realized_blended_r(self) -> Decimal | None:
        return (
            self.realized_pnl / self.original_risk_amount
            if self.original_risk_amount > 0
            else None
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ManagedPosition":
        fields = dict(value)
        fields["plan"] = TakeProfitPlan.from_dict(fields["plan"])
        for key in (
            "original_sl",
            "current_sl",
            "original_volume",
            "remaining_volume",
            "realized_pnl",
            "unrealized_pnl",
            "mfe_r",
            "mae_r",
            "entry",
        ):
            fields[key] = decimal(fields[key])
        fields["events"] = list(fields["events"])
        fields["seen_deals"] = list(fields["seen_deals"])
        fields["stop_management_completed"] = list(
            fields.get("stop_management_completed") or []
        )
        fields["original_risk_amount"] = decimal(fields.get("original_risk_amount", 0))
        fields["opening_costs"] = decimal(fields.get("opening_costs", 0))
        return cls(**fields)

    def event(self, kind: str, now: datetime, **details: Any) -> None:
        self.events.append(
            encode(
                {"kind": kind, "at": now, "trade_id": self.logical_trade_id, **details}
            )
        )

    def apply_deal(
        self, deal: Mapping[str, Any], now: datetime, *, target_name: str | None = None
    ) -> None:
        identity = str(deal["deal_id"])
        if identity in self.seen_deals:
            return
        if str(deal["position_id"]) != self.position_identifier:
            raise ValueError("deal position identity mismatch")
        if str(deal.get("entry")) in {"in", "0"}:
            costs = decimal(deal.get("commission", 0)) + decimal(deal.get("fee", 0))
            self.opening_costs += costs
            self.realized_pnl += costs
            self.seen_deals.append(identity)
            self.event("opening_costs", now, deal_id=identity, costs=costs)
            return
        if str(deal.get("entry")) not in {"out", "out_by", "1", "3"}:
            return
        volume = decimal(deal["volume"])
        pnl = (
            decimal(deal.get("profit", 0))
            + decimal(deal.get("commission", 0))
            + decimal(deal.get("swap", 0))
            + decimal(deal.get("fee", 0))
        )
        if volume <= 0 or volume > self.remaining_volume:
            raise ValueError("deal volume exceeds managed remainder")
        reason = str(deal.get("reason") or "UNKNOWN").upper()
        if target_name and reason != "TP":
            target = next(t for t in self.plan.targets if t.name == target_name)
            if target.closed_volume + volume > target.allocated_volume:
                raise ValueError("partial fill exceeds approved target allocation")
        self.remaining_volume -= volume
        self.realized_pnl += pnl
        self.seen_deals.append(identity)
        if reason == "TP":
            target_name = self.plan.targets[-1].name
        if target_name:
            targets = list(self.plan.targets)
            index = next(i for i, t in enumerate(targets) if t.name == target_name)
            target = targets[index]
            closed = target.closed_volume + volume
            if reason != "TP" and closed > target.allocated_volume:
                raise ValueError("partial fill exceeds approved target allocation")
            complete = closed >= target.allocated_volume
            targets[index] = replace(
                target,
                closed_volume=closed,
                realized_pnl=target.realized_pnl
                + pnl
                + self.opening_costs * volume / self.original_volume,
                status="HIT" if complete else "PARTIAL_FILL",
                hit_at=timestamp(deal.get("time") or now) if complete else None,
            )
            self.plan = replace(
                self.plan,
                targets=tuple(targets),
                remaining_position_size=self.remaining_volume,
            )
            self.state = target_name.upper() + ("_HIT" if complete else "_PENDING")
            self.event(
                "target_fill",
                now,
                target=target_name,
                volume=volume,
                pnl=pnl,
                deal_id=identity,
            )
        elif reason == "SL":
            improved = (
                self.current_sl >= self.entry
                if self.plan.direction == "long"
                else self.current_sl <= self.entry
            )
            self.terminal_reason = "BREAKEVEN_STOPPED" if improved else "STOPPED"
        elif reason in {"CLIENT", "MOBILE", "WEB", "EXPERT"}:
            self.terminal_reason = "MANUALLY_CLOSED"
        else:
            self.terminal_reason = reason
        if self.remaining_volume == 0:
            self.state = "POSITION_CLOSED"
            self.terminal_reason = (
                "FINAL_TARGET_HIT"
                if reason == "TP" or target_name == self.plan.targets[-1].name
                else self.terminal_reason
            )
            self.plan = replace(
                self.plan,
                remaining_position_size=ZERO,
                targets=tuple(
                    replace(t, status="BYPASSED" if reason == "TP" else "CANCELLED")
                    if t.status not in {"HIT"}
                    else t
                    for t in self.plan.targets
                ),
            )
            self.unrealized_pnl = ZERO
            self.pending_proposal_id = None
            self.event(
                "position_closed",
                now,
                reason=self.terminal_reason,
                pnl=self.realized_pnl,
            )
        self.plan = replace(self.plan, remaining_position_size=self.remaining_volume)


def protective_stop(
    state: ManagedPosition,
    *,
    policy: str,
    evidence: Mapping[str, Any],
    now: datetime,
    bid: Any,
    ask: Any,
    minimum_distance: Any,
    tick_size: Any,
) -> Decimal | None:
    """Fresh confirmed structure is mandatory, including mechanical BE modes."""
    if (
        not evidence.get("confirmed")
        or evidence.get("invalidated")
        or not evidence.get("observed_at")
    ):
        return None
    age = now - timestamp(evidence["observed_at"])
    if age < timedelta(0) or age > timedelta(minutes=5):
        return None
    if evidence.get("direction") != state.plan.direction:
        return None
    long = state.plan.direction == "long"
    if policy in {"AFTER_TP1", "AFTER_TP2"}:
        proposed = state.entry
    elif policy in {"STRUCTURE_BASED", "STRUCTURE_TRAIL"}:
        level = evidence.get("confirmed_higher_low" if long else "confirmed_lower_high")
        if level is None:
            return None
        proposed = decimal(level) + decimal(tick_size) * (-1 if long else 1)
    elif policy == "ATR_TRAIL":
        if evidence.get("atr") is None or decimal(evidence["atr"]) <= 0:
            return None
        proposed = decimal(bid if long else ask) + decimal(evidence["atr"]) * Decimal(
            2
        ) * (-1 if long else 1)
    elif policy == "LIQUIDITY_TRAIL":
        if evidence.get("protective_liquidity_level") is None:
            return None
        proposed = decimal(evidence["protective_liquidity_level"])
    else:
        return None
    tick = decimal(tick_size)
    proposed = (proposed // tick) * tick
    if long and (
        proposed <= state.current_sl
        or proposed >= decimal(bid) - decimal(minimum_distance)
    ):
        return None
    if not long and (
        proposed >= state.current_sl
        or proposed <= decimal(ask) + decimal(minimum_distance)
    ):
        return None
    return proposed


class PositionManagementService:
    def __init__(self, control: Any) -> None:
        self.control = control
        self.repository = control.repository

    async def get(self, trade_id: str) -> tuple[ManagedPosition, int] | None:
        record = await self.repository.store.get(NAMESPACE, trade_id)
        return (
            (ManagedPosition.from_dict(record.value), record.version)
            if record
            else None
        )

    async def for_ticket(
        self, ticket: str, *, include_closed: bool = False
    ) -> tuple[ManagedPosition, int] | None:
        records = await self.repository.store.list_namespace(NAMESPACE)
        return next(
            (
                (ManagedPosition.from_dict(r.value), r.version)
                for r in records
                if str(r.value["ticket"]) == ticket
                and (include_closed or r.value["state"] != "POSITION_CLOSED")
            ),
            None,
        )

    async def save(self, state: ManagedPosition, version: int) -> None:
        await self.repository._put(
            NAMESPACE, state.logical_trade_id, state.to_dict(), expected_version=version
        )
        LOGGER.info(
            "managed position persisted",
            extra={
                "logical_trade_id": state.logical_trade_id,
                "management_state": state.state,
                "remaining_volume": str(state.remaining_volume),
                "realized_pnl": str(state.realized_pnl),
                "last_event": state.events[-1] if state.events else None,
            },
        )

    async def record_structure(
        self,
        symbol: str,
        evidence: Mapping[str, Any],
        *,
        analysis_entry: Any = None,
        now: datetime | None = None,
    ) -> None:
        """Called only by Monatise analysis, never by the EA or Telegram input."""
        if not evidence.get("source") or not evidence.get("confirmed"):
            return
        timestamp(evidence["observed_at"])
        evidence = dict(evidence)
        if analysis_entry is not None:
            # Structure shares the analysis price scale. Map it before any stop
            # proposal; GC/ES/NQ levels must never be copied into CFDs directly.
            try:
                self.control._verified_instrument_mapping(symbol)
                bridge = await self.control._healthy_bridge(now)
                quote = self.control._quote_match(bridge, symbol)[1]
                broker_entry = decimal(
                    quote["ask"] if evidence["direction"] == "long" else quote["bid"]
                )
                ratio = broker_entry / decimal(analysis_entry)
                if not Decimal(".5") <= ratio <= Decimal(2):
                    raise ValueError("structure mapping outside verified ratio safety")
                evidence["analysis_evidence"] = dict(evidence)
                for key in (
                    "confirmed_higher_low",
                    "confirmed_lower_high",
                    "protective_liquidity_level",
                    "atr",
                ):
                    if evidence.get(key) is not None:
                        evidence[key] = str(decimal(evidence[key]) * ratio)
                evidence.update(
                    execution_symbol=symbol,
                    mapping_ratio=str(ratio),
                    mapping_quote_at=quote["timestamp"],
                )
            except (
                ValueError,
                ArithmeticError,
                TypeError,
                KeyError,
                IndexError,
                RuntimeError,
            ):
                await self.repository.audit(
                    "multi_tp_structure_unavailable",
                    symbol,
                    {"reason": "fresh validated broker mapping unavailable"},
                )
                return
        await self.repository._put(
            "ftmo_management_structure_v1", symbol.upper(), dict(evidence)
        )

    async def reconcile(self, snapshot: Mapping[str, Any], now: datetime) -> list[str]:
        if (
            snapshot.get("multi_tp_version") != 1
            or not snapshot.get("identity_match")
            or not snapshot.get("terminal_connected")
        ):
            return []
        published = []
        for parent in await self.repository.proposals():
            if (
                parent.get("kind") != "open_trade"
                or not parent.get("take_profit_plan")
                or not parent.get("approved_by")
            ):
                continue
            trade_id = parent["proposal_id"]
            stored = await self.get(trade_id)
            position = next(
                (
                    p
                    for p in snapshot.get("positions", [])
                    if str(p.get("ticket")) == str(parent.get("broker_ticket"))
                    or (
                        stored is not None
                        and str(p.get("identifier")) == stored[0].position_identifier
                    )
                    or str(p.get("comment"))
                    == "MNT:" + str(parent.get("command_id", ""))[:16]
                ),
                None,
            )
            if stored is None:
                deals = list(
                    {
                        str(d.get("deal_id")): d for d in snapshot.get("deals", [])
                    }.values()
                )
                opening = next(
                    (
                        d
                        for d in deals
                        if str(d.get("entry")) in {"in", "0"}
                        and (
                            d.get("comment")
                            == "MNT:" + str(parent.get("command_id", ""))[:16]
                            or str(d.get("order_id"))
                            == str(parent.get("broker_ticket"))
                        )
                    ),
                    None,
                )
                position_id = (
                    str(position.get("identifier") or "")
                    if position
                    else str((opening or {}).get("position_id") or "")
                )
                if not position_id:
                    continue
                plan = TakeProfitPlan.from_dict(parent["take_profit_plan"])
                opening_deals = [
                    d
                    for d in deals
                    if str(d.get("position_id")) == position_id
                    and str(d.get("entry")) in {"in", "0"}
                ]
                actual_volume = (
                    sum((decimal(d["volume"]) for d in opening_deals), ZERO)
                    if opening_deals
                    else decimal(position["volume"])
                )
                # A partially-filled opening is never treated as the full plan.
                if actual_volume != plan.original_position_size:
                    await self.repository.audit(
                        "multi_tp_reconciliation_required",
                        trade_id,
                        {"reason": "opening volume mismatch"},
                    )
                    continue
                state = ManagedPosition(
                    trade_id,
                    str(position["ticket"])
                    if position
                    else str(parent.get("broker_ticket") or position_id),
                    position_id,
                    plan,
                    plan.to_dict(),
                    decimal(parent["stop_loss"]),
                    decimal(position["sl"])
                    if position
                    else decimal(parent["stop_loss"]),
                    actual_volume,
                    actual_volume,
                    entry=decimal(position["price_open"])
                    if position
                    else sum(
                        (
                            decimal(d["price"]) * decimal(d["volume"])
                            for d in opening_deals
                        ),
                        ZERO,
                    )
                    / actual_volume,
                    original_risk_amount=decimal(parent["risk_amount"]),
                )
                state.original_risk_amount *= abs(
                    state.entry - state.original_sl
                ) / abs(plan.entry - plan.stop)
                state.event("position_open", now, plan=plan.to_dict())
                version = 0
            else:
                state, version = stored
            if state.state == "POSITION_CLOSED":
                continue
            try:
                pending = (
                    await self.repository.proposal(state.pending_proposal_id)
                    if state.pending_proposal_id
                    else None
                )
                command = (
                    await self.repository.command(pending[0]["command_id"])
                    if pending and pending[0].get("command_id")
                    else None
                )
                for deal in sorted(
                    snapshot.get("deals", []),
                    key=lambda d: (
                        timestamp(d.get("time") or now),
                        int(d.get("deal_id", 0)),
                    ),
                ):
                    if str(deal.get("position_id")) != state.position_identifier:
                        continue
                    target = None
                    if pending and command:
                        broker_order = str(command[0].get("broker_ticket") or "")
                        expected_comment = "MNT:" + command[0]["command_id"][:16]
                        if (
                            broker_order and str(deal.get("order_id")) == broker_order
                        ) or deal.get("comment") == expected_comment:
                            target = pending[0].get("managed_target")
                    state.apply_deal(deal, now, target_name=target)
                if position is not None:
                    state.ticket = str(position["ticket"])
                    state.current_sl = decimal(position["sl"])
                    state.unrealized_pnl = decimal(position.get("profit", 0))
                    if decimal(position["volume"]) != state.remaining_volume:
                        raise ValueError(
                            "position volume does not reconcile with deal history"
                        )
                    quote_match = self.control._quote_match(snapshot, parent["symbol"])
                    if quote_match:
                        q = quote_match[1]
                        mark = decimal(
                            q["bid"] if state.plan.direction == "long" else q["ask"]
                        )
                        r = (
                            (mark - state.entry)
                            * (1 if state.plan.direction == "long" else -1)
                            / abs(state.entry - state.original_sl)
                        )
                        state.mfe_r, state.mae_r = (
                            max(state.mfe_r, r),
                            min(state.mae_r, r),
                        )
                elif state.remaining_volume != 0:
                    raise ValueError(
                        "position absent without complete closing-deal evidence"
                    )
                if state.state == "POSITION_CLOSED":
                    await self.save(state, version)
                    continue
                if command and pending[0].get("operation") == "partial_close":
                    filled = next(
                        t
                        for t in state.plan.targets
                        if t.name == pending[0]["managed_target"]
                    )
                    if filled.status == "HIT" and command[0]["status"] != "reconciled":
                        command = (
                            await self.repository.update_command(
                                command[0]["command_id"],
                                {
                                    "status": "reconciled",
                                    "reconciliation_source": "mt5_deal_history",
                                    "reconciled_at": now.isoformat(),
                                },
                            ),
                            command[1],
                        )
                if (
                    command
                    and command[0]["status"] == "rejected"
                    and state.state != "MANAGEMENT_FAILED"
                ):
                    state.state = "MANAGEMENT_FAILED"
                    state.event(
                        "partial_close_failed",
                        now,
                        command_id=command[0]["command_id"],
                        reason=command[0].get("message") or command[0].get("reason"),
                    )
                    state.pending_proposal_id = None
                elif command and command[0]["status"] == "reconciled":
                    operation = command[0]["operation"]
                    if operation == "partial_close":
                        target = next(
                            t
                            for t in state.plan.targets
                            if t.name == pending[0]["managed_target"]
                        )
                        if target.status not in {"HIT"}:
                            state.state = "RECONCILIATION_REQUIRED"
                        else:
                            state.pending_proposal_id = None
                    elif operation in {"sl", "breakeven", "modify_targets"}:
                        if operation == "modify_targets":
                            replacement = TakeProfitPlan.from_dict(
                                pending[0]["modified_plan"]
                            )
                            if (
                                position is None
                                or decimal(position["tp"])
                                != replacement.legacy_take_profit
                            ):
                                raise ValueError("modified broker target not confirmed")
                            state.plan = replacement
                        if operation != "modify_targets" and (
                            position is None
                            or decimal(position["sl"])
                            != decimal(pending[0].get("value") or state.entry)
                        ):
                            raise ValueError(
                                "stop modification not yet confirmed by MT5"
                            )
                        state.pending_proposal_id = None
                        state.state = "OPEN"
                        state.stop_management_completed.append(
                            str(pending[0].get("management_policy") or "manual")
                        )
                        state.event(
                            "manual_modification"
                            if not pending[0].get("management_policy")
                            else "protective_stop_changed",
                            now,
                            operation=operation,
                            current_sl=state.current_sl,
                        )
                await self.save(state, version)
            except (ValueError, ArithmeticError, KeyError) as exc:
                state.state = "RECONCILIATION_REQUIRED"
                state.event("reconciliation_required", now, reason=str(exc))
                await self.save(state, version)
                continue
            except RuntimeError:
                # Another heartbeat owns this version. It will finish recovery.
                continue
            if state.state in {
                "POSITION_CLOSED",
                "RECONCILIATION_REQUIRED",
                "MANAGEMENT_FAILED",
                "MANAGEMENT_PAUSED",
            }:
                continue
            proposal_id = await self.advance(trade_id, parent, snapshot, now)
            if proposal_id:
                published.append(proposal_id)
        return published

    async def advance(
        self,
        trade_id: str,
        parent: Mapping[str, Any],
        snapshot: Mapping[str, Any],
        now: datetime,
    ) -> str | None:
        state, version = await self.get(trade_id)
        from monatise.application.take_profit import route_for

        if not self.control.configuration.multi_tp.permits(
            route_for(self.control._verified_instrument_mapping(parent["symbol"]))
        ):
            return None
        quote_match = self.control._quote_match(snapshot, parent["symbol"])
        if not quote_match:
            return None
        quote = quote_match[1]
        if (
            not timedelta(0)
            <= now - timestamp(quote["timestamp"])
            <= timedelta(seconds=self.control.configuration.quote_max_age_seconds)
        ):
            return None
        if state.pending_proposal_id:
            existing = await self.repository.proposal(state.pending_proposal_id)
            if existing is None:
                if (
                    not state.pending_intent
                    or state.pending_intent.get("proposal_id")
                    != state.pending_proposal_id
                ):
                    state.state = "RECONCILIATION_REQUIRED"
                    state.event("reservation_incomplete", now)
                    await self.save(state, version)
                    return None
                await self.repository.save_proposal(state.pending_intent)
                existing = await self.repository.proposal(state.pending_proposal_id)
            if existing is not None:
                if existing[0]["status"] == "pending_confirmation":
                    if (
                        existing[0]["operation"] == "partial_close"
                        and state.plan.management_mode == "APPROVED_PLAN"
                        and self.control.configuration.multi_tp.auto_partial_close
                    ):
                        await self.control.approve(
                            existing[0]["proposal_id"], parent["approved_by"], now=now
                        )
                        return None
                    return (
                        existing[0]["proposal_id"]
                        if not existing[0].get("telegram_message_id")
                        else None
                    )
                if existing[0]["status"] in {"rejected", "expired"}:
                    state.pending_proposal_id = None
                    state.state = "MANAGEMENT_PAUSED"
                    await self.save(state, version)
                return None
            # Crash after the state reservation: reconstruct the same proposal ID.
        else:
            stop_proposal = await self.maybe_protect(state, version, parent, quote, now)
            if stop_proposal:
                return stop_proposal
        target = next((t for t in state.plan.targets if t.status == "PENDING"), None)
        if target is None:
            return None
        mark = decimal(quote["bid"] if state.plan.direction == "long" else quote["ask"])
        if (mark - state.plan.legacy_take_profit) * (
            1 if state.plan.direction == "long" else -1
        ) >= 0:
            return None
        if (mark - target.price) * (1 if state.plan.direction == "long" else -1) < 0:
            return None
        # Final broker TP closes the residual even when the control plane is offline.
        if target.name == state.plan.targets[-1].name:
            return None
        proposal_id = hashlib.sha256(
            f"tp:{trade_id}:{target.name}:{state.plan.digest()}".encode()
        ).hexdigest()[:12]
        state.pending_proposal_id = proposal_id
        state.state = target.name.upper() + "_PENDING"
        state.event(
            "partial_close_pending",
            now,
            target=target.name,
            volume=target.allocated_volume,
        )
        proposal = {
            "proposal_id": proposal_id,
            "kind": "manage_trade",
            "status": "pending_confirmation",
            "actor": parent["approved_by"],
            "operation": "partial_close",
            "target_id": state.ticket,
            "symbol": parent["symbol"],
            "side": parent["side"],
            "volume": str(target.allocated_volume),
            "expected_remaining_volume": str(state.remaining_volume),
            "position_identifier": state.position_identifier,
            "managed_trade_id": trade_id,
            "managed_target": target.name,
            "plan_digest": state.plan.digest(),
            "trigger_price": str(target.price),
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=30)).isoformat(),
            "confirmation_required": True,
            "analysis_id": parent["analysis_id"],
            "signal_id": parent["signal_id"],
            "scope_approval_id": parent.get("approval_id"),
            "automatic_management": state.plan.management_mode == "APPROVED_PLAN"
            and self.control.configuration.multi_tp.auto_partial_close,
        }
        state.pending_intent = dict(proposal)
        await self.save(state, version)
        if await self.repository.proposal(proposal_id) is None:
            await self.repository.save_proposal(proposal)
        if (
            state.plan.management_mode == "APPROVED_PLAN"
            and self.control.configuration.multi_tp.auto_partial_close
        ):
            await self.control.approve(proposal_id, parent["approved_by"], now=now)
            return None
        return proposal_id

    async def maybe_protect(
        self,
        state: ManagedPosition,
        version: int,
        parent: Mapping[str, Any],
        quote: Mapping[str, Any],
        now: datetime,
    ) -> str | None:
        config = self.control.configuration.multi_tp
        hit = [t for t in state.plan.targets if t.status == "HIT"]
        policy = None
        if config.auto_trailing and state.plan.trail_policy != "OFF" and len(hit) >= 2:
            policy = state.plan.trail_policy
        elif config.auto_breakeven and state.plan.breakeven_policy != "NONE":
            required = 2 if state.plan.breakeven_policy == "AFTER_TP2" else 1
            if len(hit) >= required and hit[0].rr >= config.breakeven_minimum_rr:
                policy = state.plan.breakeven_policy
        if not policy:
            return None
        record = await self.repository.store.get(
            "ftmo_management_structure_v1", str(parent["symbol"]).upper()
        )
        if record is None:
            return None
        evidence = record.value
        identity = policy + ":" + str(evidence.get("observed_at"))
        if identity in state.stop_management_completed:
            return None
        price = protective_stop(
            state,
            policy=policy,
            evidence=evidence,
            now=now,
            bid=quote["bid"],
            ask=quote["ask"],
            minimum_distance=max(
                decimal(quote.get("stops_level", 0)),
                decimal(quote.get("freeze_level", 0)),
            )
            * decimal(quote.get("point", quote["tick_size"])),
            tick_size=quote["tick_size"],
        )
        if price is None:
            return None
        proposal_id = hashlib.sha256(
            f"stop:{state.logical_trade_id}:{identity}:{price}".encode()
        ).hexdigest()[:12]
        proposal = self.management_fields(state, parent, "sl", proposal_id, now)
        proposal.update(
            value=str(price),
            management_policy=identity,
            structure_evidence=dict(evidence),
        )
        state.pending_proposal_id = proposal_id
        state.pending_intent = dict(proposal)
        state.event("protective_stop_pending", now, price=price, policy=identity)
        await self.save(state, version)
        await self.repository.save_proposal(proposal)
        # Stop changes still use their own Telegram approval in v1. A trailing
        # policy is not permission to silently broaden the approved trade.
        return proposal_id

    @staticmethod
    def management_fields(
        state: ManagedPosition,
        parent: Mapping[str, Any],
        operation: str,
        proposal_id: str,
        now: datetime,
    ) -> dict[str, Any]:
        return {
            "proposal_id": proposal_id,
            "kind": "manage_trade",
            "status": "pending_confirmation",
            "actor": parent.get("approved_by"),
            "operation": operation,
            "target_id": state.ticket,
            "symbol": parent["symbol"],
            "side": parent["side"],
            "managed_trade_id": state.logical_trade_id,
            "expected_remaining_volume": str(state.remaining_volume),
            "position_identifier": state.position_identifier,
            "plan_digest": state.plan.digest(),
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=30)).isoformat(),
            "confirmation_required": True,
            "analysis_id": parent["analysis_id"],
            "signal_id": parent["signal_id"],
        }

    async def manual_proposal(
        self,
        *,
        actor: str,
        ticket: str,
        operation: str,
        value: str | None,
        now: datetime,
    ) -> dict[str, Any]:
        if actor not in self.control.configuration.authorized_user_ids:
            raise ValueError("Telegram user is not authorized")
        if operation not in {
            "tp",
            "tp1",
            "tp2",
            "tp3",
            "finaltp",
            "sl",
            "breakeven",
            "close",
        }:
            raise ValueError("unsupported managed operation")
        stored = await self.for_ticket(ticket)
        if stored is None:
            raise ValueError("no managed target plan for this ticket")
        state, version = stored
        if state.pending_proposal_id:
            pending = await self.repository.proposal(state.pending_proposal_id)
            if (
                pending
                and pending[0]["status"] in {"rejected", "expired"}
                and not pending[0].get("command_id")
            ):
                state.event(
                    "management_reservation_released",
                    now,
                    proposal_id=state.pending_proposal_id,
                )
                state.pending_proposal_id = None
            else:
                raise ValueError(
                    "management operation pending; reconcile or reject it first"
                )
        if state.state in {"MANAGEMENT_FAILED", "MANAGEMENT_PAUSED"}:
            # Definitive failure does not prevent a new explicit operator action.
            # Uncertain submissions retain their reservation and cannot get here.
            state.event("manual_management_resumed", now, previous_state=state.state)
            state.state = "OPEN"
        parent = (await self.repository.proposal(state.logical_trade_id))[0]
        proposal_id = hashlib.sha256(
            f"manual:{ticket}:{version}:{operation}:{value}:{now.isoformat()}".encode()
        ).hexdigest()[:12]
        target_operation = operation in {"tp", "tp1", "tp2", "tp3", "finaltp"}
        proposal = self.management_fields(
            state,
            parent,
            "modify_targets" if target_operation else operation,
            proposal_id,
            now,
        )
        proposal["actor"] = actor
        if target_operation:
            plan = state.plan
            name = (
                plan.targets[-1].name if operation in {"tp", "finaltp"} else operation
            )
            target = next((t for t in plan.targets if t.name == name), None)
            if target is None or target.status != "PENDING":
                raise ValueError("target is absent or already filled")
            price = decimal(value)
            rr = abs(price - plan.entry) / abs(plan.entry - plan.stop)
            changed = replace(
                target,
                price=price,
                broker_price=price,
                rr=rr,
                source="Telegram operator override",
                source_provider="operator",
                evidence_type="MANUAL_OVERRIDE",
                observed_at=now,
            )
            plan = replace(
                plan,
                targets=tuple(changed if t.name == name else t for t in plan.targets),
            )
            q = self.control._quote_match(
                await self.control._healthy_bridge(now), parent["symbol"]
            )[1]
            plan.validate(tick_size=decimal(q["tick_size"]))
            proposal.update(
                value=str(plan.legacy_take_profit), modified_plan=plan.to_dict()
            )
        else:
            proposal["value"] = value
        state.pending_proposal_id = proposal_id
        state.pending_intent = dict(proposal)
        await self.save(state, version)
        await self.repository.save_proposal(proposal)
        return proposal

    async def validate_intent(
        self, proposal: Mapping[str, Any], *, now: datetime
    ) -> None:
        stored = await self.get(proposal["managed_trade_id"])
        if stored is None:
            raise ValueError("managed position is unavailable")
        state, _ = stored
        original = await self.repository.proposal(state.logical_trade_id)
        if (
            not original
            or not original[0].get("approval_id")
            or not original[0].get("approved_by")
        ):
            raise ValueError("original trade approval is unavailable")
        if (
            proposal.get("scope_approval_id")
            and proposal["scope_approval_id"] != original[0]["approval_id"]
        ):
            raise ValueError("partial exit approval scope mismatch")
        if state.state in {
            "POSITION_CLOSED",
            "RECONCILIATION_REQUIRED",
            "MANAGEMENT_FAILED",
            "MANAGEMENT_PAUSED",
        }:
            raise ValueError("managed position is not executable")
        if (
            state.plan.digest() != proposal["plan_digest"]
            or str(state.remaining_volume) != proposal["expected_remaining_volume"]
        ):
            raise ValueError("managed plan changed; fresh approval required")
        if state.pending_proposal_id not in {None, proposal["proposal_id"]}:
            raise ValueError("another management operation is pending")
        bridge = await self.control._healthy_bridge(now)
        if (
            proposal["operation"] not in {"close", "sl", "breakeven"}
            and bridge.get("multi_tp_version") != 1
        ):
            raise ValueError("multi-target capable EA is required")
        position = next(
            (
                p
                for p in bridge.get("positions", [])
                if str(p.get("ticket")) == state.ticket
            ),
            None,
        )
        if (
            position is None
            or str(position.get("identifier")) != state.position_identifier
            or decimal(position["volume"]) != state.remaining_volume
        ):
            raise ValueError("position changed before management approval")
        if proposal["operation"] == "partial_close":
            from monatise.application.take_profit import route_for

            if not self.control.configuration.multi_tp.permits(
                route_for(self.control._verified_instrument_mapping(proposal["symbol"]))
            ):
                raise ValueError("multi-target management is disabled")
            if (
                proposal.get("automatic_management")
                and not self.control.configuration.multi_tp.auto_partial_close
            ):
                raise ValueError("automatic partial-close gate is disabled")
            target = next(
                t for t in state.plan.targets if t.name == proposal["managed_target"]
            )
            if (
                target.status != "PENDING"
                or decimal(proposal["volume"]) != target.allocated_volume
            ):
                raise ValueError("partial-close allocation changed")
            q = self.control._quote_match(bridge, proposal["symbol"])[1]
            if (
                not timedelta(0)
                <= now - timestamp(q["timestamp"])
                <= timedelta(seconds=self.control.configuration.quote_max_age_seconds)
            ):
                raise ValueError("management quote is stale")
            mark = decimal(q["bid"] if state.plan.direction == "long" else q["ask"])
            if (mark - target.price) * (
                1 if state.plan.direction == "long" else -1
            ) < 0:
                raise ValueError("target no longer reached")
            spread_ticks = (decimal(q["ask"]) - decimal(q["bid"])) / decimal(
                q["tick_size"]
            )
            if spread_ticks > self.control.configuration.maximum_spread_ticks:
                raise ValueError("management spread exceeds policy")
        elif proposal["operation"] in {"sl", "breakeven", "modify_targets"}:
            q = self.control._quote_match(bridge, proposal["symbol"])[1]
            if (
                not timedelta(0)
                <= now - timestamp(q["timestamp"])
                <= timedelta(seconds=self.control.configuration.quote_max_age_seconds)
            ):
                raise ValueError("management quote is stale")
            tick = decimal(q["tick_size"])
            minimum = max(
                decimal(q.get("stops_level", 0)), decimal(q.get("freeze_level", 0))
            ) * decimal(q.get("point", tick))
            level = (
                state.entry
                if proposal["operation"] == "breakeven"
                else decimal(proposal["value"])
            )
            long = state.plan.direction == "long"
            mark = decimal(q["bid"] if long else q["ask"])
            if level <= 0 or level % tick != 0:
                raise ValueError("managed price is not tick normalized")
            if proposal["operation"] != "modify_targets" and (
                (long and level < decimal(position["sl"]))
                or (not long and level > decimal(position["sl"]))
                or (mark - level) * (1 if long else -1) < minimum
            ):
                raise ValueError(
                    "managed stop cannot be worsened or violate broker distance"
                )
            if proposal["operation"] == "modify_targets":
                modified = TakeProfitPlan.from_dict(proposal["modified_plan"])
                modified.validate(tick_size=tick)
                if modified.legacy_take_profit != level or len(modified.targets) != len(
                    state.plan.targets
                ):
                    raise ValueError("modified target plan is inconsistent")
                if (
                    modified.entry,
                    modified.stop,
                    modified.original_position_size,
                    modified.remaining_position_size,
                    modified.management_mode,
                    modified.breakeven_policy,
                    modified.trail_policy,
                ) != (
                    state.plan.entry,
                    state.plan.stop,
                    state.plan.original_position_size,
                    state.plan.remaining_position_size,
                    state.plan.management_mode,
                    state.plan.breakeven_policy,
                    state.plan.trail_policy,
                ):
                    raise ValueError(
                        "target override cannot change the approved management policy"
                    )
                for previous, changed in zip(state.plan.targets, modified.targets):
                    if (
                        previous.name,
                        previous.allocation_pct,
                        previous.allocated_volume,
                        previous.status,
                        previous.closed_volume,
                        previous.realized_pnl,
                    ) != (
                        changed.name,
                        changed.allocation_pct,
                        changed.allocated_volume,
                        changed.status,
                        changed.closed_volume,
                        changed.realized_pnl,
                    ):
                        raise ValueError(
                            "target override cannot change allocation or fills"
                        )
                    if changed.status != "PENDING" and changed != previous:
                        raise ValueError("filled targets cannot be modified")
                    if changed.status == "PENDING" and (changed.price - mark) * (
                        1 if long else -1
                    ) < max(tick, minimum):
                        raise ValueError(
                            "modified target is reached or inside broker distance"
                        )
            if proposal.get("structure_evidence"):
                policy = str(proposal["management_policy"]).split(":", 1)[0]
                expected = protective_stop(
                    state,
                    policy=policy,
                    evidence=proposal["structure_evidence"],
                    now=now,
                    bid=q["bid"],
                    ask=q["ask"],
                    minimum_distance=max(
                        decimal(q.get("stops_level", 0)),
                        decimal(q.get("freeze_level", 0)),
                    )
                    * decimal(q.get("point", q["tick_size"])),
                    tick_size=q["tick_size"],
                )
                if expected is None or expected != level:
                    raise ValueError("protective structure changed or became stale")

    async def describe(self, ticket: str) -> str:
        record = await self.for_ticket(ticket, include_closed=True)
        if record is None:
            return "No managed target ladder for this ticket."
        state, _ = record
        return "\n".join(
            [
                f"Monatise targets — {ticket} | {state.state}",
                *format_targets(state.plan),
                f"Remaining: {state.remaining_volume}/{state.original_volume} lots | Realized: {state.realized_pnl}",
                f"SL: {state.current_sl} | BE: {state.plan.breakeven_policy} | Trail: {state.plan.trail_policy}",
            ]
        )
