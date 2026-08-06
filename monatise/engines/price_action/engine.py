from __future__ import annotations

from dataclasses import replace

from monatise.core.models import Candle
from monatise.engines.price_action.models import (
    PriceActionAssessment,
    PriceActionConfirmationStatus,
    PriceActionDirection,
    PriceActionFamily,
    PriceActionRequest,
    PriceActionSignal,
)


class PriceActionEngine:
    """Detect and qualify entry evidence without creating orders.

    Entry confirmation is intentionally unavailable without an explicit fixed
    entry price/zone and expected direction. Production must not derive these
    from a grid that is re-centred on every market-data refresh.
    """

    def assess(self, request: PriceActionRequest) -> PriceActionAssessment:
        request.validate()
        candles = request.market.candles
        if len(candles) < request.minimum_candles:
            return self._assessment(request, (), ("insufficient candles for price-action analysis",))

        detected = (
            *self._candlestick(candles, request),
            *self._head_and_shoulders(candles, request),
            *self._order_blocks(candles, request),
            *self._wyckoff(candles, request),
        )
        enriched = tuple(self._qualify(signal, request, len(candles)) for signal in detected)
        return self._assessment(request, enriched)

    def _assessment(
        self,
        request: PriceActionRequest,
        signals: tuple[PriceActionSignal, ...],
        initial_reasons: tuple[str, ...] = (),
    ) -> PriceActionAssessment:
        threshold = request.minimum_confirmation_confidence
        quality = tuple(s for s in signals if s.confirmed and s.location_aligned and s.fresh and not s.invalidated and s.confidence >= threshold)
        eligible = tuple(s for s in quality if s.direction_aligned)
        conflicts = tuple(s for s in quality if not s.direction_aligned)
        expired = tuple(s for s in signals if not s.fresh)
        invalidated = tuple(s for s in signals if s.invalidated)
        expired_relevant = tuple(
            s for s in expired
            if s.confirmed
            and s.direction_aligned
            and s.location_aligned
            and not s.invalidated
            and s.confidence >= threshold
        )
        expected_side_invalidated = tuple(s for s in invalidated if s.direction_aligned)
        confirming_families = {s.family for s in eligible}
        conflicting_families = {s.family for s in conflicts}
        aggregate = self._aggregate_confidence(eligible)
        strongest = max(eligible, key=lambda s: (s.confidence, s.evidence_score), default=None)
        strongest_conflict = max(conflicts, key=lambda s: (s.confidence, s.evidence_score), default=None)

        reasons = list(initial_reasons)
        if not request.has_entry_context or request.expected_direction is None:
            status = PriceActionConfirmationStatus.PENDING
            reasons.append("fixed entry-location context and expected direction are required")
        elif eligible and conflicts:
            status = PriceActionConfirmationStatus.CONFLICT
            reasons.append("eligible bullish and bearish price-action evidence conflicts")
        elif conflicts and not eligible:
            status = PriceActionConfirmationStatus.CONFLICT
            reasons.append("eligible evidence opposes the expected trade direction")
        elif expected_side_invalidated and not eligible:
            status = PriceActionConfirmationStatus.INVALIDATED
            reasons.append("the expected-side setup has been invalidated")
        elif len(confirming_families) >= request.minimum_aligned_families and aggregate >= threshold:
            status = PriceActionConfirmationStatus.CONFIRMED
            reasons.append(f"{len(confirming_families)} aligned price-action family/families confirmed entry")
        elif expired_relevant and not any(s.fresh and s.direction_aligned for s in signals):
            status = PriceActionConfirmationStatus.EXPIRED
            reasons.append("all otherwise relevant price-action evidence has expired")
        else:
            status = PriceActionConfirmationStatus.PENDING
            reasons.append("waiting for fresh aligned price action inside the fixed entry zone")
        if not signals and not initial_reasons:
            reasons.insert(0, "no registered price-action pattern detected")

        return PriceActionAssessment(
            symbol=request.market.symbol,
            status=status,
            signals=signals,
            reasons=tuple(dict.fromkeys(reasons)),
            eligible_signals=quality,
            confirming_signals=eligible,
            conflicting_signals=conflicts,
            expired_signals=expired,
            invalidated_signals=invalidated,
            aggregate_confidence=aggregate,
            aligned_family_count=len(confirming_families),
            conflicting_family_count=len(conflicting_families),
            strongest_confirming_pattern=strongest.pattern if strongest else None,
            strongest_conflicting_pattern=strongest_conflict.pattern if strongest_conflict else None,
        )

    @staticmethod
    def _aggregate_confidence(signals: tuple[PriceActionSignal, ...]) -> float:
        if not signals:
            return 0.0
        by_family: dict[PriceActionFamily, PriceActionSignal] = {}
        for signal in signals:
            current = by_family.get(signal.family)
            if current is None or (signal.confidence, signal.evidence_score) > (current.confidence, current.evidence_score):
                by_family[signal.family] = signal
        strongest = max(s.confidence for s in by_family.values())
        evidence = sum(s.evidence_score for s in by_family.values()) / len(by_family)
        return round(min(1.0, strongest + 0.08 * (len(by_family) - 1) + 0.05 * evidence), 4)

    @staticmethod
    def _qualify(signal: PriceActionSignal, request: PriceActionRequest, candle_count: int) -> PriceActionSignal:
        age = max(0, candle_count - 1 - signal.detected_at_index)
        fresh = age <= request.maximum_signal_age_candles
        direction_aligned = request.expected_direction is not None and signal.direction is request.expected_direction
        effective = request.effective_entry_zone
        distance = None
        location_aligned = False
        if effective is not None and signal.reference_price is not None:
            low, high = effective
            if low <= signal.reference_price <= high:
                distance = 0.0
            else:
                distance = min(abs(signal.reference_price - low), abs(signal.reference_price - high)) / max(signal.reference_price, 1e-12)
            location_aligned = distance <= request.maximum_entry_distance_ratio
        return replace(
            signal,
            age_candles=age,
            distance_to_entry_ratio=distance,
            direction_aligned=direction_aligned,
            location_aligned=location_aligned,
            fresh=fresh,
            metadata={**signal.metadata, "expiry_reason": None if fresh else f"age {age} exceeds {request.maximum_signal_age_candles} candles"},
        )

    @staticmethod
    def _average_range(candles: tuple[Candle, ...], end: int, lookback: int = 10) -> float:
        sample = candles[max(0, end - lookback):end]
        return sum(c.high - c.low for c in sample) / len(sample) if sample else 0.0

    def _candlestick(self, candles: tuple[Candle, ...], request: PriceActionRequest) -> tuple[PriceActionSignal, ...]:
        previous, latest = candles[-2], candles[-1]
        index = len(candles) - 1
        span = latest.high - latest.low
        body = abs(latest.close - latest.open)
        average_range = self._average_range(candles, index)
        if span <= 0 or body <= max(average_range * 0.08, span * 0.03):
            return ()
        volume_average = sum(c.volume for c in candles[max(0, index - 10):index]) / max(1, len(candles[max(0, index - 10):index]))
        volume_ratio = latest.volume / volume_average if volume_average > 0 else 1.0
        close_location = (latest.close - latest.low) / span
        output: list[PriceActionSignal] = []
        common = {"detected_at_index": index, "reference_price": latest.close, "evidence_score": min(1.0, 0.55 + 0.15 * min(volume_ratio, 2.0)), "metadata": {"volume_ratio": volume_ratio, "close_location": close_location, "body_to_average_range": body / max(average_range, 1e-12)}}
        if previous.close < previous.open and latest.close > latest.open and latest.open <= previous.close and latest.close >= previous.open and close_location >= 0.65:
            output.append(PriceActionSignal(PriceActionFamily.CANDLESTICK, "bullish_engulfing", PriceActionDirection.BULLISH, min(1.0, 0.72 + 0.05 * min(volume_ratio, 2)), True, "bullish body engulfed the prior bearish body with a strong close", **common))
        if previous.close > previous.open and latest.close < latest.open and latest.open >= previous.close and latest.close <= previous.open and close_location <= 0.35:
            output.append(PriceActionSignal(PriceActionFamily.CANDLESTICK, "bearish_engulfing", PriceActionDirection.BEARISH, min(1.0, 0.72 + 0.05 * min(volume_ratio, 2)), True, "bearish body engulfed the prior bullish body with a strong close", **common))
        lower_wick = min(latest.open, latest.close) - latest.low
        upper_wick = latest.high - max(latest.open, latest.close)
        if body / span <= 0.35 and lower_wick >= body * 2.0 and close_location >= 0.60:
            output.append(PriceActionSignal(PriceActionFamily.CANDLESTICK, "hammer", PriceActionDirection.BULLISH, 0.72, True, "lower-price rejection closed in the upper candle range", **common))
        elif body / span <= 0.35 and upper_wick >= body * 2.0 and close_location <= 0.40:
            output.append(PriceActionSignal(PriceActionFamily.CANDLESTICK, "shooting_star", PriceActionDirection.BEARISH, 0.72, True, "higher-price rejection closed in the lower candle range", **common))
        return tuple(output)

    def _head_and_shoulders(self, candles: tuple[Candle, ...], request: PriceActionRequest) -> tuple[PriceActionSignal, ...]:
        offset = max(0, len(candles) - 41)
        sample = candles[offset:]
        highs = [(i, sample[i].high) for i in range(1, len(sample) - 1) if sample[i].high > sample[i - 1].high and sample[i].high >= sample[i + 1].high]
        lows = [(i, sample[i].low) for i in range(1, len(sample) - 1) if sample[i].low < sample[i - 1].low and sample[i].low <= sample[i + 1].low]
        output: list[PriceActionSignal] = []
        for pivots, bearish in ((highs, True), (lows, False)):
            if len(pivots) < 3:
                continue
            left, head, right = pivots[-3:]
            if min(head[0] - left[0], right[0] - head[0]) < 2:
                continue
            shoulders_symmetric = abs(left[1] - right[1]) / max(abs(left[1]), abs(right[1]), 1e-12) <= request.shoulder_symmetry_tolerance
            prominence = (head[1] / max(left[1], right[1]) - 1) if bearish else (1 - head[1] / min(left[1], right[1]))
            between_left = sample[left[0] + 1:head[0]]
            between_right = sample[head[0] + 1:right[0]]
            if not shoulders_symmetric or prominence < 0.005 or not between_left or not between_right:
                continue
            neck_one = min(c.low for c in between_left) if bearish else max(c.high for c in between_left)
            neck_two = min(c.low for c in between_right) if bearish else max(c.high for c in between_right)
            neckline = (neck_one + neck_two) / 2
            slope = abs(neck_two - neck_one) / max(abs(neckline), 1e-12)
            latest = sample[-1]
            broke = latest.close < neckline * (1 - request.neckline_breakout_threshold) if bearish else latest.close > neckline * (1 + request.neckline_breakout_threshold)
            if broke and slope <= 0.03:
                direction = PriceActionDirection.BEARISH if bearish else PriceActionDirection.BULLISH
                pattern = "head_and_shoulders_breakdown" if bearish else "inverse_head_and_shoulders_breakout"
                output.append(PriceActionSignal(PriceActionFamily.HEAD_AND_SHOULDERS, pattern, direction, 0.82, True, "separated symmetric shoulders, prominent head, and confirmed neckline break", {"neckline": neckline, "neckline_slope": slope, "left_shoulder_index": offset + left[0], "head_index": offset + head[0], "right_shoulder_index": offset + right[0]}, len(candles) - 1, reference_price=latest.close, evidence_score=0.86))
        return tuple(output)

    def _order_blocks(self, candles: tuple[Candle, ...], request: PriceActionRequest) -> tuple[PriceActionSignal, ...]:
        output: list[PriceActionSignal] = []
        start = max(0, len(candles) - 30)
        for index in range(start, len(candles) - 3):
            anchor = candles[index]
            average_range = self._average_range(candles, index)
            if average_range <= 0:
                continue
            following = candles[index + 1:min(index + 4, len(candles))]
            bullish = anchor.close < anchor.open and max(c.high for c in following) - anchor.high >= average_range * request.order_block_displacement_threshold
            bearish = anchor.close > anchor.open and anchor.low - min(c.low for c in following) >= average_range * request.order_block_displacement_threshold
            if not bullish and not bearish:
                continue
            later = candles[index + len(following) + 1:]
            mitigations = sum(1 for c in later if c.low <= anchor.high and c.high >= anchor.low)
            retested = bool(later) and mitigations > 0
            invalidated = any(c.close < anchor.low for c in later) if bullish else any(c.close > anchor.high for c in later)
            latest = candles[-1]
            holding = latest.close >= anchor.low if bullish else latest.close <= anchor.high
            if not retested and not invalidated:
                continue
            direction = PriceActionDirection.BULLISH if bullish else PriceActionDirection.BEARISH
            displacement = (max(c.high for c in following) - anchor.high if bullish else anchor.low - min(c.low for c in following)) / average_range
            valid = retested and holding and not invalidated and mitigations <= request.maximum_order_block_mitigations
            output.append(PriceActionSignal(PriceActionFamily.ORDER_BLOCK, "bullish_order_block" if bullish else "bearish_order_block", direction, min(0.9, 0.68 + 0.05 * displacement), valid, "opposing anchor displaced, departed, and was retested" if valid else "order block was broken or over-mitigated", {"block_low": anchor.low, "block_high": anchor.high, "anchor_index": index, "displacement_strength": displacement, "mitigation_count": mitigations, "retested": retested, "invalidated": invalidated}, len(candles) - 1, reference_price=min(max(latest.close, anchor.low), anchor.high), zone_low=anchor.low, zone_high=anchor.high, invalidated=invalidated or mitigations > request.maximum_order_block_mitigations, evidence_score=min(1.0, displacement / 3)))
        return tuple(output[-2:])

    def _wyckoff(self, candles: tuple[Candle, ...], request: PriceActionRequest) -> tuple[PriceActionSignal, ...]:
        latest_index = len(candles) - 1
        for index in range(latest_index, max(6, latest_index - request.maximum_signal_age_candles - 1), -1):
            prior = candles[max(0, index - 20):index]
            if len(prior) < 10:
                continue
            event = candles[index]
            range_low, range_high = min(c.low for c in prior), max(c.high for c in prior)
            range_width = range_high - range_low
            if range_width <= 0:
                continue
            average_volume = sum(c.volume for c in prior) / len(prior)
            volume_ratio = event.volume / average_volume if average_volume > 0 else 1.0
            spring_penetration = (range_low - event.low) / range_width
            upthrust_penetration = (event.high - range_high) / range_width
            spring = spring_penetration >= request.wyckoff_penetration_threshold and event.close > range_low
            upthrust = upthrust_penetration >= request.wyckoff_penetration_threshold and event.close < range_high
            volume_ok = volume_ratio >= request.volume_confirmation_ratio
            if not volume_ok or not (spring or upthrust):
                continue
            bullish = spring
            boundary = range_low if bullish else range_high
            invalidated = any(c.close < range_low for c in candles[index + 1:]) if bullish else any(c.close > range_high for c in candles[index + 1:])
            penetration = spring_penetration if bullish else upthrust_penetration
            reclaim_strength = (event.close - range_low) / range_width if bullish else (range_high - event.close) / range_width
            return (PriceActionSignal(PriceActionFamily.WYCKOFF, "spring" if bullish else "upthrust", PriceActionDirection.BULLISH if bullish else PriceActionDirection.BEARISH, min(0.9, 0.72 + penetration), not invalidated, "range boundary penetration reclaimed with volume support", {"range_low": range_low, "range_high": range_high, "penetration_ratio": penetration, "reclaim_strength": reclaim_strength, "volume_ratio": volume_ratio, "range_length": len(prior)}, index, reference_price=boundary, invalidated=invalidated, evidence_score=min(1.0, reclaim_strength + min(volume_ratio, 2) * 0.2)),)
        return ()
