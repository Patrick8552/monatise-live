from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from monatise.application.deployment import COINGLASS_PROVIDER_KEY, SCHEDULED_ANALYSIS_DEFAULT_SYMBOLS, MigrationRunner, OrchestrationASGI, OrchestrationRuntime, PaperSafetyConfiguration, RedisCoordinationStore, RedisSchedulerLeadership, TelegramNotificationTransport, register_coinglass_provider, scheduled_analysis_configuration
from monatise.application.registry import CANONICAL_ENGINE_ORDER
from monatise.application.registry import PRODUCTION_ENGINE_ORDER
from monatise.application.production_analysis import build_production_analysis_run
from monatise.infrastructure.dependency_injection import Container
from monatise.engines.decision.models import DecisionClassification


def test_paper_safety_defaults_are_immutable_and_disabled():
    config = PaperSafetyConfiguration.from_environment({})
    assert config.mode == "paper"
    assert config.execution_enabled is False
    assert config.governance_kill_switch_enabled is True


def test_startup_failure_records_phase_and_logs_traceback(caplog):
    runtime = OrchestrationRuntime(environment={})

    with caplog.at_level(logging.ERROR, logger="monatise.orchestration"):
        with pytest.raises(RuntimeError, match="PostgreSQL configuration is unavailable"):
            asyncio.run(runtime.start())

    assert runtime.dependencies["startup"] == {
        "status": "error",
        "phase": "postgresql_configuration",
        "error_type": "RuntimeError",
    }
    record = next(item for item in caplog.records if item.message.startswith("orchestration startup failed"))
    assert record.exc_info is not None


def test_lifespan_failure_is_sanitized_and_logged(caplog):
    class FailingRuntime:
        async def start(self):
            raise RuntimeError("private provider detail")

    pending = [{"type": "lifespan.startup"}]
    sent = []

    async def receive():
        return pending.pop(0)

    async def send(message):
        sent.append(message)

    with caplog.at_level(logging.ERROR, logger="monatise.orchestration"):
        asyncio.run(OrchestrationASGI(FailingRuntime())({"type": "lifespan"}, receive, send))

    assert sent == [{"type": "lifespan.startup.failed", "message": "startup_failed"}]
    record = next(item for item in caplog.records if item.message == "application lifespan startup failed")
    assert record.exc_info is not None


def test_telegram_transport_returns_provider_message_id(monkeypatch):
    captured = {}

    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self): return b'{"ok":true,"result":{"message_id":321}}'

    def open_request(request, timeout):
        captured.update(json.loads(request.data.decode()))
        return Response()

    monkeypatch.setattr("monatise.application.deployment.urlopen", open_request)
    transport = TelegramNotificationTransport(lambda: "test-token")

    message = "Status: ready | Run: 42\nDetail: BTC < ETH\nR:R remains unchanged"
    assert asyncio.run(transport.send_message("chat", message)) == 321
    assert captured == {
        "chat_id": "chat",
        "text": "<b>Status</b>: ready | <b>Run</b>: 42\n<b>Detail</b>: BTC &lt; ETH\nR:R remains unchanged",
        "parse_mode": "HTML",
    }


@pytest.mark.parametrize(
    "environment",
    [
        {"MONATISE_MODE": "live"},
        {"MONATISE_NETWORK": "mainnet"},
        {"MONATISE_EXECUTION_ENABLED": "true"},
        {"MONATISE_AUTONOMOUS_EXECUTION": "1"},
        {"MONATISE_EXECUTION_ADAPTER_ENABLED": "yes"},
        {"MONATISE_OPENCLAW_EXECUTION_ALLOWED": "true"},
        {"MONATISE_TELEGRAM_EXECUTION_ALLOWED": "true"},
        {"MONATISE_GOVERNANCE_KILL_SWITCH_ENABLED": "false"},
        {"MONATISE_AUDIT_LOGGING_ENABLED": "false"},
    ],
)
def test_paper_safety_rejects_unsafe_environment(environment):
    with pytest.raises(ValueError, match="unsafe orchestration configuration"):
        PaperSafetyConfiguration.from_environment(environment)


def test_scheduled_analysis_configuration_is_explicit_bounded_and_crypto_only():
    assert scheduled_analysis_configuration({}) is None
    assert scheduled_analysis_configuration({
        "MONATISE_SCHEDULED_ANALYSIS_ENABLED": "true",
        "MONATISE_SCHEDULED_ANALYSIS_SYMBOLS": "BTC, ETH, BTC",
        "MONATISE_SCHEDULED_ANALYSIS_TIMEFRAMES": "5m,15m,5m",
    }) == (("BTC", "ETH"), ("5m", "15m"))
    # Without an explicit override, scheduled analysis now defaults to 15m,
    # not the old 1h.
    assert scheduled_analysis_configuration({
        "MONATISE_SCHEDULED_ANALYSIS_ENABLED": "true",
    }) == (SCHEDULED_ANALYSIS_DEFAULT_SYMBOLS, ("15m",))
    with pytest.raises(ValueError, match="unsupported scheduled analysis symbols"):
        scheduled_analysis_configuration({
            "MONATISE_SCHEDULED_ANALYSIS_ENABLED": "true",
            "MONATISE_SCHEDULED_ANALYSIS_SYMBOLS": "XAUUSD",
        })
    with pytest.raises(ValueError, match="unsupported scheduled analysis timeframes"):
        scheduled_analysis_configuration({
            "MONATISE_SCHEDULED_ANALYSIS_ENABLED": "true",
            "MONATISE_SCHEDULED_ANALYSIS_TIMEFRAMES": "2h",
        })


