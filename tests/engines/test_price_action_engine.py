from datetime import datetime, timezone
from dataclasses import replace
from types import SimpleNamespace

import pytest

from monatise.core.models import Candle
from monatise.application.production_analysis import build_moving_grid_plan, build_production_analysis_run, build_setup_validity, sanitized_result
from monatise.engines.market_data.models import DataQuality, DataStatus, MarketSnapshot
from monatise.engines.price_action import (
    PriceActionConfirmationStatus,
    PriceActionDirection,
    PriceActionEngine,
    PriceActionFamily,
    PriceActionRequest,
    PriceActionSignal,
)


def market(candles):
    now = datetime.now(timezone.utc)
    return MarketSnapshot("BTC", "15m", candles[-1].close, tuple(candles), DataQuality(DataStatus.READY, "test", now, now, 0))


def flat_candles(count=8):
    return [Candle(str(i), 100, 102, 98, 101, 10) for i in range(count)]


def signal(direction, *, family=PriceActionFamily.CANDLESTICK, pattern="pattern", index=7, reference=100, confidence=0.8, invalidated=False):
    return PriceActionSignal(family, pattern, direction, confidence, not invalidated, "test evidence", detected_at_index=index, reference_price=reference, invalidated=invalidated, evidence_score=0.8)


class StaticEngine(PriceActionEngine):
    def __init__(self, signals): self._signals = tuple(signals)
    def _candlestick(self, candles, request): return self._signals
    def _head_and_shoulders(self, candles, request): return ()
    def _order_blocks(self, candles, request): return ()
    def _wyckoff(self, candles, request): return ()


def request(*signals, direction=PriceActionDirection.BULLISH, entry=100, **kwargs):
    return StaticEngine(signals).assess(PriceActionRequest(market(flat_candles()), expected_direction=direction, entry_price=entry, **kwargs))


def test_registers_all_requested_price_action_families():
    result = PriceActionEngine().assess(PriceActionRequest(market(flat_candles())))
    assert set(result.registered_families) == set(PriceActionFamily)
    assert result.entry_confirmation_required is True


def test_bullish_pattern_inside_buy_entry_confirms():
    result = request(signal(PriceActionDirection.BULLISH, pattern="bullish_engulfing"))
    assert result.status is PriceActionConfirmationStatus.CONFIRMED
    assert result.has_confirmation is True


def test_pattern_far_outside_entry_zone_remains_pending():
    result = request(signal(PriceActionDirection.BULLISH, reference=105))
    assert result.status is PriceActionConfirmationStatus.PENDING


def test_opposing_pattern_produces_conflict_not_confirmation():
    result = request(signal(PriceActionDirection.BEARISH))
    assert result.status is PriceActionConfirmationStatus.CONFLICT
    assert result.has_confirmation is False


def test_bullish_and_bearish_eligible_patterns_produce_conflict():
    result = request(signal(PriceActionDirection.BULLISH), signal(PriceActionDirection.BEARISH, family=PriceActionFamily.WYCKOFF))
    assert result.status is PriceActionConfirmationStatus.CONFLICT
    assert result.conflicting_family_count == 1


def test_expired_signal_cannot_confirm():
    result = request(signal(PriceActionDirection.BULLISH, index=0), maximum_signal_age_candles=2)
    assert result.status is PriceActionConfirmationStatus.EXPIRED
    assert result.expired_signals


def test_invalidated_expected_side_signal_is_invalidated():
    result = request(signal(PriceActionDirection.BULLISH, invalidated=True))
    assert result.status is PriceActionConfirmationStatus.INVALIDATED


def test_invalidated_pattern_outside_active_grid_level_does_not_invalidate_entry():
    result = request(signal(PriceActionDirection.BULLISH, invalidated=True, reference=105))
    assert result.status is PriceActionConfirmationStatus.PENDING
    assert result.invalidated_signals


