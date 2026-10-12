"""Native trade recovery with explicit completeness/correction/multiplicity proof.

    A hash, EOF, observed trades or absence of a bad flag is NOT continuity proof.
    Recovery is unconnected to qualification. No synthetic/zero-volume price bar.
"""
from dataclasses import asdict, dataclass
from decimal import Decimal

from monatise.research.gc_fib.candles import GCIdentity, MINUTE, timestamp_ns
from monatise.research.gc_qualification.models import NativeContract, digest, hash_value


@dataclass(frozen=True)
class NativeTrade:
    identity: GCIdentity
    event_ns: int
    receive_ns: int
    price_fixed: int
    size: int
    sequence: int
    flags: int
    action: str
    side: str
    archive_sha256: str
    record_sha256: str
    ordinal: int
    retrieval_ns: int
    admission_ns: int
    evidence_kind: str

    def __post_init__(self):
        if not isinstance(self.identity,GCIdentity): raise ValueError("exact_native_identity_required")
        for t in (self.event_ns,self.receive_ns,self.retrieval_ns,self.admission_ns): timestamp_ns(t)
        if not self.event_ns <= self.receive_ns <= self.retrieval_ns <= self.admission_ns:
            raise ValueError("trade_clocks_contradictory")
        if (type(self.price_fixed) is not int or not 0 < self.price_fixed < 2**63-1
                or self.price_fixed % 100_000_000 or type(self.size) is not int or not 0 < self.size < 2**32):
            raise ValueError("native_trade_precision_or_size_invalid")
        if any(type(v) is not int or v < 0 for v in (self.sequence,self.flags,self.ordinal)):
            raise ValueError("trade_source_position_invalid")
        if self.action != "T" or self.side not in {"A","B","N"}:
            raise ValueError("executed_trade_required_not_quote_or_fill")
        hash_value(self.archive_sha256); hash_value(self.record_sha256)
        if self.evidence_kind not in {"AUTHENTIC_HISTORICAL_DOWNLOAD","ENGINEERING_SYNTHETIC"}:
            raise ValueError("explicit_trade_evidence_kind_required")


@dataclass(frozen=True)
class TradeContinuityReview:
    """Trusted external review boundary, analogous to existing CoverageAttestation.

    The operator must independently review the supporting evidence. This type does
    not certify itself and the forensic scanner never manufactures it. Expected
    count refers to source positions in this exact interval, not distinct bytes.
    """
    identity: GCIdentity
    start_ns: int
    end_ns: int
    archive_sha256s: tuple[str,...]
    request_sha256s: tuple[str,...]
    reviewed_reference: str
    independent_evidence_sha256: str
    continuity_complete: bool
    corrections_reviewed: bool
    multiplicity_policy: str
    expected_interval_records: int
    definition_sha256: str
    evidence_kind: str

    def __post_init__(self):
        if (not isinstance(self.identity,GCIdentity) or not self.start_ns < self.end_ns
                or not self.reviewed_reference or type(self.expected_interval_records) is not int
                or self.expected_interval_records < 0):
            raise ValueError("explicit_bounded_external_trade_review_required")
        timestamp_ns(self.start_ns); timestamp_ns(self.end_ns)
        if (not isinstance(self.archive_sha256s,tuple) or not isinstance(self.request_sha256s,tuple)
                or not self.archive_sha256s or not self.request_sha256s):
            raise ValueError("review_must_bind_source_and_requests")
        for h in (*self.archive_sha256s,*self.request_sha256s,self.independent_evidence_sha256): hash_value(h)
        hash_value(self.definition_sha256)
        if self.evidence_kind not in {"AUTHENTIC_HISTORICAL_DOWNLOAD","ENGINEERING_SYNTHETIC"}:
            raise ValueError("explicit_review_evidence_kind_required")
        if self.multiplicity_policy != "PRESERVE_VERIFIED_NATIVE_SOURCE_POSITIONS":
            raise ValueError("unreviewed_multiplicity_policy")


