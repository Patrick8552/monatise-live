"""Opt-in instrumentation used only by the offline research runner."""
from __future__ import annotations

from dataclasses import replace

from monatise.application.gold_analysis import GoldLayerEvaluator, GoldPolicy
from monatise.application.hierarchy.coordinator import HierarchyConfiguration
from monatise.application.hierarchy.models import TriggerState
from monatise.research.gold_fib.models import GoldSetupSeed, H1ParentSnapshot


class CaptureGoldLayerEvaluator(GoldLayerEvaluator):
    def __init__(self):
        super().__init__(configuration=HierarchyConfiguration(
            strategy_version=GoldPolicy().strategy), asset_route='gold')
        self.parents = {}
        self.layers = {}
        self.seed_rejections = []

    def _analyse_structure(self, snapshot, regime):
        layer = super()._analyse_structure(snapshot, regime)
        if layer is not None:
            self.layers[snapshot.timeframe] = layer
        return layer

    def _context(self, kind, snapshot, parent, state, direction, confidence, now, lifetime, evidence):
        context = super()._context(kind, snapshot, parent, state, direction, confidence, now, lifetime, evidence)
        if kind == 'strategy':
            identity = context.identity.context_id
            if identity not in self.parents:
                self.parents[identity] = H1ParentSnapshot.capture(context, snapshot, self.layers['1h'])
            else:
                prior = self.parents[identity].objects()[1]
                if [(c.candle_id,c.content_hash) for c in prior.candles] != [(c.candle_id,c.content_hash) for c in snapshot.candles]:
                    raise ValueError('H1_same_parent_revision_rejected')
        return context

    def capture_seed(self, canonical, *, calendar, broker_identity, at):
        state = self._state.get('XAU/USD')
        if state is None or state.trigger_context is None or state.trigger_context.state is not TriggerState.TRIGGER_CONFIRMED:
            return None
        try:
            contexts = (state.macro_context, state.regime_context, state.strategy_context,
                        state.setup_context, state.trigger_context)
            if any(c is None for c in contexts):
                raise ValueError('missing_canonical_context')
            parent = self.parents[contexts[2].identity.context_id]
            # Preserve the original H1 point-in-time parent, never its later refresh.
            contexts = (*contexts[:2], parent.objects()[0], *contexts[3:])
            if set(self.layers) != {'4h','1h','15m','5m','1m'}:
                raise ValueError('required_layers_unavailable')
            layers = dict(self.layers)
            layers['1h'] = parent.objects()[2]
            for tf in ('15m','5m','1m'):
                snap = state.snapshots[tf]
                if snap.latest_finalized.open_time != calendar.expected_closed_open(tf, at):
                    raise ValueError('lower_timeframe_stale:' + tf)
            prepared = self.prepare_entry_stop(state.trigger_context, at,
                entry_layer=layers['1m'], stop_layer=layers['15m'])
            return GoldSetupSeed.create(contexts=contexts, parent=parent,
                prepared=prepared, layers=tuple(sorted(layers.items())), observed_at=at,
                session_close=calendar.session_close(at), calendar_hash=calendar.fingerprint,
                broker_identity=broker_identity, broker_units=self.broker_units,
                timestamp_policy='reviewed_manifest')
        except (KeyError, ValueError) as exc:
            self.seed_rejections.append({'at':at, 'reason':str(exc)})
            return None
