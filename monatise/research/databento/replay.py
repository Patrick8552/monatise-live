"""Bounded GCReplay extension for offline research; no engine/approval binding.

Historical receive-time replay is retrospective provider-capture research,
not evidence that Monatise actually observed the records at those old times.
Raw archives and original integer clocks remain authoritative.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import asdict, dataclass
from decimal import Decimal

from monatise.adapters.databento_gold import GCReplay, definition, ns_time, price
from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.databento.acquisition import canonical_hash, inspect_request_archive, json_document
from monatise.research.databento.archive import dbn_records


@dataclass(frozen=True)
class HistoricalGCReference:
    """Retrospective reference, including expired contracts; never PIT-certified."""
    contract: object
    definition_sha256: str
    definition_event_ns: int
    definition_receive_ns: int
    expiration_ns: int
    availability_ns: int
    catalog_sha256: str
    knowledge_basis: str = "RETROSPECTIVE_REFERENCE_RECONSTRUCTION"

    @classmethod
    def reconstruct(cls, record, *, identity_policy, retrieval_ns):
        retrieval = timestamp_ns(retrieval_ns)
        identity_policy.validate_contract_identity(record, publishers=identity_policy.mapping)
        event, received, expiry = (timestamp_ns(record.ts_event), timestamp_ns(record.ts_recv),
                                    timestamp_ns(record.expiration))
        if not event <= received < expiry or max(received, identity_policy.observed_at_ns) > retrieval:
            raise ValueError("historical definition clocks contradictory")
        # Reuse authentic GC units/tick/scale/contract validation. This legacy
        # economic tuple is used ONLY after separately validating GLBX feed
        # identity. The receive clock is a reference cutoff, not local availability.
        value = definition(record, publishers={record.publisher_id: ("GLBX.MDP3", "XCEC")},
                           now=ns_time(received))
        return cls(value, hashlib.sha256(bytes(record)).hexdigest(), event, received,
                   expiry, retrieval, identity_policy.sha256)


@dataclass(frozen=True)
class RecordObservation:
    dataset: str
    schema: str
    namespace: str
    publisher_id: int
    instrument_id: int
    event_ns: int
    provider_receive_ns: int | None
    ingestion_ns: int
    historical_retrieval_ns: int | None
    availability_ns: int
    source_ordinal: int
    sequence: int | None
    flags: int | None
    action: str | None
    record_sha256: str
    payload: tuple
    availability_basis: str = "LOCAL_ARCHIVE_ADMISSION"

    @property
    def provider_order_ns(self):
        return self.provider_receive_ns if self.provider_receive_ns is not None else self.event_ns


def normalize_record(record, *, request, reference, ordinal, ingestion_ns, retrieval_ns):
    """Lossless clocks + typed payload; unknown schemas/fields fail closed."""
    import databento_dbn as dbn
    contract = reference.contract
    if (record.publisher_id, record.instrument_id) != (contract.publisher_id, contract.instrument_id):
        raise ValueError("record contract/publisher mismatch")
    event = timestamp_ns(record.ts_event)
    receive = timestamp_ns(getattr(record, "ts_recv", None), optional=True)
    if hasattr(record, "ts_recv") and receive is None:
        raise ValueError("required provider receive timestamp unavailable")
    ingestion = timestamp_ns(ingestion_ns)
    retrieval = timestamp_ns(retrieval_ns, optional=True)
    if (receive is not None and event > receive) or max(event, receive or event, reference.availability_ns) > ingestion:
        raise ValueError("record unavailable or clocks contradictory")
    if retrieval is not None and retrieval > ingestion:
        raise ValueError("retrieval after ingestion")
    order = receive if receive is not None else event
    if (not request.start_ns <= order < request.end_ns
            or event < reference.definition_event_ns or event >= reference.expiration_ns):
        raise ValueError("record outside contract/request lifetime")
    if type(ordinal) is not int or ordinal < 0:
        raise ValueError("source ordinal required")
    flags = getattr(record, "flags", getattr(record, "stat_flags", None))
    sequence = getattr(record, "sequence", None)
    action = str(record.action) if hasattr(record, "action") else None
    schema = request.schema
    if schema == "trades" and isinstance(record, dbn.TradeMsg):
        payload = (record.price, record.size, str(record.side))
    elif schema == "mbp-1" and isinstance(record, dbn.MBP1Msg):
        level = record.levels[0]
        payload = (level.bid_px, level.ask_px, level.bid_sz, level.ask_sz)
    elif schema == "statistics" and isinstance(record, dbn.StatMsg):
        payload = (int(record.stat_type), timestamp_ns(record.ts_ref, optional=True),
                   record.price, record.quantity, int(record.update_action))
        action = str(int(record.update_action))
    elif schema == "status" and isinstance(record, dbn.StatusMsg):
        payload = (int(record.action), int(record.reason), int(record.trading_event),
                   record.is_trading, record.is_quoting)
        action = str(int(record.action))
    elif schema.startswith("ohlcv-") and isinstance(record, dbn.OHLCVMsg):
        expected = {"ohlcv-1s": dbn.RType.OHLCV_1S, "ohlcv-1m": dbn.RType.OHLCV_1M,
                    "ohlcv-1h": dbn.RType.OHLCV_1H, "ohlcv-1d": dbn.RType.OHLCV_1D}[schema]
        if record.rtype != expected:
            raise ValueError("OHLCV interval/rtype mismatch")
        payload = (record.open, record.high, record.low, record.close, record.volume)
    elif schema == "definition" and isinstance(record, dbn.InstrumentDefMsg):
        payload = (str(record.raw_symbol), record.expiration, str(record.security_update_action))
        action = str(record.security_update_action)
    else:
        raise ValueError("native record/schema unsupported without conversion")
    return RecordObservation(request.dataset, schema, "COMEX:GC:" + contract.raw_symbol,
        record.publisher_id, record.instrument_id, event, receive, ingestion, retrieval,
        ingestion, ordinal, sequence, flags, action, hashlib.sha256(bytes(record)).hexdigest(), payload)


@dataclass(frozen=True)
class ReplayConfig:
    start_ns: int
    end_ns: int
    session_open_ns: int
    session_close_ns: int
    session_calendar_reference: str
    dedup_capacity: int = 1024
    profile_capacity: int = 4096
    statistics_capacity: int = 128
    version: str = "databento-gc-historical-replay-v1"

    def __post_init__(self):
        for value in (self.start_ns, self.end_ns, self.session_open_ns, self.session_close_ns):
            timestamp_ns(value)
        if not self.session_open_ns <= self.start_ns < self.end_ns <= self.session_close_ns:
            raise ValueError("explicit replay boundaries inside one reviewed session required")
        if not self.session_calendar_reference or len(self.session_calendar_reference) > 128:
            raise ValueError("reviewed session calendar reference required")
        if (type(self.dedup_capacity) is not int or not 1 <= self.dedup_capacity <= 8192
                or type(self.profile_capacity) is not int or not 1 <= self.profile_capacity <= 65536
                or type(self.statistics_capacity) is not int or not 1 <= self.statistics_capacity <= 128
                or self.version != "databento-gc-historical-replay-v1"):
            raise ValueError("bounded versioned replay configuration required")


@dataclass(frozen=True)
class CoverageAttestation:
    """Separate reviewed continuity evidence; recent ticks are insufficient.

    The caller must verify the opaque external audit source before constructing
    this object. Neither a local hash nor an API EOF proves exchange continuity.
    This is an assertion boundary, not an automatic provider certification.
    """
    archive_sha256: str
    request_sha256: str
    reviewed_reference: str
    covered_from_ns: int
    covered_to_ns: int
    expected_records: int
    gaps: tuple[str, ...] = ()


class HistoricalGCReplay(GCReplay):
    """Explicit offline extension; legacy select/ingest/snapshot remain untouched.

    Incremental integer aggregates, bounded profile and recent dedup window.
    Duplicate outside that window arrives out of order and quarantines evidence;
    it is never double-counted. Filtered packet sequences need not be contiguous.
    No unsupported correction is applied speculatively.
    """
    def __init__(self, *, reference, config, publishers):
        super().__init__(publishers=publishers, capacity=10)
        self.reference, self.config = reference, config
        self.contract = reference.contract
        self.recent = OrderedDict()
        self.profile = {}
        self.total_volume = self.notional_fixed = self.known_volume = self.delta = 0
        self.accepted = self.duplicates = self.rejected = self.input_records = 0
        self.previous_order_ns = None
        self.quote_ns = None
        self.rolling_sha256 = "0" * 64
        self.last_observation = None
        self.coverage_state = "PARTIAL"
        self.completion_watermark_ns = None

    @property
    def config_sha256(self):
        # Include the frozen contract/catalog; a checkpoint cannot switch legs.
        return canonical_hash({"config": asdict(self.config), "definition": self.reference.definition_sha256,
                               "catalog": self.reference.catalog_sha256, "namespace": self.contract.raw_symbol,
                               "reference_availability_ns": self.reference.availability_ns,
                               "expiration_ns": self.reference.expiration_ns})

    def consume(self, observation):
        self.input_records += 1
        self.rolling_sha256 = canonical_hash([self.rolling_sha256, asdict(observation)])
        self.last_observation = observation
        if (observation.namespace != "COMEX:GC:" + self.contract.raw_symbol
                or (observation.publisher_id, observation.instrument_id) != (self.contract.publisher_id, self.contract.instrument_id)
                or not self.config.start_ns <= observation.provider_order_ns < self.config.end_ns
                or not self.config.session_open_ns <= observation.event_ns < self.config.session_close_ns):
            return self._reject("record_identity_or_session_mismatch")
        if observation.schema != "statistics" and (observation.flags or 0) & 8:
            return self._reject("bad_receive_timestamp")
        if observation.record_sha256 in self.recent:
            self.duplicates += 1
            return False
        if self.previous_order_ns is not None and observation.provider_order_ns < self.previous_order_ns:
            return self._reject("out_of_order_or_old_duplicate")
        self.previous_order_ns = observation.provider_order_ns
        try:
            accepted = self._aggregate(observation)
        except (ValueError, TypeError, IndexError):
            return self._reject("record_quality_rejected")
        if accepted:
            self.recent[observation.record_sha256] = None
            if len(self.recent) > self.config.dedup_capacity:
                self.recent.popitem(last=False)
            self.accepted += 1
        return accepted

    def _reject(self, reason):
        self.rejected += 1
        self.mark_gap(reason)
        return False

    def _aggregate(self, o):
        if o.schema == "trades":
            p, size, side = o.payload
            # Reuse GCReplay's unit/tick/side conventions, retain fixed-point sums.
            if o.action != "T":
                return self._reject("unsupported_trade_correction")
            if price(p) % self.contract.tick or type(size) is not int or not 0 < size < 2**32-1 or side not in {"A", "B", "N"}:
                raise ValueError("invalid trade")
            if p not in self.profile and len(self.profile) >= self.config.profile_capacity:
                return self._reject("volume_profile_capacity_exceeded")
            self.profile[p] = self.profile.get(p, 0) + size
            self.total_volume += size
            self.notional_fixed += p * size
            if side != "N":
                self.known_volume += size
                self.delta += size if side == "B" else -size
            return True
        if o.schema == "mbp-1":
            bid, ask, bid_size, ask_size = o.payload
            if (price(bid) > price(ask) or price(ask)-price(bid) > 5
                    or price(bid) % self.contract.tick or price(ask) % self.contract.tick
                    or bid_size <= 0 or ask_size <= 0):
                raise ValueError("invalid top of book")
            self.quote = o.payload
            self.quote_ns = o.provider_receive_ns
            return True  # MBP-1 trade actions NEVER add volume.
        if o.schema == "statistics":
            kind, ref, _, _, action = o.payload
            key = (kind, ref)
            if action != 1:  # Native StatUpdateAction.NEW; DELETE=2 stays quarantined.
                return self._reject("unsupported_statistics_correction")
            if key not in self.statistics and len(self.statistics) >= self.config.statistics_capacity:
                return self._reject("statistics_capacity_exceeded")
            self.statistics[key] = o.payload
            return True
        if o.schema == "status":
            # Retain categorical status; status does not certify market continuity.
            self.market_status = o.payload
            return True
        if o.schema == "definition":
            if o.record_sha256 != self.reference.definition_sha256:
                return self._reject("contract_definition_revision_requires_new_reference")
            return True
        if o.schema.startswith("ohlcv-"):
            # Preserve native candles as separate inputs; never merge their volume
            # with trades or label historical bars broker/PIT-finalized candles.
            opening, high, low, close, volume = o.payload
            if not price(low) <= price(opening) <= price(high) or not price(low) <= price(close) <= price(high) or volume < 0:
                raise ValueError("invalid native OHLCV")
            self.latest_native_candle = asdict(o)
            return True
        raise ValueError("unsupported replay schema")

    def finish(self, *, manifest, attestation=None, assessed_at_ns, max_age_ns=10 * 10**9):
        timestamp_ns(assessed_at_ns)
        coverage = manifest["coverage"]
        if manifest["status"] != "ARCHIVED" or not coverage["transport_complete"]:
            self.coverage_state = "PARTIAL"
        elif self.gaps:
            self.coverage_state = "GAPPED"
        elif attestation is None:
            self.coverage_state = "UNCERTIFIED"
        elif (attestation.archive_sha256 != manifest["archive_sha256"]
                or attestation.request_sha256 != manifest["request_sha256"]
                or not attestation.reviewed_reference
                or attestation.covered_from_ns != self.config.start_ns
                or attestation.covered_to_ns != self.config.end_ns
                or attestation.expected_records != self.input_records
                or self.input_records != coverage["record_count"]):
            self.coverage_state = "UNCERTIFIED"
        elif attestation.gaps:
            for gap in attestation.gaps:
                self.mark_gap(gap)
            self.coverage_state = "GAPPED"
        elif assessed_at_ns < self.config.end_ns or assessed_at_ns - self.config.end_ns > max_age_ns:
            self.coverage_state = "STALE"
        else:
            self.coverage_state = "COMPLETE"
        if coverage["transport_complete"]:
            self.completion_watermark_ns = self.config.end_ns
        return self.result()

    def result(self):
        return json_document(dict(version=self.config.version, config_sha256=self.config_sha256,
            namespace="COMEX:GC:" + self.contract.raw_symbol, execution_price_authority=False,
            observation_basis="RETROSPECTIVE_PROVIDER_CAPTURE_REPLAY", trading_eligible=False,
            accepted=self.accepted, duplicates=self.duplicates, rejected=self.rejected,
            input_records=self.input_records, coverage_state=self.coverage_state,
            aggregates_usable=self.coverage_state == "COMPLETE" and not self.gaps,
            gaps=sorted(self.gaps), completion_watermark_ns=self.completion_watermark_ns,
            completion_watermark_basis="REQUEST_TRANSPORT_NOT_EXCHANGE_CONTINUITY",
            rolling_sha256=self.rolling_sha256, volume=self.total_volume,
            notional_fixed=self.notional_fixed, known_side_volume=self.known_volume,
            cvd_known_side=self.delta, cvd_complete=self.total_volume > 0 and self.known_volume == self.total_volume,
            vwap=str(Decimal(self.notional_fixed) / Decimal(self.total_volume) / Decimal(10**9)) if self.total_volume else None,
            poc_fixed=max(self.profile, key=lambda p: (self.profile[p], -p)) if self.profile else None,
            profile=sorted(self.profile.items()), quote=self.quote, quote_ns=self.quote_ns,
            statistics=[list(value) for _, value in sorted(self.statistics.items(), key=lambda item: str(item[0]))],
            market_status=getattr(self, "market_status", None),
            latest_native_candle=getattr(self, "latest_native_candle", None),
            recent_record_hashes=list(self.recent), previous_order_ns=self.previous_order_ns,
            last_record=asdict(self.last_observation) if self.last_observation else None))

    def checkpoint(self, archive_sha256):
        result = self.result()
        return dict(config_sha256=self.config_sha256, archive_sha256=archive_sha256,
                    record_ordinal=self.input_records, rolling_sha256=self.rolling_sha256,
                    state_sha256=canonical_hash(result), result=result)


def replay_archive(*, archive, manifest, request, reference, config, checkpoint=None,
                   attestation=None, assessed_at_ns):
    """Integrity verified before replay; restart rebuilds prefix, then continues.

    Rebuilding a bounded-state prefix avoids trusting serialized mutable engine
    internals. It costs O(prefix) I/O after restart and cannot count records twice.
    No merge/reorder of separate schema files; each request is replayed explicitly.
    """
    import databento_dbn as dbn
    if manifest["request_sha256"] != request.sha256 or (config.start_ns, config.end_ns) != (request.start_ns, request.end_ns):
        raise ValueError("manifest/replay request mismatch")
    path = archive.verify(manifest["archive_sha256"])
    actual = inspect_request_archive(path, request)
    if actual != manifest["coverage"]:
        raise ValueError("manifest coverage contradicts DBN archive")
    replay = HistoricalGCReplay(reference=reference, config=config, publishers={reference.contract.publisher_id: ("GLBX.MDP3", "GLBX")})
    if checkpoint and (checkpoint["archive_sha256"] != manifest["archive_sha256"]
                       or checkpoint["config_sha256"] != replay.config_sha256
                       or not 0 <= checkpoint["record_ordinal"] <= actual["record_count"]):
        raise ValueError("checkpoint incompatible with archive/replay")
    cutoff = checkpoint["record_ordinal"] if checkpoint else None
    if cutoff == 0 and replay.checkpoint(manifest["archive_sha256"]) != checkpoint:
        raise ValueError("checkpoint initial state corrupted")
    for record in dbn_records(path, max_records=request.record_limit):
        if isinstance(record, dbn.Metadata):
            continue
        try:
            observation = normalize_record(record, request=request, reference=reference,
                ordinal=replay.input_records, ingestion_ns=manifest["availability_ns"],
                retrieval_ns=manifest["retrieval_ns"])
        except ValueError:
            # Preserve count/hash for rejected native records too; no skipping
            # a bad record and pretending all retrieved evidence was qualified.
            replay.input_records += 1
            replay.rolling_sha256 = canonical_hash([replay.rolling_sha256, hashlib.sha256(bytes(record)).hexdigest(), "NORMALIZATION_REJECTED"])
            replay._reject("normalization_rejected")
        else:
            replay.consume(observation)
        if replay.input_records == cutoff and replay.checkpoint(manifest["archive_sha256"]) != checkpoint:
            raise ValueError("checkpoint prefix/state corrupted")
    replay.finish(manifest=manifest, attestation=attestation, assessed_at_ns=assessed_at_ns)
    return replay
