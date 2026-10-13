"""Research diagnostics over the canonical typed preview; no GIL registration.

Databento is primary exchange-data input for this research. Existing production
provider roles are inherited, never replaced. Options cannot create LONG/SHORT.
"""
from ..models import SignalPreview, PreviewDecision, encode, digest
from . import SAFETY

REQUIRED_GATES=('higher_timeframe_structure','canonical_H1_fibonacci','liquidity_and_volume',
                'M15_M5_confirmation','valid_entry_trigger','risk_reward','broker_price_validation','execution_governance')


def integrate(*, technical_preview: SignalPreview | None, gates, basis, chain, greeks,
              provider_statuses, independently_validated_veto=None):
    reasons=[]
    # Missing/unknown observations never become PASS by boolean truthiness.
    for name in REQUIRED_GATES:
        if gates.get(name)!='PASS':reasons.append(name+':'+str(gates.get(name,'MISSING')))
    if technical_preview is None:reasons.append('canonical_technical_preview_missing')
    if basis['status']!='CERTIFIED':reasons.append('basis_not_certified')
    if chain['status']!='REVIEWED_SCOPE_COVERED':reasons.append('INSUFFICIENT_CHAIN_COVERAGE')
    if not greeks or any(g['status']!='VALIDATED_MODEL_SENSITIVITIES' for g in greeks):reasons.append('validated_options_sensitivities_missing')
    providers={name:provider_statuses.get(name,'UNAVAILABLE') for name in ('Databento','FlashAlpha','ThetaData','UnusualWhales')}
    for name,status in providers.items():
        if status!='AVAILABLE':reasons.append('provider_'+name+':'+status)
    # No scenario-based directional boosts. Independently supplied adverse
    # evidence must be a hash-bound reviewed finding and may only veto.
    effect='NO_DIRECTIONAL_CHANGE'
    if independently_validated_veto is not None:
        if (independently_validated_veto.get('status')!='INDEPENDENTLY_REVIEWED_ADVERSE_EVIDENCE'
                or not independently_validated_veto.get('review_reference')
                or len(independently_validated_veto.get('source_sha256',''))!=64):
            raise ValueError('independently_reviewed_hash_bound_veto_required')
        reasons.append('independently_validated_options_veto');effect='VETO'
    decision=PreviewDecision.NO_TRADE
    if not reasons and technical_preview.decision in {PreviewDecision.LONG,PreviewDecision.SHORT}:
        decision=technical_preview.decision
    if technical_preview is not None and technical_preview.decision==PreviewDecision.NO_TRADE:
        reasons.extend(technical_preview.rejection_reasons or ('canonical_preview_NO_TRADE',))
    return dict(schema='monatise-phase7-research-GIL-v1',decision=str(decision),options_effect=effect,
        technical_preview=encode(technical_preview),technical_gate_results=gates,
        grid_setup=None,entry_levels=None,analysis_expiry='IMMEDIATE_RESEARCH_ONLY',
        provider_statuses=providers,production_provider_hierarchy_changed=False,
        research_exchange_data_source='Databento',rejection_reasons=sorted(set(reasons)),
        inputs_sha256=digest(dict(technical_preview=technical_preview,gates=gates,basis=basis,
            chain=chain,greeks=greeks,provider_statuses=providers,veto=independently_validated_veto)),**SAFETY)
