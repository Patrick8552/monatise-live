"""Immutable, request-bound billing and research-release review; no acquisition."""
from decimal import Decimal
from pathlib import Path
import json
import sqlite3

from monatise.research.databento.acquisition import HistoricalRequest
from monatise.research.databento.archive import sha256_file
from ..cached_bundle import admit
from ..models import digest, encode, hash_required, number
from . import SAFETY


def reservations(path):
    """Read the existing control plane without schema/budget/settlement writes."""
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True) as db:
        rows = db.execute("SELECT approval_id,request_hash,reserved_usd,billed_usd,credit_used_usd,transport_started "
                          "FROM reservations WHERE approval_id LIKE 'phase5-esnq-%'").fetchall()
    return [dict(zip(('approval_id','request_sha256','reserved_usd','actual_usage_usd',
                      'credit_used_usd','transport_started'), r)) for r in rows]


def manifests(root):
    result = []
    for path in sorted(Path(root).glob('result-*.json')):
        if path.is_symlink():
            raise ValueError('regular_request_manifest_required')
        value = json.loads(path.read_text())
        result.append(dict(value, manifest_sha256=sha256_file(path)))
    return result


def reconcile(values, *, diagnostics, ledger_rows, provider_records=(), billing_review=None,
              admission_review=None):
    """Reviews must originate outside this calculator. Hashes are integrity proof,
    not proof of provider authorship. A reviewed request journal/statement must
    establish exact attribution; estimates and rounded totals cannot substitute.
    """
    if len(values) != 6 or len(ledger_rows) != 6:
        raise ValueError('six_exact_ES_NQ_requests_and_reservations_required')
    rows, hashes, scopes = [], set(), set()
    records = {}; provider_ids=set()
    for record in provider_records:
        h = record['request_sha256']; hash_required(h)
        if h in records:
            raise ValueError('ambiguous_duplicate_provider_request')
        provider_id=record.get('provider_request_id')
        if provider_id and provider_id in provider_ids:
            raise ValueError('duplicate_provider_request_ID_cannot_settle_distinct_downloads')
        if provider_id:provider_ids.add(provider_id)
        records[h] = record
    ledger = {v['request_sha256']: v for v in ledger_rows}
    if len(ledger) != 6:
        raise ValueError('unique_request_reservations_required')
    diagnostic_costs = {c['request_sha256']: c for p in diagnostics['products'].values() for c in p['costs']}
    for m in values:
        params = dict(m['request']); params['contracts'] = tuple(tuple(c) for c in params['contracts'])
        request = HistoricalRequest(**params)
        h = request.sha256; native = diagnostic_costs.get(h)
        if (h in hashes or h != m['request_sha256'] or h not in ledger
                or request.dataset != 'GLBX.MDP3' or len(request.contracts) != 1
                or request.contracts[0] not in {(1,10252,'ESZ6'), (1,261401,'NQZ6')}
                or request.schema not in {'definition','trades','ohlcv-1m'}
                or m['status'] != 'ARCHIVED' or m['evidence_kind'] != 'AUTHENTIC_HISTORICAL_DOWNLOAD'
                or not m['coverage']['transport_complete'] or m['download_attempts'] != 1
                or not native or native['archive_sha256'] != m['archive_sha256']
                or ledger[h]['approval_id'] != m['authorization']['approval_id']
                or ledger[h]['transport_started'] != 1):
            raise ValueError('native_cache_request_identity_or_ledger_mismatch')
        hashes.add(h); scopes.add((request.contracts[0][2],request.schema))
        actual = credit = cash = None; reasons = []
        record = records.pop(h, None)
        if record is None:
            reasons.append('authoritative_request_usage_credit_cash_record_missing')
        else:
            hash_required(record['provider_source_sha256'])
            review = billing_review or {}
            if (record.get('source_kind') not in {'PROVIDER_REQUEST_JOURNAL','PROVIDER_SETTLED_STATEMENT'}
                    or not record.get('provider_request_id') or not record.get('settled')
                    or not review.get('independent_review_reference')
                    or record['provider_source_sha256'] not in review.get('verified_source_hashes', ())
                    or record.get('dataset') != request.dataset or record.get('schema') != request.schema
                    or tuple(tuple(c) for c in record.get('contracts', ())) != request.contracts
                    or record.get('start_ns') != request.start_ns or record.get('end_ns') != request.end_ns
                    or record.get('acquired_at_ns') != m['retrieval_ns']):
                reasons.append('authoritative_provider_scope_origin_or_settlement_unverified')
            else:
                actual, credit, cash = (number(record[k]) for k in ('actual_usage_usd','credit_used_usd','cash_usd'))
                if min(actual,credit,cash) < 0 or credit+cash != actual:
                    raise ValueError('usage_credit_cash_accounting_mismatch')
                if cash != 0:
                    reasons.append('cash_expenditure_requires_independent_resolution')
                if ledger[h]['actual_usage_usd'] is not None and (
                        number(ledger[h]['actual_usage_usd'])!=actual or ledger[h]['credit_used_usd'] is None
                        or number(ledger[h]['credit_used_usd'])!=credit):
                    reasons.append('existing_ledger_settlement_conflict')
        product = request.contracts[0][2][:-2]
        quality = diagnostics['products'][product]
        if quality['missing_minute_opens_ns']:
            reasons.append('independent_missing_candle_quality_quarantine')
        a = admission_review or {}
        if a.get('approved_request_hashes') is None or h not in a['approved_request_hashes'] or not a.get('human_review_reference'):
            reasons.append('explicit_research_admission_missing')
        independent = a.get('unresolved_quality_requests', ())
        if h in independent:
            reasons.append('independent_quality_quarantine_unresolved')
        rows.append(dict(request=encode(request),request_sha256=h,archive_sha256=m['archive_sha256'],
            manifest_sha256=m['manifest_sha256'],acquired_at_ns=m['retrieval_ns'],
            provider_estimate_usd=str(number(m['preflight']['estimated_usd'])),
            actual_usage_usd=None if actual is None else str(actual),
            credit_used_usd=None if credit is None else str(credit),cash_usd=None if cash is None else str(cash),
            reservation=ledger[h],provider_record=record,rejection_reasons=reasons,
            billing_reconciled=actual is not None and not any('provider' in r or 'cash_' in r or 'settlement_conflict' in r for r in reasons),
            research_admission_eligible=not reasons))
    if records or scopes != {(s,k) for s in ('ESZ6','NQZ6') for k in ('definition','trades','ohlcv-1m')}:
        raise ValueError('unexpected_provider_record_or_incomplete_schema_scope')
    # Bundle admission is all-or-none; definitions, trades and candles stay together.
    released = all(r['research_admission_eligible'] for r in rows)
    return dict(status='RESEARCH_RELEASE_APPROVED' if released else 'BILLING_OR_QUALITY_QUARANTINE_RETAINED',
        rows=rows,provider_estimate_usd=str(sum((number(r['provider_estimate_usd']) for r in rows),Decimal(0))),
        actual_usage_usd=str(sum(number(r['actual_usage_usd']) for r in rows)) if all(r['actual_usage_usd'] is not None for r in rows) else None,
        credit_used_usd=str(sum(number(r['credit_used_usd']) for r in rows)) if all(r['credit_used_usd'] is not None for r in rows) else None,
        cash_usd=str(sum(number(r['cash_usd']) for r in rows)) if all(r['cash_usd'] is not None for r in rows) else None,
        reserved_usd=str(sum(number(r['reservation']['reserved_usd']) for r in rows)),
        inputs_sha256=digest(dict(manifests=values,diagnostics_sha256=digest(diagnostics),ledger=ledger_rows,
                                 records=provider_records,billing_review=billing_review,admission_review=admission_review)),
        research_admission_eligible=released,independent_continuity_restrictions_preserved=True,
        reservation_is_charge=False,redownloads=0,**SAFETY)


