from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from monatise.application.ftmo_execution import (
    DurableFTMOIntentRepository,
    FTMOAccount,
    FTMOAccountEnvironment,
    FTMOAnalyticalSetup,
    FTMOExecutionConfiguration,
    FTMOExecutionMode,
    FTMOIntentStatus,
    FTMONativePriceAuthority,
    FTMOPlatform,
    FTMOQuote,
    FTMORiskPolicy,
    FTMOShadowExecutionService,
    FTMOSymbolSpecification,
    FTMOValidationError,
    UnavailableFTMOAdapter,
    format_ftmo_price_diagnostic,
)
from monatise.application.persistence import DurableRecord


NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def account(**changes):
    value = FTMOAccount(
        "demo-100", FTMOPlatform.MT5, FTMOAccountEnvironment.DEMO,
        "USD", Decimal("100000"), Decimal("100000"), Decimal("100000"),
        Decimal("5000"), Decimal("10000"), NOW,
    )
    return replace(value, **changes)


def quote(**changes):
    value = FTMOQuote(
        "XAU/USD", Decimal("2500.00"), Decimal("2500.20"), NOW,
        FTMOPlatform.MT5, "demo-100", "quote-1",
    )
    return replace(value, **changes)


def specification(**changes):
    value = FTMOSymbolSpecification(
        "XAU/USD", 2, Decimal("0.01"), Decimal("1"), Decimal("100"),
        Decimal("0.01"), Decimal("50"), Decimal("0.01"), Decimal("0.50"),
        "XAU", "USD",
    )
    return replace(value, **changes)


def setup(**changes):
    value = FTMOAnalyticalSetup(
        "signal-1", "XAU/USD", "long", Decimal("2500.10"),
        Decimal("2490.10"), Decimal("2520.10"), "external_context",
        NOW - timedelta(seconds=1), NOW + timedelta(minutes=5),
    )
    return replace(value, **changes)


def test_configuration_is_disabled_by_default_and_requires_both_identity_fields():
    configuration = FTMOExecutionConfiguration.from_environment({})
    assert configuration.mode is FTMOExecutionMode.DISABLED
    assert configuration.connected_identity_configured is False
    assert configuration.order_submission_allowed is False

    with pytest.raises(ValueError, match="configured together"):
        FTMOExecutionConfiguration.from_environment({"MONATISE_FTMO_PLATFORM": "mt5"})


def test_live_configuration_requires_explicit_environment_and_confirmation():
    base = {
        "MONATISE_FTMO_PLATFORM": "ctrader",
        "MONATISE_FTMO_ACCOUNT_ID": "123",
        "MONATISE_FTMO_EXECUTION_MODE": "live",
        "MONATISE_FTMO_EXECUTION_ENABLED": "true",
    }
    with pytest.raises(ValueError, match="live-capable"):
        FTMOExecutionConfiguration.from_environment(base)
    with pytest.raises(ValueError, match="exact live confirmation"):
        FTMOExecutionConfiguration.from_environment({**base, "MONATISE_FTMO_ACCOUNT_ENVIRONMENT": "live_capable"})
    configured = FTMOExecutionConfiguration.from_environment({
        **base,
        "MONATISE_FTMO_ACCOUNT_ENVIRONMENT": "live_capable",
        "MONATISE_FTMO_LIVE_CONFIRMATION": "I_APPROVE_FTMO_LIVE_EXECUTION",
    })
    assert configured.order_submission_allowed is True


def test_ftmo_quote_requires_ftmo_source_and_valid_bid_ask():
    with pytest.raises(ValueError, match="ask cannot be below bid"):
        quote(bid=Decimal("2501"), ask=Decimal("2500"))
    with pytest.raises(ValueError, match="source must be ftmo_platform"):
        quote(source="GC futures")


def test_shadow_intent_uses_ftmo_ask_and_limits_actual_risk_to_one_percent():
    authority = FTMONativePriceAuthority()
    intent = authority.build_shadow_intent(setup(), quote(), specification(), account(), now=NOW)
    assert intent.entry == Decimal("2500.20")
    assert intent.stop_loss == Decimal("2490.19")
    assert intent.targets == (Decimal("2520.20"),)
    assert intent.volume == Decimal("0.09")
    assert intent.risk_amount == Decimal("90.09")
    assert intent.risk_fraction < Decimal("0.01")
    assert intent.status is FTMOIntentStatus.SHADOW_VALIDATED
    assert intent.execution_enabled is False


def test_short_intent_uses_ftmo_bid_and_rounds_to_platform_ticks():
    short = setup(
        side="short",
        analysis_price=Decimal("2500.10"),
        analysis_stop=Decimal("2510.10"),
        analysis_target=Decimal("2480.10"),
    )
    intent = FTMONativePriceAuthority().build_shadow_intent(
        short, quote(), specification(tick_size=Decimal("0.10")), account(), now=NOW,
    )
    assert intent.entry == Decimal("2500.0")
    assert intent.stop_loss == Decimal("2510.0")
    assert intent.targets == (Decimal("2480.10"),)


@pytest.mark.parametrize(
    "unsafe_quote,reason",
    [
        (quote(timestamp=NOW - timedelta(seconds=6)), "stale"),
        (quote(market_open=False), "market is closed"),
        (quote(bid=Decimal("2490"), ask=Decimal("2500.20")), "spread exceeds"),
    ],
)
def test_quote_safety_conditions_fail_closed(unsafe_quote, reason):
    with pytest.raises(FTMOValidationError, match=reason):
        FTMONativePriceAuthority().build_shadow_intent(setup(), unsafe_quote, specification(), account(), now=NOW)


