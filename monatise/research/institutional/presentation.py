"""Pure research formatting; no publisher or Telegram client is imported."""
from . import SAFETY
from .models import encode,digest


def complete(result, *, market, institutional=None, mapping=None, missing=()):
    p=encode(result.get('preview',result));canonical=result.get('canonical') or {}
    if any(p.get(k,False) for k in SAFETY):raise ValueError('non_executable_research_preview_required')
    layers=canonical.get('layers') or {}
    # Only pass through fields actually produced by the canonical engine. No
    # reconstructed hierarchy or populated geometry from missing observations.
    value=dict(schema='monatise-phase5-preview-v1',asset=p['asset'],market=market,
        source_instrument=p.get('institutional_source_instrument'),broker_instrument=p['broker_instrument'],
        analysis_timestamp_ns=p['generated_ns'],h4_regime=canonical.get('regime') or (canonical.get('market_structure') or {}).get('regime'),
        h1_structure=canonical.get('market_structure') if canonical.get('analysis_timeframe')=='1h' else layers.get('h1'),
        m15_setup=canonical.get('liquidity') if canonical.get('setup_timeframe')=='15m' else layers.get('m15'),
        m5_trigger=canonical.get('trigger') if canonical.get('confirmation_timeframe')=='5m' else layers.get('m5'),
        m1_entry_zone=p.get('entry_zone'),institutional_evidence=institutional,
        fibonacci_evidence=canonical.get('fibonacci'),liquidity_evidence=canonical.get('liquidity'),
        direction=p.get('directional_bias') if p.get('directional_bias')!='unavailable' else None,
        decision=p['decision'],reference_entry=p.get('proposed_entry'),structural_stop=p.get('structural_stop'),
        take_profit_targets=p.get('take_profits') or None,risk_to_reward=p.get('reward_risk'),
        expiration_ns=p.get('expiration_ns'),data_quality_status=p['evidence_kind'],
        missing_evidence=list(missing),rejection_reasons=p.get('rejection_reasons',[]),
        mapping_status=(mapping or {}).get('status',p['mapping_status']),
        mapping_uncertainty=(mapping or {}).get('uncertainty'),
        analytical_qualification=('QUALIFIED_RESEARCH_GEOMETRY' if p['decision'] in {'LONG','SHORT'} else
            'BLOCKED_AUTHENTIC_INPUTS' if missing else 'CANONICAL_NO_TRADE'),
        evidence_kind=p['evidence_kind'],source_provenance=p.get('source_provenance',[]),
        canonical_path=p.get('canonical_path'),limitations=p.get('limitations',[]),
        canonical_result_sha256=digest(canonical) if canonical else None,**SAFETY)
    return value


def text_preview(value):
    if value.get('schema')!='monatise-phase5-preview-v1' or any(value.get(k,False) for k in SAFETY):
        raise ValueError('research_presentation_boundary_required')
    fields=(('Asset','asset'),('Market','market'),('Source instrument','source_instrument'),
        ('Broker instrument','broker_instrument'),('Analysis timestamp (UTC ns)','analysis_timestamp_ns'),
        ('H4 regime','h4_regime'),('H1 structure','h1_structure'),('M15 setup','m15_setup'),
        ('M5 trigger','m5_trigger'),('M1 entry zone','m1_entry_zone'),('Institutional evidence','institutional_evidence'),
        ('Fibonacci evidence','fibonacci_evidence'),('Liquidity evidence','liquidity_evidence'),
        ('Direction','direction'),('Decision','decision'),('Reference entry','reference_entry'),
        ('Structural stop','structural_stop'),('Take-profit targets','take_profit_targets'),('Risk-to-reward','risk_to_reward'),
        ('Expiration (UTC ns)','expiration_ns'),('Data quality','data_quality_status'),('Missing evidence','missing_evidence'),
        ('Rejection reasons','rejection_reasons'),('Mapping status','mapping_status'),('Mapping uncertainty','mapping_uncertainty'),
        ('Analytical qualification','analytical_qualification'))
    import json
    def render(v):
        return 'unavailable' if v is None else json.dumps(v,sort_keys=True) if isinstance(v,(list,dict,tuple)) else str(v)
    return '\n'.join(['RESEARCH ONLY — '+value['evidence_kind']]+[label+': '+render(value.get(key)) for label,key in fields]
                     +['Publication eligible: FALSE','Approval eligible: FALSE','Execution eligible: FALSE'])
