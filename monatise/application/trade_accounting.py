"""Broker-deal accounting and a durable, duplicate-safe notification outbox.

Price snapshots are never a substitute for realized P/L. Missing history remains
unresolved. An uncertain Telegram send is retained for reconciliation, not resent.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

ACCOUNTS = "ftmo_trade_accounting_v1"
NOTIFICATIONS = "ftmo_trade_notifications_v1"
ZERO = Decimal("0")


def number(value: Any) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError("missing broker amount")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid broker amount") from exc
    if not result.is_finite():
        raise ValueError("non-finite broker amount")
    return result


def instant(value: Any) -> datetime:
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("broker timestamp has no timezone")
    return result.astimezone(timezone.utc)


def reconstruct(proposal: Mapping[str, Any], deals: list[dict], *, position: Mapping | None,
                currency: str, coverage: Mapping | None = None,
                commands: tuple[Mapping, ...] = ()) -> dict:
    """Reconcile complete position history, including all entry/exit charges."""
    unique: dict[str, dict] = {}
    for deal in deals:
        identity = str(deal.get("deal_id") or "")
        if not identity or identity == "0":
            raise ValueError("missing broker deal identity")
        if identity in unique and unique[identity] != deal:
            raise ValueError("conflicting duplicate broker deal")
        unique[identity] = deal
    rows = sorted(unique.values(), key=lambda d: (instant(d.get("time")), int(d["deal_id"])))
    if not rows:
        raise ValueError("broker history unavailable")
    identifiers = {str(d.get("position_id")) for d in rows}
    if len(identifiers) != 1 or identifiers & {"0", "None", ""}:
        raise ValueError("broker position identity mismatch")
    if coverage is not None and (coverage.get("complete") is not True
                                or int(coverage.get("deal_count", -1)) != len(rows)):
        raise ValueError("broker history incomplete")
    symbols = {str(d["symbol"]).casefold() for d in rows if d.get("symbol")}
    if symbols and symbols != {str(proposal.get("symbol")).casefold()}:
        raise ValueError("broker history symbol mismatch")
    entries = [d for d in rows if str(d.get("entry")) in {"in", "0"}]
    exits = [d for d in rows if str(d.get("entry")) in {"out", "out_by", "1", "3"}]
    if any(str(d.get("entry")) not in {"in", "0", "out", "out_by", "1", "3", "charge"} for d in rows):
        raise ValueError("reversal history requires reconciliation")
    if not entries:
        raise ValueError("opening deal history unavailable")
    opened = sum((number(d.get("volume")) for d in entries), ZERO)
    exited = sum((number(d.get("volume")) for d in exits), ZERO)
    if opened <= 0 or exited > opened or any(number(d.get("volume")) <= 0 for d in entries + exits):
        raise ValueError("broker deal volume mismatch")
    expected = number(proposal.get("executed_volume") or proposal.get("volume"))
    if coverage is None and opened != expected:
        raise ValueError("legacy opening history does not reconcile with fill")
    remaining = opened - exited
    if position is not None and number(position.get("volume")) != remaining:
        raise ValueError("deal history does not reconcile with live position")
    if position is None and remaining != 0:
        raise ValueError("closing deal history incomplete")
    if position is not None and remaining <= 0:
        raise ValueError("position still visible; await a consistent heartbeat")
    first, last = entries[0], exits[-1] if exits else entries[-1]
    expected_side = {"buy": "0", "sell": "1"}.get(str(proposal.get("side", "")).lower())
    if any(d.get("deal_type") is not None and str(d["deal_type"]) != expected_side for d in entries):
        raise ValueError("opening deal direction mismatch")
    opened_at, closed_at = instant(first.get("time")), instant(last.get("time"))
    if closed_at < opened_at:
        raise ValueError("broker close precedes entry")
    totals = {key: sum((number(d.get(key)) for d in rows), ZERO)
              for key in ("profit", "commission", "swap", "fee")}
    net = sum(totals.values(), ZERO)
    reason = str(last.get("reason") or "UNKNOWN").upper()
    reason = {"CLIENT": "manual close", "MOBILE": "manual close (mobile)",
              "WEB": "manual close (web)", "EXPERT": "EA close",
              "SO": "broker stop-out", "ROLLOVER": "broker rollover",
              "VMARGIN": "broker variation margin", "UNKNOWN": "other / broker reason unavailable"}.get(reason, reason)
    for command in commands:
        payload = command.get("payload") or {}
        target_matches = str(payload.get("target_id")) in identifiers | {str(proposal.get("broker_ticket"))}
        accepted = command.get("status") in {"accepted", "reconciled"}
        if (reason == "SL" and target_matches and accepted and command.get("operation") in {"sl", "breakeven"}
                and last.get("sl") is not None and payload.get("value") is not None
                and number(last["sl"]) == number(payload["value"])):
            policy = str(command.get("management_policy") or "")
            if "TRAIL" in policy:
                reason = "SL — trailing management"
            elif command.get("operation") == "breakeven" or policy.startswith("AFTER_TP"):
                reason = "SL — breakeven management"
        if (str(payload.get("target_id")) in identifiers | {str(proposal.get("broker_ticket"))}
                and str(command.get("broker_ticket")) == str(last.get("order_id"))
                and command.get("status") in {"accepted", "reconciled"}):
            reason = "Telegram close" if command.get("operation") == "close" else "approved management action"
    result = {
        "position_id": next(iter(identifiers)), "broker_ticket": proposal.get("broker_ticket"),
        "symbol": proposal.get("symbol"), "side": str(proposal.get("side") or "").upper(),
        "proposal_id": proposal.get("proposal_id"), "command_id": proposal.get("command_id"),
        "analysis_id": proposal.get("analysis_id"), "signal_id": proposal.get("signal_id"),
        "entry_price": str(number(first.get("price"))),
        "average_entry_price": str(sum((number(d["price"]) * number(d["volume"]) for d in entries), ZERO) / opened),
        "exit_price": str(number(last.get("price"))) if exits else None,
        "original_volume": str(opened), "closed_volume": str(exited), "remaining_volume": str(remaining),
        "stop_loss": last.get("sl", (proposal.get("position_snapshot") or {}).get("sl", proposal.get("stop_loss"))),
        "original_stop_loss": first.get("sl", proposal.get("stop_loss")),
        "take_profit": last.get("tp", proposal.get("take_profit")),
        "targets": [{"name": t.get("name"), "price": t.get("price")} for t in (proposal.get("take_profit_plan") or {}).get("targets", [])],
        "opened_at": opened_at.isoformat(), "closed_at": closed_at.isoformat() if remaining == 0 else None,
        "last_exit_at": closed_at.isoformat() if exits else None,
        "duration_seconds": int((closed_at - opened_at).total_seconds()), "close_reason": reason,
        "gross_pnl": str(totals["profit"]), "commission": str(totals["commission"]),
        "swap": str(totals["swap"]), "fees": str(totals["fee"]), "net_pnl": str(net),
        "currency": currency, "result": "PROFIT" if net > 0 else "LOSS" if net < 0 else "BREAKEVEN",
        "state": "CLOSED" if remaining == 0 else "PARTIAL_CLOSE" if exits else "OPEN",
        "deal_ids": sorted(unique), "exit_deal_ids": [str(d["deal_id"]) for d in exits],
        "pnl_percent": None, "pnl_percent_basis": None, "source": "MT5 broker deal history",
    }
    # Only an explicitly captured pre-entry account-equity basis is valid.
    basis = proposal.get("account_equity_at_entry")
    if basis is not None and number(basis) > 0:
        result.update(pnl_percent=str(net / number(basis) * 100), pnl_percent_basis="account equity at entry")
    return result


def format_trade_result(result: Mapping) -> str:
    closed = result["state"] == "CLOSED"
    minutes, seconds = divmod(int(result["duration_seconds"]), 60)
    targets = ", ".join(f"{t['name']}: {t['price']}" for t in result.get("targets", [])) or str(result.get("take_profit") or "not available")
    money = lambda key: f"{number(result[key]):+.2f} {result['currency']}"
    return "\n".join([
        f"MONATISE {'CLOSED TRADE' if closed else 'PARTIAL CLOSE — POSITION STILL OPEN'}",
        f"{result['symbol']} | {result['side']} | {'Final result' if closed else 'Realized result so far'}: {result['result']}",
        f"Position: {result['position_id']} | Ticket: {result.get('broker_ticket') or result['position_id']}",
        f"Entry: {result['entry_price']} | {'Final exit' if closed else 'Latest exit'}: {result['exit_price']}",
        f"Size: {result['original_volume']} lots | Closed: {result['closed_volume']} | Remaining: {result['remaining_volume']}",
        f"SL: {result.get('stop_loss') or 'not available'} | Original SL: {result.get('original_stop_loss') or 'not available'}",
        f"TP: {targets}",
        f"Opened: {result['opened_at']}",
        f"{'Closed' if closed else 'Latest partial'}: {result.get('closed_at') or result['last_exit_at']}",
        f"Duration: {minutes}m {seconds}s | Reason: {result['close_reason']}",
        f"Gross P/L: {money('gross_pnl')}", f"Commission: {money('commission')}",
        f"Swap/financing: {money('swap')} | Other deal fees: {money('fees')}",
        f"NET REALIZED P/L: {money('net_pnl')}",
        (f"P/L: {number(result['pnl_percent']):+.3f}% of {result['pnl_percent_basis']}" if result.get('pnl_percent') is not None
         else "P/L %: unavailable — no verified entry-equity basis"),
        "Includes entry and exit charges; source: MT5 broker history.",
        f"Trace: {result['proposal_id']} | Deals: {','.join(result['exit_deal_ids'])}",
    ])


class TradeAccountingService:
    def __init__(self, master):
        self.master, self.store = master, master.repository.store

    async def reconcile(self, snapshot, now, *, previously_closed=()):
        if not all(snapshot.get(key) for key in ("identity_match", "terminal_connected", "ea_attached")):
            return
        proposals = await self.master.repository.proposals()
        policies = {p["proposal_id"]: p.get("management_policy") for p in proposals}
        commands = tuple({**r.value, "management_policy": policies.get(r.value.get("proposal_id"))}
                         for r in await self.store.list_namespace(self.master.repository.COMMANDS))
        for proposal in proposals:
            if proposal.get("kind") != "open_trade" or not proposal.get("broker_ticket") or not proposal.get("approved_by"):
                continue
            previous = proposal.get("position_snapshot") or {}
            identifier = str(previous.get("identifier") or proposal["broker_ticket"])
            position = next((p for p in snapshot.get("positions", []) if str(p.get("identifier") or p.get("ticket")) == identifier), None)
            deals = [d for d in snapshot.get("deals", []) if str(d.get("position_id")) == identifier]
            key = hashlib.sha256(f"{snapshot['account_id']}|{snapshot['server']}|{identifier}".encode()).hexdigest()
            current = await self.store.get(ACCOUNTS, key)
            try:
                coverage = (snapshot.get("deal_history_coverage") or {}).get(identifier)
                if snapshot.get("deal_history_version") == 1 and coverage is None:
                    raise ValueError("broker history coverage unavailable")
                result = reconstruct(proposal, deals, position=position, currency=snapshot["currency"], coverage=coverage, commands=commands)
                # Repeated heartbeats and repeated deal IDs cannot create a new notification.
                exits = result["exit_deal_ids"]
                event_id = hashlib.sha256(f"{key}|{result['state']}|{','.join(exits)}".encode()).hexdigest()
                historical = (current.value.get("historical_import", False) if current else proposal["proposal_id"] in previously_closed)
                previous_result = (current.value.get("result") or {}) if current else {}
                changed_exit = (previous_result.get("exit_deal_ids") != exits
                                or previous_result.get("state") != result["state"])
                if exits and not historical and changed_exit:
                    event = await self.store.get(NOTIFICATIONS, event_id)
                    if event is None:
                        await self.store.put(NOTIFICATIONS, event_id, {"status": "pending", "result": result,
                            "created_at": now.isoformat(), "event_id": event_id}, expected_version=0)
                value = {"status": "reconciled", "result": result, "updated_at": now.isoformat(), "historical_import": historical}
                if current is None or current.value.get("result") != result or current.value.get("status") != "reconciled":
                    await self.store.put(ACCOUNTS, key, value, expected_version=current.version if current else 0)
                    await self.master.repository.audit("trade_accounting_reconciled", proposal["proposal_id"], result)
            except ValueError as exc:
                reason = str(exc)
                if current is None or current.value.get("reason") != reason:
                    await self.store.put(ACCOUNTS, key, {"status": "awaiting_history", "reason": reason,
                        "historical_import": current.value.get("historical_import", False) if current else proposal["proposal_id"] in previously_closed,
                        "proposal_id": proposal["proposal_id"], "position_id": identifier, "updated_at": now.isoformat()},
                        expected_version=current.version if current else 0)
                    await self.master.repository.audit("trade_accounting_pending", proposal["proposal_id"], {"reason": reason})
            except RuntimeError:
                continue  # A concurrent heartbeat owns the record; deterministic event IDs persist.

    async def publish_pending(self, notifier):
        if notifier is None:
            return
        for record in await self.store.list_namespace(NOTIFICATIONS):
            value = dict(record.value)
            if value.get("status") != "pending":
                continue
            value.update(status="sending", attempted_at=datetime.now(timezone.utc).isoformat())
            try:
                claimed = await self.store.put(NOTIFICATIONS, record.key, value, expected_version=record.version)
            except RuntimeError:
                continue
            try:
                receipt = await notifier.command_response(format_trade_result(value["result"]))
                if not isinstance(receipt, int) or isinstance(receipt, bool) or receipt <= 0:
                    raise ValueError("Telegram receipt missing")
                value.update(status="published", telegram_message_id=receipt,
                             published_at=datetime.now(timezone.utc).isoformat())
            except Exception as exc:
                value.update(status="outcome_unknown", error_type=type(exc).__name__)
            await self.store.put(NOTIFICATIONS, record.key, value, expected_version=claimed.version)
            await self.master.repository.audit("trade_result_notification", value["result"]["proposal_id"],
                {"event_id": record.key, "status": value["status"], "telegram_message_id": value.get("telegram_message_id")})
