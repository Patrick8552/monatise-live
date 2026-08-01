from __future__ import annotations

from monatise.core.models import Candle
from monatise.engines.market_data.models import DataStatus
from monatise.engines.market_structure.models import (
    BreakType,
    MarketStructureAssessment,
    MarketStructureRequest,
    StructureBias,
    StructureEvent,
    StructureState,
)
from monatise.engines.reclaim.models import (
    ReclaimDirection,
    ReclaimStatus,
)
from monatise.engines.regime.models import RegimeState


class MarketStructureEngine:
    """Classifies crypto structure using swing breaks and context.

    This engine may confirm BOS or CHoCH. It does not create entries, stops,
    targets, grids, orders, or final trade decisions.
    """

    def assess(
        self,
        request: MarketStructureRequest,
    ) -> MarketStructureAssessment:
        request.validate()
        market = request.market
        reasons: list[str] = []

        if market.quality.status is DataStatus.NO_DATA:
            return self._unknown(market.symbol, "market data unavailable")

        candles = list(market.candles)
        minimum = request.swing_window * 2 + 3
        if len(candles) < minimum:
            return self._unknown(
                market.symbol,
                f"insufficient candles: required {minimum}, received {len(candles)}",
            )

        if market.quality.status is DataStatus.DEGRADED:
            reasons.append("structure derived from degraded market data")

        swing_highs, swing_lows = self._swings(
            candles,
            request.swing_window,
        )

        if not swing_highs or not swing_lows:
            return self._unknown(
                market.symbol,
                "insufficient confirmed swing structure",
                reasons,
                swing_highs,
                swing_lows,
            )

        prior_bias = self._prior_bias(swing_highs, swing_lows, candles)
        events = self._detect_breaks(
            candles=candles,
            swing_highs=swing_highs,
            swing_lows=swing_lows,
            prior_bias=prior_bias,
            request=request,
        )

        events.extend(
            self._detect_failed_breaks(
                candles=candles,
                events=events,
                request=request,
            )
        )

        events.sort(key=lambda event: event.candle_index)
        latest = next(
            (event for event in reversed(events) if event.confirmed),
            None,
        )

        bias, state = self._classify(
            prior_bias=prior_bias,
            latest_event=latest,
            swing_highs=swing_highs,
            swing_lows=swing_lows,
        )

        contextual_score = 0.0

        if request.reclaim and request.reclaim.strongest_event:
            reclaim = request.reclaim.strongest_event
            if reclaim.status is ReclaimStatus.CONFIRMED:
                if (
                    reclaim.direction is ReclaimDirection.BULLISH_RECLAIM
                    and bias is StructureBias.BULLISH
                ):
                    contextual_score += 0.15
                    reasons.append("bullish reclaim aligns with bullish structure")
                elif (
                    reclaim.direction is ReclaimDirection.BEARISH_RECLAIM
                    and bias is StructureBias.BEARISH
                ):
                    contextual_score += 0.15
                    reasons.append("bearish reclaim aligns with bearish structure")
                else:
                    contextual_score -= 0.10
                    reasons.append("reclaim conflicts with current structure")

        if request.regime is not None:
            if request.regime.state in {
                RegimeState.UNKNOWN,
                RegimeState.UNSTABLE,
            }:
                state = StructureState.UNSTABLE
                contextual_score -= 0.25
                reasons.append(
                    f"regime is {request.regime.state.value}; structure is informational only"
                )
            elif (
                request.regime.state is RegimeState.TREND_UP
                and bias is StructureBias.BULLISH
            ):
                contextual_score += 0.10
                reasons.append("bullish regime aligns with structure")
            elif (
                request.regime.state is RegimeState.TREND_DOWN
                and bias is StructureBias.BEARISH
            ):
                contextual_score += 0.10
                reasons.append("bearish regime aligns with structure")

        if request.zones is not None:
            if bias is StructureBias.BULLISH and request.zones.active_demand:
                contextual_score += 0.10
                reasons.append("bullish structure is supported by active demand")
            elif bias is StructureBias.BEARISH and request.zones.active_supply:
                contextual_score += 0.10
                reasons.append("bearish structure is supported by active supply")

        if latest is None:
            reasons.append("no confirmed BOS or CHoCH detected")
        else:
            reasons.append(
                f"latest structure event is {latest.break_type.value}"
            )

        confidence = self._confidence(
            latest=latest,
            bias=bias,
            contextual_score=contextual_score,
            degraded=market.quality.status is DataStatus.DEGRADED,
        )

        return MarketStructureAssessment(
            symbol=market.symbol,
            bias=bias,
            state=state,
            events=tuple(events),
            latest_event=latest,
            swing_highs=tuple(swing_highs),
            swing_lows=tuple(swing_lows),
            confidence=confidence,
            reasons=tuple(reasons),
            metadata={
                "engine_scope": "crypto_only",
                "prior_bias": prior_bias.value,
                "swing_window": request.swing_window,
                "confirmation_closes": request.confirmation_closes,
            },
        )

    @staticmethod
    def _swings(
        candles: list[Candle],
        window: int,
    ) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
        highs: list[tuple[int, float]] = []
        lows: list[tuple[int, float]] = []

        for index in range(window, len(candles) - window):
            candle = candles[index]
            neighbours = (
                candles[index - window:index]
                + candles[index + 1:index + 1 + window]
            )

            if all(candle.high > item.high for item in neighbours):
                highs.append((index, candle.high))

            if all(candle.low < item.low for item in neighbours):
                lows.append((index, candle.low))

        # Equal-price plateaus are valid swings only after price has moved
        # away on both sides. An unfinished plateau at the series boundary is
        # deliberately excluded because it is not yet a confirmed swing.
        highs.extend(
            MarketStructureEngine._plateau_swings(candles, "high", window)
        )
        lows.extend(
            MarketStructureEngine._plateau_swings(candles, "low", window)
        )

        highs = sorted(set(highs))
        lows = sorted(set(lows))

        return highs, lows

    @staticmethod
    def _plateau_swings(
        candles: list[Candle],
        field: str,
        window: int,
    ) -> list[tuple[int, float]]:
        result: list[tuple[int, float]] = []
        index = window
        final = len(candles) - window

        while index < final:
            value = getattr(candles[index], field)
            end = index
            while (
                end + 1 < len(candles)
                and getattr(candles[end + 1], field) == value
            ):
                end += 1

            if end > index and end < final:
                left = candles[index - window:index]
                right = candles[end + 1:end + 1 + window]
                surrounding = [getattr(candle, field) for candle in (*left, *right)]
                if field == "high" and surrounding and all(value > item for item in surrounding):
                    result.append((end, value))
                elif field == "low" and surrounding and all(value < item for item in surrounding):
                    result.append((end, value))

            index = max(index + 1, end + 1)

        return result

    @staticmethod
    def _prior_bias(
        swing_highs: list[tuple[int, float]],
        swing_lows: list[tuple[int, float]],
        candles: list[Candle],
    ) -> StructureBias:
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            context = candles[:-1] if len(candles) > 1 else candles
            midpoint = len(context) // 2
            early = context[:midpoint]
            late = context[midpoint:]
            if not early or not late:
                return StructureBias.UNKNOWN
            early_mean = sum((c.high + c.low) / 2 for c in early) / len(early)
            late_mean = sum((c.high + c.low) / 2 for c in late) / len(late)
            if late_mean > early_mean:
                return StructureBias.BULLISH
            if late_mean < early_mean:
                return StructureBias.BEARISH
            return StructureBias.NEUTRAL

        high_up = swing_highs[-1][1] > swing_highs[-2][1]
        low_up = swing_lows[-1][1] > swing_lows[-2][1]
        high_down = swing_highs[-1][1] < swing_highs[-2][1]
        low_down = swing_lows[-1][1] < swing_lows[-2][1]

        if high_up and low_up:
            return StructureBias.BULLISH
        if high_down and low_down:
            return StructureBias.BEARISH
        if not high_up and not high_down and not low_up and not low_down:
            return StructureBias.NEUTRAL
        return StructureBias.CONFLICTED

    def _detect_breaks(
        self,
        *,
        candles: list[Candle],
        swing_highs: list[tuple[int, float]],
        swing_lows: list[tuple[int, float]],
        prior_bias: StructureBias,
        request: MarketStructureRequest,
    ) -> list[StructureEvent]:
        events: list[StructureEvent] = []

        last_high_index, last_high = swing_highs[-1]
        last_low_index, last_low = swing_lows[-1]

        start = min(last_high_index, last_low_index) + 1

        for index in range(start, len(candles)):
            candle = candles[index]
            body_ratio = self._body_ratio(candle)

            high_threshold = last_high * (1 + request.break_tolerance_pct)
            low_threshold = last_low * (1 - request.break_tolerance_pct)

            if candle.close > high_threshold:
                confirmed = self._confirmation_count(
                    candles,
                    index,
                    lambda item: item.close > high_threshold,
                ) >= request.confirmation_closes

                break_type = (
                    BreakType.BULLISH_CHOCH
                    if prior_bias is StructureBias.BEARISH
                    else BreakType.BULLISH_BOS
                )

                events.append(
                    StructureEvent(
                        break_type=break_type,
                        level=last_high,
                        candle_index=index,
                        close_price=candle.close,
                        displacement_ratio=body_ratio,
                        confirmed=(
                            confirmed
                            and body_ratio >= request.displacement_body_ratio
                        ),
                        reasons=self._event_reasons(
                            confirmed,
                            body_ratio,
                            request.displacement_body_ratio,
                        ),
                    )
                )

            if candle.close < low_threshold:
                confirmed = self._confirmation_count(
                    candles,
                    index,
                    lambda item: item.close < low_threshold,
                ) >= request.confirmation_closes

                break_type = (
                    BreakType.BEARISH_CHOCH
                    if prior_bias is StructureBias.BULLISH
                    else BreakType.BEARISH_BOS
                )

                events.append(
                    StructureEvent(
                        break_type=break_type,
                        level=last_low,
                        candle_index=index,
                        close_price=candle.close,
                        displacement_ratio=body_ratio,
                        confirmed=(
                            confirmed
                            and body_ratio >= request.displacement_body_ratio
                        ),
                        reasons=self._event_reasons(
                            confirmed,
                            body_ratio,
                            request.displacement_body_ratio,
                        ),
                    )
                )

        return events

    @staticmethod
    def _detect_failed_breaks(
        *,
        candles: list[Candle],
        events: list[StructureEvent],
        request: MarketStructureRequest,
    ) -> list[StructureEvent]:
        failed: list[StructureEvent] = []

        for event in events:
            if not event.confirmed:
                continue

            later = candles[
                event.candle_index + 1:
                event.candle_index + 1 + request.failed_break_window
            ]
            if not later:
                continue

            if event.break_type in {
                BreakType.BULLISH_BOS,
                BreakType.BULLISH_CHOCH,
            }:
                if any(candle.close < event.level for candle in later):
                    candle = next(
                        candle for candle in later
                        if candle.close < event.level
                    )
                    failed.append(
                        StructureEvent(
                            break_type=BreakType.FAILED_BULLISH_BREAK,
                            level=event.level,
                            candle_index=(
                                event.candle_index
                                + 1
                                + later.index(candle)
                            ),
                            close_price=candle.close,
                            displacement_ratio=MarketStructureEngine._body_ratio(candle),
                            confirmed=True,
                            reasons=(
                                "price closed back below the bullish break level",
                            ),
                        )
                    )

            if event.break_type in {
                BreakType.BEARISH_BOS,
                BreakType.BEARISH_CHOCH,
            }:
                if any(candle.close > event.level for candle in later):
                    candle = next(
                        candle for candle in later
                        if candle.close > event.level
                    )
                    failed.append(
                        StructureEvent(
                            break_type=BreakType.FAILED_BEARISH_BREAK,
                            level=event.level,
                            candle_index=(
                                event.candle_index
                                + 1
                                + later.index(candle)
                            ),
                            close_price=candle.close,
                            displacement_ratio=MarketStructureEngine._body_ratio(candle),
                            confirmed=True,
                            reasons=(
                                "price closed back above the bearish break level",
                            ),
                        )
                    )

        return failed

    @staticmethod
    def _classify(
        *,
        prior_bias: StructureBias,
        latest_event: StructureEvent | None,
        swing_highs: list[tuple[int, float]],
        swing_lows: list[tuple[int, float]],
    ) -> tuple[StructureBias, StructureState]:
        if latest_event is None:
            if prior_bias is StructureBias.BULLISH:
                return prior_bias, StructureState.BULLISH_CONTINUATION
            if prior_bias is StructureBias.BEARISH:
                return prior_bias, StructureState.BEARISH_CONTINUATION
            if prior_bias is StructureBias.NEUTRAL:
                return prior_bias, StructureState.RANGE
            return prior_bias, StructureState.TRANSITION

        if latest_event.break_type is BreakType.BULLISH_BOS:
            return StructureBias.BULLISH, StructureState.BULLISH_CONTINUATION
        if latest_event.break_type is BreakType.BEARISH_BOS:
            return StructureBias.BEARISH, StructureState.BEARISH_CONTINUATION
        if latest_event.break_type is BreakType.BULLISH_CHOCH:
            return StructureBias.BULLISH, StructureState.BULLISH_REVERSAL
        if latest_event.break_type is BreakType.BEARISH_CHOCH:
            return StructureBias.BEARISH, StructureState.BEARISH_REVERSAL
        if latest_event.break_type in {
            BreakType.FAILED_BULLISH_BREAK,
            BreakType.FAILED_BEARISH_BREAK,
        }:
            return StructureBias.CONFLICTED, StructureState.TRANSITION

        return StructureBias.UNKNOWN, StructureState.UNKNOWN

    @staticmethod
    def _confirmation_count(
        candles: list[Candle],
        start: int,
        predicate,
    ) -> int:
        count = 0
        for candle in candles[start:]:
            if predicate(candle):
                count += 1
            else:
                break
        return count

    @staticmethod
    def _event_reasons(
        confirmed: bool,
        body_ratio: float,
        minimum_body_ratio: float,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        reasons.append(
            "required close confirmation achieved"
            if confirmed
            else "required close confirmation not achieved"
        )
        reasons.append(
            "displacement body meets minimum ratio"
            if body_ratio >= minimum_body_ratio
            else "displacement body is too weak"
        )
        return tuple(reasons)

    @staticmethod
    def _body_ratio(candle: Candle) -> float:
        candle_range = candle.high - candle.low
        if candle_range <= 0:
            return 0.0
        return abs(candle.close - candle.open) / candle_range

    @staticmethod
    def _confidence(
        *,
        latest: StructureEvent | None,
        bias: StructureBias,
        contextual_score: float,
        degraded: bool,
    ) -> float:
        if bias is StructureBias.UNKNOWN:
            return 0.0

        score = 0.45

        if latest is not None:
            if latest.confirmed:
                score += 0.25
            score += min(0.15, latest.displacement_ratio * 0.15)

        if bias in {StructureBias.BULLISH, StructureBias.BEARISH}:
            score += 0.10
        elif bias is StructureBias.CONFLICTED:
            score -= 0.20

        score += contextual_score

        if degraded:
            score -= 0.20

        return round(max(0.0, min(1.0, score)), 4)

    @staticmethod
    def _unknown(
        symbol: str,
        reason: str,
        prior_reasons: list[str] | None = None,
        swing_highs: list[tuple[int, float]] | None = None,
        swing_lows: list[tuple[int, float]] | None = None,
    ) -> MarketStructureAssessment:
        return MarketStructureAssessment(
            symbol=symbol,
            bias=StructureBias.UNKNOWN,
            state=StructureState.UNKNOWN,
            events=(),
            latest_event=None,
            swing_highs=tuple(swing_highs or ()),
            swing_lows=tuple(swing_lows or ()),
            confidence=0.0,
            reasons=tuple([*(prior_reasons or []), reason]),
            metadata={"engine_scope": "crypto_only"},
        )
