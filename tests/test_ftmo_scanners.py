import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from monatise.application.deployment import OrchestrationRuntime
from monatise.application.ftmo_registry import (
    FTMOAssetClass,
    FTMOInstrument,
    FTMOInstrumentRegistry,
    FTMO_REGISTRY,
)
from monatise.application.ftmo_scanner import (
    FTMOScannerConfiguration,
    FTMOScannerPipeline,
    publication_allowed,
    rank_ftmo_observations,
)
from monatise.application.workflows import TelegramNotifier


def test_registry_contains_complete_current_ftmo_scanner_universes():
    assert len(FTMO_REGISTRY.for_asset_class(FTMOAssetClass.STOCK)) == 59
    assert len(FTMO_REGISTRY.for_asset_class(FTMOAssetClass.FUTURES_LINKED)) == 34
    assert len(FTMO_REGISTRY.for_asset_class(FTMOAssetClass.CRYPTO)) == 30
    assert len(FTMO_REGISTRY.all()) == 123
    assert all(item.source and item.registry_version and item.last_verified_at.tzinfo for item in FTMO_REGISTRY.all())


@pytest.mark.parametrize("asset_class", tuple(FTMOAssetClass))
def test_every_enabled_ftmo_instrument_can_enter_its_scanner(asset_class):
    universe = FTMO_REGISTRY.for_asset_class(asset_class)
    observations = [
        {"ftmo_symbol": item.ftmo_symbol, "score": index + 1, "direction": "long"}
        for index, item in enumerate(universe)
    ]
    ranked = rank_ftmo_observations(FTMO_REGISTRY, asset_class, observations, limit=len(universe) + 1)
    assert {item.instrument.ftmo_symbol for item in ranked} == {item.ftmo_symbol for item in universe}


def test_disabled_and_random_provider_instruments_cannot_enter():
    bitcoin = FTMO_REGISTRY.resolve("BTCUSD")
    registry = FTMOInstrumentRegistry((replace(bitcoin, enabled=False, instrument_status="disabled"),))
    observations = (
        {"symbol": "BTC", "score": 10, "direction": "long"},
        {"symbol": "PEPE", "score": 999, "direction": "long"},
    )
    assert rank_ftmo_observations(registry, FTMOAssetClass.CRYPTO, observations) == ()
    assert rank_ftmo_observations(FTMO_REGISTRY, FTMOAssetClass.CRYPTO, [observations[1]]) == ()


def test_required_ftmo_futures_mappings_are_explicit_and_cfds_are_not_conflated():
    expected = {
        "US100.cash": ("NQ", "MNQ"),
        "US500.cash": ("ES", "MES"),
        "US30.cash": ("YM", "MYM"),
        "US2000.cash": ("RTY", "M2K"),
        "XAU/USD": ("GC", "MGC"),
        "USOIL.cash": ("CL", "MCL"),
    }
    for symbol, mapping in expected.items():
        item = FTMO_REGISTRY.resolve(symbol)
        assert (item.futures_symbol, item.micro_futures_symbol) == mapping
        assert item.ftmo_symbol not in mapping
        assert item.asset_class is FTMOAssetClass.FUTURES_LINKED

    message = TelegramNotifier.format_ftmo_futures_setup({
        "underlying_market": "Nasdaq-100", "ftmo_symbol": "US100.cash",
        "futures_symbol": "NQ", "micro_futures_symbol": "MNQ",
        "direction": "LONG", "score": 8, "score_threshold": 7,
        "entry": 20_000, "stop_loss": 19_900, "target": 20_200,
        "reward_risk": 2, "data_source": "test",
    })
    assert "FTMO Symbol: US100.cash" in message
    assert "Underlying Futures: NQ" in message
    assert "Asset Class: FUTURES-LINKED CFD" in message
    assert "not an exchange-traded futures contract" in message


@pytest.mark.parametrize("overrides", [
    {"decision": "NO_TRADE"},
    {"setup_status": "suppressed"},
    {"freshness": "stale"},
    {"publication_valid": False},
    {"execution": {"enabled": True, "orders_placed": 0}},
    {"execution": {"enabled": False, "orders_placed": 1}},
])
def test_scanner_score_cannot_bypass_publication_validation(overrides):
    analysis = {
        "decision": "BUY_WATCH", "setup_status": "confirmed", "freshness": "fresh",
        "publication_valid": True, "score": 999,
        "execution": {"enabled": False, "orders_placed": 0},
    }
    analysis.update(overrides)
    assert publication_allowed(analysis) is False