def release_bundle(result, *, root, contracts):
    """Create a separate admitted view only after verified complete review.
    Do not change old manifests, billing flags, archives or trading certificates.
    """
    if result['status'] != 'RESEARCH_RELEASE_APPROVED' or not result['research_admission_eligible']:
        raise ValueError('unresolved_reconciliation_cannot_release')
    values = {m['request_sha256']: m for m in manifests(root)}
    admitted = []
    for row in result['rows']:
        m = values[row['request_sha256']]
        if m['manifest_sha256'] != row['manifest_sha256']:
            raise ValueError('manifest_changed_after_billing_review')
        p = dict(row['request']); p['contracts'] = tuple(tuple(c) for c in p['contracts'])
        request = HistoricalRequest(**p); contract = contracts[request.contracts[0][2]]
        admitted.append(admit(Path(root)/'native-dbn/objects'/(row['archive_sha256']+'.dbn'),
            request=request,contract=contract,enabled_schemas=('definition','trades','ohlcv-1m'),
            review=dict(origin_review_reference=result['inputs_sha256'],request_sha256=request.sha256,
                definition_sha256=contract.metadata.definition_sha256,billing_status='RECONCILED',
                request_receipt_reference=row['provider_record']['provider_request_id'],
                evidence_kind='AUTHENTIC_ARCHIVED_RECORD',archive_sha256=row['archive_sha256'],
                retrieval_ns=m['retrieval_ns'],admission_ns=m['ingestion_ns'])))
    return admitted