def test_stale_invalidated_pattern_does_not_invalidate_current_entry():
    result = request(signal(PriceActionDirection.BULLISH, invalidated=True, index=0), maximum_signal_age_candles=2)
    assert result.status is PriceActionConfirmationStatus.PENDING
    assert result.expired_signals


def test_missing_entry_context_detects_but_stays_pending():
    engine = StaticEngine((signal(PriceActionDirection.BULLISH),))
    result = engine.assess(PriceActionRequest(market(flat_candles()), expected_direction=PriceActionDirection.BULLISH))
    assert result.signals
    assert result.status is PriceActionConfirmationStatus.PENDING
    assert "fixed entry-location context" in result.reasons[0]


def test_entry_zone_precedes_entry_price():
    item = signal(PriceActionDirection.BULLISH, reference=105)
    engine = StaticEngine((item,))
    result = engine.assess(PriceActionRequest(market(flat_candles()), expected_direction=PriceActionDirection.BULLISH, entry_price=100, entry_zone_low=104.9, entry_zone_high=105.1))
    assert result.status is PriceActionConfirmationStatus.CONFIRMED
    assert result.signals[0].distance_to_entry_ratio == 0


def test_multiple_families_strengthen_confidence_without_same_family_inflation():
    one = request(signal(PriceActionDirection.BULLISH, confidence=0.72))
    duplicate = request(signal(PriceActionDirection.BULLISH, confidence=0.72), signal(PriceActionDirection.BULLISH, pattern="duplicate", confidence=0.71))
    multiple = request(signal(PriceActionDirection.BULLISH, confidence=0.72), signal(PriceActionDirection.BULLISH, family=PriceActionFamily.WYCKOFF, confidence=0.72))
    assert duplicate.aggregate_confidence == one.aggregate_confidence
    assert multiple.aggregate_confidence > one.aggregate_confidence


def test_minimum_aligned_family_policy_is_enforced():
    result = request(signal(PriceActionDirection.BULLISH), minimum_aligned_families=2)
    assert result.status is PriceActionConfirmationStatus.PENDING


def test_has_confirmation_only_for_confirmed_status():
    assert request(signal(PriceActionDirection.BULLISH)).has_confirmation
    assert not request(signal(PriceActionDirection.BEARISH)).has_confirmation
    assert not request(signal(PriceActionDirection.BULLISH, index=0), maximum_signal_age_candles=1).has_confirmation


def test_request_validation_and_zone_precedence_contract():
    base = market(flat_candles())
    with pytest.raises(ValueError, match="between 0 and 1"):
        PriceActionRequest(base, minimum_confirmation_confidence=1.1).validate()
    with pytest.raises(ValueError, match="both low and high"):
        PriceActionRequest(base, entry_zone_low=99).validate()
    with pytest.raises(ValueError, match="cannot exceed"):
        PriceActionRequest(base, entry_zone_low=101, entry_zone_high=99).validate()


def test_real_bullish_engulfing_inside_entry_confirms():
    candles = flat_candles(6)
    candles.extend([Candle("6", 101, 102, 98, 99, 10), Candle("7", 98.5, 102, 98, 101.5, 14)])
    result = PriceActionEngine().assess(PriceActionRequest(market(candles), expected_direction=PriceActionDirection.BULLISH, entry_zone_low=101, entry_zone_high=102))
    assert any(item.pattern == "bullish_engulfing" for item in result.confirming_signals)
    assert result.status is PriceActionConfirmationStatus.CONFIRMED


def test_near_zero_body_candle_is_not_a_false_rejection_pattern():
    candles = flat_candles(7) + [Candle("7", 100, 104, 96, 100.01, 20)]
    result = PriceActionEngine().assess(PriceActionRequest(market(candles), expected_direction=PriceActionDirection.BULLISH, entry_price=100))
    assert not any(item.pattern in {"hammer", "shooting_star"} for item in result.signals)


