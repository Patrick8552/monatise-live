"""Admit a reviewed local native archive; never initiate provider acquisition."""
from pathlib import Path

from monatise.research.databento.archive import dbn_records, sha256_file
from monatise.research.databento.acquisition import HistoricalRequest, inspect_request_archive
from .models import digest, encode
from .normalize import observation


def admit(path, *, request, contract, review, enabled_schemas=()):
    """The independent review is a trust boundary, not proof created by this code.

    New downloads need reconciled billing and the existing one-use receipt. Native
    normalization alone never certifies exchange continuity or historical access.
    """
    import databento_dbn as dbn
    if (not isinstance(request, HistoricalRequest) or request.schema not in enabled_schemas
            or request.schema not in {'definition','trades','ohlcv-1m','ohlcv-1h','mbp-1','status','statistics'}
            or request.contracts != (contract.identity[1:4],)
            or request.dataset != contract.metadata.dataset
            or not review.get('origin_review_reference')
            or review.get('request_sha256') != request.sha256
            or review.get('definition_sha256') != contract.metadata.definition_sha256
            or review.get('billing_status') != 'RECONCILED'
            or not review.get('request_receipt_reference')
            or review.get('evidence_kind') not in {'AUTHENTIC_ARCHIVED_RECORD','ENGINEERING_SYNTHETIC'}):
        raise ValueError('reviewed_exact_archive_identity_billing_and_receipt_required')
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>request.wire_byte_limit:
        raise ValueError('bounded_regular_native_archive_required')
    before=sha256_file(path)
    if before!=review.get('archive_sha256'):raise ValueError('native_archive_hash_mismatch')
    coverage=inspect_request_archive(path,request)
    if not coverage['transport_complete']:raise ValueError('incomplete_archive_quarantined')
    values=tuple(observation(row,schema=request.schema,contract=contract,archive_sha256=before,
        ordinal=i,retrieval_ns=review['retrieval_ns'],admission_ns=review['admission_ns'],
        evidence_kind=review['evidence_kind'],enabled_schemas=enabled_schemas)
        for i,row in enumerate(r for r in dbn_records(path,max_records=request.record_limit)
                               if not isinstance(r,dbn.Metadata)))
    if sha256_file(path)!=before:raise ValueError('native_archive_changed_during_admission')
    return dict(observations=values,coverage=coverage,request_sha256=request.sha256,
        archive_sha256=before,review_sha256=digest(review),normalized_sha256=digest(values),
        contract=encode(contract),billing_status='RECONCILED',
        evidence_kind=review['evidence_kind'],continuity_certified=False,execution_eligible=False)
