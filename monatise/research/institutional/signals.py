"""Offline transport adapters to the existing asset-specific analytical paths."""
from dataclasses import dataclass
from datetime import timedelta
from types import SimpleNamespace

from monatise.application.ftmo_registry import FTMO_REGISTRY
from monatise.application.gold_analysis import GoldHierarchyAnalysis, GoldAnalysisCoordinator
from monatise.application.hierarchy.assets import AssetHierarchyAnalysis
from monatise.application.hierarchy.policy import INTERVAL_SECONDS
from monatise.application.production_analysis import build_production_analysis_run
from monatise.application.registry import canonical_registrations
from monatise.engines.market_data import MarketDataEngine
from .models import SignalPreview, PreviewDecision, digest, hash_required, number, encode
from .mapping import dt


@dataclass(frozen=True)
class CandleEvidence:
    instrument: str
    provider: str
    evidence_kind: str
    source_sha256: str
    captured_ns: int
    session_end_ns: int
    # Native/broker export rows, serialized canonically to avoid mutable inputs.
    timeframes_json: str
    point: float
    tick_size: float
    spread_price: float
    continuity_review_reference: str
    confirmation_sha256: str | None = None
    confirmation_ns: int | None = None

    def rows(self, *, expected, now_ns):
        import json
        from monatise.application.hierarchy.assets import _timestamp
        from monatise.adapters.databento_identity import datetime_ns
        hash_required(self.source_sha256)
        if self.confirmation_sha256 is not None:
            hash_required(self.confirmation_sha256)
            if (self.confirmation_sha256 == self.source_sha256 or self.confirmation_ns is None
                    or not self.captured_ns < self.confirmation_ns):
                raise ValueError("independent_confirmation_observation_required")
        if (self.instrument != expected or not self.provider or not self.continuity_review_reference
                or self.evidence_kind not in {"AUTHENTIC_ARCHIVED_RECORD", "ENGINEERING_SYNTHETIC"}
                or not self.captured_ns <= now_ns < self.session_end_ns):
            raise ValueError("canonical_candle_identity_or_availability_invalid")
        number(self.point, positive=True); number(self.tick_size, positive=True)
        if number(self.spread_price) < 0:
            raise ValueError("invalid_broker_spread")
        rows = json.loads(self.timeframes_json)
        if set(rows) != set(INTERVAL_SECONDS):
            raise ValueError("canonical_timeframes_incomplete")
        for tf, series in rows.items():
            width = INTERVAL_SECONDS[tf]*10**9
            if not isinstance(series,list) or not 51 <= len(series) <= 240:
                raise ValueError("canonical_history_incomplete")
            stamps = [datetime_ns(_timestamp(r['t'])) for r in series]
            if (any(t % width or t+width+10*10**9 > now_ns for t in stamps)
                    or any(b-a != width for a,b in zip(stamps,stamps[1:]))):
                raise ValueError("canonical_candle_continuity_or_finalization_invalid")
        return rows


class OfflineIndex(AssetHierarchyAnalysis):
    def __init__(self, evidence):
        super().__init__(environment={})
        self.evidence = evidence

    async def _batch(self, instrument, now):
        from monatise.adapters.databento_identity import datetime_ns
        rows = self.evidence.rows(expected=instrument.ftmo_symbol, now_ns=datetime_ns(now))
        return rows, dt(self.evidence.session_end_ns), self._provenance(), None

    def _provenance(self):
        return dict(provider=self.evidence.provider, evidence_kind=self.evidence.evidence_kind,
            source_sha256=self.evidence.source_sha256, volume_kind="tick_volume",
            timestamp_policy="reviewed_UTC_export", point=self.evidence.point,
            tick_size=self.evidence.tick_size, spread_price=self.evidence.spread_price)


class OfflineGold(GoldHierarchyAnalysis):
    def __init__(self, evidence):
        super().__init__(environment={})
        self.evidence = evidence

    async def _batch(self, instrument, now):
        from monatise.adapters.databento_identity import datetime_ns
        rows = self.evidence.rows(expected=instrument.ftmo_symbol, now_ns=datetime_ns(now))
        self._engines[instrument.ftmo_symbol][2].broker_units = dict(point=self.evidence.point,
            tick_size=self.evidence.tick_size, spread_price=self.evidence.spread_price)
        return rows, dt(self.evidence.session_end_ns), OfflineIndex._provenance(self), None


