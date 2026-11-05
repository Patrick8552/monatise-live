"""One auditable reference decision per instrument/stream/cycle."""
from dataclasses import replace
from decimal import Decimal
import json
from . import VERSION, BASE_COMMIT, CODE_HASH
from .models import Candidate, Plan, Target, Side, TERMINAL, encode, digest, identity
from .evidence import build_frames, observations, bias, EvidenceCache
from .pathways import EVALUATORS
from .eligibility import validate, final_revalidate, volume_support
from .arbitration import arbitrate, earliest_baseline
from .store import Conflict
from .models import fixed_decimal, current_quote


def decode_plan(body):
    names = Plan.__dataclass_fields__
    x = {k: v for k, v in body.items() if k in names}
    for key in ('entry', 'entry_low', 'entry_high', 'stop', 'initial_risk', 'round_trip_cost', 'cost_risk_ratio', 'spread_points'):
        x[key] = Decimal(x[key])
    x['side'] = Side(x['side']); x['net_rr'] = tuple(Decimal(v) for v in x['net_rr'])
    x['targets'] = tuple(Target(Decimal(v['price']), v['reference_id'], v['available_ns']) for v in x['targets'])
    x['evidence_ids'] = tuple(x['evidence_ids'])
    return Plan(**x)


class DecisionService:
    def __init__(self, store, policy, *, stream, pathways=('A', 'B', 'C'), final_snapshot=None, evidence_cache=None, arbitration_mode='DOMINANCE'):
        if not stream or not pathways or any(x not in EVALUATORS for x in pathways):
            raise ValueError('explicit_experiment_and_pathways_required')
        self.store, self.policy, self.stream = store, policy, stream
        self.pathways = tuple(sorted(set(pathways)))
        self.final_snapshot = final_snapshot
        self.evidence_cache = evidence_cache or EvidenceCache()
        if arbitration_mode not in ('DOMINANCE','EARLIEST_BASELINE'):
            raise ValueError('registered_arbitration_mode_required')
        self.arbitration_mode = arbitration_mode

    @fixed_decimal
    def evaluate(self, snapshot, cycle, *, observation_override=None, frame_override=None, failpoint=None):
        # Overrides are an explicitly marked engineering interface, never a
        # genuine-data shortcut. Production/replay always derive evidence.
        if (observation_override is not None or frame_override is not None) and snapshot.evidence_kind != 'ENGINEERING_SYNTHETIC':
            raise ValueError('engineering_override_forbidden_for_market_data')
        config_hash = digest({'policy': self.policy, 'pathways': self.pathways, 'version': VERSION, 'arbitration_mode': self.arbitration_mode, 'code_hash': CODE_HASH})
        if observation_override is None and frame_override is None:
            frames, found, snapshot_hash, evidence_summary = self.evidence_cache.get(snapshot, self.policy)
        else:
            snapshot_hash = snapshot.hash
            frames = frame_override if frame_override is not None else build_frames(snapshot, self.policy)
            found = observation_override if observation_override is not None else observations(snapshot, self.policy, frames)
            from .diagnostics import describe
            evidence_summary = describe(snapshot,frames)
        input_hash = digest({'snapshot': snapshot_hash, 'configuration': config_hash,
                             'engineering_observations': observation_override,
                             'engineering_frames': frame_override})
        found = tuple(sorted((o for o in found if o.pathway in self.pathways),
                             key=lambda o: (o.detected_ns, o.origin.key, o.pathway, o.stage)))
        for o in found:
            if (o.origin.contract != snapshot.instrument.key or o.detected_ns > snapshot.cutoff_ns
                    or any(e.available_ns > snapshot.cutoff_ns or e.at_ns > snapshot.cutoff_ns for e in o.events)):
                raise ValueError('NONCAUSAL_OR_WRONG_CONTRACT_OBSERVATION')
        candidates = [validate(o, snapshot, self.policy, frames) for o in found]
        # Source and structural/economic eligibility precedes context/arbitration.
        permitted = []
        for c in candidates:
            if c.eligible:
                reasons, category = EVALUATORS[c.observation.pathway](c.observation, frames, self.policy, snapshot.instrument.tick)
                c = replace(c, reasons=reasons, context_category=category)
            permitted.append(c)
        store = self.store
        with store.transaction():
            store.bind(self.stream, config_hash, snapshot.manifest_hash)
            cached = store.cached(self.stream, snapshot.instrument.key, cycle, input_hash)
            if cached is not None:
                return cached
            store.check_cutoff(self.stream, snapshot.instrument.key, snapshot.cutoff_ns)
            qualified_observation_ids = {c.observation.key for c in permitted if c.eligible}
            for o in found:
                fully_qualified = o.key in qualified_observation_ids
                store.record_observation(self.stream, o, snapshot.cutoff_ns, qualified=fully_qualified)
            store.expire(self.stream, snapshot.instrument.key, snapshot.cutoff_ns)
            active = []
            for c in permitted:
                oid = c.observation.opportunity_id
                if oid and store.status(self.stream, oid) in TERMINAL:
                    c = replace(c, reasons=c.reasons+('PERSISTED_TERMINAL_STATE',))
                if c.eligible and store.exposure_conflict(self.stream, snapshot.instrument.key, oid, snapshot.cutoff_ns):
                    c = replace(c, reasons=c.reasons+('SHADOW_EXPOSURE_RESTRICTION',))
                old = store.selected(self.stream, oid) if oid else None
                if old and c.eligible and store.selection_completed(self.stream, old['selection']):
                    c = replace(c, reasons=c.reasons+('SELECTED_OPPORTUNITY_ALREADY_COMPLETED',))
                if old and c.eligible:
                    # Later annotations cannot rewrite or rerank selected economics.
                    c = replace(c, plan=decode_plan(json.loads(old['plan'])))
                active.append(c)
            selector = arbitrate if self.arbitration_mode == 'DOMINANCE' else earliest_baseline
            selected, reason, arbitration = selector(active)
            final_codes = ()
            final = snapshot
            if selected:
                if self.final_snapshot:
                    final = self.final_snapshot(snapshot)
                    if final.instrument.key != snapshot.instrument.key or final.cutoff_ns < snapshot.cutoff_ns:
                        raise Conflict('FINAL_SNAPSHOT_IDENTITY_OR_TIME_CONFLICT')
                final_codes = final_revalidate(selected.plan, final, self.policy)
                context_inputs_unchanged = all(getattr(final,k)==getattr(snapshot,k) for k in ('bars','trades','coverage','schedule','news','news_coverage','quality'))
                if not context_inputs_unchanged:
                    final_frames = build_frames(final,self.policy)
                    final_observations = observations(final,self.policy,final_frames)
                    matching = [o for o in final_observations if o.opportunity_id == selected.observation.opportunity_id and o.pathway == selected.observation.pathway and o.stage == 'TRIGGERED']
                    if not matching:
                        final_codes += ('FINAL_STRUCTURE_NO_LONGER_CONFIRMED',)
                    else:
                        context_codes,_ = EVALUATORS[matching[0].pathway](matching[0],final_frames,self.policy,final.instrument.tick)
                        final_codes += context_codes + volume_support(matching[0],final,self.policy,final_frames)
                else:
                    from .models import WIDTHS
                    if any(not f.bars or final.cutoff_ns-f.bars[-1].close_ns>WIDTHS[tf] for tf,f in frames.items() if tf in ('4h','1h','15m','5m')):
                        final_codes += ('FINAL_CONTEXT_STALE',)
                if final_codes:
                    reason = 'FINAL_REVALIDATION_FAILED'
                    selected = None  # Deliberately no runner-up promotion.
            sid = None; new_selection = False; plan = None
            if selected:
                oid = selected.observation.opportunity_id
                primary = selected.observation.pathway
                sid, new_selection, plan = store.claim(self.stream, selected, final.cutoff_ns,
                                                       config_hash, snapshot_hash if final is snapshot else final.hash, primary,
                                                       policy=self.policy)
            if failpoint:
                failpoint()  # Engineering crash injection: whole transaction rolls back.
            audit = [{'opportunity_id': c.observation.opportunity_id, 'observation_id': c.observation.key,
                      'pathway': c.observation.pathway, 'stage': c.observation.stage,
                      'eligible': c.eligible, 'reasons': c.reasons,
                      'context_category': c.context_category,
                      'origin_event_id': c.observation.origin.key,
                      'market_trigger_event_id': c.observation.trigger.key if c.observation.trigger else None,
                      'causal_evidence_ids': [e.key for e in c.observation.events],
                      'economic_gate': 'PASSED' if c.plan else 'REJECTED_OR_NOT_EVALUATED',
                      'tested_net_rr': encode(c.plan.net_rr) if c.plan else None} for c in active]
            readiness = self.policy.missing
            if selected is None and reason == 'NO_ELIGIBLE_TRIGGERED_OPPORTUNITY' and readiness:
                reason = 'POLICY_NOT_READY'
            current_l1 = current_quote(snapshot)
            result = {
                'schema_version': VERSION, 'base_commit': BASE_COMMIT, 'code_hash': CODE_HASH,
                'decision_id': identity('decision-v1', self.stream, snapshot.instrument.key, cycle, input_hash),
                'cycle_id': cycle, 'experiment_id': self.stream, 'configuration_hash': config_hash,
                'manifest_hash': snapshot.manifest_hash, 'snapshot_hash': snapshot_hash,
                'instrument': encode(snapshot.instrument), 'price_label': 'CME FUTURES REFERENCE PRICES',
                'market_bias': bias(frames), 'trade_action': selected.observation.side if selected else 'NO_TRADE',
                'selected_opportunity_id': selected.observation.opportunity_id if selected else None,
                'signal_status': 'TRIGGERED' if selected else None,
                'selected_pathway': plan['primary_pathway'] if plan else None,
                'supporting_classifications': sorted({c.observation.pathway for c in active if c.eligible and selected and c.observation.opportunity_id == selected.observation.opportunity_id}),
                'historically_qualified_classifications': store.classifications(self.stream, selected.observation.opportunity_id) if selected else [],
                'market_trigger_event_id': selected.plan.trigger_id if selected else None,
                'selection_event_id': sid, 'is_new_selection': new_selection,
                'entry': {'price': plan['entry'], 'zone': [plan['entry_low'], plan['entry_high']],
                          'method': 'MODELED_MARKET_WITHIN_FROZEN_TRIGGER_ZONE',
                          'trigger_id': plan['trigger_id']} if plan else None,
                'stop_loss': plan['stop'] if plan else None,
                'invalidation': {'structural_reference': plan['stop_reference'], 'expires_ns': plan['expires_ns'],
                                 'conditions': ['STRUCTURAL_STOP_BREACH', 'DATA_OR_CONTEXT_FAILURE', 'EXPIRED_OR_SUPERSEDED']} if plan else None,
                'targets': plan['targets'] if plan else None, 'net_rr': plan['net_rr'] if plan else None,
                'selected_plan': plan, 'reason': reason, 'final_revalidation_reasons': final_codes,
                'reconsideration': None if selected else 'Resolve listed gates; require a completed, fresh, context-permitted structural trigger and supported economic plan.',
                'cutoff_ns': snapshot.cutoff_ns, 'final_revalidation_cutoff_ns': final.cutoff_ns,
                'final_snapshot_hash': snapshot_hash if final is snapshot else final.hash,
                'replay_mode': snapshot.replay_mode, 'evidence_kind': snapshot.evidence_kind,
                'evidence_summary': evidence_summary,
                'frame_states': {tf: {'state': f.state, 'last_close_ns': f.bars[-1].close_ns if f.bars else None,
                                      'reasons': f.reasons} for tf, f in frames.items()},
                'data_quality': snapshot.quality, 'parameter_prerequisites': readiness,
                'source_freshness': {
                    'latest_quote_receive_ns': current_l1.receive_ns if current_l1 else None,
                    'latest_quote_age_ns': snapshot.cutoff_ns-current_l1.receive_ns if current_l1 else None,
                    'quote_basis': 'MODELED_SPREAD_ASSUMPTION' if current_l1 and current_l1.source.startswith('MODELED_SPREAD_FROM_NATIVE_CLOSE:') else 'NATIVE_L1' if current_l1 else 'UNAVAILABLE',
                    'latest_trade_receive_ns': max((t.receive_ns for t in snapshot.trades),default=None)},
                'candidate_audit': audit, 'arbitration_audit': arbitration,
                'watch_record_count': sum(o.stage in ('WATCHING', 'ARMED') for o in found),
                'account_risk_validation': 'UNAVAILABLE_REFERENCE_ONLY_NO_ACCOUNT_SIZING',
                'numeric_decimal_precision': 40,
                'mode': 'SHADOW', 'execution_eligible': False, 'orders_created': 0,
            }
            result = encode(result)
            store.commit_decision(self.stream, snapshot.instrument.key, cycle, input_hash, final.cutoff_ns, result)
            return result
