"""Source, participation and economic gates; no account sizing or order intent."""
from .models import fixed_decimal, current_quote
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from statistics import median
from .models import Candidate, Plan, Target, WIDTHS, Side, TERMINAL


def round_tick(price, tick, up):
    return (price/tick).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)*tick


def volume_support(observation, snapshot, policy, frames):
    if not observation.trigger:
        return ('TRIGGER_INCOMPLETE',)
    bar = next((b for b in frames['5m'].bars if b.key == observation.trigger.bar_id), None)
    if bar is None:
        return ('TRIGGER_BAR_UNAVAILABLE',)
    if policy.volume_mode == 'EXECUTED_BAR_PARTICIPATION':
        preceding = [b for b in frames['5m'].bars if b.close_ns <= bar.open_ns][-policy.baseline_bars:]
        if len(preceding) < policy.baseline_bars:
            return ('VOLUME_BASELINE_INSUFFICIENT',)
        if bar.volume < median(b.volume for b in preceding) or bar.volume <= 0:
            return ('EXECUTED_BAR_VOLUME_NOT_CONFIRMED',)
        # Direction comes from completed price rejection, not unsigned volume.
        if observation.side.sign*(bar.close-bar.open) <= 0:
            return ('REJECTION_PRICE_DIRECTION_NOT_CONFIRMED',)
        return ()
    start, end = bar.open_ns, bar.close_ns
    if not any(c.kind == 'trades' and c.covers(start, end, snapshot.cutoff_ns) for c in snapshot.coverage):
        return ('EXECUTED_FLOW_WINDOW_NOT_COVERED',)
    trades = [t for t in snapshot.trades if start <= t.receive_ns < end]
    if not trades or any(t.quality for t in trades):
        return ('EXECUTED_FLOW_UNAVAILABLE_OR_FLAGGED',)
    buy = sum(t.size for t in trades if t.aggressor == 'BUY')
    sell = sum(t.size for t in trades if t.aggressor == 'SELL')
    unknown = sum(t.size for t in trades if t.aggressor is None)
    # Sign must remain directional even if every unknown execution opposed it.
    if observation.side.sign*(buy-sell) <= unknown:
        return ('DIRECTIONAL_FLOW_NOT_ROBUST_TO_UNKNOWN',)
    return ()


@fixed_decimal
def economic_plan(observation, snapshot, policy, frames):
    reasons = []
    q = current_quote(snapshot)
    if q is None or q.quality:
        return None, ('ENTRY_QUOTE_UNAVAILABLE',)
    if snapshot.cutoff_ns-q.receive_ns > policy.quote_age_ns:
        return None, ('ENTRY_QUOTE_STALE',)
    inst = snapshot.instrument; tick = inst.tick; side = observation.side; d = side.sign
    trigger_bar = next((b for b in frames['5m'].bars if b.key == observation.trigger.bar_id), None)
    if trigger_bar is None or observation.stop_level is None:
        return None, ('STRUCTURAL_INVALIDATION_MISSING',)
    spread = q.ask-q.bid
    slip = policy.slippage_ticks_per_side*tick
    tolerance = policy.entry_tolerance_ticks*tick
    # Permitted entry derives from completed trigger close plus observed/modeled
    # spread and registered drift. Costs are in modeled fills, never added twice.
    cap = trigger_bar.close+d*(spread+tolerance+slip)
    current = (q.ask if side == Side.BUY else q.bid)+d*slip
    if d*(current-cap) > 0:
        return None, ('MISSED_ENTRY',)
    low, high = sorted((current, cap))
    entry = round_tick(high if side == Side.BUY else low, tick, side == Side.BUY)
    stop = round_tick(observation.stop_level-d*policy.stop_buffer_ticks*tick, tick, side == Side.SELL)
    current_price = q.bid if side == Side.BUY else q.ask
    if d*(current_price-stop) <= 0 or d*(entry-stop) <= 0:
        return None, ('STRUCTURAL_STOP_INVALIDATED',)
    references = {}
    for f in frames.values():
        for pivot in f.pivots:
            if (pivot.kind == ('HIGH' if side == Side.BUY else 'LOW')
                    and pivot.available_ns <= snapshot.cutoff_ns and d*(pivot.price-entry) > 0):
                existing = references.get(pivot.price)
                if existing is None or (pivot.available_ns, pivot.key) < (existing.available_ns, existing.reference_id):
                    references[pivot.price] = Target(pivot.price, pivot.key, pivot.available_ns)
    targets = tuple(sorted(references.values(), key=lambda t: d*t.price)[:3])
    if not targets:
        return None, ('NO_OBSERVED_TARGET_AHEAD',)
    nearest = targets[0]
    # Only information known after arming matters. A touch that established a
    # historical swing before arming is never mistaken for a missed opportunity.
    watch_start = max(observation.armed_ns, nearest.available_ns)
    for b in frames['1m'].bars:
        if b.open_ns >= watch_start and b.close_ns <= observation.trigger.at_ns:
            reached = b.high >= nearest.price if side == Side.BUY else b.low <= nearest.price
            if reached:
                return None, ('TARGET_PASSED_POST_ARM_BEFORE_SELECTION',)
    for t in snapshot.trades:
        if t.receive_ns >= max(watch_start, observation.trigger.at_ns) and d*(t.price-nearest.price) >= 0:
            return None, ('TARGET_PASSED_POST_ARM_BEFORE_SELECTION',)
    fee = policy.fee_ticks_per_side*tick*inst.multiplier
    stop_fill = stop-d*slip
    risk = d*(entry-stop_fill)*inst.multiplier+2*fee
    rr = tuple((d*((t.price-d*slip)-entry)*inst.multiplier-2*fee)/risk for t in targets)
    if risk <= 0 or rr[0] < policy.min_net_rr:
        return None, ('NET_RR_TO_NEAREST_TARGET_INSUFFICIENT',)
    cost = (spread+2*slip)*inst.multiplier+2*fee
    expires = min(observation.trigger.available_ns+policy.trigger_bars*WIDTHS['5m'],
                  snapshot.schedule.closes_after(observation.trigger.at_ns-1), inst.expiry_ns)
    return Plan(observation.opportunity_id, side, entry, low, high, stop, targets,
                rr, risk, cost, cost/risk, snapshot.cutoff_ns-observation.trigger.available_ns,
                observation.trigger.key, observation.trigger.available_ns, observation.armed_ns,
                expires, observation.trigger.bar_id,
                tuple(dict.fromkeys(e.key for e in observation.events)),
                'EXPLICIT_TICK_EQUIVALENT_RESEARCH_COSTS', spread), tuple(reasons)


