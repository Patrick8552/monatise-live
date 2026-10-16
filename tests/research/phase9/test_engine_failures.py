"""Reproduced Phase 9 defects, fixed clocks; no networking or publication."""
import asyncio
from collections.abc import Mapping
from threading import Event
from types import SimpleNamespace

import pytest

from monatise.application.deployment import OrchestrationRuntime
from monatise.application.ftmo_registry import FTMO_REGISTRY
from monatise.engines.market_data import MarketDataEngine, MarketDataRequest, DataStatus
from tests.engines.test_market_data_engine import GoodProvider, NOW


class BrokenMapping(Mapping):
    def __len__(self): return 1
    def __iter__(self): raise RuntimeError('bad iterator')
    def __getitem__(self, key): raise RuntimeError('bad item')


@pytest.mark.parametrize('payload', [None, [], 'bad', BrokenMapping(), {1: 2}, {'x': float('nan')}])
def test_malformed_optional_preserves_valid_candles(payload):
    provider = SimpleNamespace(derivatives_snapshot=lambda *args: payload)
    engine = MarketDataEngine({'fixture': GoodProvider()}, derivatives_provider=provider, clock=lambda: NOW)
    r = engine.collect(MarketDataRequest('GCZ6', interval='1m', max_age_seconds=120))
    assert r.quality.status is DataStatus.READY and len(r.candles) == 2
    assert r.metadata['derivatives_quality']['issues']
    if not isinstance(payload, dict) or 1 in payload:
        assert len(engine._derivative_quarantine) == 1
        assert len(engine._derivative_quarantine[0]['representation']) <= 65536


def test_optional_timeout_and_outstanding_call_are_bounded():
    release = Event()
    calls = []
    def slow(*args):
        calls.append(1)
        release.wait(5)
        return {'open_interest': 123}
    engine = MarketDataEngine({'fixture': GoodProvider()}, derivatives_provider=SimpleNamespace(derivatives_snapshot=slow),
        clock=lambda: NOW, derivatives_timeout_seconds=.01)
    try:
        for _ in range(3):
            r = engine.collect(MarketDataRequest('ESZ6', interval='1m', max_age_seconds=120))
            assert r.quality.status is DataStatus.READY and r.derivatives == {}
        assert len(calls) == 1
    finally:
        release.set()


def test_optional_exception_does_not_disclose_provider_secrets():
    def fail(*args): raise OSError('https://secret.invalid?api_key=NEVER_REPORT')
    engine = MarketDataEngine({'fixture': GoodProvider()}, derivatives_provider=SimpleNamespace(derivatives_snapshot=fail), clock=lambda: NOW)
    r = engine.collect(MarketDataRequest('NQZ6', interval='1m', max_age_seconds=120))
    assert r.quality.status is DataStatus.READY and 'OSError' in str(r.quality.issues)
    assert 'NEVER_REPORT' not in str(r)


@pytest.mark.parametrize('error', [OSError, ValueError, RuntimeError])
def test_gold_failure_does_not_abort_es_nq(monkeypatch, error):
    import monatise.application.deployment as deployment
    monkeypatch.setattr(deployment, 'validate_flashalpha_context', lambda *a, **k: NOW)
    calls = []
    async def fail(*a, **k): raise error('synthetic failure')
    async def invalidate(*a): calls.append('invalidate')
    async def independent(instrument, **kwargs):
        calls.append(instrument.futures_symbol)
        return {'decision': 'NO_TRADE', 'reasons': ['no_setup'], 'publication_valid': False}
    async def alerts(**kwargs): return []
    runtime = SimpleNamespace(environment={}, flashalpha=SimpleNamespace(context=lambda *a: {}),
        recent_tradingview_alerts=alerts, _flashalpha_scheduled_capacity=lambda **kw: None,
        _gold_coordinator=lambda: SimpleNamespace(analyse=fail, technical=SimpleNamespace(invalidate=invalidate)),
        _shared_asset_hierarchy=lambda: SimpleNamespace(analyse=independent))
    instruments = tuple(FTMO_REGISTRY.resolve(s) for s in ('XAU/USD', 'US500.cash', 'US100.cash'))
    result = asyncio.run(OrchestrationRuntime._analyze_ftmo_futures(runtime, instruments, 300, 'test'))
    assert calls == ['invalidate', 'ES', 'NQ']
    assert result['analysis_completed_count'] == 2 and result['analysis_failure_count'] == 1
    assert result['telegram_published'] == 0 and not result['execution_enabled']
    gold = next(r for r in result['results'] if r.get('ftmo_symbol') == instruments[0].ftmo_symbol)
    assert gold['decision'] == 'INSUFFICIENT_MARKET_DATA' and not gold['execution_eligible']
    assert gold['unexpected_error'] == (error is RuntimeError)


def test_cancelled_scan_still_propagates():
    async def fail(*a, **k): raise asyncio.CancelledError()
    async def alerts(**kwargs): return []
    runtime = SimpleNamespace(environment={}, recent_tradingview_alerts=alerts,
        _gold_coordinator=lambda: SimpleNamespace(analyse=fail))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(OrchestrationRuntime._analyze_ftmo_futures(runtime, (FTMO_REGISTRY.resolve('XAU/USD'),), 300, 'test'))
