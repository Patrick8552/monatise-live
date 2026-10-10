from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from monatise.application.hierarchy.policy import SHARED_TIMEFRAME_POLICY as TF
from monatise.engines.fibonacci_liquidity import FibonacciAnchorConstraint, FibonacciDirection
from monatise.engines.market_structure import MarketStructureEngine, MarketStructureRequest
from monatise.engines.market_structure.models import BreakType
from monatise.research.gold_fib import POLICY_ID
from monatise.research.gold_fib.models import FrozenRecord, digest


BULL = {BreakType.BULLISH_BOS, BreakType.BULLISH_CHOCH}
BEAR = {BreakType.BEARISH_BOS, BreakType.BEARISH_CHOCH}
FAILED = {BreakType.FAILED_BULLISH_BREAK, BreakType.FAILED_BEARISH_BREAK}


def pivot_known(rows, index, window):
    """Canonical plateau end is index. All right-side bars must actually be known."""
    if index + window >= len(rows):
        return None
    return max(c.received_at for c in rows[index:index + window + 1])


@dataclass(frozen=True)
class H1StructuralEpisode:
    record: FrozenRecord


class H1StructuralEpisodeAdapter:
    """Causal prefix ledger from authentic price-only structure events.

    Contextual inputs affect confidence/state, not the core pivot/break detector.
    The final selector still uses the exact full Gold H1 parent assessment.
    No historical observation times are inferred from eventual OHLC timestamps.
    """

    def assess(self, parent):
        context, snapshot, layer = parent.objects()
        rows = tuple(c for c in snapshot.candles if c.is_final)
        window = layer.structure.metadata.get("swing_window", 3)
        confirmations = layer.structure.metadata.get("confirmation_closes", 1)
        active = None
        seen = set()
        events = []
        latest_unresolved = None
        termination = None
        for count in range(window * 2 + 3, len(rows) + 1):
            prefix = rows[:count]
            cutoff = max(c.received_at for c in prefix)
            market = replace(layer.market, candles=layer.market.candles[:count],
                price=prefix[-1].close)
            assessment = MarketStructureEngine().assess(MarketStructureRequest(
                market, swing_window=window, confirmation_closes=confirmations))
            for event in assessment.events:
                if not event.confirmed:
                    continue
                side = "long" if event.break_type in BULL else "short" if event.break_type in BEAR else "failed"
                key = (side, prefix[event.candle_index].candle_id, event.level)
                if key in seen:
                    continue
                seen.add(key)
                if side == "failed":
                    if active and event.candle_index >= active["event_index"]:
                        termination = "confirmed_failed_break"
                        events.append({"type": "terminated", "reason": termination, "event": event, "known_at": cutoff})
                        active = None
                    continue
                pivots = assessment.swing_highs if side == "long" else assessment.swing_lows
                matches = [p for p in pivots if p[0] < event.candle_index and p[1] == event.level]
                broken = max(matches, default=None, key=lambda p: p[0])
                known = pivot_known(prefix, broken[0], window) if broken else None
                event_open = prefix[event.candle_index].open_time
                confirm_end = event.candle_index + confirmations - 1
                causal = known is not None and known < event_open and confirm_end < count
                if not causal:
                    latest_unresolved = {"index": event.candle_index, "reason": "broken_pivot_not_known_before_break", "event": event}
                    events.append({"type": "quarantined", **latest_unresolved, "known_at": cutoff})
                    continue
                if latest_unresolved and event.candle_index >= latest_unresolved["index"]:
                    latest_unresolved = None
                if active and event.candle_index < active["event_index"]:
                    continue
                broken_id = prefix[broken[0]].candle_id
                family = (side, broken_id)
                if active and (active["direction"], active["broken_pivot_id"]) == family:
                    events.append({"type": "repeated_same_family", "event": event})
                    continue
                origins = assessment.swing_lows if side == "long" else assessment.swing_highs
                origins = [p for p in origins if p[0] < event.candle_index and pivot_known(prefix, p[0], window) < event_open]
                origin = max(origins, default=None, key=lambda p: p[0])
                active = {
                    "direction": side, "event_index": event.candle_index,
                    "event_id": digest({"bar": prefix[event.candle_index].candle_id, "level": event.level, "direction": side}),
                    "event": event, "broken_pivot_id": broken_id, "broken_pivot": broken,
                    "broken_pivot_known_at": known,
                    "event_known_at": max(c.received_at for c in prefix[event.candle_index:confirm_end + 1]),
                    "origin": origin, "origin_id": prefix[origin[0]].candle_id if origin else None,
                    "origin_known_at": pivot_known(prefix, origin[0], window) if origin else None,
                }
                active["h1_episode_id"] = "h1-" + digest({
                    "instrument": context.identity.symbol, "direction": side,
                    "start_event": active["event_id"], "broken": broken_id,
                    "origin": active["origin_id"], "policy": POLICY_ID,
                })[:24]
                termination = None
                events.append({"type": "started_or_superseded", "episode": active.copy()})
            if active and active["origin"]:
                ai, ap = active["origin"]
                if count - 1 > ai and (prefix[-1].low <= ap if active["direction"] == "long" else prefix[-1].high >= ap):
                    termination = "H1_origin_breached"
                    events.append({"type": "terminated", "reason": termination, "bar": prefix[-1].candle_id})
                    active = None
        reason = termination or "no_causal_active_event" if active is None else None
        if latest_unresolved and (not active or latest_unresolved["index"] >= active["event_index"]):
            reason = "latest_event_unresolvable"
        if active and active["direction"] != context.direction:
            reason = "active_episode_direction_mismatch"
        return H1StructuralEpisode(FrozenRecord.from_value({
            "policy_id": POLICY_ID, "h1_context_id": parent.context_id,
            "h1_snapshot_hash": parent.record.sha256, "cutoff": parent.cutoff,
            "active": active, "reason": reason, "events": events,
        }))