def test_production_analysis_graph_completely_excludes_risk_engine_and_consumers():
    run = build_production_analysis_run("BTC", interval="15m")

    assert tuple(run.stage_inputs) == PRODUCTION_ENGINE_ORDER
    assert "risk_validation" not in run.stage_inputs
    assert "capital_allocation" not in run.stage_inputs
    assert "execution_policy" not in run.stage_inputs
    assert "governance_loss_control" not in run.stage_inputs
    assert set(PRODUCTION_ENGINE_ORDER).issubset(CANONICAL_ENGINE_ORDER)


def test_order_flow_input_uses_real_change_and_split_liquidations_not_duplicated_levels():
    run = build_production_analysis_run("BTC", interval="15m")
    flow = run.stage_inputs["order_flow"]
    context = SimpleNamespace(outputs={
        "market_data": SimpleNamespace(derivatives={
            "open_interest": 500_000.0, "open_interest_change_pct": -2.4,
            "cvd": 900.0, "cvd_delta": -350.0,
            "liquidation_volume": 70_000.0, "liquidation_long_usd": 55_000.0, "liquidation_short_usd": 15_000.0,
            "order_book_imbalance": 0.12, "funding_rate": 0.0003,
        }),
        "regime": None,
        "market_structure": None,
    })

    request = flow(context)

    # open_interest_change_pct must be the signed percentage change, never the
    # always-positive absolute level -- that would make every symbol read as
    # permanently "expanding" regardless of actual direction.
    assert request.flow.open_interest_change_pct == -2.4
    assert request.flow.cvd_change == -350.0
    assert request.flow.liquidation_long_usd == 55_000.0
    assert request.flow.liquidation_short_usd == 15_000.0
    assert request.flow.liquidation_long_usd != request.flow.liquidation_short_usd


def test_runtime_registers_paper_only_analysis_jobs_for_each_configured_symbol():
    class Scheduler:
        def __init__(self): self.definitions = []
        async def register(self, definition): self.definitions.append(definition)

    scheduler = Scheduler()
    runtime = OrchestrationRuntime(environment={
        "MONATISE_SCHEDULED_ANALYSIS_ENABLED": "true",
        "MONATISE_SCHEDULED_ANALYSIS_SYMBOLS": "BTC,SOL",
        "MONATISE_SCHEDULED_ANALYSIS_TIMEFRAMES": "5m,1h",
    })
    runtime.application = SimpleNamespace(infrastructure=SimpleNamespace(scheduler=scheduler))

    job_ids = asyncio.run(runtime._register_scheduled_analysis())

    assert job_ids == ("scheduled-analysis-btc-5m", "scheduled-analysis-btc-1h", "scheduled-analysis-sol-5m", "scheduled-analysis-sol-1h")
    assert [item.interval.total_seconds() for item in scheduler.definitions] == [300, 3600, 300, 3600]
    assert all(item.metadata["execution_enabled"] is False for item in scheduler.definitions)
    assert all(item.metadata["notification_policy"] == "qualified_changes" for item in scheduler.definitions)
    assert all("paper-only" in item.tags for item in scheduler.definitions)


def _record_delivered(runtime, symbol, interval, candidate, message_id=1):
    assert asyncio.run(runtime._reserve_telegram_notification(symbol, interval, candidate)) is True
    asyncio.run(runtime._finish_telegram_notification(symbol, interval, candidate, "delivered", message_id=message_id))


@pytest.mark.parametrize(("direction", "signed_score"), [("long", 8), ("short", -8)])
def test_qualified_directional_setups_are_claimed_for_telegram(direction, signed_score):
    runtime = OrchestrationRuntime(environment={})
    decision = SimpleNamespace(
        classification=SimpleNamespace(value="trend"),
        direction=SimpleNamespace(value=direction),
        metadata={"signed_signal_score": signed_score, "minimum_signal_score": 7},
    )
    risk = SimpleNamespace(
        decision=SimpleNamespace(value="approved"),
        validated_entry=65_000,
        validated_invalidation=63_500 if direction == "long" else 66_500,
        validated_target=68_000 if direction == "long" else 62_000,
        metadata={},
    )
    result = SimpleNamespace(
        symbol="BTC",
        status=SimpleNamespace(value="completed"),
        context=SimpleNamespace(outputs={"decision": decision, "risk_validation": risk}),
    )

    candidate = asyncio.run(runtime._telegram_notification_candidate(result, "1h"))
    assert candidate is not None
    _record_delivered(runtime, "BTC", "1h", candidate)
    assert asyncio.run(runtime._telegram_notification_candidate(result, "1h")) is None


