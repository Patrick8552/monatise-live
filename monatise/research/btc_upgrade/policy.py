"""Explicit research assumptions; none are calibrated broker defaults."""
from dataclasses import dataclass,field
from decimal import Decimal as D
from monatise.research.unified.policy import Policy
from monatise.research.unified.models import digest,MINUTE,NS

@dataclass(frozen=True)
class RegimePolicy:
    lookback:int=20
    trend_efficiency:D=D('.30')
    trend_chop_max:D=D('50')
    range_efficiency_max:D=D('.25')
    range_chop_min:D=D('55')
    edge_fraction:D=D('.15')
    boundary_drift_fraction:D=D('.20')
    min_edge_touches:int=2
    confirmation_closes:int=2
    def __post_init__(self):
        if type(self.lookback) is not int or not 20<=self.lookback<=100:raise ValueError('REGIME_LOOKBACK_REQUIRED')
        if any(type(getattr(self,k)) is not int or getattr(self,k)<1 for k in ('min_edge_touches','confirmation_closes')):raise ValueError('REGIME_COUNTS_REQUIRED')
        for k in ('trend_efficiency','range_efficiency_max','edge_fraction','boundary_drift_fraction'):
            if not D(0)<getattr(self,k)<D(1):raise ValueError('BOUNDED_REGIME_FRACTION_REQUIRED')
        if not D(0)<self.trend_chop_max<self.range_chop_min<D(100):raise ValueError('SEPARATED_REGIME_THRESHOLDS_REQUIRED')

@dataclass(frozen=True)
class RiskPolicy:
    max_contracts:int=1
    max_trade_risk_usd:D=D('1000')
    max_open_risk_usd:D=D('1000')
    max_daily_loss_usd:D=D('2000')
    range_stop_buffer_ticks:int=2
    def __post_init__(self):
        if type(self.max_contracts) is not int or not 1<=self.max_contracts<=10:raise ValueError('BOUNDED_RESEARCH_INVENTORY_REQUIRED')
        if type(self.range_stop_buffer_ticks) is not int or self.range_stop_buffer_ticks<1:raise ValueError('RANGE_STOP_BUFFER_REQUIRED')
        if any(not v.is_finite() or v<=0 for v in (self.max_trade_risk_usd,self.max_open_risk_usd,self.max_daily_loss_usd)):raise ValueError('FINITE_RISK_CAPS_REQUIRED')

@dataclass(frozen=True)
class BTCPolicy:
    trend:Policy
    regime:RegimePolicy=field(default_factory=RegimePolicy)
    risk:RiskPolicy=field(default_factory=RiskPolicy)
    range_enabled:bool=False
    cost_basis:str='UNVERIFIED_RESEARCH_ASSUMPTIONS'
    analysis_quote_age_ns:int=60*NS
    def __post_init__(self):
        if type(self.analysis_quote_age_ns) is not int or self.analysis_quote_age_ns<=0:raise ValueError('POSITIVE_ANALYSIS_QUOTE_AGE_REQUIRED')
        if self.trend.missing:raise ValueError('EXPLICIT_TREND_RESEARCH_POLICY_REQUIRED')
        if self.trend.outcome_mode!='NATIVE_L1':raise ValueError('OBSERVED_NATIVE_L1_OUTCOMES_REQUIRED')
        if not self.trend.news_required:raise ValueError('BTC_UPGRADE_REQUIRES_REVIEWED_NEWS_COVERAGE')
        if type(self.range_enabled) is not bool:raise ValueError('EXPLICIT_RANGE_OPT_IN_REQUIRED')
        if self.cost_basis!='UNVERIFIED_RESEARCH_ASSUMPTIONS':raise ValueError('VERIFIED_BROKER_COST_CLAIM_REQUIRES_UNIMPLEMENTED_BROKER_CALIBRATION')
    @property
    def hash(self):return digest(self)
