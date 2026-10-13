"""Actual canonical decisions behind reviewed authentic input boundaries."""
from ..signals import broker_preview,crypto_preview
from ..models import digest,hash_required
from . import SAFETY


async def evaluate_broker(*,asset,instrument,cutoff_ns,evidence=None,positioning=None,
                          institutional_context=None,allow_engineering=False):
    base=dict(asset=asset,instrument=instrument,canonical=None,preview=None,entry=None,stop=None,targets=None,
              status='BLOCKED_AUTHENTIC_INPUTS',canonical_evaluation_attempted=False,
              institutional_context=institutional_context,institutional_context_used_for_scoring=False,**SAFETY)
    if evidence is None:
        return dict(base,rejection_reasons=['genuine_broker_candles_unavailable'])
    if evidence.evidence_kind!='AUTHENTIC_ARCHIVED_RECORD' and not allow_engineering:
        return dict(base,status='REJECTED_QUALITY',rejection_reasons=['engineering_fixture_cannot_enter_authentic_evaluation'])
    try:
        evidence.rows(expected=instrument,now_ns=cutoff_ns)
        if evidence.confirmation_ns is not None and evidence.confirmation_ns>cutoff_ns:
            raise ValueError('confirmation_not_available_at_cutoff')
    except (ValueError,TypeError,KeyError,ArithmeticError) as exc:
        return dict(base,status='REJECTED_QUALITY',rejection_reasons=[str(exc)],input_sha256=digest(evidence))
    if asset in {'ES','NQ'} and not positioning:
        return dict(base,rejection_reasons=['canonical_primary_index_positioning_missing'],input_sha256=digest(evidence))
    raw=await broker_preview(asset=asset,instrument=instrument,now_ns=cutoff_ns,evidence=evidence,
        positioning=positioning,include_canonical=True)
    p=raw['preview'];canonical=raw['canonical']
    if canonical is None:
        return dict(base,status='REJECTED_QUALITY',preview=p,rejection_reasons=p['rejection_reasons'],
                    input_sha256=digest(evidence))
    decision=p['decision']
    status=decision if decision in {'LONG','SHORT','NO_TRADE'} else 'REJECTED_QUALITY'
    return dict(base,status=status,canonical_evaluation_attempted=True,canonical=canonical,preview=p,
        entry=p['proposed_entry'],stop=p['structural_stop'],targets=p['take_profits'] or None,
        input_sha256=digest(dict(evidence=evidence,positioning=positioning,cutoff_ns=cutoff_ns)),
        rejection_reasons=p['rejection_reasons'],evidence_kind=evidence.evidence_kind,
        result_kind='ENGINEERING_CANONICAL_CODE_PATH' if allow_engineering and evidence.evidence_kind=='ENGINEERING_SYNTHETIC'
                    else 'AUTHENTIC_CANONICAL_ENGINE_RESULT',strategy_profitability=None)


def evaluate_crypto(*,asset,cutoff_ns,evidence=None,derivatives=None,allow_engineering=False):
    if evidence is None or derivatives is None:
        return dict(asset=asset,status='BLOCKED_AUTHENTIC_INPUTS',canonical=None,
                    rejection_reasons=['native_crypto_inputs_missing'],**SAFETY)
    if evidence.evidence_kind!='AUTHENTIC_ARCHIVED_RECORD' and not allow_engineering:
        return dict(asset=asset,status='REJECTED_QUALITY',canonical=None,
                    rejection_reasons=['engineering_fixture_cannot_enter_authentic_evaluation'],**SAFETY)
    try:
        hash_required(derivatives.get('_source_sha256'))
        if (derivatives.get('_evidence_kind')!=evidence.evidence_kind
                or type(derivatives.get('_available_ns')) is not int
                or not 0<=cutoff_ns-derivatives['_available_ns']<=60*10**9
                or not {'open_interest','open_interest_change_pct','cvd_delta','funding_rate',
                        'order_book_imbalance','liquidation_short_usd','liquidation_long_usd'}<=derivatives.keys()):
            raise ValueError('reviewed_crypto_derivative_inputs_incomplete_or_unavailable')
    except (ValueError,TypeError,AttributeError) as exc:
        return dict(asset=asset,status='REJECTED_QUALITY',canonical=None,rejection_reasons=[str(exc)],**SAFETY)
    raw=crypto_preview(asset=asset,now_ns=cutoff_ns,evidence=evidence,derivatives=derivatives)
    p=raw['preview']
    return dict(asset=asset,status='NO_TRADE' if raw.get('canonical_decision') else 'REJECTED_QUALITY',
                canonical=raw.get('canonical_decision'),preview=p,analytical_stages=raw.get('analytical_stages'),
                rejection_reasons=p['rejection_reasons'],result_kind='ENGINEERING_CANONICAL_CODE_PATH' if evidence.evidence_kind=='ENGINEERING_SYNTHETIC'
                else 'AUTHENTIC_CANONICAL_ENGINE_RESULT',structural_execution_plan_available=False,**SAFETY)
