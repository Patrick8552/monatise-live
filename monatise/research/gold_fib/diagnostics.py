"""Counts are seed-level and episode-clustered; never trading performance claims."""
from collections import Counter, defaultdict
from math import ceil
from statistics import median
from datetime import datetime

from monatise.research.gold_fib import RATIOS


def distribution(values):
    xs=sorted(float(x) for x in values if x is not None)
    if not xs:
        return {'n':0,'min':None,'median':None,'p90':None,'max':None}
    return {'n':len(xs),'min':xs[0],'median':median(xs),
            'p90':xs[max(0,ceil(.9*len(xs))-1)],'max':xs[-1]}


def elapsed(a,b):
    return (datetime.fromisoformat(a)-datetime.fromisoformat(b)).total_seconds()


def summarize(rows):
    reasons=Counter(r['reason'] or 'SHADOW_VALID' for r in rows)
    slots=[s for r in rows for s in r['raw_slots']]
    return {
        'total_GoldSetupSeed_events':len(rows),
        'identifiable_active_H1_episode':sum(bool(r['anchor']['episode_identifiable']) for r in rows),
        'valid_A':sum(bool(r['anchor']['valid_a']) for r in rows),
        'valid_B':sum(bool(r['anchor']['valid_b']) for r in rows),
        'B_unconfirmed_at_parent_cutoff':reasons['B_UNCONFIRMED_AT_PARENT_CUTOFF'],
        'AB_geometry_rejected':reasons['H1_LEG_GEOMETRY_REJECTED'],
        'two_ATR_rejected':reasons['TWO_ATR_REJECTED'],
        'structure_confidence_rejected':reasons['STRUCTURE_CONFIDENCE_REJECTED'],
        'anchor_age_rejected':reasons['ANCHOR_AGE_REJECTED'],
        'H1_parent_expired':sum(r.get('expiry_checks',{}).get('H1_parent_expired',r['reason']=='H1_PARENT_EXPIRED') for r in rows),
        'M15_M5_expired':sum(r.get('expiry_checks',{}).get('M15_M5_expired',r['reason']=='M15_M5_EXPIRED') for r in rows),
        'valid_constrained_Fib_assessment':sum(r['valid_constrained_fib'] for r in rows),
        'pre_decision_candidate_admitted_counts':{str(i):sum(r.get('candidate_admitted_count',r['eligible_target_count'])==i for r in rows) for i in range(4)},
        'eligible_target_counts':{str(i):sum(r['eligible_target_count']==i for r in rows) for i in range(4)},
        'final_target_counts':{str(i):sum(r['final_target_count']==i for r in rows) for i in range(4)},
        'nearest_objective_RR_rejected_seeds':reasons['NEAREST_OBJECTIVE_RR_REJECTED'],
        'target_distance_ceiling_rejected_candidates':sum(s['rejection_reason']=='outside_mapping_safety' for s in slots),
        'target_distance_ceiling_rejected_seeds':sum(any(s['rejection_reason']=='outside_mapping_safety' for s in r['raw_slots']) for r in rows),
        'rejection_counts':dict(sorted(reasons.items())),
        'candidate_rejection_counts':dict(sorted(Counter(s['rejection_reason'] for s in slots if s['rejection_reason']).items())),
        'B_confirmation_latency_seconds':distribution(
            elapsed(r['anchor']['B']['known_at'],r['anchor']['B']['close_time'])
            for r in rows if r['anchor'].get('B')),
        'remaining_setup_eligibility_seconds':distribution(
            elapsed(r['expiry'],r['seed_observed_at']) for r in rows),
        'H1_leg_size_USD':distribution(r['anchor'].get('range_usd') for r in rows),
        'H1_leg_size_ATR_multiples':distribution(r['anchor'].get('range_atr_multiple') for r in rows),
        'ratio_distances':{str(ratio):{
            key:distribution(s.get(key) for s in slots if s['ratio']==ratio)
            for key in ('distance_usd','distance_pct','distance_atr','rr')}
            for ratio in RATIOS},
        'canonical_vs_F0':dict(sorted(Counter(
            (('CANONICAL_VALID' if r['canonical'].get('validation',{} ) and r['canonical']['validation']['eligible_for_shadow_decision'] else 'CANONICAL_REJECTED')
             + ' -> '+r['status']) for r in rows).items())),
        'reachability': 'NOT_MEASURED: requires causal future bars, spread/cost/fill model and a representative historical sample',
    }


def diagnostics(rows):
    # One original assessment per seed; lifecycle reassessments must be reported
    # separately, otherwise the denominator could be inflated by polling.
    ids=[r['setup_identifier'] for r in rows]
    if len(set(ids))!=len(ids):
        raise ValueError('duplicate seed events in diagnostic denominator')
    groups=defaultdict(list)
    for r in rows:
        groups[r['h1_episode_id'] or 'UNAVAILABLE:'+r['h1_context_id']+':'+r['anchor']['h1_snapshot_hash']].append(r)
    return {'seed_level':summarize(rows),
        'episode_cluster_count':sum(not key.startswith('UNAVAILABLE:') for key in groups),
        'unavailable_parent_clusters':sum(key.startswith('UNAVAILABLE:') for key in groups),
        'clusters':{key:summarize(group) for key,group in sorted(groups.items())},
        'episode_weighted':{key:{'seed_events':len(group),
            'any_valid_F0':any(r['status']=='SHADOW_VALID' for r in group),
            'any_valid_constrained_Fib':any(r['valid_constrained_fib'] for r in group)}
            for key,group in sorted(groups.items())},
        'interpretation':'Engineering counts are not estimates of historical availability, reachability or performance.'}
