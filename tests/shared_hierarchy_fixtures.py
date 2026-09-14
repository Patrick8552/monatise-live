"""Confirmed hierarchy evidence for tests of downstream approval safeguards."""

from dataclasses import asdict
from datetime import timedelta
from monatise.application.hierarchy.models import EvidenceIdentity
from monatise.application.hierarchy.policy import SHARED_TIMEFRAME_POLICY
from monatise.application.hierarchy.approval import (
    SIGNALS,
    CURRENT,
    requires_shared_hierarchy,
)


async def persist_proof(
    control,
    symbol,
    now,
    *,
    entry="2500",
    stop="2490",
    target="2520",
    direction="LONG",
    identity="test-hierarchy",
    zone=None,
    observed_price=None,
):
    instrument = control._verified_instrument_mapping(symbol)
    if not requires_shared_hierarchy(instrument):
        return {}
    parent = None
    contexts = []
    for tf in ("macro", "4h", "1h", "15m", "5m"):
        context = EvidenceIdentity.create(
            kind=tf,
            symbol=instrument.ftmo_symbol,
            timeframe=tf,
            candle_id=f"{identity}-{tf}",
            parent_id=parent,
            strategy_version="hierarchy-shadow-v1",
        )
        contexts.append(asdict(context))
        parent = context.context_id
    proof = {
        **SHARED_TIMEFRAME_POLICY.metadata(),
        "bundle_id": identity + instrument.ftmo_symbol,
        **({"entry_zone": zone} if zone else {}),
        "contexts": contexts,
        "entry_candle": {
            "timeframe": "1m",
            "candle_id": identity + "-1m",
            "closed_at": now.isoformat(),
        },
    }
    observation = {
        "price": observed_price if observed_price is not None else entry,
        "source": "test",
        "kind": "closed_candle",
        "timeframe": "1m",
        "observed_at": now.isoformat(),
    }
    await control.repository.store.put(
        SIGNALS,
        proof["bundle_id"],
        {
            "evidence": proof,
            "expires_at": (now + timedelta(minutes=15)).isoformat(),
            "symbol": instrument.ftmo_symbol,
            "entry": entry,
            "stop": stop,
            "target": target,
            "direction": direction,
            "market_price_observation": observation,
        },
    )
    await control.repository.store.put(
        CURRENT,
        instrument.ftmo_symbol,
        {"state": "valid", "bundle_id": proof["bundle_id"]},
    )
    return {"evidence_bundle": proof, "market_price_observation": observation}