@pytest.mark.parametrize(("direction", "signed_score"), [("long", -8), ("short", 8)])
def test_mismatched_directional_scores_are_not_claimed_for_telegram(direction, signed_score):
    runtime = OrchestrationRuntime(environment={})
    result = SimpleNamespace(
        symbol="BTC",
        status=SimpleNamespace(value="completed"),
        context=SimpleNamespace(outputs={
            "decision": SimpleNamespace(
                classification=SimpleNamespace(value="trend"),
                direction=SimpleNamespace(value=direction),
                metadata={"signed_signal_score": signed_score, "minimum_signal_score": 7},
            ),
            "risk_validation": SimpleNamespace(metadata={}),
        }),
    )

    assert asyncio.run(runtime._telegram_notification_candidate(result, "1h")) is None


def test_incomplete_directional_setups_are_not_claimed_for_telegram():
    runtime = OrchestrationRuntime(environment={})
    result = SimpleNamespace(
        symbol="BTC",
        status=SimpleNamespace(value="blocked"),
        context=SimpleNamespace(outputs={
            "decision": SimpleNamespace(
                classification=SimpleNamespace(value="trend"),
                direction=SimpleNamespace(value="long"),
                metadata={"signed_signal_score": 8, "minimum_signal_score": 7},
            ),
        }),
    )

    assert asyncio.run(runtime._telegram_notification_candidate(result, "1h")) is None


def test_legacy_risk_rejection_does_not_block_completed_directional_notification():
    runtime = OrchestrationRuntime(environment={})
    result = SimpleNamespace(
        symbol="BTC",
        status=SimpleNamespace(value="completed"),
        context=SimpleNamespace(outputs={
            "decision": SimpleNamespace(
                classification=SimpleNamespace(value="trend"),
                direction=SimpleNamespace(value="long"),
                metadata={"signed_signal_score": 8, "minimum_signal_score": 7},
            ),
            "risk_validation": SimpleNamespace(decision=SimpleNamespace(value="rejected")),
        }),
    )

    assert asyncio.run(runtime._telegram_notification_candidate(result, "1h")) is not None


def _grid_result(confirmation_status="pending", price=65_000):
    return SimpleNamespace(
        symbol="BTC",
        status=SimpleNamespace(value="completed"),
        context=SimpleNamespace(outputs={
            "decision": SimpleNamespace(
                classification=SimpleNamespace(value="grid"),
                direction=SimpleNamespace(value="two_sided"),
                metadata={"grid_signal_score": 8, "minimum_signal_score": 7},
            ),
            "market_data": SimpleNamespace(symbol="BTC", price=price, candles=()),
            "price_action": SimpleNamespace(
                status=SimpleNamespace(value=confirmation_status),
                strongest_confirming_pattern="bullish_engulfing" if confirmation_status == "confirmed" else None,
            ),
        }),
    )


@pytest.mark.parametrize("status", ("pending", "conflict", "expired", "invalidated"))
def test_unconfirmed_grid_setups_are_not_claimed_for_scheduled_telegram(status):
    runtime = OrchestrationRuntime(environment={})

    assert asyncio.run(runtime._telegram_notification_candidate(_grid_result(status), "15m")) is None


def test_confirmed_grid_setup_is_claimed_once_for_scheduled_telegram():
    runtime = OrchestrationRuntime(environment={})
    result = _grid_result("confirmed")

    candidate = asyncio.run(runtime._telegram_notification_candidate(result, "15m"))
    assert candidate is not None
    assert candidate["expires_at"] is not None
    assert candidate["validity_candles"] == 4
    _record_delivered(runtime, "BTC", "15m", candidate)
    assert asyncio.run(runtime._telegram_notification_candidate(result, "15m")) is None


def test_grid_level_drift_does_not_repeat_same_confirmation():
    runtime = OrchestrationRuntime(environment={})
    candidate = asyncio.run(runtime._telegram_notification_candidate(_grid_result("confirmed", price=65_000), "15m"))
    assert candidate is not None
    _record_delivered(runtime, "BTC", "15m", candidate)

    assert asyncio.run(runtime._telegram_notification_candidate(_grid_result("confirmed", price=65_500), "15m")) is None