def preview(*, asset, broker_instrument, institutional_instrument, now_ns, canonical=None,
            evidence_kind="UNAVAILABLE", provenance=(), mapping_status="MAPPING_UNAVAILABLE",
            reasons=(), path="canonical_inputs_unavailable", limitations=()):
    result = canonical or {}
    reasons = tuple(reasons)+tuple(result.get('reasons') or ())
    qualified = bool(result.get('analytical_qualified',result.get('publication_valid',False)))
    raw = result.get('decision')
    decision = (PreviewDecision.LONG if result.get('direction') == 'LONG' else PreviewDecision.SHORT)
    if not qualified or result.get('direction') not in {'LONG','SHORT'}:
        decision = (PreviewDecision.INSUFFICIENT_MARKET_DATA if raw == 'INSUFFICIENT_MARKET_DATA'
                    else PreviewDecision.MAPPING_UNAVAILABLE if not canonical and mapping_status == 'MAPPING_UNAVAILABLE'
                    else PreviewDecision.NO_TRADE)
    entry = result.get('entry') if qualified else None
    stop = result.get('stop_loss') if qualified else None
    zone = result.get('entry_zone') if qualified else None
    targets = result.get('targets') or ([result['target']] if result.get('target') else [])
    expiry = result.get('expires_at') if qualified else None
    from monatise.adapters.databento_identity import datetime_ns
    return SignalPreview(asset,broker_instrument,institutional_instrument,decision,
        str((result.get('regime') or {}).get('state','unavailable')),str(result.get('technical_bias') or result.get('direction') or 'unavailable'),
        (str(zone['low']),str(zone['high'])) if zone else None, str(entry) if entry is not None else None,
        str(stop) if stop is not None else None, tuple(str(v) for v in targets) if qualified else (),
        str(result['reward_risk']) if qualified and result.get('reward_risk') is not None else None,
        str(result['score']) if result.get('score') is not None else None,
        tuple(limitations)+('Analytical preview only; canonical governance and broker execution have not been activated.',
                            'Evidence scores are confluence/conviction measures, not win probabilities.'),
        tuple((str(k),str(v)) for k,v in sorted((result.get('freshness') or {}).items()))
            if isinstance(result.get('freshness'),dict) else (('canonical_status',str(result.get('freshness','unavailable'))),),
        now_ns, datetime_ns(dt_parse(expiry)) if expiry else None, mapping_status, tuple(provenance),
        reasons, evidence_kind, path)


def dt_parse(value):
    from datetime import datetime
    return datetime.fromisoformat(str(value).replace('Z','+00:00'))


async def broker_preview(*, asset, instrument, now_ns, evidence=None, positioning=None,
                         institutional_instrument=None, mapping_status="MAPPING_UNAVAILABLE", include_canonical=False):
    if asset not in {'GC','ES','NQ'} or instrument != {'GC':'XAU/USD','ES':'US500.cash','NQ':'US100.cash'}[asset]:
        raise ValueError("canonical_asset_route_mismatch")
    registered = FTMO_REGISTRY.resolve(instrument)
    def output(value, canonical=None):
        return dict(preview=encode(value),canonical=encode(canonical)) if include_canonical else value
    if evidence is None:
        return output(preview(asset=asset,broker_instrument=instrument,institutional_instrument=institutional_instrument,
            now_ns=now_ns,mapping_status=mapping_status,reasons=('verified_broker_candles_unavailable',)))
    try:
        if evidence.confirmation_ns is not None and evidence.confirmation_ns > now_ns:
            raise ValueError("confirmation_not_available_at_decision")
        evidence.rows(expected=instrument,now_ns=now_ns)
        if asset == 'GC':
            technical = OfflineGold(evidence)
            coordinator = GoldAnalysisCoordinator(technical=technical, environment={})
            result = await coordinator.analyse(registered,now=dt(evidence.captured_ns))
            if evidence.confirmation_sha256 is not None:
                result = await coordinator.analyse(registered,now=dt(now_ns))
            path = 'GoldAnalysisCoordinator/GoldHierarchyAnalysis/GoldLayerEvaluator'
        else:
            if not positioning:
                raise ValueError('required_primary_index_positioning_unavailable')
            hash_required(positioning.get('_source_sha256'))
            if (positioning.get('_evidence_kind') != evidence.evidence_kind
                    or not isinstance(positioning.get('_available_ns'),int)
                    or positioning['_available_ns'] > evidence.captured_ns):
                raise ValueError('index_positioning_provenance_or_availability_invalid')
            from monatise.application.market_intelligence import validate_flashalpha_context
            validate_flashalpha_context(positioning, provider_symbol=asset+'=F', now=dt(now_ns),
                                        maximum_age=timedelta(minutes=60))
            validate_flashalpha_context(positioning, provider_symbol=asset+'=F', now=dt(evidence.captured_ns),
                                        maximum_age=timedelta(minutes=60))
            # No GIL resolution/provider calls. Supplied context must pass the existing boundary.
            analysis = OfflineIndex(evidence)
            result = await analysis.analyse(registered,context=positioning,now=dt(evidence.captured_ns))
            if evidence.confirmation_sha256 is not None:
                result = await analysis.analyse(registered,context=positioning,now=dt(now_ns))
            path = 'validate_flashalpha_context/AssetHierarchyAnalysis/HierarchyLayerEvaluator'
        return output(preview(asset=asset,broker_instrument=instrument,institutional_instrument=institutional_instrument,
            now_ns=now_ns,canonical=result,evidence_kind=evidence.evidence_kind,
            provenance=(evidence.source_sha256,digest(positioning or {}))+((evidence.confirmation_sha256,) if evidence.confirmation_sha256 else ()),mapping_status=mapping_status,path=path,
            limitations=('Institutional observations are separate context; no new scoring or price substitution.',)),result)
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        return output(preview(asset=asset,broker_instrument=instrument,institutional_instrument=institutional_instrument,
            now_ns=now_ns,canonical={'decision':'INSUFFICIENT_MARKET_DATA'},evidence_kind=evidence.evidence_kind,
            provenance=(evidence.source_sha256,),mapping_status=mapping_status,reasons=(str(exc),),
            path='canonical_input_boundary'))