@dataclass(frozen=True)
class AnchorSelection:
    record: FrozenRecord
    constraint: FibonacciAnchorConstraint | None = None


class GoldH1StructuralLegSelector:
    def select(self, parent, episode):
        context, snapshot, layer = parent.objects()
        rows = tuple(c for c in snapshot.candles if c.is_final)
        data = episode.record.data
        active = data["active"]
        result = {
            "policy_id": POLICY_ID, "anchor_timeframe": TF.analysis,
            "h1_context_id": parent.context_id, "h1_snapshot_hash": parent.record.sha256,
            "h1_episode_id": active.get("h1_episode_id") if active else None,
            "episode_identifiable": active is not None and data["reason"] is None,
            "valid_a": False, "valid_b": False, "A": None, "B": None,
            "episode_provenance": data, "reason": data["reason"],
        }
        def reject(reason):
            result["reason"] = reason
            return AnchorSelection(FrozenRecord.from_value(result))
        if data["h1_context_id"] != parent.context_id or data["h1_snapshot_hash"] != parent.record.sha256:
            return reject("H1_EPISODE_PARENT_MISMATCH")
        if not result["episode_identifiable"]:
            return reject("H1_EPISODE_UNAVAILABLE:" + str(data["reason"]))
        if active["origin"] is None:
            return reject("H1_ORIGIN_UNAVAILABLE")
        ai, ap = active["origin"]
        long = active["direction"] == "long"
        starts = layer.structure.swing_lows if long else layer.structure.swing_highs
        if (ai, ap) not in starts:
            return reject("H1_ORIGIN_NOT_IN_PARENT")
        window = layer.structure.metadata.get("swing_window", 3)
        result["A"] = self._endpoint(rows, ai, ap, window)
        result["valid_a"] = True
        ei = active["event_index"]
        opposing = layer.structure.swing_lows if long else layer.structure.swing_highs
        boundary = min([i for i, _ in opposing if i > ei] or [len(rows)])
        ends = layer.structure.swing_highs if long else layer.structure.swing_lows
        options = [p for p in ends if ei <= p[0] < boundary]
        if not options:
            interval = range(ei, boundary)
            if not interval:
                return reject("H1_ENDPOINT_UNAVAILABLE")
            extreme_index = (max if long else min)(interval, key=lambda i: rows[i].high if long else rows[i].low)
            if extreme_index + window >= len(rows):
                return reject("B_UNCONFIRMED_AT_PARENT_CUTOFF")
            return reject("H1_ENDPOINT_UNAVAILABLE")
        bi, bp = min(options, key=lambda p: p[0])
        result["B"] = self._endpoint(rows, bi, bp, window)
        if result["B"]["known_at"] > parent.cutoff:
            return reject("B_UNCONFIRMED_AT_PARENT_CUTOFF")
        span = rows[ai:bi + 1]
        if bi <= ai or (bp <= ap if long else bp >= ap) or (max(c.high for c in span) != bp or min(c.low for c in span) != ap if long else min(c.low for c in span) != bp or max(c.high for c in span) != ap):
            return reject("H1_LEG_GEOMETRY_REJECTED")
        result.update(valid_b=True, reason=None, range_usd=abs(bp - ap))
        result["h1_leg_id"] = "leg-" + digest({"episode": active["h1_episode_id"], "A": {k: result["A"][k] for k in ("candle_id", "content_hash")}, "B": {k: result["B"][k] for k in ("candle_id", "content_hash")}})[:24]
        constraint = FibonacciAnchorConstraint(context.identity.symbol, TF.analysis,
            FibonacciDirection.BULLISH if long else FibonacciDirection.BEARISH,
            ai, ap, bi, bp, result["h1_leg_id"])
        return AnchorSelection(FrozenRecord.from_value(result), constraint)

    @staticmethod
    def _endpoint(rows, i, price, window):
        return {"index": i, "price": price, "candle_id": rows[i].candle_id,
            "open_time": rows[i].open_time, "close_time": rows[i].scheduled_close_time,
            "content_hash": rows[i].content_hash, "known_at": pivot_known(rows, i, window),
            "confirming_candles": [{"id": c.candle_id, "hash": c.content_hash, "known_at": c.received_at} for c in rows[i:i + window + 1]]}
