"""Local, non-executable H1-Fib F0 research decisions. GIL is intentionally absent."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from monatise.application.hierarchy.adapter import CanonicalEvidenceAdapter, HierarchicalAnalysisRequest
from monatise.application.hierarchy.models import EvidenceBundle
from monatise.application.take_profit import MultiTPConfiguration, build_plan, decimal, timestamp
from monatise.application.target_evidence import candidate, crypto_layer_candidates
from monatise.engines.fibonacci_liquidity import FibonacciLiquidityEngine, FibonacciRequest
from monatise.research.gold_fib import ENGINE_VERSION, POLICY_ID, RATIOS
from monatise.research.gold_fib.episode import GoldH1StructuralLegSelector, H1StructuralEpisodeAdapter
from monatise.research.gold_fib.models import FrozenRecord, digest


ISOLATION = {k: False for k in (
    'publication_enabled', 'approval_eligible', 'pending_order_eligible',
    'execution_enabled', 'production_integrated', 'gil_target_modification_enabled')}


def target_rejection(c, *, entry, sign, now, config):
    """Exactly the build_plan admission rules; boundary parity is regression-tested."""
    if (c.price - entry) * sign <= 0:
        return 'wrong_side'
    if c.observed_at > now + timedelta(seconds=5) or now - c.observed_at > timedelta(hours=5):
        return 'stale_or_future'
    if c.confidence < Decimal('.35') or c.structural_relevance < Decimal('.4'):
        return 'insufficient_evidence'
    if abs(c.price - entry) / entry > config.max_relative_target_distance:
        return 'outside_mapping_safety'
    return None


class H1FibF0:
    def __init__(self):
        self._frozen = {}

    def assess(self, seed, *, canonical, at=None):
        contexts, prepared, layers = seed.objects()
        now = timestamp(at or seed.observed_at)
        if now < seed.observed_at:
            raise ValueError('assessment cannot precede seed')
        layer = seed.parent.objects()[2]
        entry, stop = decimal(prepared.reference_entry), decimal(prepared.final_stop)
        risk, sign = abs(entry - stop), Decimal(1 if prepared.direction == 'long' else -1)
        tick = decimal(seed.record.data['broker_units']['tick_size'])
        # Research never reads environment flags or management configuration.
        config = replace(MultiTPConfiguration(), enabled=True,
            minimum_rr=max(Decimal('1.5'), decimal(prepared.minimum_reward_to_risk)))
        key = seed.association_id
        if key not in self._frozen:
            episode = H1StructuralEpisodeAdapter().assess(seed.parent)
            self._frozen[key] = GoldH1StructuralLegSelector().select(seed.parent, episode)
        selected = self._frozen[key]
        if selected.record.data['h1_snapshot_hash'] != seed.parent.record.sha256:
            raise ValueError('H1_PARENT_CHANGED_AFTER_FREEZE')
        selection = selected.record.data
        result = {
            'policy_id': POLICY_ID, 'engine_version': ENGINE_VERSION, 'arm': 'H1_FIB_F0', 'setup_identifier': seed.seed_id,
            'association_id': seed.association_id, 'seed_hash': seed.record.sha256,
            'assessed_at': now, 'seed_observed_at': seed.observed_at,
            'h1_context_id': seed.parent.context_id, 'h1_parent_cutoff': seed.parent.cutoff,
            'h1_episode_id': selection['h1_episode_id'], 'anchor': selection,
            'anchor_hash': selected.record.sha256,
            'm15_setup_id': contexts[3].identity.context_id,
            'm5_trigger_id': contexts[4].identity.context_id,
            'observed_price': seed.record.data['observed_price'],
            'entry': entry, 'stop': stop, 'expiry': seed.record.data['expires_at'],
            'canonical': canonical, 'status': 'REJECTED', 'reason': selection['reason'],
            'valid_constrained_fib': False, 'raw_slots': [], 'targets': [],
            'candidate_admitted_count': 0, 'eligible_target_count': 0, 'final_target_count': 0,
            'expiry_checks': {'H1_parent_expired': now >= contexts[2].expires_at,
                'M15_M5_expired': now >= min(contexts[3].expires_at,contexts[4].expires_at),
                'seed_or_session_expired': now >= timestamp(seed.record.data['expires_at'])},
            'nearest_objective': None, 'gil': {'status': 'DISABLED_F0', 'evidence': None},
            'data_status': 'FROZEN_POINT_IN_TIME_TECHNICAL', **ISOLATION,
        }
        def finish():
            if result['status'] != 'SHADOW_VALID':
                for slot in result['raw_slots']:
                    if slot.get('candidate_admitted'):
                        slot['eligible'] = False
                        slot['decision_rejection_reason'] = result['reason']
            result['comparison_id'] = 'f0-' + digest(result)[:24]
            return FrozenRecord.from_value(result)
        # Retain all three identities even when no price can be calculated.
        result['raw_slots'] = [dict(identity=f'FIB_TP{i+1}', ratio=r, raw_price=None,
            target_price=None, candidate_admitted=False, eligible=False, rejection_reason=selection['reason'],
            sources=[], gil_evidence=None, gc_contract=None, gc_maturity=None,
            basis_mapping=None, mapping_uncertainty=None) for i, r in enumerate(RATIOS)]
        if now >= contexts[2].expires_at:
            result['reason'] = 'H1_PARENT_EXPIRED'
        elif now >= min(contexts[3].expires_at, contexts[4].expires_at):
            result['reason'] = 'M15_M5_EXPIRED'
        elif now >= timestamp(seed.record.data['expires_at']):
            result['reason'] = 'SEED_OR_SESSION_EXPIRED'
        if result['reason'] and result['reason'].endswith('EXPIRED'):
            for slot in result['raw_slots']:
                slot['rejection_reason'] = result['reason']
            return finish()
        if selected.constraint is None:
            return finish()
        request = FibonacciRequest(layer.market, layer.structure,
            liquidity=layer.liquidity, zones=layer.zones, reclaim=layer.reclaim,
            extension_ratios=RATIOS, anchor_constraint=selected.constraint)
        atr = FibonacciLiquidityEngine._atr(list(layer.market.candles), 14)
        result['anchor']['atr'] = atr
        result['anchor']['range_atr_multiple'] = selection['range_usd'] / atr if atr > 0 else None
        reason = None
        if len(layer.market.candles) < 15 or atr <= 0:
            reason = 'H1_HISTORY_OR_ATR_UNAVAILABLE'
        elif layer.structure.confidence < request.minimum_structure_confidence:
            reason = 'STRUCTURE_CONFIDENCE_REJECTED'
        elif min(selected.constraint.start_index, selected.constraint.end_index) < len(layer.market.candles) - request.maximum_anchor_age_candles:
            reason = 'ANCHOR_AGE_REJECTED'
        elif selection['range_usd'] < request.minimum_anchor_range_atr * atr:
            reason = 'TWO_ATR_REJECTED'
        fib = FibonacciLiquidityEngine().assess(request)
        result['fib_assessment'] = fib
        if reason or not fib.has_valid_anchor:
            result['reason'] = reason or 'CONSTRAINED_FIB_REJECTED'
            for slot in result['raw_slots']:
                slot['rejection_reason'] = result['reason']
            return finish()
        result['valid_constrained_fib'] = True
        accepted = []
        level_by_ratio = {v.ratio: v for v in fib.extension_levels}
        for slot in result['raw_slots']:
            v = level_by_ratio[slot['ratio']]
            raw = decimal(v.price)
            rounded = (raw / tick).to_integral_value(
                rounding=ROUND_FLOOR if sign > 0 else ROUND_CEILING) * tick
            c = candidate(rounded, provider='monatise_gold_h1_fib_f0',
                kind=slot['identity'], timeframe='1h', observed=contexts[2].source_close_time,
                confidence=str(min(1, fib.primary_anchor.structure_confidence)))
            confluent = v.liquidity_confluence or v.zone_confluence or v.structure_confluence
            rejection = 'technical_confluence_unavailable' if not confluent else target_rejection(
                c, entry=entry, sign=sign, now=now, config=config)
            slot.update(raw_price=raw, target_price=rounded, candidate_admitted=rejection is None, eligible=rejection is None,
                rejection_reason=rejection, distance_usd=(raw-entry)*sign,
                distance_pct=(raw-entry)*sign/entry, rr=(raw-entry)*sign/risk,
                distance_atr=(float(raw-entry)*float(sign)/atr),
                tick_adjustment=rounded-raw, adjustment_reason='conservative_tick_rounding' if rounded != raw else None,
                sources={'liquidity': v.liquidity_confluence, 'zone': v.zone_confluence,
                         'structure': v.structure_confluence, 'reclaim': v.reclaim_confluence},
                observed_at=c.observed_at, freshness='PASS' if target_rejection(c,entry=entry,sign=sign,now=now,config=config) != 'stale_or_future' else 'FAIL',
                certification='TECHNICAL_ONLY_NO_OPTIONS_CERTIFICATION')
            if not rejection:
                accepted.append(c)
        result['candidate_admitted_count'] = len(accepted)
        # Credible nearer canonical objectives remain mandatory even though they
        # are not F0 targets. No farther extension can conceal a weak first RR.
        obstacles = []
        for tf, l in layers:
            observed = timestamp(l.market.candles[-1].timestamp) + timedelta(
                seconds={'4h':14400,'1h':3600,'15m':900,'5m':300,'1m':60}[tf])
            obstacles += [c for c in crypto_layer_candidates(l, timeframe=tf,
                observed=observed, provider='monatise_gold', include_fibonacci=False)
                if target_rejection(c, entry=entry, sign=sign, now=now, config=config) is None]
        if obstacles:
            nearest = min(obstacles, key=lambda c: (c.price-entry)*sign)
            rr = (nearest.price-entry)*sign/risk
            result['nearest_objective'] = dict(price=nearest.price, rr=rr,
                evidence=nearest, minimum_rr=config.minimum_rr)
            if rr < config.minimum_rr:
                result['reason'] = 'NEAREST_OBJECTIVE_RR_REJECTED'
                return finish()
        if not accepted:
            result['reason'] = 'NO_ELIGIBLE_FIB_TARGETS'
            return finish()
        try:
            plan = build_plan(candidates=accepted, direction=prepared.direction,
                entry=entry, stop=stop, now=now,
                expires_at=timestamp(seed.record.data['expires_at']), config=config, tick_size=tick)
            completed = prepared.complete(float(plan.targets[0].price))
            completed = replace(completed, expires_at=plan.expires_at,
                minimum_reward_to_risk=float(config.minimum_rr))
            bundle = EvidenceBundle.create(symbol='XAU/USD', created_at=now,
                macro_context=contexts[0], regime_4h=contexts[1], strategy_1h=contexts[2],
                setup_15m=contexts[3], trigger_5m=contexts[4], risk_inputs=completed,
                strategy_version=contexts[2].identity.strategy_version)
            validation = CanonicalEvidenceAdapter().validate(HierarchicalAnalysisRequest('XAU/USD', bundle, now))
            result['validation'] = validation
            if not validation.eligible_for_shadow_decision:
                result['reason'] = 'FINAL_VALIDATION_REJECTED'
                return finish()
        except ValueError as exc:
            result['reason'] = 'TARGET_PLAN_REJECTED:' + str(exc)
            return finish()
        # No executable bundle/intent is exported, only research audit facts.
        result.update(status='SHADOW_VALID', reason=None, plan=plan,
            final_target_count=len(plan.targets), targets=[{
                'final_name': t.name, 'final_tp': t.price, 'rr': t.rr,
                'allocation_pct': t.allocation_pct,
                'setup_identifier': seed.seed_id,
                'h1_episode_id': selection['h1_episode_id'],
                'anchor_timeframe': '1h', 'anchor_A': selection['A'], 'anchor_B': selection['B'],
                'anchor_hash': selected.record.sha256,
                'gil_evidence': None, 'gc_contract': None, 'gc_maturity': None,
                'basis_mapping': None, 'mapping_uncertainty': None,
                'freshness': 'PASS', 'certification': 'TECHNICAL_ONLY_NO_OPTIONS_CERTIFICATION',
                'raw_candidates': [s.copy() for s in result['raw_slots']
                    if s['eligible'] and abs(decimal(s['target_price'])-t.price) < max(tick*2,risk*config.minimum_increment_r)],
                'raw_sources': [s['identity'] for s in result['raw_slots']
                    if s['eligible'] and abs(decimal(s['target_price'])-t.price) < max(tick*2,risk*config.minimum_increment_r)],
            } for t in plan.targets])
        for rejection in plan.rejection_log:
            if rejection.endswith(':merged_nearby'):
                identity = rejection.split(':')[0]
                for slot in result['raw_slots']:
                    if slot['identity'] == identity:
                        slot.update(eligible=False, rejection_reason='merged_nearby')
        result['eligible_target_count'] = len(plan.targets)
        return finish()