@pytest.mark.parametrize("status", ("conflict", "expired", "invalidated"))
def test_terminal_grid_transition_cancels_once_after_confirmation(status):
    runtime = OrchestrationRuntime(environment={})
    confirmed = asyncio.run(runtime._telegram_notification_candidate(_grid_result("confirmed"), "15m"))
    assert confirmed is not None
    _record_delivered(runtime, "BTC", "15m", confirmed)

    terminal = asyncio.run(runtime._telegram_notification_candidate(_grid_result(status), "15m"))
    assert terminal is not None
    assert terminal["confirmation_status"] == "cancelled"
    assert terminal["cancellation_reason"] == f"price-action confirmation became {status}"
    _record_delivered(runtime, "BTC", "15m", terminal)
    assert asyncio.run(runtime._telegram_notification_candidate(_grid_result(status), "15m")) is None


def test_one_point_grid_score_drop_does_not_cancel_confirmed_entry():
    runtime = OrchestrationRuntime(environment={})
    confirmed = asyncio.run(runtime._telegram_notification_candidate(_grid_result("confirmed"), "15m"))
    assert confirmed is not None
    _record_delivered(runtime, "BTC", "15m", confirmed)
    disqualified = _grid_result("confirmed")
    disqualified.context.outputs["decision"].metadata["grid_signal_score"] = 6

    cancellation = asyncio.run(runtime._telegram_notification_candidate(disqualified, "15m"))

    assert cancellation is None


def test_two_point_grid_score_drop_cancels_previously_confirmed_entry():
    runtime = OrchestrationRuntime(environment={})
    confirmed = asyncio.run(runtime._telegram_notification_candidate(_grid_result("confirmed"), "15m"))
    assert confirmed is not None
    _record_delivered(runtime, "BTC", "15m", confirmed)
    disqualified = _grid_result("confirmed")
    disqualified.context.outputs["decision"].metadata["grid_signal_score"] = 5

    cancellation = asyncio.run(runtime._telegram_notification_candidate(disqualified, "15m"))

    assert cancellation is not None
    assert cancellation["confirmation_status"] == "cancelled"
    assert cancellation["cancellation_reason"] == "signal score 5/10 fell below the 7/10 threshold"


def test_no_trade_does_not_cancel_previously_confirmed_grid():
    runtime = OrchestrationRuntime(environment={})
    confirmed = asyncio.run(runtime._telegram_notification_candidate(_grid_result("confirmed"), "15m"))
    assert confirmed is not None
    _record_delivered(runtime, "BTC", "15m", confirmed)
    disqualified = _grid_result("confirmed")
    disqualified.context.outputs["decision"].classification = DecisionClassification.NO_TRADE

    assert asyncio.run(runtime._telegram_notification_candidate(disqualified, "15m")) is None


def test_expired_directional_setup_is_transitioned_before_new_analysis():
    runtime = OrchestrationRuntime(environment={})
    runtime._telegram_signal_states[("BTC", "15m")] = {
        "fingerprint": "directional-1",
        "classification": "trend",
        "confirmation_status": "pending",
        "delivery_status": "delivered",
        "expires_at": "2026-08-07T10:00:00+00:00",
        "version": 7,
    }

    expiry = asyncio.run(runtime._telegram_notification_candidate(_grid_result("pending"), "15m"))

    assert expiry["expires_directional_setup"] is True
    assert expiry["confirmation_status"] == "expired"
    assert expiry["expected_version"] == 7


def test_no_trade_does_not_notify_without_previous_confirmed_grid():
    runtime = OrchestrationRuntime(environment={})
    result = _grid_result("pending")
    result.context.outputs["decision"].classification = SimpleNamespace(value="no_trade")

    assert asyncio.run(runtime._telegram_notification_candidate(result, "15m")) is None


def test_failed_telegram_delivery_is_recorded_without_automatic_duplicate_retry():
    class Orchestrator:
        async def run(self, run):
            result = _grid_result("confirmed")
            result.run_id = "run-failed-delivery"
            result.correlation_id = run.correlation_id
            result.statistics = SimpleNamespace(completed_stages=1)
            result.blocked_by = None
            return result

    class Telegram:
        async def deliver(self, result):
            raise RuntimeError("offline")

    class Audit:
        async def append(self, **kwargs):
            return None

    runtime = OrchestrationRuntime(environment={})
    runtime.application = SimpleNamespace(orchestrator=Orchestrator(), infrastructure=SimpleNamespace(audit=Audit()))
    runtime.telegram = Telegram()

    asyncio.run(runtime.analyse("BTC", interval="15m", notification_policy="qualified_changes"))
    assert asyncio.run(runtime._telegram_notification_candidate(_grid_result("confirmed"), "15m")) is None
    state = runtime._telegram_signal_states[("BTC", "15m")]
    assert state["delivery_status"] == "failed"
    assert state["error_type"] == "RuntimeError"


def test_confirmed_grid_to_directional_setup_is_one_replacement_candidate():
    runtime = OrchestrationRuntime(environment={})
    confirmed = asyncio.run(runtime._telegram_notification_candidate(_grid_result("confirmed"), "15m"))
    _record_delivered(runtime, "BTC", "15m", confirmed)
    directional = _grid_result("pending")
    directional.context.outputs["decision"] = SimpleNamespace(
        classification=SimpleNamespace(value="trend"),
        direction=SimpleNamespace(value="long"),
        metadata={"signed_signal_score": 8, "minimum_signal_score": 7},
    )

    replacement = asyncio.run(runtime._telegram_notification_candidate(directional, "15m"))

    assert replacement is not None
    assert replacement["replaces_confirmed_grid"] is True
    assert replacement["classification"] == "trend"