def test_gc_or_other_external_price_mismatch_is_diagnostic_only():
    futures_setup = setup(
        analysis_price=Decimal("2550"),
        analysis_stop=Decimal("2540"),
        analysis_target=Decimal("2570"),
        analysis_source="FlashAlpha GC=F",
    )
    authority = FTMONativePriceAuthority()
    diagnostic = authority.diagnose(futures_setup, quote(), specification())
    assert diagnostic.aligned is False
    assert diagnostic.status == "mismatch_external_reference_only"
    with pytest.raises(FTMOValidationError, match="materially misaligned"):
        authority.build_shadow_intent(futures_setup, quote(), specification(), account(), now=NOW)
    message = format_ftmo_price_diagnostic(diagnostic, rejection_reason="FTMO price mismatch")
    assert "FlashAlpha GC=F" in message
    assert "Mode: SHADOW — NO ORDER SENT" in message


def test_stop_distance_daily_loss_and_total_exposure_guards_fail_closed():
    authority = FTMONativePriceAuthority()
    with pytest.raises(FTMOValidationError, match="stop distance"):
        authority.build_shadow_intent(
            setup(analysis_stop=Decimal("2499.90"), analysis_target=Decimal("2501")),
            quote(), specification(minimum_stop_distance=Decimal("1")), account(), now=NOW,
        )
    with pytest.raises(FTMOValidationError, match="daily loss capacity"):
        authority.build_shadow_intent(
            setup(), quote(), specification(),
            account(equity=Decimal("95500")), now=NOW,
        )
    with pytest.raises(FTMOValidationError, match="total open risk"):
        authority.build_shadow_intent(
            setup(), quote(), specification(), account(),
            existing_open_risk=Decimal("2950"), now=NOW,
        )


def test_policy_rejects_more_than_one_percent_risk():
    with pytest.raises(ValueError, match="cannot exceed 1%"):
        FTMORiskPolicy(risk_fraction=Decimal("0.011"))


def test_unavailable_adapter_fails_closed():
    async def scenario():
        with pytest.raises(FTMOValidationError, match="not configured"):
            await UnavailableFTMOAdapter().get_quote("XAU/USD")

    asyncio.run(scenario())


def test_durable_intent_claim_survives_retries_and_marks_unknown_without_resend():
    class Store:
        def __init__(self):
            self.values = {}

        async def get(self, namespace, key):
            return self.values.get((namespace, key))

        async def put(self, namespace, key, value, *, expected_version=None):
            current = self.values.get((namespace, key))
            if current is not None and expected_version != current.version:
                raise RuntimeError("version conflict")
            version = 1 if current is None else current.version + 1
            record = DurableRecord(namespace, key, value, version)
            self.values[(namespace, key)] = record
            return record

    async def scenario():
        intent = FTMONativePriceAuthority().build_shadow_intent(setup(), quote(), specification(), account(), now=NOW)
        store = Store()
        first = DurableFTMOIntentRepository(store)
        second = DurableFTMOIntentRepository(store)
        assert await first.claim(intent) is True
        assert await first.claim(intent) is False
        assert await second.claim(intent) is False
        await first.mark_reconciliation_required(intent.execution_intent_id, reason="network timeout after submit")
        persisted = await second.get(intent.execution_intent_id)
        assert persisted["status"] == "reconciliation_required"
        assert persisted["automatic_resend"] is False

    asyncio.run(scenario())


def test_shadow_service_uses_adapter_persists_once_and_exposes_safe_telemetry():
    class Adapter:
        async def get_account(self): return account()
        async def get_symbol(self, symbol): return specification(symbol=symbol)
        async def get_quote(self, symbol): return quote(symbol=symbol)

    class Store:
        def __init__(self): self.values = {}
        async def get(self, namespace, key): return self.values.get((namespace, key))
        async def put(self, namespace, key, value, *, expected_version=None):
            current = self.values.get((namespace, key))
            if current is not None and expected_version != current.version:
                raise RuntimeError("version conflict")
            record = DurableRecord(namespace, key, value, 1 if current is None else current.version + 1)
            self.values[(namespace, key)] = record
            return record

    async def scenario():
        service = FTMOShadowExecutionService(Adapter(), DurableFTMOIntentRepository(Store()))
        first = await service.evaluate(setup(), now=NOW)
        second = await service.evaluate(setup(), now=NOW)
        assert first.intent is not None and first.execution_enabled is False
        assert "Proposed FTMO-native entry: 2500.20" in first.telegram_message
        assert "Mode: SHADOW — NO ORDER SENT" in first.telegram_message
        assert second.duplicate is True and second.intent is None
        telemetry = service.telemetry.snapshot()
        assert telemetry == {
            "connectivity": "connected",
            "last_successful_quote_at": NOW.isoformat(),
            "last_quote_age_seconds": 0.0,
            "last_spread": "0.20",
            "signal_count": 2,
            "rejection_count": 0,
            "last_rejection_reason": None,
            "shadow_intent_count": 1,
            "duplicate_intent_count": 1,
            "submitted_order_count": 0,
            "reconciliation_state": "not_started",
            "execution_kill_switch": True,
            "execution_enabled": False,
        }

    asyncio.run(scenario())


def test_shadow_service_reports_unavailable_adapter_without_creating_intent():
    class Store:
        async def get(self, namespace, key): return None

    async def scenario():
        service = FTMOShadowExecutionService(
            UnavailableFTMOAdapter(), DurableFTMOIntentRepository(Store())
        )
        result = await service.evaluate(setup(), now=NOW)
        assert result.intent is None
        assert result.rejection_reason == "FTMO platform adapter is not configured"
        assert "NO ORDER SENT" in result.telegram_message
        assert service.telemetry.snapshot()["rejection_count"] == 1

    asyncio.run(scenario())