def _crypto_preview(*, asset, now_ns, evidence=None, derivatives=None):
    """Use unchanged production stage inputs/defaults, not Gold's hierarchy."""
    if asset not in {'BTC','ETH','SOL'}:
        raise ValueError('unsupported_canonical_crypto_asset')
    if evidence is None:
        return preview(asset=asset,broker_instrument=asset,institutional_instrument=None,now_ns=now_ns,
            canonical={'decision':'INSUFFICIENT_MARKET_DATA'},mapping_status='NOT_APPLICABLE',
            reasons=('verified_native_crypto_observations_unavailable',))
    rows = evidence.rows(expected=asset,now_ns=now_ns)
    from monatise.core.models import Candle
    class NativeProvider:
        def latest_price(self, symbol):
            if symbol != asset: raise ValueError('native_crypto_symbol_mismatch')
            # Preserve the canonical engine's explicitly labelled reference-price
            # fallback; a recorded close is not a contemporaneous exchange quote.
            raise ValueError('native_current_quote_unavailable_closed_candle_reference_only')
        def candles(self,symbol,limit,interval):
            if symbol != asset or interval != '1h': raise ValueError('native_crypto_series_mismatch')
            return [Candle(r['t'],r['o'],r['h'],r['l'],r['c'],r['v']) for r in rows[interval][-limit:]]
    class Derivatives:
        def derivatives_snapshot(self,symbol,interval):
            return derivatives or {}
    run = build_production_analysis_run(asset,interval='1h',correlation_id=digest(evidence),source='institutional.offline')
    outputs = {}
    for registration in canonical_registrations():
        if registration.name not in run.stage_inputs:
            continue
        factory = run.stage_inputs[registration.name]
        request = factory(SimpleNamespace(outputs=outputs)) if callable(factory) else factory
        engine = (MarketDataEngine({evidence.provider:NativeProvider()}, derivatives_provider=Derivatives(),clock=lambda:dt(now_ns))
                  if registration.name == 'market_data' else registration.engine_type())
        value = getattr(engine,registration.method)(request)
        outputs[registration.name] = value
        if registration.blocking and registration.blocking(value):
            break
    decision = outputs.get('decision')
    # This production analytical builder has no structural risk/entry plan stage.
    # A directional score alone is not a qualified entry/stop/target preview.
    result = {'decision':'NO_TRADE','direction':'NONE','regime':{'state':str(outputs['regime'].state)} if 'regime' in outputs else {},
              'reasons':list(getattr(decision,'reasons',()))+['structural_crypto_entry_stop_target_unavailable'],
              'score':getattr(decision,'conviction',None)}
    return dict(preview=encode(preview(asset=asset,broker_instrument=asset,institutional_instrument=None,
        now_ns=now_ns,canonical=result,evidence_kind=evidence.evidence_kind,provenance=(evidence.source_sha256,),
        mapping_status='NOT_APPLICABLE',path='build_production_analysis_run/canonical_registrations/DecisionEngine',
        limitations=('Native crypto observations retained; no CME price substitution.',))),
        analytical_stages=tuple(outputs), canonical_decision=encode(decision) if decision else None,
        order_flow=encode(outputs.get('order_flow')),
        price_kind=outputs['market_data'].metadata.get('price_type'),
        execution_eligible=False)


def crypto_preview(*, asset, now_ns, evidence=None, derivatives=None):
    if asset not in {'BTC','ETH','SOL'}:
        raise ValueError('unsupported_canonical_crypto_asset')
    try:
        result=_crypto_preview(asset=asset,now_ns=now_ns,evidence=evidence,derivatives=derivatives)
        return result if isinstance(result,dict) else dict(preview=encode(result),analytical_stages=(),execution_eligible=False)
    except (ValueError,TypeError,KeyError,ArithmeticError) as exc:
        return dict(preview=encode(preview(asset=asset,broker_instrument=asset,institutional_instrument=None,
            now_ns=now_ns,canonical={'decision':'INSUFFICIENT_MARKET_DATA'},mapping_status='NOT_APPLICABLE',
            evidence_kind=evidence.evidence_kind if evidence else 'UNAVAILABLE',
            provenance=(evidence.source_sha256,) if evidence else (),reasons=(str(exc),),path='canonical_crypto_input_boundary')),
            analytical_stages=(),execution_eligible=False)