def test_redis_notification_state_survives_runtime_restart():
    class Redis:
        def __init__(self): self.values = {}
        async def get(self, key): return self.values.get(key)
        async def set(self, key, value, **kwargs): self.values[key] = value; return True
        async def eval(self, script, count, key, expected_version, encoded):
            current = json.loads(self.values[key]) if key in self.values else {}
            if int(current.get("version", 0)) != int(expected_version): return None
            incoming = json.loads(encoded)
            incoming["version"] = int(expected_version) + 1
            self.values[key] = json.dumps(incoming)
            return self.values[key]

    redis = Redis()
    first = OrchestrationRuntime(environment={})
    first.redis_coordination = RedisCoordinationStore(redis, namespace="test")
    candidate = asyncio.run(first._telegram_notification_candidate(_grid_result("confirmed"), "15m"))
    assert candidate is not None
    _record_delivered(first, "BTC", "15m", candidate)

    restarted = OrchestrationRuntime(environment={})
    restarted.redis_coordination = RedisCoordinationStore(redis, namespace="test")
    assert asyncio.run(restarted._telegram_notification_candidate(_grid_result("confirmed"), "15m")) is None


def test_atomic_reservation_allows_only_one_overlapping_sender():
    class Redis:
        def __init__(self): self.values = {}
        async def get(self, key): return self.values.get(key)
        async def eval(self, script, count, key, expected_version, encoded):
            current = json.loads(self.values[key]) if key in self.values else {}
            if int(current.get("version", 0)) != int(expected_version): return None
            incoming = json.loads(encoded)
            incoming["version"] = int(expected_version) + 1
            self.values[key] = json.dumps(incoming)
            return self.values[key]

    redis = Redis()
    first = OrchestrationRuntime(environment={})
    second = OrchestrationRuntime(environment={})
    first.redis_coordination = RedisCoordinationStore(redis, namespace="test")
    second.redis_coordination = RedisCoordinationStore(redis, namespace="test")
    first_candidate = asyncio.run(first._telegram_notification_candidate(_grid_result("confirmed"), "15m"))
    second_candidate = asyncio.run(second._telegram_notification_candidate(_grid_result("confirmed"), "15m"))

    assert asyncio.run(first._reserve_telegram_notification("BTC", "15m", first_candidate)) is True
    assert asyncio.run(second._reserve_telegram_notification("BTC", "15m", second_candidate)) is False


def test_redis_notification_state_rejects_stale_compare_and_set():
    class Redis:
        def __init__(self): self.values = {}
        async def get(self, key): return self.values.get(key)
        async def set(self, key, value, **kwargs): self.values[key] = value; return True
        async def eval(self, script, count, key, expected_version, encoded):
            current = json.loads(self.values[key]) if key in self.values else {}
            if int(current.get("version", 0)) != int(expected_version): return None
            incoming = json.loads(encoded)
            incoming["version"] = int(expected_version) + 1
            self.values[key] = json.dumps(incoming)
            return self.values[key]

    redis = Redis()
    runtime = OrchestrationRuntime(environment={})
    runtime.redis_coordination = RedisCoordinationStore(redis, namespace="test")
    key = ("BTC", "15m")
    redis.values["test:notification-state:btc:15m"] = json.dumps({
        "fingerprint": "new",
        "classification": "grid",
        "confirmation_status": "confirmed",
        "version": 20,
    })

    stored = asyncio.run(runtime.redis_coordination.notification_state_compare_and_put(
        "btc:15m", 10, {"fingerprint": "old"},
    ))

    assert stored is None
    assert json.loads(redis.values["test:notification-state:btc:15m"])["fingerprint"] == "new"


def test_runtime_registers_fail_closed_hierarchy_shadow_jobs_without_publication():
    class Scheduler:
        def __init__(self): self.definitions = []
        async def register(self, definition): self.definitions.append(definition)

    scheduler = Scheduler()
    runtime = OrchestrationRuntime(environment={
        "MONATISE_HIERARCHICAL_SHADOW_ENABLED": "true",
        "MONATISE_SCHEDULED_ANALYSIS_SYMBOLS": "BTC,ETH",
    })
    runtime.application = SimpleNamespace(infrastructure=SimpleNamespace(scheduler=scheduler))
    runtime.coinglass = SimpleNamespace()

    job_ids = asyncio.run(runtime._register_hierarchy_shadow(SimpleNamespace()))

    assert job_ids == ("hierarchy-shadow-btc", "hierarchy-shadow-eth")
    assert all(item.interval.total_seconds() == 60 for item in scheduler.definitions)
    assert all(item.metadata["shadow"] is True for item in scheduler.definitions)
    assert all(item.metadata["telegram_publish_enabled"] is False for item in scheduler.definitions)
    assert all(item.metadata["execution_enabled"] is False for item in scheduler.definitions)
    assert runtime.dependencies["hierarchy_shadow"]["enabled"] is True


