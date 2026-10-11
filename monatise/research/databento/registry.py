"""Bounded, point-in-time GC/standard-OG definition registry.

Phase 1 only: no downloads, streams, persistence or trading. Phase 2 must
persist raw DBN externally and metadata in PostgreSQL. SDK-shaped synthetic
records are not actual market observations and are never called certified.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

from monatise.adapters.databento_gold import GCDefinition, definition, ns_time
from monatise.adapters.databento_identity import DatabentoPublisherPolicy, timestamp_ns
from monatise.application.gold_options import GoldOptionDefinition, normalize_option

STANDARD_OG = {
    "family": "OG", "style": "American", "settlement": "future_delivery",
    "currency": "USD", "multiplier": 100,
}


@dataclass(frozen=True)
class DefinitionProvenance:
    event_ns: int | None
    provider_receive_ns: int | None
    ingestion_ns: int
    historical_retrieval_ns: int | None
    availability_ns: int
    source_ordinal: int
    dataset: str
    schema: str
    publisher_id: int
    instrument_id: int
    record_sha256: str
    metadata_sha256: str
    evidence_kind: str
    availability_basis: str = "LOCAL_OBSERVATION"
    sequence: None = None  # Definition schema supplies no sequence/flags.
    validity_flags: None = None


@dataclass(frozen=True)
class RegisteredDefinition:
    namespace: str
    canonical: GCDefinition | GoldOptionDefinition | None
    provenance: DefinitionProvenance
    raw_record_bytes: bytes
    expiration_ns: int | None
    status: str
    action: str
    underlying_record_sha256: str | None = None


class GoldInstrumentRegistry:
    def __init__(self, *, identity_policy: DatabentoPublisherPolicy, capacity=4096):
        if not isinstance(identity_policy, DatabentoPublisherPolicy):
            raise ValueError("explicit Databento research identity policy required")
        if isinstance(capacity, bool) or not isinstance(capacity, int) or not 1 <= capacity <= 65536:
            raise ValueError("invalid registry capacity")
        self.identity_policy = identity_policy
        self.capacity = capacity
        self._history = {}
        self._count = 0
        self._last_observation = None
        self._unavailable_from = None

    def ingest(self, record, *, ingestion_ns, source_ordinal, evidence_kind,
               historical_retrieval_ns=None, convention=None):
        ingestion_ns = timestamp_ns(ingestion_ns)
        historical_retrieval_ns = timestamp_ns(historical_retrieval_ns, optional=True)
        if historical_retrieval_ns is not None and historical_retrieval_ns > ingestion_ns:
            raise ValueError("retrieval after ingestion")
        if isinstance(source_ordinal, bool) or not isinstance(source_ordinal, int) or source_ordinal < 0:
            raise ValueError("explicit source ordering required")
        if evidence_kind not in {"ENGINEERING_SYNTHETIC", "AUTHENTIC_ARCHIVED_RECORD"}:
            raise ValueError("explicit evidence kind required")
        order = (ingestion_ns, source_ordinal)
        if self._last_observation is not None and order <= self._last_observation:
            raise ValueError("out-of-order or ambiguous local observation")
        if self._count >= self.capacity:
            if self._unavailable_from is None:
                self._unavailable_from = order
            raise ValueError("registry full; rotate/checkpoint before more records")
        raw = bytes(record)
        if len(raw) < 24 or raw[0] * 4 != len(raw) or raw[1] != 19:
            raise ValueError("native DBN instrument definition required")
        _, _, pid, iid, event = struct.unpack_from("<BBHIQ", raw)
        received = struct.unpack_from("<Q", raw, 16)[0]
        if (pid, iid, event, received) != (record.publisher_id, record.instrument_id, record.ts_event, record.ts_recv):
            raise ValueError("definition fields contradict raw DBN header")
        key = (pid, iid)
        if not 0 < iid < (1 << 32):
            raise ValueError("invalid instrument identifier")
        history = self._history.get(key, [])
        provenance = DefinitionProvenance(
            timestamp_ns(event, optional=True), timestamp_ns(received, optional=True),
            ingestion_ns, historical_retrieval_ns, ingestion_ns, source_ordinal,
            "GLBX.MDP3", "definition", pid, iid, hashlib.sha256(raw).hexdigest(),
            self.identity_policy.sha256, evidence_kind,
        )
        self._last_observation = order
        try:
            value = self._normalize(record, provenance, history, convention)
        except (ValueError, AttributeError, TypeError):
            # A rejected update cannot leave the latest contract trusted.
            if history:
                rejected = RegisteredDefinition(history[-1].namespace, None, provenance,
                    raw, None, "QUARANTINED", str(record.security_update_action))
                self._append(key, rejected)
            raise
        if history and value.raw_record_bytes == history[-1].raw_record_bytes:
            return history[-1]  # Preserve original local availability, not a refresh.
        self._append(key, value)
        return value

    def _normalize(self, record, provenance, history, convention):
        now = ns_time(provenance.ingestion_ns)
        self.identity_policy.validate(record, publishers=self.identity_policy.mapping,
                                      now=now, cutoff_ns=provenance.ingestion_ns)
        event, received = provenance.event_ns, provenance.provider_receive_ns
        if event is None or received is None or not event <= received <= provenance.ingestion_ns:
            raise ValueError("missing, future or inconsistent definition timestamps")
        valid_events = [v.provenance.event_ns for v in history
                        if v.status in {"ACTIVE", "DELETED"}]
        if valid_events and event < valid_events[-1]:
            raise ValueError("out-of-order definition event")
        expiration = timestamp_ns(record.expiration)
        if expiration <= provenance.ingestion_ns:
            raise ValueError("expired definition")
        action = str(record.security_update_action)
        if action not in {"A", "M", "D"}:
            raise ValueError("unknown definition action")
        symbol = str(record.raw_symbol)
        if not symbol or len(symbol) > 70 or not symbol.isascii() or any(ord(c) < 32 for c in symbol):
            raise ValueError("invalid raw contract symbol")
        if history:
            prior = next((v for v in reversed(history) if v.canonical is not None), None)
            if prior is None or (prior.canonical.raw_symbol, prior.expiration_ns) != (symbol, expiration):
                raise ValueError("instrument identifier remapped to another contract")
        if action == "D":
            if not history or history[-1].status != "ACTIVE":
                raise ValueError("deletion of unknown or unavailable instrument")
            previous = history[-1].canonical
            expected_class = "F" if isinstance(previous, GCDefinition) else previous.kind
            expected_asset = "GC" if isinstance(previous, GCDefinition) else "OG"
            if (str(record.instrument_class), str(record.asset)) != (expected_class, expected_asset):
                raise ValueError("deletion identity contradicts contract")
            return RegisteredDefinition(history[-1].namespace, None, provenance,
                bytes(record), expiration, "DELETED", action)
        if str(record.instrument_class) == "F":
            value = definition(record, publishers=self.identity_policy.mapping, now=now,
                               identity_policy=self.identity_policy,
                               cutoff_ns=provenance.ingestion_ns)
            namespace, underlying_hash = "COMEX:GC:" + symbol, None
        elif str(record.instrument_class) in {"C", "P"}:
            if str(record.security_type) != "OOF" or not symbol.startswith("OG"):
                raise ValueError("unsupported Gold option security type or symbol")
            if convention != STANDARD_OG:
                raise ValueError("reviewed standard OG convention required")
            parent = self.resolve(publisher_id=record.publisher_id,
                instrument_id=record.underlying_id, at_ns=provenance.ingestion_ns,
                through_ordinal=provenance.source_ordinal)
            if not isinstance(parent.canonical, GCDefinition):
                raise ValueError("option underlying must be a GC future")
            if expiration > parent.expiration_ns:
                raise ValueError("option expiry beyond its underlying")
            if str(record.underlying) and str(record.underlying) != parent.canonical.raw_symbol:
                raise ValueError("contradictory option underlying symbol")
            value = normalize_option(record, futures={parent.canonical.instrument_id: parent.canonical},
                publishers=self.identity_policy.mapping, now=now, convention=convention,
                identity_policy=self.identity_policy, cutoff_ns=provenance.ingestion_ns)
            namespace, underlying_hash = "COMEX:OG:" + symbol, parent.provenance.record_sha256
            if history:
                prior = next((v for v in reversed(history) if isinstance(v.canonical, GoldOptionDefinition)), None)
                if prior is not None and (prior.canonical.kind, prior.canonical.strike, prior.canonical.underlying_id) != (value.kind, value.strike, value.underlying_id):
                    raise ValueError("option identity changed")
        else:
            raise ValueError("unsupported GC/OG contract class")
        return RegisteredDefinition(namespace, value, provenance, bytes(record), expiration,
                                    "ACTIVE", action, underlying_hash)

    def _append(self, key, value):
        self._history.setdefault(key, []).append(value)
        self._count += 1

    def resolve(self, *, publisher_id, instrument_id, at_ns, through_ordinal=None):
        at_ns = timestamp_ns(at_ns)
        if through_ordinal is not None and (isinstance(through_ordinal, bool)
                or not isinstance(through_ordinal, int) or through_ordinal < 0):
            raise ValueError("invalid point-in-time ordinal")
        if (isinstance(publisher_id, bool) or not isinstance(publisher_id, int)
                or isinstance(instrument_id, bool) or not isinstance(instrument_id, int)
                or not 0 < publisher_id < 65536 or not 0 < instrument_id < (1 << 32)):
            raise ValueError("invalid registry identity")
        if self.identity_policy.observed_at_ns > at_ns:
            raise ValueError("metadata not yet observed")
        if self._unavailable_from is not None:
            failed_ns, failed_ordinal = self._unavailable_from
            if at_ns > failed_ns or (at_ns == failed_ns and
                    (through_ordinal is None or through_ordinal >= failed_ordinal)):
                raise ValueError("registry coverage lost after capacity overflow")
        eligible = [v for v in self._history.get((publisher_id, instrument_id), ())
                    if v.provenance.availability_ns <= at_ns and
                    (through_ordinal is None or v.provenance.availability_ns < at_ns
                     or v.provenance.source_ordinal <= through_ordinal)]
        if not eligible:
            raise ValueError("instrument unavailable at cutoff")
        latest = eligible[-1]
        if latest.status != "ACTIVE" or at_ns >= latest.expiration_ns:
            raise ValueError("instrument deleted, quarantined or expired")
        if isinstance(latest.canonical, GoldOptionDefinition):
            parent = self.resolve(publisher_id=publisher_id,
                instrument_id=latest.canonical.underlying_id, at_ns=at_ns,
                through_ordinal=through_ordinal)
            if parent.provenance.record_sha256 != latest.underlying_record_sha256:
                raise ValueError("option underlying changed; fresh definition required")
        return latest

    @property
    def observations(self):
        return tuple(sorted((v for history in self._history.values() for v in history),
                            key=lambda v: (v.provenance.ingestion_ns, v.provenance.source_ordinal)))
