"""Pure eligibility-first dominance. Labels/IDs never resolve an economic tie."""
from .models import Candidate, encode, digest


def dominates(a, b):
    if a.context_category != b.context_category or a.plan.cost_model != b.plan.cost_model:
        return False
    x = (a.plan.net_rr[0], -a.plan.cost_risk_ratio, -a.plan.lateness_ns)
    y = (b.plan.net_rr[0], -b.plan.cost_risk_ratio, -b.plan.lateness_ns)
    return all(u >= v for u, v in zip(x, y)) and any(u > v for u, v in zip(x, y))


def arbitrate(candidates):
    eligible = [c for c in candidates if c.eligible]
    groups = {}
    for c in eligible:
        groups.setdefault(c.observation.opportunity_id, []).append(c)
    representatives = []
    audit = []
    for oid, group in sorted(groups.items()):
        by_plan = {}
        for c in group:
            # Pathway labels sharing an identical plan add no independent votes.
            terms = encode(c.plan)
            terms.pop('evidence_ids')
            by_plan.setdefault((digest(terms), c.context_category), []).append(c)
        plans = [sorted(g, key=lambda c: (c.observation.detected_ns, c.observation.pathway))[0] for g in by_plan.values()]
        if len(plans) == 1:
            selected = plans[0]
        else:
            winners = [c for c in plans if all(c is other or dominates(c, other) for other in plans)]
            selected = winners[0] if len(winners) == 1 else None
        if selected is None:
            audit.append({'opportunity_id': oid, 'reason': 'INCOMPARABLE_SAME_EPISODE_PLANS'})
        else:
            representatives.append(selected)
            audit.append({'opportunity_id': oid, 'pathways': sorted({c.observation.pathway for c in group}),
                          'unique_evidence': sorted({e for c in group for e in c.plan.evidence_ids}),
                          'deduplicated_candidates': len(group)-1})
    if len({c.observation.side for c in eligible}) > 1:
        return None, 'OPPOSING_ELIGIBLE_OPPORTUNITIES', audit
    if any(x.get('reason') == 'INCOMPARABLE_SAME_EPISODE_PLANS' for x in audit):
        return None, 'INCOMPARABLE_SAME_EPISODE_PLANS', audit
    if not representatives:
        return None, 'NO_ELIGIBLE_TRIGGERED_OPPORTUNITY', audit
    if len({c.observation.side for c in representatives}) > 1:
        return None, 'OPPOSING_ELIGIBLE_OPPORTUNITIES', audit
    if len(representatives) == 1:
        return representatives[0], 'UNIQUE_ELIGIBLE_OPPORTUNITY', audit
    winners = [c for c in representatives if all(c is other or dominates(c, other) for other in representatives)]
    if len(winners) != 1:
        return None, 'NO_UNIQUE_DOMINANT_OPPORTUNITY', audit
    return winners[0], 'UNIQUE_DOMINANT_OPPORTUNITY', audit


def earliest_baseline(candidates):
    """Registered comparison only: oldest still-valid trigger; conflict/tie abstains."""
    groups = {}
    for c in candidates:
        if c.eligible:
            groups.setdefault(c.observation.opportunity_id, []).append(c)
    representatives = []; audit = []
    for _, group in sorted(groups.items()):
        selected, _, records = arbitrate(group)
        audit.extend(records)
        if selected is not None:
            representatives.append(selected)
    if not representatives:
        return None, 'NO_ELIGIBLE_TRIGGERED_OPPORTUNITY', audit
    if len({c.observation.side for c in representatives}) > 1:
        return None, 'OPPOSING_ELIGIBLE_OPPORTUNITIES', audit
    oldest = min(c.plan.trigger_ns for c in representatives)
    tied = [c for c in representatives if c.plan.trigger_ns == oldest]
    if len(tied) != 1:
        return None, 'BASELINE_TRIGGER_TIME_TIE', audit
    return tied[0], 'BASELINE_EARLIEST_STILL_ELIGIBLE', audit