def test_runtime_registers_btc_15m_5m_confluence_on_a_15_minute_cycle():
    class Scheduler:
        def __init__(self): self.definitions = []
        async def register(self, definition): self.definitions.append(definition)

    scheduler = Scheduler()
    runtime = OrchestrationRuntime(environment={
        "MONATISE_HIERARCHICAL_SHADOW_ENABLED": "true",
        "MONATISE_HIERARCHICAL_INTERVAL_SECONDS": "900",
        "MONATISE_HIERARCHICAL_ALWAYS_COLLECT_5M": "true",
        "MONATISE_SCHEDULED_ANALYSIS_SYMBOLS": "BTC",
    })
    runtime.application = SimpleNamespace(infrastructure=SimpleNamespace(scheduler=scheduler))
    runtime.coinglass = SimpleNamespace()

    job_ids = asyncio.run(runtime._register_hierarchy_shadow(SimpleNamespace()))

    assert job_ids == ("hierarchy-shadow-btc",)
    definition = scheduler.definitions[0]
    assert definition.interval.total_seconds() == 900
    assert definition.metadata["confluence_timeframes"] == ("15m", "5m")


def test_runtime_reports_requested_hierarchy_publication_without_publisher_as_error():
    class Scheduler:
        def __init__(self): self.definitions = []
        async def register(self, definition): self.definitions.append(definition)

    scheduler = Scheduler()
    runtime = OrchestrationRuntime(environment={
        "MONATISE_HIERARCHICAL_SHADOW_ENABLED": "true",
        "MONATISE_HIERARCHICAL_TELEGRAM_PUBLISH_ENABLED": "true",
        "MONATISE_SCHEDULED_ANALYSIS_SYMBOLS": "BTC",
    })
    runtime.application = SimpleNamespace(infrastructure=SimpleNamespace(scheduler=scheduler))
    runtime.coinglass = SimpleNamespace()

    asyncio.run(runtime._register_hierarchy_shadow(SimpleNamespace()))

    status = runtime.dependencies["hierarchy_shadow"]
    assert status["status"] == "error"
    assert status["telegram_publish_enabled"] is True
    assert status["telegram_publisher_configured"] is False
    assert status["telegram_publication_operational"] is False
    reconciliation = next(item for item in scheduler.definitions if item.job_id == "hierarchy-publication-reconciliation")
    assert reconciliation.metadata == {
        "operator_resolution_required": True,
        "automatic_resend": False,
        "execution_enabled": False,
    }


def test_runtime_notifies_every_analysis_result():
    delivered = []

    class Orchestrator:
        def __init__(self): self.completed = False
        async def run(self, run):
            outputs = {"decision": SimpleNamespace(classification=SimpleNamespace(value="trend"))}
            if self.completed:
                outputs.update({name: object() for name in (
                    "risk_validation", "capital_allocation", "execution_policy", "governance_loss_control",
                )})
            return SimpleNamespace(
                run_id="run-1", correlation_id=run.correlation_id, symbol=run.symbol,
                status=SimpleNamespace(value="completed" if self.completed else "blocked"),
                blocked_by=None if self.completed else "risk_validation",
                context=SimpleNamespace(outputs=outputs),
                statistics=SimpleNamespace(completed_stages=19 if self.completed else 12),
            )

    class Telegram:
        async def deliver(self, result): delivered.append(result.run_id)

    orchestrator = Orchestrator()
    runtime = OrchestrationRuntime(environment={})
    runtime.application = SimpleNamespace(orchestrator=orchestrator)
    runtime.telegram = Telegram()

    asyncio.run(runtime.analyse("BTC", source="monatise.scheduler"))
    assert delivered == ["run-1"]
    orchestrator.completed = True
    asyncio.run(runtime.analyse("BTC", source="monatise.scheduler"))
    assert delivered == ["run-1", "run-1"]


class _ReadyRuntime:
    async def start(self):
        return None

    async def shutdown(self):
        return None

    def readiness(self):
        return True, {
            "status": "ready",
            "mode": "paper",
            "execution_enabled": False,
            "dependencies": {"engine_registry": {"status": "ok", "count": 20, "order": list(CANONICAL_ENGINE_ORDER)}},
        }


def _request(app, path):
    async def call():
        messages = []

        async def receive():
            return {"type": "http.request"}

        async def send(message):
            messages.append(message)

        await app({"type": "http", "path": path}, receive, send)
        return messages

    messages = asyncio.run(call())
    return messages[0]["status"], json.loads(messages[1]["body"])


