"""Bind stock/index approval and execution to the persisted shared hierarchy."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from monatise.application.hierarchy.broker_candles import is_index
from monatise.application.hierarchy.policy import SHARED_TIMEFRAME_POLICY as POLICY

SIGNALS = "shared_hierarchy_signals_v1"
CURRENT = "shared_hierarchy_current_v1"


def requires_shared_hierarchy(instrument: Any) -> bool:
    return instrument.asset_class.value == "stock" or is_index(instrument)


async def validate_shared_evidence(
    store: Any, instrument: Any, evidence: Mapping | None, now: datetime
) -> dict:
    if evidence is not None and not isinstance(evidence, Mapping):
        raise ValueError("malformed shared hierarchy evidence")
    payload = dict(evidence or {})
    proof = payload.get("evidence_bundle") or payload
    if not isinstance(proof, Mapping) or not proof.get("bundle_id"):
        raise ValueError("stock/index signal lacks shared hierarchy evidence")
    for key, expected in POLICY.metadata().items():
        if proof.get(key) != expected:
            raise ValueError("stock/index signal timeframe policy mismatch")
    entry_candle = proof.get("entry_candle")
    if (
        not isinstance(entry_candle, Mapping)
        or entry_candle.get("timeframe") != POLICY.entry
    ):
        raise ValueError("stock/index signal lacks entry refinement evidence")
    contexts = proof.get("contexts")
    if (
        not isinstance(contexts, list)
        or not all(isinstance(c, Mapping) and c.get("context_id") for c in contexts)
        or [c.get("source_timeframe") for c in contexts]
        != ["macro", *POLICY.timeframes[:-1]]
    ):
        raise ValueError("stock/index signal has an incomplete hierarchy")
    for index, context in enumerate(contexts):
        expected_parent = contexts[index - 1]["context_id"] if index else None
        if (
            context.get("parent_context_id") != expected_parent
            or context.get("symbol") != instrument.ftmo_symbol.upper()
        ):
            raise ValueError("stock/index evidence parent or symbol mismatch")
    record = await store.get(SIGNALS, proof["bundle_id"])
    current = await store.get(CURRENT, instrument.ftmo_symbol)
    if record is None or record.value.get("evidence") != dict(proof):
        raise ValueError("shared hierarchy proof is missing or changed")
    if (
        current is None
        or current.value.get("bundle_id") != proof["bundle_id"]
        or current.value.get("state") != "valid"
    ):
        raise ValueError("shared hierarchy setup was invalidated or superseded")
    expiry = datetime.fromisoformat(record.value["expires_at"])
    if expiry.tzinfo is None or now >= expiry:
        raise ValueError("shared hierarchy setup expired")
    return record.value
