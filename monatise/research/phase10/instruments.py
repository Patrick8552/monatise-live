"""Candidate audit descriptors only. This registry cannot enable an instrument."""
from copy import deepcopy

CANDIDATES={
 'YM':dict(name='E-mini Dow',exchange='XCBT',tick_size='1',multiplier='5',price_unit='INDEX_POINTS',settlement='cash',contract_cycle='quarterly',specification='https://www.cmegroup.com/markets/equities/dow-jones/e-mini-dow.contractSpecs.html'),
 'RTY':dict(name='E-mini Russell 2000',exchange='XCME',tick_size='0.1',multiplier='50',price_unit='INDEX_POINTS',settlement='cash',contract_cycle='quarterly',specification='https://www.cmegroup.com/markets/equities/russell/e-mini-russell-2000.contractSpecs.html'),
 'CL':dict(name='WTI Crude Oil',exchange='XNYM',tick_size='0.01',multiplier='1000',price_unit='USD_PER_BARREL',settlement='physical',contract_cycle='monthly',specification='https://www.cmegroup.com/markets/energy/crude-oil/light-sweet-crude.contractSpecs.html'),
 'SI':dict(name='Silver',exchange='XCEC',tick_size='0.005',multiplier='5000',price_unit='USD_PER_TROY_OUNCE',settlement='physical',contract_cycle='product_specific_delivery_months',specification='https://www.cmegroup.com/markets/metals/precious/silver.contractSpecs.html'),
}

def audit_catalog():
    candidates=deepcopy(CANDIDATES)
    for row in candidates.values():
        row.update(analytical_support_enabled=False,dataset='GLBX.MDP3',native_definition_required=True,
            dated_session_calendar_required=True,independent_quality_calibration_required=True,
            live_operation_verified=False,regular_hours_reference='https://www.cmegroup.com/trading-hours.html',
            blockers=['exact_native_definition_and_expiry_review','dated_session_calendar_and_holidays','contract_schema_quality_calibration','genuine_live_validation'])
    return dict(version='phase10-instrument-audit-catalog-v1',supported_research_products=['GC','ES','NQ'],
        candidates=candidates,expansion_activated=False,subscription_changes=0)