def test_weak_wyckoff_boundary_wick_is_rejected():
    candles = flat_candles(20) + [Candle("20", 100, 102, 97.999, 101, 20)]
    result = PriceActionEngine().assess(PriceActionRequest(market(candles), expected_direction=PriceActionDirection.BULLISH, entry_price=98, wyckoff_penetration_threshold=0.01))
    assert not any(item.family is PriceActionFamily.WYCKOFF for item in result.signals)


def test_valid_wyckoff_spring_with_volume_confirms():
    candles = flat_candles(20) + [Candle("20", 99, 101, 96, 99, 20)]
    result = PriceActionEngine().assess(PriceActionRequest(market(candles), expected_direction=PriceActionDirection.BULLISH, entry_price=98, maximum_entry_distance_ratio=0.001, wyckoff_penetration_threshold=0.01, volume_confirmation_ratio=1.2))
    assert any(item.pattern == "spring" for item in result.confirming_signals)


def order_block_candles(*, broken=False, mitigations=1):
    candles = flat_candles(5)
    candles.extend([
        Candle("5", 101, 102, 98, 99, 10),
        Candle("6", 100, 108, 100, 107, 16),
        Candle("7", 107, 110, 106, 109, 14),
        Candle("8", 109, 111, 108, 110, 12),
    ])
    for number in range(mitigations):
        close = 97 if broken and number == mitigations - 1 else 101
        candles.append(Candle(str(9 + number), 101, 102, 97 if close == 97 else 99, close, 11))
    return candles


def test_valid_bullish_order_block_retest_confirms():
    candles = order_block_candles()
    result = PriceActionEngine().assess(PriceActionRequest(market(candles), expected_direction=PriceActionDirection.BULLISH, entry_zone_low=98, entry_zone_high=102))
    assert any(item.pattern == "bullish_order_block" for item in result.confirming_signals)


def test_broken_bullish_order_block_is_invalidated():
    candles = order_block_candles(broken=True)
    result = PriceActionEngine().assess(PriceActionRequest(market(candles), expected_direction=PriceActionDirection.BULLISH, entry_zone_low=98, entry_zone_high=102))
    assert result.status is PriceActionConfirmationStatus.INVALIDATED
    assert result.invalidated_signals


def test_over_mitigated_order_block_cannot_confirm():
    candles = order_block_candles(mitigations=3)
    result = PriceActionEngine().assess(PriceActionRequest(market(candles), expected_direction=PriceActionDirection.BULLISH, entry_zone_low=98, entry_zone_high=102, maximum_order_block_mitigations=2))
    assert not result.has_confirmation
    assert any(item.invalidated for item in result.signals if item.family is PriceActionFamily.ORDER_BLOCK)


def test_head_and_shoulders_without_swing_separation_is_rejected():
    candles = flat_candles(8)
    result = PriceActionEngine().assess(PriceActionRequest(market(candles), expected_direction=PriceActionDirection.BEARISH, entry_price=100))
    assert not any(item.family is PriceActionFamily.HEAD_AND_SHOULDERS for item in result.signals)


def test_valid_head_and_shoulders_neckline_break_confirms_sell():
    candles = [Candle(str(i), 101, 103, 99, 101, 10) for i in range(13)]
    candles[2] = Candle("2", 104, 110, 101, 106, 12)
    candles[4] = Candle("4", 99, 101, 95, 98, 10)
    candles[6] = Candle("6", 108, 116, 104, 112, 14)
    candles[8] = Candle("8", 100, 102, 96, 99, 10)
    candles[10] = Candle("10", 104, 109, 101, 105, 12)
    candles[12] = Candle("12", 98, 99, 93, 94, 16)
    result = PriceActionEngine().assess(PriceActionRequest(market(candles), expected_direction=PriceActionDirection.BEARISH, entry_zone_low=93, entry_zone_high=96))
    assert any(item.pattern == "head_and_shoulders_breakdown" for item in result.confirming_signals)


