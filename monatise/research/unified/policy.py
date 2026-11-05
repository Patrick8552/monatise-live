"""Versioned parameters. Defaults are deliberately unresolved, not trading defaults."""
from dataclasses import dataclass, fields
from decimal import Decimal
from .models import MINUTE, digest


@dataclass(frozen=True)
class Policy:
    version: str = 'unified-research-v1'
    behavior_checked: bool = False
    rationale_hash: str = ''
    pivot_radius: int | None = None
    baseline_bars: int | None = None
    quote_age_ns: int | None = None
    trigger_bars: int | None = None
    entry_tolerance_ticks: int | None = None
    stop_buffer_ticks: int | None = None
    fee_ticks_per_side: Decimal | None = None
    slippage_ticks_per_side: Decimal | None = None
    min_net_rr: Decimal | None = None
    volume_mode: str | None = None
    news_required: bool = True
    allow_neutral_h4: bool = False
    allow_neutral_h1_c: bool = False
    allow_neutral_m15: bool = True
    allow_mixed_transition: bool = False
    outcome_mode: str = 'MINUTE_BAR'

    def __post_init__(self):
        for name in ('behavior_checked','news_required','allow_neutral_h4','allow_neutral_h1_c','allow_neutral_m15','allow_mixed_transition'):
            if type(getattr(self,name)) is not bool:
                raise ValueError('boolean_policy_field_required:'+name)
        if not isinstance(self.version,str) or not self.version:
            raise ValueError('versioned_policy_required')
        for key in ('pivot_radius', 'baseline_bars', 'quote_age_ns', 'trigger_bars', 'entry_tolerance_ticks', 'stop_buffer_ticks'):
            value = getattr(self, key)
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError('positive_integer_parameter_required:'+key)
        for key in ('fee_ticks_per_side', 'slippage_ticks_per_side', 'min_net_rr'):
            value = getattr(self, key)
            if value is not None and (not value.is_finite() or value < 0):
                raise ValueError('nonnegative_finite_parameter_required:'+key)
        if self.min_net_rr is not None and self.min_net_rr <= 0:
            raise ValueError('positive_net_rr_required')
        if self.volume_mode not in (None, 'AGGRESSOR_ROBUST', 'EXECUTED_BAR_PARTICIPATION'):
            raise ValueError('explicit_volume_mode_required')
        if self.outcome_mode not in ('MINUTE_BAR','NATIVE_L1'):
            raise ValueError('explicit_outcome_mode_required')

    @property
    def missing(self):
        names = ('pivot_radius', 'baseline_bars', 'quote_age_ns', 'trigger_bars',
                 'entry_tolerance_ticks', 'stop_buffer_ticks', 'fee_ticks_per_side',
                 'slippage_ticks_per_side', 'min_net_rr', 'volume_mode')
        result = [n for n in names if getattr(self, n) is None]
        if not self.behavior_checked or len(self.rationale_hash) != 64:
            result.append('BEHAVIOR_RATIONALE_NOT_RECORDED')
        return tuple(result)

    @property
    def hash(self):
        return digest(self)


def exploratory_policy(*, rationale_hash, volume_mode='AGGRESSOR_ROBUST'):
    """Explicit opt-in hypothesis, never a calibrated or production policy.

    Radius 2 reproduces the reviewed native descriptive baseline. Twelve M5 bars
    are one H1 window. Price buffers are one native tick. Quote age is the
    existing finite-capture heartbeat period. One M5 trigger bar is the entry
    permission horizon. Costs are declared tick-equivalent sensitivity assumptions.
    The symmetric net-1R floor is an economic research constraint, not an edge.
    See docs/unified/parameters.md for behavioral and data limitations.
    """
    return Policy(behavior_checked=True, rationale_hash=rationale_hash, pivot_radius=2,
                  baseline_bars=12, quote_age_ns=5*10**9, trigger_bars=1,
                  entry_tolerance_ticks=1, stop_buffer_ticks=1,
                  fee_ticks_per_side=Decimal(1), slippage_ticks_per_side=Decimal(1),
                  min_net_rr=Decimal(1), volume_mode=volume_mode, allow_mixed_transition=True)
