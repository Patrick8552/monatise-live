from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from math import isfinite

from monatise.application.gold_analysis import GoldLayerEvaluator, GoldPolicy
from monatise.application.hierarchy.adapter import target_independent_reasons
from monatise.application.hierarchy.models import StrategicState
from monatise.application.hierarchy.policy import SHARED_TIMEFRAME_POLICY as TF
from monatise.application.take_profit import timestamp
from monatise.research.gold_fib import POLICY_ID
from monatise.engines.market_data.models import DataStatus


def encode(value):
    if is_dataclass(value):
        return encode(asdict(value))
    if isinstance(value, (datetime, Decimal)):
        return str(value.isoformat() if isinstance(value, datetime) else value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [encode(v) for v in value]
    return value


def canonical_json(value):
    return json.dumps(encode(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


@dataclass(frozen=True)
class FrozenRecord:
    """Only immutable JSON is stored; consumers get detached decoded copies."""

    payload: str

    @classmethod
    def from_value(cls, value):
        return cls(canonical_json(value))

    @property
    def data(self):
        return json.loads(self.payload)

    @property
    def sha256(self):
        return hashlib.sha256(self.payload.encode()).hexdigest()


@dataclass(frozen=True)
class H1ParentSnapshot:
    context_id: str
    cutoff: datetime
    source_candle_id: str
    record: FrozenRecord
    _context: object = field(repr=False, compare=False)
    _snapshot: object = field(repr=False, compare=False)
    _layer: object = field(repr=False, compare=False)

    @classmethod
    def capture(cls, context, snapshot, layer):
        if context.identity.source_timeframe != TF.analysis or snapshot.timeframe != TF.analysis:
            raise ValueError("H1 parent required")
        if context.identity.source_candle_id != snapshot.latest_finalized.candle_id:
            raise ValueError("H1 parent source mismatch")
        if context.evaluated_at != snapshot.observed_at:
            raise ValueError("H1 capture must occur at context creation")
        final = tuple(c for c in snapshot.candles if c.is_final)
        if tuple(c.timestamp for c in layer.market.candles) != tuple(c.open_time.isoformat() for c in final):
            raise ValueError("H1 layer snapshot mismatch")
        if any(c.received_at > context.evaluated_at or c.scheduled_close_time > context.evaluated_at for c in final):
            raise ValueError("H1 future evidence")
        objects = copy.deepcopy((context, snapshot, layer))
        return cls(context.identity.context_id, context.evaluated_at,
            context.identity.source_candle_id, FrozenRecord.from_value(objects), *objects)

    def objects(self):
        if digest((self._context, self._snapshot, self._layer)) != self.record.sha256:
            raise ValueError("H1 frozen capture changed")
        return copy.deepcopy((self._context, self._snapshot, self._layer))


@dataclass(frozen=True)
class GoldSetupSeed:
    seed_id: str
    association_id: str
    observed_at: datetime
    parent: H1ParentSnapshot
    record: FrozenRecord
    _contexts: tuple = field(repr=False, compare=False)
    _prepared: object = field(repr=False, compare=False)
    _layers: tuple = field(repr=False, compare=False)

    @classmethod
    def create(cls, *, contexts, parent, prepared, layers, observed_at, session_close,
               calendar_hash, broker_identity, broker_units, timestamp_policy):
        if len(contexts) != 5 or any(c is None for c in contexts):
            raise ValueError("seed_rejected:invalid_parent_chain")
        observed_at, session_close = timestamp(observed_at), timestamp(session_close)
        reasons = target_independent_reasons(contexts, strategy_version=GoldPolicy().strategy,
            requested_at=observed_at, risk_expires_at=prepared.expires_at)
        identities = [c.identity for c in contexts]
        expected = [None, *[i.context_id for i in identities[:-1]]]
        if len(contexts) != 5 or [i.parent_context_id for i in identities] != expected:
            reasons.append("invalid_parent_chain")
        if [i.source_timeframe for i in identities] != ["macro", *TF.timeframes[:-1]]:
            reasons.append("invalid_timeframe_chain")
        if any(i.symbol != "XAU/USD" for i in identities):
            reasons.append("invalid_gold_identity")
        if set(dict(layers)) != {"4h", "1h", "15m", "5m", "1m"}:
            raise ValueError("seed_rejected:required_layers_unavailable")
        if any(l.market.symbol != "XAU/USD" or l.market.interval != tf for tf, l in layers):
            reasons.append("layer_identity_mismatch")
        if any(not isfinite(float(getattr(prepared, k))) for k in ("reference_entry", "final_stop", "entry_zone_low", "entry_zone_high", "minimum_reward_to_risk")):
            reasons.append("nonfinite_risk_inputs")
        if any(c.evaluated_at > observed_at or (c.source_close_time is not None and c.source_close_time > c.evaluated_at) for c in contexts):
            reasons.append("future_context_evidence")
        if any(l.market.quality.status is not DataStatus.READY for _, l in layers):
            reasons.append("technical_data_not_ready")
        side = prepared.direction
        if side not in {"long", "short"} or contexts[2].state is not (StrategicState.LONG_ONLY if side == "long" else StrategicState.SHORT_ONLY):
            reasons.append("H1_direction_mismatch")
        if any(c.direction != side for c in contexts[2:]):
            reasons.append("direction_mismatch")
        if parent.context_id != contexts[2].identity.context_id:
            reasons.append("H1_parent_mismatch")
        parent.objects()
        if not contexts[3].evidence.get("gold_pattern", {}).get("confirmed"):
            reasons.append("gold_pattern_unconfirmed")
        if not contexts[4].evidence.get("confirmed_break"):
            reasons.append("gold_trigger_unconfirmed")
        if session_close <= observed_at or not calendar_hash or timestamp_policy != "reviewed_manifest":
            reasons.append("uncertified_or_closed_session")
        units_ok = all(type(broker_units.get(k)) in (int, float)
            and isfinite(broker_units[k]) and broker_units[k] > 0
            for k in ("point", "tick_size"))
        spread_ok = type(broker_units.get("spread_price")) in (int, float) and isfinite(broker_units["spread_price"]) and broker_units["spread_price"] >= 0
        if not broker_identity or not units_ok or not spread_ok:
            reasons.append("invalid_broker_units_or_identity")
        price = dict(layers)[TF.entry].market.price
        if price is None or not isfinite(price) or price <= 0:
            reasons.append("observed_price_unavailable")
        if prepared.reference_entry <= 0 or not prepared.entry_zone_low <= prepared.reference_entry <= prepared.entry_zone_high:
            reasons.append("entry_zone_mismatch")
        sign = 1 if side == "long" else -1
        if sign * (prepared.reference_entry - prepared.final_stop) <= 0:
            reasons.append("invalid_stop_geometry")
        if reasons:
            raise ValueError("seed_rejected:" + ",".join(reasons))
        # Do not allow a caller to forge a narrower stop or a fabricated entry
        # preparation and then obtain a research-valid target plan.
        verifier = GoldLayerEvaluator()
        verifier.broker_units = broker_units
        authentic = verifier.prepare_entry_stop(contexts[4], observed_at,
            entry_layer=dict(layers)["1m"], stop_layer=dict(layers)["15m"])
        if digest(authentic) != digest(prepared):
            raise ValueError("seed_rejected:entry_stop_not_canonical")
        association = digest({"h1": parent.context_id, "m15": identities[3].context_id, "m5": identities[4].context_id, "policy": POLICY_ID})
        copied_contexts, copied_prepared, copied_layers = copy.deepcopy((tuple(contexts), prepared, tuple(layers)))
        payload = {
            "policy_id": POLICY_ID, "source_contract": GoldPolicy().strategy,
            "h1_context_id": parent.context_id, "h1_snapshot_hash": parent.record.sha256,
            "m15_setup_id": identities[3].context_id, "m5_trigger_id": identities[4].context_id,
            "contexts": copied_contexts, "prepared": copied_prepared,
            "layer_hashes": {tf: digest(l) for tf, l in copied_layers},
            "observed_at": observed_at, "observed_price": price,
            "calendar_hash": calendar_hash, "broker_identity": broker_identity,
            "broker_units": broker_units, "session_close": session_close,
            "expires_at": min(session_close, prepared.expires_at, *[c.expires_at for c in contexts]),
        }
        record = FrozenRecord.from_value(payload)
        return cls("seed-" + record.sha256[:24], association, observed_at, parent, record,
            copied_contexts, copied_prepared, copied_layers)

    def objects(self):
        data = self.record.data
        if encode(self._contexts) != data["contexts"] or encode(self._prepared) != data["prepared"] or {tf: digest(l) for tf, l in self._layers} != data["layer_hashes"]:
            raise ValueError("immutable_seed_changed")
        self.parent.objects()
        return copy.deepcopy((self._contexts, self._prepared, self._layers))