def recover_minute(records, *, start_ns, review, sessions, contract):
    """Vendor-compatible receive-time buckets; retain original event nanoseconds.

    Repeated ingestion of the same archive ordinal is idempotent. Identical native
    bytes at DIFFERENT ordinals are preserved: serialization/sequence is not a
    unique CME execution identifier. Ambiguous corrections/coverage reject.
    """
    if start_ns % MINUTE or not isinstance(review,TradeContinuityReview):
        raise ValueError("aligned_minute_and_external_review_required")
    end_ns = start_ns+MINUTE
    if (not isinstance(contract,NativeContract) or review.identity != contract.identity
            or review.definition_sha256 != contract.definition_sha256):
        raise ValueError("verified_native_definition_lineage_required")
    if (review.continuity_complete is not True or review.corrections_reviewed is not True
            or (review.start_ns,review.end_ns) != (start_ns,end_ns)):
        raise ValueError("complete_trade_coverage_and_correction_review_required")
    if not any(a <= start_ns < end_ns <= b for a,b in sessions):
        raise ValueError("recovery_crosses_exchange_session")
    unique = {}
    for row in records:
        if (not isinstance(row,NativeTrade) or row.identity != review.identity
                or row.archive_sha256 not in review.archive_sha256s or row.evidence_kind != review.evidence_kind):
            raise ValueError("unreviewed_trade_source_or_identity")
        if not start_ns <= row.receive_ns < end_ns:
            raise ValueError("record_outside_receive_time_bucket")
        if not contract.definition_event_ns <= row.event_ns <= row.receive_ns < contract.expiration_ns:
            raise ValueError("trade_outside_native_definition_lifetime")
        if row.flags & (4|8|32): raise ValueError("trade_gap_clock_or_snapshot_flag")
        key = (row.archive_sha256,row.ordinal)
        if key in unique and unique[key] != row: raise ValueError("conflicting_source_revision")
        unique[key] = row
    rows = sorted(unique.values(),key=lambda r:(r.archive_sha256,r.ordinal))
    if len(rows) != review.expected_interval_records: raise ValueError("reviewed_trade_count_mismatch")
    if len({r.archive_sha256 for r in rows}) > 1:
        # Cross-archive ties and overlap need a reviewed total ordering rather
        # than arbitrary hash ordering. Initial recovery supports one partition.
        raise ValueError("cross_archive_recovery_order_requires_review")
    if any(a.receive_ns > b.receive_ns for a,b in zip(rows,rows[1:])):
        raise ValueError("native_receive_order_regressed")
    if not rows:
        return dict(classification="B",evidence_kind=review.evidence_kind,observation_kind="VERIFIED_NO_TRADE_INTERVAL",candle=None,
                    review_sha256=digest(asdict(review)),synthetic_price_created=False,qualification_admitted=False)
    o,h,l,c = rows[0].price_fixed,max(r.price_fixed for r in rows),min(r.price_fixed for r in rows),rows[-1].price_fixed
    value = dict(evidence_kind="TRADE_DERIVED_VERIFIED" if review.evidence_kind == "AUTHENTIC_HISTORICAL_DOWNLOAD" else "ENGINEERING_SYNTHETIC",
        derivation_kind="REVIEWED_NATIVE_TRADE_DERIVATION",identity=asdict(review.identity),definition_sha256=contract.definition_sha256,
        timeframe="1m",open_ns=start_ns,close_ns=end_ns,prices_fixed=[o,h,l,c],
        prices=[str(Decimal(p)/Decimal(10**9)) for p in (o,h,l,c)],volume=sum(r.size for r in rows),
        source_records=[asdict(r) for r in rows],review_sha256=digest(asdict(review)),
        request_sha256s=review.request_sha256s,aggregation_clock="ts_recv",
        event_clock_preserved=True,availability_basis="RETROSPECTIVE_ASSUMED_AVAILABILITY",
        assumed_available_ns=end_ns+10*10**9,retrieval_ns=max(r.retrieval_ns for r in rows),
        admission_ns=max(r.admission_ns for r in rows),synthetic_price_created=False,
        qualification_admitted=False,requires_reviewed_qualification_source_interface=True)
    return {**value,"sha256":digest(value)}