def test_sanitized_output_exposes_contextual_confirmation_fields():
    assessment = request(signal(PriceActionDirection.BULLISH, pattern="bullish_engulfing"))
    result = SimpleNamespace(
        run_id="run-1", correlation_id="correlation-1", symbol="BTC",
        status=SimpleNamespace(value="completed"), blocked_by=None,
        statistics=SimpleNamespace(completed_stages=14),
        context=SimpleNamespace(outputs={
            "market_data": market(flat_candles()),
            "decision": SimpleNamespace(classification=SimpleNamespace(value="grid"), direction=SimpleNamespace(value="two_sided"), conviction=0.8, metadata={}, reasons=(), blockers=()),
            "price_action": assessment,
        }),
    )
    payload = sanitized_result(result)
    assert payload["entry_confirmation_status"] == "confirmed"
    assert payload["price_action_confirmed"] is True
    assert payload["price_action_aggregate_confidence"] > 0
    assert payload["price_action_aligned_family_count"] == 1
    assert payload["price_action_reasons"]
    assert payload["price_action_signals"][0]["age_candles"] == 0
    assert payload["price_action_signals"][0]["location_aligned"] is True
    assert isinstance(payload["price_action_signals"][0]["metadata"], dict)
    assert payload["generated_at"] is not None
    assert payload["expires_at"] is not None
    assert payload["validity_candles"] == 4
    assert payload["validity_seconds"] > 0
    assert payload["execution_enabled"] is False


def test_setup_validity_uses_four_candle_boundaries():
    generated_at = datetime(2026, 8, 7, 14, 15, 10, tzinfo=timezone.utc)

    validity = build_setup_validity("15m", generated_at)

    assert validity["generated_at"] == generated_at
    assert validity["expires_at"] == datetime(2026, 8, 7, 15, 15, tzinfo=timezone.utc)
    assert validity["validity_candles"] == 4
    assert validity["remaining_candles"] == 4
    assert validity["validity_seconds"] == 3_590


def test_setup_validity_does_not_refresh_an_aged_confirmation():
    generated_at = datetime(2026, 8, 7, 14, 15, 10, tzinfo=timezone.utc)

    validity = build_setup_validity("15m", generated_at, age_candles=3)

    assert validity["expires_at"] == datetime(2026, 8, 7, 14, 30, tzinfo=timezone.utc)
    assert validity["remaining_candles"] == 1
    assert validity["validity_seconds"] == 890


def test_moving_grid_uses_rolling_range_instead_of_latest_price():
    candles = [Candle(str(i), 100, 110, 90, 105, 10) for i in range(20)]
    snapshot = replace(market(candles), symbol="ETH")
    grid = build_moving_grid_plan(snapshot)
    assert grid["basis"] == "rolling_range"
    assert grid["center"] == 100
    assert grid["center"] != snapshot.price
    assert grid["lower_boundary"] == 90
    assert grid["upper_boundary"] == 110


def test_btc_moving_grid_enforces_500_dollar_minimum_spacing():
    candles = [Candle(str(i), 64_600, 64_971, 64_473, 64_722, 10) for i in range(20)]
    grid = build_moving_grid_plan(market(candles))
    assert grid["spacing"] == 500
    assert grid["center"] == 64_722
    assert grid["buy_levels"] == [64_222, 63_722, 63_222]
    assert grid["sell_levels"] == [65_222, 65_722, 66_222]
    assert grid["lower_invalidation"] == 62_722
    assert grid["upper_invalidation"] == 66_722
    assert grid["basis"] == "rolling_range_minimum_spacing"


def test_production_price_action_receives_nearest_moving_grid_side_and_zone():
    candles = [Candle(str(i), 64_600, 64_971, 64_473, 64_722, 10) for i in range(20)]
    snapshot = market(candles)
    run = build_production_analysis_run("BTC", interval="15m")
    request_builder = run.stage_inputs["price_action"]
    context = SimpleNamespace(outputs={"market_data": snapshot})
    built = request_builder(context)
    assert built.expected_direction is PriceActionDirection.BULLISH
    assert built.entry_price == pytest.approx(64_222)
    assert built.entry_zone_low < built.entry_price < built.entry_zone_high
