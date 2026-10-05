"""Optional GLBX.MDP3 GC adapter. Constructors/replay never open a connection.

Only trades schema contributes traded volume. MBP-1 is quote evidence only.
Unsupported corrections and uncertain gap recovery quarantine derived evidence.
Licensed raw DBN records remain in operator-controlled local storage.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

SCALE = Decimal(1_000_000_000)
UNDEF_PRICE = (1 << 63) - 1
UNDEF_TIMESTAMP = (1 << 64) - 1


def ns_time(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 < value < UNDEF_TIMESTAMP
    ):
        raise ValueError("undefined or invalid timestamp")
    seconds, nanos = divmod(value, 1_000_000_000)
    return datetime.fromtimestamp(seconds, UTC).replace(microsecond=nanos // 1000)


def price(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value == UNDEF_PRICE
        or value <= 0
    ):
        raise ValueError("undefined or invalid fixed-point price")
    return Decimal(value) / SCALE


@dataclass(frozen=True)
class GCDefinition:
    instrument_id: int
    raw_symbol: str
    publisher_id: int
    venue: str
    tick: Decimal
    multiplier: Decimal
    currency: str
    as_of: datetime
    available_at: datetime
    expiry: datetime


def definition(record, *, publishers, now):
    publisher = publishers.get(record.publisher_id)
    if publisher != ("GLBX.MDP3", "XCEC"):
        raise ValueError("unknown or contradictory GC publisher")
    if (
        str(record.instrument_class) != "F"
        or str(record.asset) != "GC"
        or str(record.security_type) != "FUT"
        or record.leg_count != 0
        or str(record.user_defined_instrument) != "N"
        or not re.fullmatch(r"GC[FGHJKMNQUVXZ]\d{1,2}", str(record.raw_symbol))
    ):
        raise ValueError("unsupported GC instrument: outright definition required")
    if str(record.currency) != "USD" or str(record.unit_of_measure) not in {
        "oz",
        "OZS",
        "TROY_OUNCE",
    }:
        raise ValueError("GC currency or units unsupported")
    if (
        price(record.display_factor) != 1
        or price(record.min_price_increment) != Decimal(".1")
        or price(record.unit_of_measure_qty) != 100
    ):
        raise ValueError("GC tick, scale or multiplier contradictory")
    event, received, expiry = (
        ns_time(record.ts_event),
        ns_time(record.ts_recv),
        ns_time(record.expiration),
    )
    if not event <= received <= now < expiry:
        raise ValueError("definition not available point-in-time")
    if str(record.security_update_action) not in {"A", "M"}:
        raise ValueError("deleted or unknown definition")
    return GCDefinition(
        record.instrument_id,
        str(record.raw_symbol),
        record.publisher_id,
        "XCEC",
        Decimal(".1"),
        Decimal(100),
        "USD",
        event,
        received,
        expiry,
    )


class GCReplay:
    """One explicitly selected contract/session; bounded, fail-closed cache.

    Exact duplicate identity includes schema, sequence, event, price and size.
    CME packet sequence numbers are NOT assumed contiguous in filtered trades.
    A gap must come from transport diagnostics; reordering is quarantined.
    """

    def __init__(self, *, publishers, capacity=50000):
        if not 10 <= capacity <= 500000:
            raise ValueError("invalid bounded replay capacity")
        self.publishers = dict(publishers)
        self.capacity = capacity
        self.definitions = {}
        self.contract = None
        self.records = deque()
        self.seen = set()
        self.quote = None
        self.statistics = {}
        self.gaps = set()
        self.session = None
        self.last_event = None
        self.last_received = None
        self.coverage = None

    def add_definition(self, record, *, now):
        try:
            value = definition(record, publishers=self.publishers, now=now)
        except ValueError:
            if self.contract and record.instrument_id == self.contract.instrument_id:
                self.mark_gap("selected_contract_definition_rejected")
            raise
        if (
            self.contract
            and value.instrument_id == self.contract.instrument_id
            and value != self.contract
        ):
            self.mark_gap("selected_contract_definition_changed")
        if value.instrument_id not in self.definitions and len(self.definitions) >= 256:
            raise ValueError("definition cache capacity exceeded")
        self.definitions[value.instrument_id] = value
        return value

    def select(self, instrument_id, *, now, session_open, session_close):
        value = self.definitions.get(instrument_id)
        if value is None or not value.available_at <= now < value.expiry:
            raise ValueError(
                "contract selection requires point-in-time outright definition"
            )
        if (
            any(t.tzinfo is None for t in (now, session_open, session_close))
            or not session_open <= now < session_close
        ):
            raise ValueError("verified COMEX session required")
        if self.contract != value or self.session != (session_open, session_close):
            self.records.clear()
            self.seen.clear()
            self.quote = None
            self.statistics.clear()
            self.gaps.clear()
            self.last_event = self.last_received = None
            self.coverage = None
        self.contract, self.session = value, (session_open, session_close)

    def complete_replay(self, *, covered_from, covered_to, now):
        """Called only after a verified replay envelope has been fully consumed.

        A local fixture/DBN loader is responsible for attesting the retrieval
        window, including empty intervals. First/last trades cannot prove it.
        Live end-of-replay watermark verification is not yet certified.
        """
        if (
            self.session is None
            or self.gaps
            or covered_from != self.session[0]
            or not covered_from < covered_to <= now
            or (self.last_received and covered_to < self.last_received)
        ):
            raise ValueError("incomplete or quarantined replay envelope")
        self.coverage = (covered_from, covered_to)

    def mark_gap(self, reason):
        self.gaps.add(reason)
        self.quote = None

    def ingest(self, schema, record, *, now):
        try:
            return self._ingest(schema, record, now=now)
        except (ValueError, TypeError, AttributeError, IndexError):
            self.mark_gap("record_quality_rejected")
            raise

    def _ingest(self, schema, record, *, now):
        if (
            self.contract is None
            or record.instrument_id != self.contract.instrument_id
            or record.publisher_id != self.contract.publisher_id
        ):
            raise ValueError("record contract/publisher mismatch")
        event, received = ns_time(record.ts_event), ns_time(record.ts_recv)
        if (
            not self.contract.available_at <= received <= now
            or not event <= received
            or not self.session[0] <= event < self.session[1]
        ):
            raise ValueError("record availability/session mismatch")
        if getattr(record, "flags", 0) & 8:
            self.mark_gap("bad_receive_timestamp")
            raise ValueError("unreliable receive timestamp")
        if schema == "trades":
            p, size = price(record.price), record.size
            if (
                isinstance(size, bool)
                or not isinstance(size, int)
                or not 0 < size < (1 << 32) - 1
            ):
                raise ValueError("invalid trade size")
            if p % self.contract.tick:
                raise ValueError("trade price off contract tick")
            key = (schema, record.sequence, record.ts_event, record.price, size)
            if str(record.action) != "T":
                self.mark_gap("unsupported_trade_correction")
                return False
            if key in self.seen:
                return False
            if self.last_event is not None and event < self.last_event:
                self.mark_gap("out_of_order_trade")
                return False
            if len(self.records) >= self.capacity:
                self.mark_gap("bounded_cache_overflow")
                return False
            side = str(record.side)
            if side not in {"A", "B", "N"}:
                raise ValueError("unknown trade-side encoding")
            self.records.append((key, event, received, p, size, side))
            self.seen.add(key)
            self.last_event, self.last_received = event, received
            return True
        if schema == "mbp-1":
            # Trade actions also appear here. They NEVER contribute volume.
            level = record.levels[0]
            bid, ask = price(level.bid_px), price(level.ask_px)
            if (
                bid > ask
                or (ask - bid) > Decimal(5)
                or bid % self.contract.tick
                or ask % self.contract.tick
            ):
                raise ValueError("crossed, wide or off-tick GC quote")
            if level.bid_sz <= 0 or level.ask_sz <= 0:
                raise ValueError("one-sided GC quote")
            if self.quote and received < self.quote["as_of"]:
                self.mark_gap("out_of_order_quote")
                return False
            self.quote = {
                "bid": bid,
                "ask": ask,
                "mid": (bid + ask) / 2,
                "as_of": received,
                "event_at": event,
            }
            return True
        if schema == "statistics":
            # Preserve publication and reference times independently. OI is
            # daily context; an update must never imply live dealer inventory.
            key = (str(record.stat_type), record.ts_ref)
            if len(self.statistics) >= 128 and key not in self.statistics:
                self.mark_gap("statistics_cache_overflow")
                return False
            self.statistics[key] = {
                "stat_type": str(record.stat_type),
                "quantity": record.quantity,
                "reference_at": ns_time(record.ts_ref),
                "published_at": received,
                "update_action": str(record.update_action),
            }
            return True
        raise ValueError("schema unsupported")

    def snapshot(self, *, now, max_age=timedelta(seconds=10)):
        unavailable = {
            "status": "unavailable",
            "reasons": sorted(self.gaps),
            "direction": None,
        }
        if (
            self.contract is None
            or not self.records
            or not self.quote
            or self.gaps
            or self.coverage is None
        ):
            return {**unavailable, "reason": "missing_or_quarantined_gc_evidence"}
        if not self.session[0] <= now < min(self.session[1], self.contract.expiry):
            return {**unavailable, "reason": "gc_session_or_contract_expired"}
        times = [
            self.coverage[1],
            self.last_event,
            self.last_received,
            self.quote["event_at"],
            self.quote["as_of"],
        ]
        if any(not timedelta(0) <= now - t <= max_age for t in times):
            return {**unavailable, "reason": "stale_or_future_gc_evidence"}
        profile = Counter()
        total, known, cvd, notional = 0, 0, 0, Decimal(0)
        for _, _, _, p, size, side in self.records:
            total += size
            notional += p * size
            profile[p] += size
            if side != "N":
                known += size
                # Databento A is sell aggressor, B is buy aggressor.
                cvd += size if side == "B" else -size
        return {
            "status": "usable",
            "symbol": "XAU/USD",
            "strategy_version": "xauusd-technical-v1",
            "dataset": "GLBX.MDP3",
            "publisher_id": self.contract.publisher_id,
            "contract": self.contract.raw_symbol,
            "instrument_id": self.contract.instrument_id,
            "units": "USD_per_troy_ounce",
            "multiplier": str(self.contract.multiplier),
            "volume_kind": "exchange_traded_contracts",
            "volume": total,
            "vwap": str(notional / total),
            "poc": str(max(profile, key=lambda p: (profile[p], -p))),
            "profile": {str(p): v for p, v in sorted(profile.items())},
            "cvd_known_side": cvd,
            "side_coverage": known / total,
            "unknown_side_volume": total - known,
            "cvd_complete": known == total,
            "absorption": None,
            "direction": None,
            "quote": {
                k: v.isoformat() if isinstance(v, datetime) else str(v)
                for k, v in self.quote.items()
            },
            "as_of": min(times).isoformat(),
            "expires_at": min(
                min(times) + max_age, self.session[1], self.contract.expiry
            ).isoformat(),
            "coverage_from": self.coverage[0].isoformat(),
            "coverage_to": self.coverage[1].isoformat(),
            "session_open": self.session[0].isoformat(),
            "session_close": self.session[1].isoformat(),
            "roll_policy": "explicit_point_in_time_contract_v1",
        }


class DatabentoGoldAdapter:
    """Reusable replay/cache provider; SDK client creation is explicit opt-in.

    No environment loader or background job opens paid streams automatically.
    Operator injects verified publisher metadata and selected outright IDs.
    Reconnects quarantine until a new complete replay/session is supplied.
    """

    def __init__(self, replay, *, client_factory=None):
        self.replay = replay
        self.client_factory = client_factory
        self.client = None

    async def snapshot(self, instrument, *, now):
        return self.replay.snapshot(now=now)

    @staticmethod
    def sdk_client(api_key):
        import databento as db  # optional; only on separately authorized use

        return db.Live(key=api_key, reconnect_policy="none")

    async def stream(self, *, api_key, authorized=False, duration_seconds=60):
        if (
            not authorized
            or not 1 <= duration_seconds <= 300
            or self.replay.contract is None
        ):
            raise ValueError(
                "explicit live authorization, bounded duration and selected GC required"
            )
        if self.client is not None:
            raise ValueError("reuse the running Gold stream")
        queue = asyncio.Queue(maxsize=2048)
        loop = asyncio.get_running_loop()
        client = (self.client_factory or self.sdk_client)(api_key)
        self.client = client

        def enqueue(record):
            try:
                queue.put_nowait(record)
            except asyncio.QueueFull:
                self.replay.mark_gap("stream_backpressure")

        # SDK callback runs on another thread. Schedule only a bounded number
        # of deliveries; a semaphore guards the event-loop callback backlog.
        import threading

        pending = threading.BoundedSemaphore(2048)
        overflow_notified = threading.Event()

        def callback(record):
            if not pending.acquire(blocking=False):
                if not overflow_notified.is_set():
                    overflow_notified.set()
                    loop.call_soon_threadsafe(
                        self.replay.mark_gap, "callback_backpressure"
                    )
                return

            def deliver():
                try:
                    enqueue(record)
                finally:
                    pending.release()

            loop.call_soon_threadsafe(deliver)

        try:
            client.add_callback(callback)
            for schema in ("trades", "mbp-1", "statistics"):
                await asyncio.to_thread(
                    client.subscribe,
                    dataset="GLBX.MDP3",
                    schema=schema,
                    symbols=[self.replay.contract.instrument_id],
                    stype_in="instrument_id",
                    start=self.replay.session[0],
                )
            client.start()
            async with asyncio.timeout(duration_seconds):
                while True:
                    record = await queue.get()
                    name = type(record).__name__
                    schema = {
                        "TradeMsg": "trades",
                        "MBP1Msg": "mbp-1",
                        "StatMsg": "statistics",
                    }.get(name)
                    if schema:
                        try:
                            self.replay.ingest(schema, record, now=datetime.now(UTC))
                        except ValueError:
                            self.replay.mark_gap("stream_record_rejected")
                    elif name in {"ErrorMsg", "SystemMsg"}:
                        # Unknown system status cannot certify gap-free flow.
                        self.replay.mark_gap("stream_status_requires_review")
        except TimeoutError:
            pass
        except asyncio.CancelledError:
            self.replay.mark_gap("stream_cancelled")
            raise
        except Exception:
            self.replay.mark_gap("stream_disconnected_or_permission_failed")
            raise
        finally:
            client.terminate()
            self.client = None
            self.replay.mark_gap("stream_stopped_requires_replay")