def test_asgi_liveness_and_readiness():
    app = OrchestrationASGI(_ReadyRuntime())
    assert _request(app, "/health/live") == (200, {"status": "alive"})
    code, payload = _request(app, "/health/ready")
    assert code == 200
    assert payload["execution_enabled"] is False


def test_asgi_readiness_is_sanitized_when_unavailable():
    class Runtime(_ReadyRuntime):
        def readiness(self):
            return False, {"status": "not_ready", "execution_enabled": False, "dependencies": {"postgresql": {"status": "error", "reason": "ConnectionError"}}}

    code, payload = _request(OrchestrationASGI(Runtime()), "/health/ready")
    assert code == 503
    rendered = json.dumps(payload)
    assert "postgresql://" not in rendered
    assert "password" not in rendered.casefold()


class _Redis:
    def __init__(self):
        self.value = None

    async def set(self, key, value, **kwargs):
        if kwargs.get("nx") and self.value is not None:
            return False
        self.value = value
        return True

    async def eval(self, script, count, key, *args):
        if "DEL" in script and self.value == args[0]:
            self.value = None
            return 1
        if "EXPIRE" in script and self.value == args[0]:
            return 1
        return 0


def test_scheduler_leadership_is_singleton_and_recoverable():
    async def scenario():
        redis = _Redis()
        first = RedisSchedulerLeadership(redis, namespace="test", ttl_seconds=30)
        second = RedisSchedulerLeadership(redis, namespace="test", ttl_seconds=30)
        assert await first.acquire() is True
        assert await second.acquire() is False
        await first.release()
        assert await second.acquire() is True
        await second.release()

    asyncio.run(scenario())


def test_scheduler_non_leader_retries_and_starts_after_release():
    async def scenario():
        redis = _Redis()
        first = RedisSchedulerLeadership(redis, namespace="test", ttl_seconds=0.03)
        second = RedisSchedulerLeadership(redis, namespace="test", ttl_seconds=0.03)
        started = asyncio.Event()

        assert await first.acquire() is True
        assert await second.acquire_or_wait(started.set) is False
        await first.release()
        await asyncio.wait_for(started.wait(), timeout=0.2)
        assert second.is_leader is True
        await second.release()

    asyncio.run(scenario())


def test_scheduler_stops_and_recontends_after_leadership_loss():
    async def scenario():
        redis = _Redis()
        leadership = RedisSchedulerLeadership(redis, namespace="test", ttl_seconds=0.03)
        restarted = asyncio.Event()
        stopped = asyncio.Event()

        assert await leadership.acquire_or_wait(restarted.set, stopped.set) is True
        redis.value = "another-leader"
        await asyncio.wait_for(stopped.wait(), timeout=0.2)
        await asyncio.sleep(0)

        assert leadership.is_leader is False
        assert leadership._contender is not None  # noqa: SLF001
        await leadership.release()

    asyncio.run(scenario())


def test_coinglass_request_failure_makes_runtime_not_ready_even_with_fallback_policy():
    runtime = OrchestrationRuntime()
    runtime.dependencies["coinglass"] = {"status": "ok"}
    runtime.dependencies["market_data"] = {"status": "ok"}
    runtime.coinglass = SimpleNamespace(
        health=lambda: SimpleNamespace(healthy=False, consecutive_failures=3)
    )

    ready, payload = runtime.readiness()

    assert ready is False
    assert payload["dependencies"]["coinglass"] == {
        "status": "error",
        "latest_request": "failed",
        "consecutive_failures": 3,
    }


def test_single_coinglass_request_failure_is_degraded_but_still_ready():
    runtime = OrchestrationRuntime()
    runtime.safety = SimpleNamespace()
    runtime.application = SimpleNamespace(registry=SimpleNamespace(ordered=lambda: tuple(SimpleNamespace(name=name) for name in PRODUCTION_ENGINE_ORDER)))
    runtime.dependencies = {key: {"status": "ok"} for key in (
        "configuration", "postgresql", "migrations", "redis", "event_bus", "state_manager",
        "audit_repository", "audit_integrity", "audit_logging", "scheduler", "engine_registry",
        "pipeline_orchestrator", "governance", "notifications", "coinglass", "market_data", "hierarchy_shadow",
    )}
    runtime.coinglass = SimpleNamespace(health=lambda: SimpleNamespace(healthy=False, consecutive_failures=1))

    ready, payload = runtime.readiness()

    assert ready is True
    assert payload["dependencies"]["coinglass"] == {
        "status": "ok", "latest_request": "degraded", "consecutive_failures": 1,
    }


def test_runtime_requires_managed_dependencies_without_exposing_urls():
    runtime = OrchestrationRuntime(environment={"MONATISE_MODE": "paper"})
    with pytest.raises(RuntimeError, match="PostgreSQL configuration is unavailable"):
        asyncio.run(runtime.start())
    assert "postgresql://" not in json.dumps(runtime.dependencies)