def test_confirmed_analysis_remains_notification_only():
    assert publication_allowed({
        "decision": "SELL_WATCH", "setup_status": "confirmed", "freshness": "fresh",
        "execution": {"enabled": False, "orders_placed": 0},
    }) is True


def test_registry_validation_rejects_duplicates_malformed_mappings_and_missing_provenance():
    apple = FTMO_REGISTRY.resolve("AAPL")
    with pytest.raises(ValueError, match="duplicate FTMO symbol"):
        FTMOInstrumentRegistry((apple, apple))
    with pytest.raises(ValueError, match="malformed FTMO symbol"):
        replace(apple, ftmo_symbol="BAD SYMBOL")
    with pytest.raises(ValueError, match="missing provenance"):
        replace(apple, source="")
    with pytest.raises(ValueError, match="non-futures instrument"):
        replace(apple, futures_symbol="ES")
    nasdaq = FTMO_REGISTRY.resolve("US100.cash")
    with pytest.raises(ValueError, match="no legitimate futures mapping"):
        replace(nasdaq, futures_symbol=None)
    collision = replace(
        FTMO_REGISTRY.resolve("MSFT"), market_data_provider=apple.market_data_provider,
        provider_symbol=apple.provider_symbol,
    )
    with pytest.raises(ValueError, match="duplicate provider mapping"):
        FTMOInstrumentRegistry((apple, collision))


def test_pipeline_bounds_provider_concurrency_and_provider_failures_fail_closed():
    instruments = FTMO_REGISTRY.for_asset_class(FTMOAssetClass.CRYPTO)[:8]
    registry = FTMOInstrumentRegistry(instruments)
    active = maximum = 0
    published = []

    async def observe(instrument):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1
        if instrument.ftmo_symbol == instruments[0].ftmo_symbol:
            raise RuntimeError("provider unavailable")
        return {"ftmo_symbol": instrument.ftmo_symbol, "score": 2, "direction": "long"}

    async def analyze(candidate):
        return {
            "ftmo_symbol": candidate.instrument.ftmo_symbol, "decision": "NO_TRADE",
            "setup_status": "confirmed", "execution": {"enabled": False, "orders_placed": 0},
        }

    async def publish(instrument, _analysis):
        published.append(instrument.ftmo_symbol)

    result = asyncio.run(FTMOScannerPipeline(
        registry, FTMOScannerConfiguration(candidate_limit=8, deep_analysis_limit=8, maximum_concurrency=3)
    ).run(FTMOAssetClass.CRYPTO, observe=observe, analyze=analyze, publish=publish))
    assert maximum <= 3
    assert result.provider_failures == 1
    assert result.published == 0 and published == []
    assert result.execution_enabled is False


def test_three_ftmo_scanner_jobs_replace_legacy_scheduler_jobs():
    class Scheduler:
        def __init__(self): self.jobs = []
        async def register(self, job): self.jobs.append(job)

    scheduler = Scheduler()
    runtime = OrchestrationRuntime.__new__(OrchestrationRuntime)
    runtime.environment = {
        "MONATISE_FTMO_STOCK_SCAN_ENABLED": "true",
        "MONATISE_FTMO_CRYPTO_SCAN_ENABLED": "true",
        "MONATISE_FTMO_FUTURES_SCAN_ENABLED": "true",
    }
    runtime.application = SimpleNamespace(infrastructure=SimpleNamespace(scheduler=scheduler))
    runtime.coinglass = object()
    runtime.telegram = object()
    runtime.redis = object()
    runtime.dependencies = {}
    asyncio.run(runtime._register_ftmo_stock_scanner())
    asyncio.run(runtime._register_ftmo_crypto_scanner())
    asyncio.run(runtime._register_ftmo_futures_scanner())
    job_ids = {job.job_id for job in scheduler.jobs}
    assert job_ids == {
        "ftmo-stock-scanner-telegram",
        "ftmo-crypto-scanner-telegram",
        "ftmo-futures-scanner-telegram",
    }
    assert not any("coin-discovery" in job_id or "altcoin" in job_id for job_id in job_ids)
    assert all(job.metadata["execution_enabled"] is False for job in scheduler.jobs)