def validate(observation, snapshot, policy, frames):
    reasons = list(observation.reasons)
    if not observation.canonical:
        reasons.append('OPPORTUNITY_IDENTITY_AMBIGUOUS')
    if policy.missing:
        reasons.append('POLICY_NOT_READY')
    if snapshot.quality:
        reasons.append('SOURCE_QUALITY_UNRESOLVED')
    if snapshot.cutoff_ns >= snapshot.instrument.expiry_ns:
        reasons.append('CONTRACT_EXPIRED')
    if observation.stage != 'TRIGGERED':
        reasons.append('LIFECYCLE_'+observation.stage)
    if not snapshot.schedule.contains(snapshot.cutoff_ns, snapshot.cutoff_ns+1):
        reasons.append('OUTSIDE_REVIEWED_TRADING_SESSION')
    if policy.news_required and not snapshot.news_coverage:
        reasons.append('NEWS_CALENDAR_UNAVAILABLE')
    if any(n.available_ns <= snapshot.cutoff_ns and n.start_ns <= snapshot.cutoff_ns < n.end_ns for n in snapshot.news):
        reasons.append('SCHEDULED_NEWS_WINDOW')
    if reasons:
        return Candidate(observation, None, tuple(sorted(set(reasons))))
    reasons.extend(volume_support(observation, snapshot, policy, frames))
    plan = None
    if not reasons:
        plan, codes = economic_plan(observation, snapshot, policy, frames)
        reasons.extend(codes)
    if plan and snapshot.cutoff_ns >= plan.expires_ns:
        reasons.append('TRIGGER_EXPIRED')
    return Candidate(observation, plan, tuple(sorted(set(reasons))))


@fixed_decimal
def final_revalidate(plan, snapshot, policy):
    reasons = []
    if policy.missing or snapshot.quality:
        reasons.append('FINAL_POLICY_OR_SOURCE_UNAVAILABLE')
    if policy.missing:
        return tuple(reasons)
    if snapshot.cutoff_ns >= min(plan.expires_ns, snapshot.instrument.expiry_ns):
        reasons.append('FINAL_EXPIRED')
    if not snapshot.schedule.contains(snapshot.cutoff_ns, snapshot.cutoff_ns+1):
        reasons.append('FINAL_SESSION_CLOSED')
    if policy.news_required and not snapshot.news_coverage:
        reasons.append('FINAL_NEWS_UNAVAILABLE')
    if any(n.available_ns <= snapshot.cutoff_ns and n.start_ns <= snapshot.cutoff_ns < n.end_ns for n in snapshot.news):
        reasons.append('FINAL_NEWS_WINDOW')
    q = current_quote(snapshot)
    if q is None or q.quality or snapshot.cutoff_ns-q.receive_ns > (policy.quote_age_ns or 0):
        reasons.append('FINAL_QUOTE_UNAVAILABLE_OR_STALE')
    else:
        d = plan.side.sign; market = q.ask if plan.side == Side.BUY else q.bid
        if q.ask-q.bid > plan.spread_points:
            reasons.append('FINAL_SPREAD_WIDENED')
        modeled = market+d*policy.slippage_ticks_per_side*snapshot.instrument.tick
        if not plan.entry_low <= modeled <= plan.entry_high:
            reasons.append('FINAL_ENTRY_OUTSIDE_FROZEN_ZONE')
        if d*(market-plan.stop) <= 0:
            reasons.append('FINAL_STOP_INVALIDATED')
        if d*(market-plan.targets[0].price) >= 0:
            reasons.append('FINAL_TARGET_PASSED')
    d = plan.side.sign
    for t in snapshot.trades:
        if t.receive_ns >= plan.trigger_ns:
            if d*(t.price-plan.stop) <= 0:
                reasons.append('FINAL_STOP_BREACHED_IN_WINDOW')
            if d*(t.price-plan.targets[0].price) >= 0:
                reasons.append('FINAL_TARGET_PREVIOUSLY_PASSED')
    for b in snapshot.bars:
        if b.timeframe == '1m' and b.close_ns > plan.trigger_ns:
            stop_hit = b.low <= plan.stop if d > 0 else b.high >= plan.stop
            target_hit = b.high >= plan.targets[0].price if d > 0 else b.low <= plan.targets[0].price
            if stop_hit or target_hit:
                reasons.append('FINAL_WINDOW_INTRABAR_AMBIGUOUS' if b.open_ns < plan.trigger_ns else
                               'FINAL_STOP_OR_TARGET_PREVIOUSLY_PASSED')
    return tuple(reasons)
