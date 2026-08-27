import asyncio
import logging
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
from monatise.application.registry import PRODUCTION_ENGINE_ORDER
from monatise.application.workflows import TelegramNotifier


def test_registry_contains_complete_current_ftmo_scanner_universes():
    assert len(FTMO_REGISTRY.for_asset_class(FTMOAssetClass.STOCK)) == 59
    assert len(FTMO_REGISTRY.for_asset_class(FTMOAssetClass.FUTURES_LINKED)) == 34
    assert len(FTMO_REGISTRY.for_asset_class(FTMOAssetClass.FOREX)) == 28
    assert len(FTMO_REGISTRY.for_asset_class(FTMOAssetClass.CRYPTO)) == 30
    assert len(FTMO_REGISTRY.all()) == 151
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
    assert "FTMO executable entry/stop/target: WITHHELD" in message
    assert "Entry: 20,000" not in message
    assert "Invalidation: 19,900" not in message
    assert "Target: 20,200" not in message


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


def test_every_scanner_analysis_replaces_inherited_session_with_a_fresh_check():
    instrument = FTMO_REGISTRY.resolve("BTCUSD")
    registry = FTMOInstrumentRegistry((instrument,))
    published = []

    async def observe(_instrument):
        return {"ftmo_symbol": "BTCUSD", "score": 2, "direction": "long"}

    async def analyze(_candidate):
        return {
            "decision": "BUY_WATCH", "setup_status": "confirmed", "freshness": "fresh",
            "execution": {"enabled": False, "orders_placed": 0},
            "market_session": "STALE_PREVIOUS_SESSION", "session_checked_at": "2000-01-01T00:00:00+00:00",
        }

    async def publish(_instrument, analysis):
        published.append(analysis)

    result = asyncio.run(FTMOScannerPipeline(registry).run(
        FTMOAssetClass.CRYPTO, observe=observe, analyze=analyze, publish=publish,
    ))
    assert result.published == 1
    assert published[0]["market_session"] != "STALE_PREVIOUS_SESSION"
    assert published[0]["session_checked_at"] != "2000-01-01T00:00:00+00:00"
    assert published[0]["session_source"]


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
    assert runtime.dependencies["ftmo_stock_scan"]["scheduled"] is True
    assert runtime.dependencies["ftmo_stock_scan"]["poll_interval_seconds"] == 1800
    assert runtime.dependencies["ftmo_crypto_scan"]["poll_interval_seconds"] == 300
    assert runtime.dependencies["ftmo_futures_scan"]["poll_interval_seconds"] == 3600
    assert runtime.dependencies["ftmo_futures_scan"]["futures_roots"] == ["ES", "GC", "NQ"]


@pytest.mark.parametrize(
    ("remaining", "expected"),
    [(0, 0), (1, 0), (2, 0), (3, 0), (4, 1), (100, 49), ("unlimited", None)],
)
def test_flashalpha_scheduler_capacity_reserves_two_requests_for_on_demand(remaining, expected):
    runtime = OrchestrationRuntime.__new__(OrchestrationRuntime)
    runtime.environment = {}
    runtime.flashalpha = None
    runtime.dependencies = {"flashalpha": {"status": "healthy", "remaining": remaining}}

    assert runtime._flashalpha_scheduled_capacity() == expected


def test_flashalpha_cycle_budget_scales_to_plan_and_scanner_cadence():
    runtime = OrchestrationRuntime.__new__(OrchestrationRuntime)
    runtime.environment = {}
    runtime.flashalpha = None
    runtime.dependencies = {"flashalpha": {
        "status": "healthy", "plan": "growth", "daily_limit": 2500, "remaining": 2500,
    }}

    assert runtime._flashalpha_scheduled_capacity(interval_seconds=1800, allocation_fraction=0.7) == 17
    assert runtime._flashalpha_scheduled_capacity(interval_seconds=3600, allocation_fraction=0.3) == 15

    runtime.dependencies["flashalpha"].update({"plan": "basic", "daily_limit": 250, "remaining": 250})
    assert runtime._flashalpha_scheduled_capacity(interval_seconds=1800, allocation_fraction=0.7) == 1
    assert runtime._flashalpha_scheduled_capacity(interval_seconds=3600, allocation_fraction=0.3) == 1


class _RecordingScheduler:
    def __init__(self):
        self.jobs = []

    async def register(self, job):
        self.jobs.append(job)


async def _stock_runtime_async(scan):
    scheduler = _RecordingScheduler()
    runtime = OrchestrationRuntime.__new__(OrchestrationRuntime)
    runtime.environment = {"MONATISE_FTMO_STOCK_SCAN_ENABLED": "true"}
    runtime.application = SimpleNamespace(infrastructure=SimpleNamespace(scheduler=scheduler))
    runtime.telegram = object()
    runtime.redis = object()
    runtime.dependencies = {}
    runtime._run_stock_universe_scan = scan
    await runtime._register_ftmo_stock_scanner()
    return runtime, scheduler.jobs[0]


def _stock_runtime(scan):
    return asyncio.run(_stock_runtime_async(scan))


def _stock_cycle_result(**overrides):
    result = {
        "deep_analysis_attempted": 0,
        "deep_analysis_completed": 0,
        "qualified_setups": 0,
        "suppressed_count": 0,
        "telegram_published": 0,
        "proposal_published_count": 0,
        "execution_enabled": False,
    }
    result.update(overrides)
    return result


