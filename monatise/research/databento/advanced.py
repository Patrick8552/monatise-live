"""Disabled-by-default native CME observations, with no acquisition interface.

Trade-side evidence is used only when supplied by the exchange. Book quantities
are visible resting liquidity, not executions, inventory or institutional intent.
MBO outputs are order events, not certified queue positions or reconstructed books.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal

from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.databento.datasets import InstrumentMetadata

UNDEF = 2**63-1
SCALE = Decimal(10**9)
SCHEMAS = frozenset({"trades", "mbp-1", "mbp-10", "mbo"})


def fixed(value):
    # CL can have negative conventional prices; do not reuse GC's positive-only
    # economic constraint for all futures. Undefined sentinels always reject.
    if type(value) is not int or not -(2**63) < value < UNDEF:
        raise ValueError("native fixed-point price required")
    return Decimal(value)/SCALE


def quantity(value, *, zero=False):
    if type(value) is not int or not (0 if zero else 1) <= value < 2**32-1:
        raise ValueError("bounded native quantity required")
    return value


@dataclass(frozen=True)
class Observation:
    dataset: str
    schema: str
    namespace: str
    publisher_id: int
    instrument_id: int
    raw_symbol: str
    event_ns: int
    receive_ns: int
    sequence: int
    flags: int
    action: str
    record_sha256: str
    payload: tuple
    definition_sha256: str
    execution_eligible: bool = False
    ts_in_delta: int | None = None

    @property
    def index_ns(self):return None if self.flags&8 else self.receive_ns

    @property
    def publisher_send_ns(self):
        return None if self.flags&8 or self.ts_in_delta in (None,-(2**31),2**31-1) else self.receive_ns-self.ts_in_delta


class AdvancedAdapters:
    def __init__(self, *, identity, enabled_schemas=(), mbo_research_reference=None, mbo_snapshot_reference=None):
        if not isinstance(identity, InstrumentMetadata) or identity.dataset != "GLBX.MDP3":
            raise ValueError("reviewed explicit CME instrument metadata required")
        self.enabled = frozenset(enabled_schemas)
        if not self.enabled <= SCHEMAS:
            raise ValueError("unreviewed advanced schema")
        if "mbo" in self.enabled and not mbo_research_reference:
            raise ValueError("explicit MBO research question reference required")
        self.identity = identity
        self.mbo_research_reference = mbo_research_reference
        self.mbo_snapshot_reference = mbo_snapshot_reference
        terms = dict(identity.native_terms)
        self.tick = fixed(int(terms["min_price_increment"]))
        if self.tick <= 0:
            raise ValueError("valid definition tick required")

    def _price(self, value):
        p = fixed(value)
        if p % self.tick or (self.identity.product in {"GC", "OG", "ES", "NQ"} and p <= 0):
            raise ValueError("off-tick or invalid instrument price")
        return str(p)

    def normalize(self, schema, record):
        if schema not in self.enabled:
            raise ValueError("advanced adapter disabled")
        import databento_dbn as dbn
        expected = {"trades": dbn.TradeMsg, "mbp-1": dbn.MBP1Msg,
                    "mbp-10": dbn.MBP10Msg, "mbo": dbn.MBOMsg}[schema]
        if not isinstance(record, expected):
            raise ValueError("native record and schema mismatch")
        from .semantics import flag_eligibility
        quality=flag_eligibility(schema,int(record.flags),reviewed_mbo_snapshot=bool(schema=='mbo' and record.flags&32 and self.mbo_snapshot_reference))
        event=timestamp_ns(record.ts_event)
        empty_snapshot=bool(quality['snapshot_book_seed_eligible'] and str(record.action)=='R' and record.flags&128 and record.ts_recv==2**64-1)
        receive=record.ts_recv if empty_snapshot else timestamp_ns(record.ts_recv)
        if ((record.publisher_id,record.instrument_id) != (self.identity.publisher_id,self.identity.instrument_id)
                or not self.identity.event_ns <= event < self.identity.expiration_ns
                or not empty_snapshot and not self.identity.event_ns <= receive < self.identity.expiration_ns
                or not (quality['ordinary_record_eligible'] or quality['snapshot_book_seed_eligible'])):
            raise ValueError("record identity, lifetime or receive quality mismatch")
        action, side = str(record.action), str(record.side)
        if schema == "trades":
            if action != "T" or side not in {"A", "B", "N"}:
                raise ValueError("unsupported trade correction or side")
            payload = (self._price(record.price), quantity(record.size),
                       {"A":"SELL", "B":"BUY", "N":None}[side])
        elif schema.startswith("mbp-"):
            count = 1 if schema == "mbp-1" else 10
            if len(record.levels) != count:
                raise ValueError("incorrect book depth")
            if action not in {"A", "C", "M", "R", "T", "F", "N"}:
                raise ValueError("unknown book event")
            # T/F book messages remain quotes, never another trade contribution.
            payload = tuple(self._level(level) for level in record.levels)
            self._validate_order(payload)
        else:
            if record.flags & 16:
                raise ValueError("MBP-synthesized events are not individual orders")
            if action not in {"A", "C", "M", "R", "T", "F", "N"} or side not in {"A","B","N"}:
                raise ValueError("unknown MBO event")
            if type(record.order_id) is not int or not 0 <= record.order_id < 2**64-1:
                raise ValueError("invalid order identifier")
            if action in {"A","C","M"} and (not record.order_id or side == "N"):
                raise ValueError("order lifecycle identity required")
            p = None if action in {"R", "N"} else self._price(record.price)
            size = quantity(record.size, zero=action in {"R", "N", "M"})
            payload = (record.order_id, p, size, side,
                       "INFORMATIONAL_FILL_NO_DOUBLE_COUNT" if action == "F" else "ORDER_EVENT")
        return Observation(self.identity.dataset, schema, self.identity.namespace,
            record.publisher_id, record.instrument_id, self.identity.raw_symbol, event, receive,
            record.sequence, record.flags, action, hashlib.sha256(bytes(record)).hexdigest(),
            payload, self.identity.definition_sha256,ts_in_delta=record.ts_in_delta)

    def _level(self, level):
        result = []
        for side in ("bid", "ask"):
            p, size, count = (getattr(level,side+suffix) for suffix in ("_px","_sz","_ct"))
            quantity(size, zero=True); quantity(count, zero=True)
            if p == UNDEF:
                if size or count:
                    raise ValueError("undefined price has resting quantity")
                result.extend((None,0,0))
            else:
                if not size:
                    raise ValueError("priced level without size")
                result.extend((self._price(p),size,count))
        return tuple(result)

    @staticmethod
    def _validate_order(levels):
        for offset, descending in ((0,True),(3,False)):
            prices = [level[offset] for level in levels]
            present = [Decimal(p) for p in prices if p is not None]
            if prices[:len(present)] != [str(p) for p in present]:
                raise ValueError("book has holes")
            if any((a <= b if descending else a >= b) for a,b in zip(present,present[1:])):
                raise ValueError("book prices not strictly ordered")
        bid, ask = levels[0][0], levels[0][3]
        if bid is not None and ask is not None and Decimal(bid) > Decimal(ask):
            raise ValueError("crossed book")


def book_metrics(observation):
    if observation.schema not in {"mbp-1", "mbp-10"}:
        raise ValueError("quote observation required")
    bids = sum(level[1] for level in observation.payload)
    asks = sum(level[4] for level in observation.payload)
    top = observation.payload[0]
    both = top[0] is not None and top[3] is not None
    return {"dataset":observation.dataset,"schema":observation.schema,
            "contract":observation.raw_symbol,"record_sha256":observation.record_sha256,
            "formula_version":"visible-book-metrics-v1", "event_ns":observation.event_ns,
            "spread":str(Decimal(top[3])-Decimal(top[0])) if both else None,
            "visible_bid_quantity":bids,"visible_ask_quantity":asks,
            "imbalance":str(Decimal(bids-asks)/Decimal(bids+asks)) if both and bids+asks else None,
            "bid_concentration":str(Decimal(max(l[1] for l in observation.payload))/bids) if bids else None,
            "ask_concentration":str(Decimal(max(l[4] for l in observation.payload))/asks) if asks else None,
            "executed_volume":None,"institutional_intent":None,
            "limitation":"Visible depth can change through trades, cancellation, replenishment or hidden liquidity; no causal attribution.",
            "trading_eligible":False}


def visible_changes(previous, current):
    if (previous.schema != current.schema or previous.namespace != current.namespace
            or current.receive_ns < previous.receive_ns or previous.schema not in {"mbp-1","mbp-10"}):
        raise ValueError("ordered same-contract book snapshots required")
    changes = {}
    for side,offset in (("B",0),("A",3)):
        before = {l[offset]:l[offset+1] for l in previous.payload if l[offset] is not None}
        after = {l[offset]:l[offset+1] for l in current.payload if l[offset] is not None}
        for p in sorted(before.keys() | after.keys(), key=Decimal):
            delta = after.get(p,0)-before.get(p,0)
            if delta:
                changes[(side,p)] = delta
    return {"net_visible_changes":tuple((side,p,d) for (side,p),d in changes.items()),
            "executed_volume":None,"cause":"UNKNOWN_FROM_SNAPSHOTS",
            "boundary_limitation":"Depth beyond the sampled levels is unobserved."}
