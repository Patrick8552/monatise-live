"""Independent A/B/C permission evaluations over shared causal observations."""
from .models import State, Side
from .evidence import structural_breaks


def _direction(side):
    return State.UP if side == Side.BUY else State.DOWN


def _confirmed_transition(f, side, tick):
    events = structural_breaks(f, tick)
    return bool(events and events[-1][1].side == side
                and side.sign*(f.bars[-1].close-events[-1][1].level) >= tick)


def context(observation, frames, policy, tick):
    expected = _direction(observation.side)
    reasons = []
    h4, h1, m15, m5 = (frames[tf] for tf in ('4h', '1h', '15m', '5m'))
    category = 'TREND_CONTEXT'
    if h4.state == State.UNAVAILABLE:
        reasons.append('H4_UNAVAILABLE')
    elif h4.state not in (expected,):
        if h4.state == State.NEUTRAL and policy.allow_neutral_h4:
            category = 'NEUTRAL_H4_CONTEXT'
        elif h4.state == State.MIXED and policy.allow_mixed_transition and _confirmed_transition(h4, observation.side, tick):
            category = 'CONFIRMED_H4_TRANSITION'
        else:
            reasons.append('H4_OPPOSED_OR_UNPERMITTED')
    if h1.state == State.UNAVAILABLE:
        reasons.append('H1_UNAVAILABLE')
    elif observation.pathway == 'B' and h1.state != expected:
        reasons.append('B_H1_NOT_ALIGNED')
    elif observation.pathway == 'C' and h1.state == State.NEUTRAL and policy.allow_neutral_h1_c:
        pass
    elif observation.pathway != 'B' and h1.state != expected:
        if not (policy.allow_mixed_transition and h1.state == State.MIXED
                and _confirmed_transition(h1, observation.side, tick)):
            reasons.append('H1_DIRECTION_NOT_CONFIRMED')
    if m15.state == State.UNAVAILABLE:
        reasons.append('M15_UNAVAILABLE')
    elif observation.pathway == 'B' and m15.state != expected:
        reasons.append('B_M15_NOT_ALIGNED')
    elif observation.pathway != 'B' and m15.state != expected:
        if not (m15.state == State.NEUTRAL and policy.allow_neutral_m15):
            # A mixed frame is never treated as neutral. Only its separately
            # confirmed matching break can grant this explicit transition rule.
            if not (m15.state == State.MIXED and policy.allow_mixed_transition
                    and _confirmed_transition(m15, observation.side, tick)):
                reasons.append('M15_OPPOSED_OR_UNPERMITTED')
    if observation.pathway == 'B' and m5.state != expected:
        reasons.append('B_M5_NOT_ALIGNED')
    if m5.state == State.UNAVAILABLE:
        reasons.append('M5_UNAVAILABLE')
    return tuple(reasons), category


def model_a(observation, frames, policy, tick):
    if observation.pathway != 'A':
        raise ValueError('model_a_observation_required')
    return context(observation, frames, policy, tick)


def model_b(observation, frames, policy, tick):
    if observation.pathway != 'B':
        raise ValueError('model_b_observation_required')
    return context(observation, frames, policy, tick)


def model_c(observation, frames, policy, tick):
    if observation.pathway != 'C':
        raise ValueError('model_c_observation_required')
    reasons, category = context(observation, frames, policy, tick)
    kinds = [e.kind for e in observation.events]
    if observation.canonical and not ('SWEEP_REJECTION' in kinds and 'BREAK' in kinds):
        reasons += ('C_SWEEP_REVERSAL_EVIDENCE_MISSING',)
    return reasons, category


EVALUATORS = {'A': model_a, 'B': model_b, 'C': model_c}