def test_stock_scanner_records_actual_start_and_running_state():
    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()

        async def scan(_configuration, _cooldown, _namespace):
            entered.set()
            await release.wait()
            return _stock_cycle_result()

        runtime, job = await _stock_runtime_async(scan)
        task = asyncio.create_task(job.task())
        await entered.wait()
        state = runtime.dependencies["ftmo_stock_scan"]
        assert state["scheduled"] is True
        assert state["running"] is True
        assert state["last_cycle_status"] == "running"
        assert datetime.fromisoformat(state["last_started_at"]).tzinfo is not None
        assert state["last_success_at"] is None
        release.set()
        await task

    asyncio.run(scenario())


def test_stock_scanner_successful_zero_publication_cycle_is_successful(caplog):
    async def scan(_configuration, _cooldown, _namespace):
        return _stock_cycle_result(deep_analysis_attempted=4, deep_analysis_completed=4, suppressed_count=4)

    runtime, job = _stock_runtime(scan)
    with caplog.at_level(logging.INFO, logger="monatise.orchestration"):
        asyncio.run(job.task())

    state = runtime.dependencies["ftmo_stock_scan"]
    assert state["running"] is False
    assert state["last_cycle_status"] == "succeeded"
    assert state["last_success_at"] == state["last_succeeded_at"]
    assert state["last_cycle_duration_ms"] >= 0
    assert state["candidate_count"] == 4
    assert state["analysis_completed_count"] == 4
    assert state["qualified_count"] == 0
    assert state["suppressed_count"] == 4
    assert state["published_count"] == 0
    assert state["last_error"] is None
    assert {record.message for record in caplog.records} >= {"stock_scan_started", "stock_scan_completed"}


def test_stock_scanner_successful_qualified_cycle_records_counters():
    async def scan(_configuration, _cooldown, _namespace):
        return _stock_cycle_result(
            candidate_count=5,
            analysis_completed_count=4,
            qualified_count=2,
            suppressed_count=2,
            proposal_published_count=1,
        )

    runtime, job = _stock_runtime(scan)
    asyncio.run(job.task())
    state = runtime.dependencies["ftmo_stock_scan"]
    assert {
        key: state[key]
        for key in ("candidate_count", "analysis_completed_count", "qualified_count", "suppressed_count", "published_count")
    } == {
        "candidate_count": 5,
        "analysis_completed_count": 4,
        "qualified_count": 2,
        "suppressed_count": 2,
        "published_count": 1,
    }


def test_stock_scanner_failure_is_sanitized_and_preserves_previous_success(caplog):
    outcomes = [_stock_cycle_result(deep_analysis_attempted=1, deep_analysis_completed=1), RuntimeError("private provider detail")]

    async def scan(_configuration, _cooldown, _namespace):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    runtime, job = _stock_runtime(scan)
    asyncio.run(job.task())
    previous_success = runtime.dependencies["ftmo_stock_scan"]["last_success_at"]
    with caplog.at_level(logging.WARNING, logger="monatise.orchestration"):
        with pytest.raises(RuntimeError, match="private provider detail"):
            asyncio.run(job.task())

    state = runtime.dependencies["ftmo_stock_scan"]
    assert state["running"] is False
    assert state["last_cycle_status"] == "failed"
    assert state["last_failure_at"] == state["last_failed_at"]
    assert state["last_success_at"] == previous_success
    assert state["last_succeeded_at"] == previous_success
    assert state["last_error"] == "RuntimeError"
    assert "private provider detail" not in str(state)
    assert next(record for record in caplog.records if record.message == "stock_scan_failed").error_type == "RuntimeError"


def test_readiness_exposes_stock_scanner_cycle_and_scheduler_state():
    async def scan(_configuration, _cooldown, _namespace):
        return _stock_cycle_result(candidate_count=3, analysis_completed_count=3, suppressed_count=3)

    runtime, job = _stock_runtime(scan)
    asyncio.run(job.task())
    stock_state = runtime.dependencies["ftmo_stock_scan"]
    mandatory = (
        "configuration", "postgresql", "migrations", "redis", "event_bus", "state_manager",
        "audit_repository", "audit_integrity", "audit_logging", "scheduler", "engine_registry",
        "pipeline_orchestrator", "governance", "notifications", "coinglass", "market_data", "hierarchy_shadow",
    )
    runtime.dependencies.update({name: {"status": "ok"} for name in mandatory})
    runtime.dependencies["ftmo_stock_scan"] = stock_state
    runtime.application = SimpleNamespace(registry=SimpleNamespace(ordered=lambda: tuple(
        SimpleNamespace(name=name) for name in PRODUCTION_ENGINE_ORDER
    )))
    runtime.safety = object()
    runtime.leadership = None
    runtime.coinglass = None

    ready, payload = runtime.readiness()
    assert ready is True
    exposed = payload["dependencies"]["ftmo_stock_scan"]
    assert exposed["scheduled"] is True
    assert exposed["job"] == "ftmo-stock-scanner-telegram"
    assert exposed["poll_interval_seconds"] == 1800
    assert exposed["last_started_at"]
    assert exposed["last_succeeded_at"]
    assert exposed["last_failed_at"] is None
    assert exposed["candidate_count"] == 3
    assert exposed["analysis_completed_count"] == 3
    assert exposed["suppressed_count"] == 3
    assert exposed["published_count"] == 0