def test_real_coinglass_adapter_is_resolved_through_di_without_exposing_key():
    container = Container()
    adapter = register_coinglass_provider(container, {"COINGLASS_API_KEY": "never-render-this"}, transport=lambda *_: {"code": 0, "data": []})
    assert container.resolve(COINGLASS_PROVIDER_KEY) is adapter
    assert container.registrations[0].metadata["execution_enabled"] is False
    assert "never-render-this" not in repr(container.registrations)


def test_runtime_uses_coinglass_with_public_backpack_fallback():
    primary = object()
    fallback = object()
    runtime = OrchestrationRuntime()
    runtime.coinglass = primary
    runtime.backpack = fallback

    assert runtime.market_data_providers() == {
        "coinglass": primary,
        "backpack_public": fallback,
    }


class _MigrationCursor:
    def __init__(self, row=None):
        self.row = row

    async def fetchone(self):
        return self.row


class _MigrationConnection:
    def __init__(self):
        self.queries = []

    async def execute(self, query, params=None):
        self.queries.append((query, params))
        return _MigrationCursor(None)


def test_migrations_use_advisory_lock_and_record_version(tmp_path):
    migration = tmp_path / "001_test.sql"
    migration.write_text("CREATE TABLE IF NOT EXISTS test_table(id INT);", encoding="utf-8")
    connection = _MigrationConnection()
    runner = MigrationRunner(connection, tmp_path)
    asyncio.run(runner.run())
    rendered = "\n".join(query for query, _ in connection.queries)
    assert "pg_advisory_lock" in rendered
    assert "pg_advisory_unlock" in rendered
    assert "monatise_schema_migrations" in rendered
    assert runner.current is True
    assert runner.version == "001_test"


def test_render_blueprint_targets_production_only():
    production = (Path(__file__).parents[1] / "render.yaml").read_text(encoding="utf-8")
    assert "name: monatise-live" in production


class _FakeSnapshotStore:
    def __init__(self, *, raises=False):
        self.calls: list[tuple[str, dict]] = []
        self._raises = raises

    async def append(self, stream, value):
        if self._raises:
            raise RuntimeError("store unavailable")
        self.calls.append((stream, value))


def _full_grid_result(run):
    # _grid_result() alone is missing fields sanitized_result() needs for a
    # complete analyse() call -- mirrors the pattern already used by
    # test_failed_telegram_delivery_is_recorded_without_automatic_duplicate_retry.
    result = _grid_result("confirmed")
    result.run_id = "run-snapshot-test"
    result.correlation_id = run.correlation_id
    result.statistics = SimpleNamespace(completed_stages=3)
    result.blocked_by = None
    return result


def test_analyse_records_a_decision_snapshot_with_every_stage_output():
    class Orchestrator:
        async def run(self, run):
            return _full_grid_result(run)

    runtime = OrchestrationRuntime(environment={"RENDER_GIT_COMMIT": "abc123"})
    runtime.application = SimpleNamespace(orchestrator=Orchestrator(), infrastructure=SimpleNamespace(audit=SimpleNamespace(append=lambda **_: None)))
    store = _FakeSnapshotStore()
    runtime.decision_snapshot_store = store

    asyncio.run(runtime.analyse("BTC", interval="15m", notify=False))

    assert len(store.calls) == 1
    stream, snapshot = store.calls[0]
    assert stream == "decision-snapshot:BTC:15m"
    assert snapshot["symbol"] == "BTC"
    assert snapshot["interval"] == "15m"
    assert snapshot["code_version"] == "abc123"
    assert snapshot["schema_version"] >= 1
    assert set(snapshot["outputs"]) == {"decision", "market_data", "price_action"}


def test_analyse_does_not_record_a_snapshot_when_no_store_is_configured():
    class Orchestrator:
        async def run(self, run):
            return _full_grid_result(run)

    runtime = OrchestrationRuntime(environment={})
    runtime.application = SimpleNamespace(orchestrator=Orchestrator(), infrastructure=SimpleNamespace(audit=SimpleNamespace(append=lambda **_: None)))
    assert runtime.decision_snapshot_store is None

    # Must not raise even though no store is configured.
    asyncio.run(runtime.analyse("BTC", interval="15m", notify=False))


def test_snapshot_recording_failure_never_breaks_analysis(caplog):
    class Orchestrator:
        async def run(self, run):
            return _full_grid_result(run)

    runtime = OrchestrationRuntime(environment={})
    runtime.application = SimpleNamespace(orchestrator=Orchestrator(), infrastructure=SimpleNamespace(audit=SimpleNamespace(append=lambda **_: None)))
    runtime.decision_snapshot_store = _FakeSnapshotStore(raises=True)

    with caplog.at_level(logging.WARNING, logger="monatise.orchestration"):
        result = asyncio.run(runtime.analyse("BTC", interval="15m", notify=False))

    assert result["symbol"] == "BTC"
    assert any("decision snapshot recording failed" in record.message for record in caplog.records)
