"""Prefix admission and canonical delegation. Import in the pinned worker only."""
from bisect import bisect_right
from dataclasses import replace
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from monatise.application.gold_analysis import GoldLayerEvaluator
from monatise.application.hierarchy.coordinator import HierarchyConfiguration
from monatise.application.target_evidence import crypto_layer_candidates
from monatise.application.take_profit import build_plan
from monatise.engines.regime import RegimeRequest
from monatise.research.gc_fib.candles import INTERVALS
from monatise.research.gc_fib.worker import snapshot, instant

NS = 10**9


def required_history(timeframe):
    # H4 regime's returns baseline needs slow_window + 1, not 50. The other
    # roles retain the canonical transport/liquidity floor of 50. This is a
    # stricter warmup correction; history remains capped at 200 unchanged.
    if timeframe == "4h":
        fields = RegimeRequest.__dataclass_fields__
        return max(50,*(fields[k].default+1 for k in ("slow_window","atr_window","compression_window")))
    return 50


class CutoffAdapter:
    def __init__(self, bars, sessions):
        self.sessions = tuple((s["start_ns"], s["end_ns"]) for s in sessions)
        if not self.sessions or any(a >= b or a % (60*NS) or b % (60*NS) for a,b in self.sessions):
            raise ValueError("reviewed minute sessions required")
        if any(self.sessions[i][1] > self.sessions[i+1][0] for i in range(len(self.sessions)-1)):
            raise ValueError("conflicting sessions")
        keys = [(b.timeframe,b.open_ns) for b in bars]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate_or_revised_bars")
        self.rows = {tf: tuple(sorted((b for b in bars if b.timeframe == tf), key=lambda b:b.open_ns)) for tf in INTERVALS}
        self.bar_hashes = {(b.timeframe,b.open_ns):b.sha256 for b in bars}
        self.clocks = {tf: tuple(b.assumed_available_ns for b in rows) for tf,rows in self.rows.items()}
        # Normalize immutable bars once using the existing GC adapter. Reusing
        # an object is never described as a second independent observation.
        self.normalized = {tf:tuple(snapshot((b,),timeframe=tf,cutoff=b.assumed_available_ns).latest_finalized
                                  for b in rows) for tf,rows in self.rows.items()}
        self.templates = {tf:snapshot(rows[:1],timeframe=tf,cutoff=rows[0].assumed_available_ns)
                          for tf,rows in self.rows.items() if rows}
        self.expected = {}
        for tf,width in INTERVALS.items():
            step = width*NS
            self.expected[tf] = tuple(t for a,b in self.sessions for t in range((a+step-1)//step*step,b,step) if t+step <= b)

    def session(self, cutoff):
        return next(((a,b) for a,b in self.sessions if a <= cutoff < b), None)

    def frames(self, cutoff):
        issues, frames, lineage = [], {}, {}
        session = self.session(cutoff)
        if session is None:
            return {}, ["exchange_closed_or_unreviewed_session"], {}
        for tf,width in INTERVALS.items():
            index = bisect_right(self.clocks[tf],cutoff)
            rows = self.rows[tf][max(0,index-200):index]
            if len(rows) < required_history(tf):
                issues.append(tf+":canonical_history_insufficient"); continue
            expected = self.expected[tf]
            last_expected = bisect_right(expected,cutoff-(width+10)*NS)
            window = expected[bisect_right(expected,rows[0].open_ns-1):last_expected]
            missing = sorted(set(window)-{b.open_ns for b in rows})
            invalid = [b.open_ns for b in rows if not any(a <= b.open_ns < b.close_ns <= z for a,z in self.sessions)]
            if missing: issues.append(tf+":missing_or_no_trade_bar")
            if invalid: issues.append(tf+":bar_outside_session")
            if not last_expected or rows[-1].open_ns != expected[last_expected-1]:
                issues.append(tf+":latest_expected_bar_missing")
            # Required canonical source lifetimes are enforced by Gold._context;
            # this extra transport rule reproduces the two-interval age bound.
            if cutoff-rows[-1].close_ns > 2*width*NS:
                issues.append(tf+":canonical_source_stale")
            normalized = self.normalized[tf][max(0,index-200):index]
            frames[tf] = replace(self.templates[tf],observed_at=instant(cutoff),candles=normalized,
                                 latest_finalized=normalized[-1])
            lineage[tf] = dict(latest_bar_sha256=self.bar_hashes[(tf,rows[-1].open_ns)],
                prefix_sha256=__import__('hashlib').sha256(''.join(self.bar_hashes[(tf,b.open_ns)] for b in rows).encode()).hexdigest(),
                known_at_ns=rows[-1].assumed_available_ns, close_ns=rows[-1].close_ns,
                missing_or_no_trade_opens_ns=missing, outside_session_opens_ns=invalid)
        return frames,issues,lineage


def native_plan(candidates, prepared, *, now, config, tick):
    """Canonical selection first; inward rounding cannot skip a weak near target."""
    plan = build_plan(candidates=candidates,direction=prepared.direction,
        entry=prepared.reference_entry,stop=prepared.final_stop,now=now,
        expires_at=prepared.expires_at,config=config,tick_size=tick)
    sign = Decimal(1 if prepared.direction == "long" else -1)
    entry,stop = Decimal(str(prepared.reference_entry)),Decimal(str(prepared.final_stop))
    targets = []
    for t in plan.targets:
        price = (t.price/tick).to_integral_value(rounding=ROUND_FLOOR if sign == 1 else ROUND_CEILING)*tick
        targets.append(replace(t,price=price,analysis_price=t.price,rr=(price-entry)*sign/abs(entry-stop)))
    plan = replace(plan,targets=tuple(targets))
    plan.validate(now=now,tick_size=tick)
    return plan


class NativeGoldEvaluator(GoldLayerEvaluator):
    """Keep actual setup/trigger/context/bundle validation, delegate only risk I/O."""
    def __init__(self, contract):
        super().__init__(asset_route="gold",configuration=replace(HierarchyConfiguration(),
            strategy_version="gold-sweep-reversal-technical-v1",always_collect_5m=True))
        self.contract = contract
        self.target_config = self.multi_tp
        # The inherited evaluate otherwise computes a second default 1e-8 plan.
        # The research _risk below runs the SAME producer/builder with native tick.
        self.multi_tp = replace(self.multi_tp,enabled=False)
        self.layers, self.prepared, self.plan, self.target_candidates = {},None,None,[]
        self.risk_error = None

    def _analyse_structure(self, snapshot, regime):
        layer = super()._analyse_structure(snapshot,regime)
        if layer is not None:
            for name in ("liquidity","sweep","zones","reclaim","structure"):
                value = getattr(layer,name)
                layer = replace(layer,**{name:replace(value,metadata={**value.metadata,
                    "engine_scope":"native_gc_exchange_candles","volume_kind":"exchange_traded_contracts"})})
            self.layers[snapshot.timeframe] = layer
        return layer

    def _risk(self, layer, trigger, now, *, entry_layer=None, stop_layer=None):
        try:
            return self._prepare_and_complete(layer,trigger,now,entry_layer=entry_layer,stop_layer=stop_layer)
        except ValueError as exc:
            allowed = {"gold_entry_zone_unavailable","gold_stop_pattern_unavailable",
                "stop and target are inconsistent with direction","insufficient target evidence",
                "insufficient TP1 reward/risk; cannot skip first objective",
                "invalid stop or setup expiry","target reversed, duplicated or insufficiently spaced"}
            self.risk_error = str(exc) if str(exc) in allowed else "canonical_risk_validation_error"
            raise

    def _prepare_and_complete(self, layer, trigger, now, *, entry_layer=None, stop_layer=None):
        self.prepared = self.prepare_entry_stop(trigger,now,entry_layer=entry_layer,stop_layer=stop_layer)
        self.target_candidates = []
        state = self._state["GCZ6"]
        for tf,snap in state.snapshots.items():
            evidence = self._analyse_structure(snap,state.regime_assessment)
            self.target_candidates.extend(crypto_layer_candidates(evidence,timeframe=tf,
                observed=snap.latest_finalized.scheduled_close_time,provider="monatise_gold"))
        self.plan = native_plan(self.target_candidates,self.prepared,now=now,
            config=self.target_config,tick=Decimal(self.contract.tick_size))
        return self.prepared.complete(float(self.plan.targets[0].price))

    def evaluate_native(self, frames, *, now, spread):
        self.broker_units = self.contract.units(spread)
        self.layers,self.prepared,self.plan,self.target_candidates = {},None,None,[]
        self.risk_error = None
        result = super().evaluate("GCZ6",frames,evaluated_at=now,macro_degraded=True)
        return replace(result,take_profit_plan=self.plan)
