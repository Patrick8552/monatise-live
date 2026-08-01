from __future__ import annotations

from statistics import mean

from monatise.core.models import Candle
from monatise.engines.fibonacci_liquidity.models import (
    AnchorQuality,
    FibonacciAnchor,
    FibonacciAssessment,
    FibonacciDirection,
    FibonacciLevel,
    FibonacciLevelType,
    FibonacciRequest,
    FibonacciZone,
    FibonacciZoneType,
)
from monatise.engines.market_data.models import DataStatus
from monatise.engines.market_structure.models import (
    BreakType,
    StructureBias,
    StructureState,
)
from monatise.engines.reclaim.models import (
    ReclaimDirection,
    ReclaimStatus,
)


class FibonacciLiquidityEngine:
    """Advanced crypto Fibonacci liquidity intelligence engine.

    This engine validates anchors, maps retracement and extension structure,
    builds OTE and extension zones, scores confluence, and exposes invalidation.

    It remains a confluence engine. It does not create entries, stops, targets,
    grids, orders, or final trade decisions.
    """

    def assess(
        self,
        request: FibonacciRequest,
    ) -> FibonacciAssessment:
        request.validate()
        market = request.market
        structure = request.structure
        reasons: list[str] = []

        if market.quality.status is DataStatus.NO_DATA:
            return self._empty(market.symbol, "market data unavailable")

        if market.symbol != structure.symbol:
            return self._empty(
                market.symbol,
                "market and market-structure symbols do not match",
            )

        if market.price is None:
            return self._empty(market.symbol, "market price unavailable")

        if structure.confidence < request.minimum_structure_confidence:
            return self._empty(
                market.symbol,
                (
                    "market-structure confidence is below the minimum required "
                    "for Fibonacci anchoring"
                ),
            )

        direction = self._direction(structure)
        if direction is FibonacciDirection.UNKNOWN:
            return self._empty(
                market.symbol,
                "structure is not directional enough for Fibonacci anchoring",
            )

        if market.quality.status is DataStatus.DEGRADED:
            reasons.append("Fibonacci analysis uses degraded market data")

        atr = self._atr(list(market.candles), 14)
        if atr <= 0:
            return self._empty(market.symbol, "ATR unavailable for anchor validation")

        anchors = self._candidate_anchors(
            direction=direction,
            swing_highs=list(structure.swing_highs),
            swing_lows=list(structure.swing_lows),
            candle_count=len(market.candles),
            atr=atr,
            structure_confidence=structure.confidence,
            request=request,
        )

        if not anchors:
            return self._empty(
                market.symbol,
                "no structurally valid Fibonacci anchor found",
                reasons,
            )

        evaluated = [
            self._evaluate_anchor(anchor, request)
            for anchor in anchors
        ]
        evaluated.sort(key=lambda anchor: anchor.score, reverse=True)

        primary = evaluated[0]
        alternates = tuple(
            evaluated[1:1 + request.maximum_alternate_anchors]
        )

        if primary.quality is AnchorQuality.INVALID:
            return self._empty(
                market.symbol,
                "all Fibonacci anchors failed quality validation",
                reasons,
            )

        retracements = tuple(
            sorted(
                (
                    self._build_level(
                        ratio=ratio,
                        price=self._retracement_price(
                            primary.direction,
                            primary.start_price,
                            primary.end_price,
                            ratio,
                        ),
                        level_type=FibonacciLevelType.RETRACEMENT,
                        request=request,
                        anchor=primary,
                    )
                    for ratio in request.retracement_ratios
                ),
                key=lambda level: (level.distance_pct, -level.score),
            )
        )

        extensions = tuple(
            sorted(
                (
                    self._build_level(
                        ratio=ratio,
                        price=self._extension_price(
                            primary.direction,
                            primary.start_price,
                            primary.end_price,
                            ratio,
                        ),
                        level_type=FibonacciLevelType.EXTENSION,
                        request=request,
                        anchor=primary,
                    )
                    for ratio in request.extension_ratios
                ),
                key=lambda level: (level.distance_pct, -level.score),
            )
        )

        zones = self._build_zones(
            request=request,
            anchor=primary,
            retracements=retracements,
            extensions=extensions,
        )

        invalidation = self._invalidation_level(
            request=request,
            anchor=primary,
        )

        active_zone = next(
            (zone for zone in zones if zone.current_price_inside),
            None,
        )

        reasons.append(
            f"primary anchor quality is {primary.quality.value}"
        )
        reasons.append(
            f"primary anchor score is {primary.score:.3f}"
        )
        if alternates:
            reasons.append(
                f"{len(alternates)} alternate anchor(s) retained for comparison"
            )
        if active_zone:
            reasons.append(
                f"current price is inside {active_zone.zone_type.value}"
            )

        return FibonacciAssessment(
            symbol=market.symbol,
            direction=direction,
            primary_anchor=primary,
            alternate_anchors=alternates,
            retracement_levels=retracements,
            extension_levels=extensions,
            zones=tuple(zones),
            invalidation_level=invalidation,
            nearest_retracement=retracements[0] if retracements else None,
            nearest_extension=extensions[0] if extensions else None,
            active_zone=active_zone,
            reasons=tuple(reasons),
            metadata={
                "engine_scope": "crypto_only",
                "atr": atr,
                "anchor_candidates": len(anchors),
                "structure_state": structure.state.value,
                "structure_bias": structure.bias.value,
                "canonical_ratios_preserved": True,
            },
        )

    @staticmethod
    def _direction(structure) -> FibonacciDirection:
        if (
            structure.bias is StructureBias.BULLISH
            and structure.state in {
                StructureState.BULLISH_CONTINUATION,
                StructureState.BULLISH_REVERSAL,
            }
        ):
            return FibonacciDirection.BULLISH

        if (
            structure.bias is StructureBias.BEARISH
            and structure.state in {
                StructureState.BEARISH_CONTINUATION,
                StructureState.BEARISH_REVERSAL,
            }
        ):
            return FibonacciDirection.BEARISH

        return FibonacciDirection.UNKNOWN

    def _candidate_anchors(
        self,
        *,
        direction: FibonacciDirection,
        swing_highs: list[tuple[int, float]],
        swing_lows: list[tuple[int, float]],
        candle_count: int,
        atr: float,
        structure_confidence: float,
        request: FibonacciRequest,
    ) -> list[FibonacciAnchor]:
        minimum_index = max(
            0,
            candle_count - request.maximum_anchor_age_candles,
        )
        highs = [item for item in swing_highs if item[0] >= minimum_index]
        lows = [item for item in swing_lows if item[0] >= minimum_index]
        anchors: list[FibonacciAnchor] = []

        if direction is FibonacciDirection.BULLISH:
            for low_index, low_price in lows:
                for high_index, high_price in highs:
                    if high_index <= low_index or high_price <= low_price:
                        continue
                    anchors.append(
                        self._raw_anchor(
                            direction=direction,
                            start_index=low_index,
                            start_price=low_price,
                            end_index=high_index,
                            end_price=high_price,
                            candle_count=candle_count,
                            atr=atr,
                            structure_confidence=structure_confidence,
                            request=request,
                        )
                    )
        else:
            for high_index, high_price in highs:
                for low_index, low_price in lows:
                    if low_index <= high_index or low_price >= high_price:
                        continue
                    anchors.append(
                        self._raw_anchor(
                            direction=direction,
                            start_index=high_index,
                            start_price=high_price,
                            end_index=low_index,
                            end_price=low_price,
                            candle_count=candle_count,
                            atr=atr,
                            structure_confidence=structure_confidence,
                            request=request,
                        )
                    )

        return anchors

    def _raw_anchor(
        self,
        *,
        direction: FibonacciDirection,
        start_index: int,
        start_price: float,
        end_index: int,
        end_price: float,
        candle_count: int,
        atr: float,
        structure_confidence: float,
        request: FibonacciRequest,
    ) -> FibonacciAnchor:
        range_size = abs(end_price - start_price)
        range_atr = range_size / atr if atr > 0 else 0.0
        age = max(0, candle_count - 1 - end_index)
        reclaim_aligned = self._reclaim_aligned(direction, request)

        reasons = (
            f"anchor range is {range_atr:.2f} ATR",
            f"anchor endpoint age is {age} candle(s)",
        )

        return FibonacciAnchor(
            direction=direction,
            start_index=start_index,
            end_index=end_index,
            start_price=start_price,
            end_price=end_price,
            range_size=range_size,
            range_atr_multiple=range_atr,
            age_candles=age,
            structure_confidence=structure_confidence,
            reclaim_aligned=reclaim_aligned,
            quality=AnchorQuality.LOW,
            score=0.0,
            reasons=reasons,
        )

    def _evaluate_anchor(
        self,
        anchor: FibonacciAnchor,
        request: FibonacciRequest,
    ) -> FibonacciAnchor:
        reasons = list(anchor.reasons)
        score = 0.0

        if anchor.range_atr_multiple < request.minimum_anchor_range_atr:
            reasons.append("anchor range is below minimum ATR requirement")
            quality = AnchorQuality.INVALID
            return FibonacciAnchor(
                **{
                    **anchor.__dict__,
                    "quality": quality,
                    "score": 0.0,
                    "reasons": tuple(reasons),
                }
            )

        score += min(0.35, anchor.range_atr_multiple / 10)
        score += anchor.structure_confidence * 0.30

        recency_score = max(
            0.0,
            1.0 - anchor.age_candles / request.maximum_anchor_age_candles,
        )
        score += recency_score * 0.20

        if anchor.reclaim_aligned:
            score += 0.10
            reasons.append("anchor direction aligns with confirmed reclaim")

        span = anchor.end_index - anchor.start_index
        if span >= 3:
            score += 0.05
            reasons.append("anchor spans a meaningful structural leg")

        if score >= 0.75:
            quality = AnchorQuality.HIGH
        elif score >= 0.50:
            quality = AnchorQuality.MEDIUM
        else:
            quality = AnchorQuality.LOW

        return FibonacciAnchor(
            **{
                **anchor.__dict__,
                "quality": quality,
                "score": round(min(1.0, score), 4),
                "reasons": tuple(reasons),
            }
        )

    def _build_level(
        self,
        *,
        ratio: float,
        price: float,
        level_type: FibonacciLevelType,
        request: FibonacciRequest,
        anchor: FibonacciAnchor,
    ) -> FibonacciLevel:
        liquidity = self._liquidity_confluence(
            price,
            anchor.direction,
            level_type,
            request,
        )
        zone = self._zone_confluence(
            price,
            anchor.direction,
            level_type,
            request,
        )
        structure = self._structure_confluence(
            ratio,
            level_type,
            request,
        )
        reclaim = anchor.reclaim_aligned

        score = 0.25
        reasons: list[str] = []

        if liquidity:
            score += 0.25
            reasons.append("level aligns with mapped liquidity")
        if zone:
            score += 0.25
            reasons.append("level aligns with supply or demand")
        if structure:
            score += 0.15
            reasons.append("level aligns with structural break context")
        if reclaim:
            score += 0.05
            reasons.append("anchor direction aligns with reclaim context")

        if ratio in {
            0.5,
            0.618,
            0.705,
            0.786,
            1.272,
            1.414,
            1.618,
        }:
            score += 0.05
            reasons.append("ratio is part of the preferred Monatise set")

        if anchor.quality is AnchorQuality.HIGH:
            score += 0.05
            reasons.append("level derives from a high-quality anchor")

        if not reasons:
            reasons.append("level has no external confluence")

        current_price = request.market.price or price
        return FibonacciLevel(
            ratio=ratio,
            price=price,
            level_type=level_type,
            distance_pct=abs(price - current_price) / current_price,
            liquidity_confluence=liquidity,
            zone_confluence=zone,
            structure_confluence=structure,
            reclaim_confluence=reclaim,
            score=round(min(1.0, score), 4),
            reasons=tuple(reasons),
        )

    def _build_zones(
        self,
        *,
        request: FibonacciRequest,
        anchor: FibonacciAnchor,
        retracements: tuple[FibonacciLevel, ...],
        extensions: tuple[FibonacciLevel, ...],
    ) -> list[FibonacciZone]:
        zones: list[FibonacciZone] = []

        equilibrium = self._zone_from_ratios(
            zone_type=FibonacciZoneType.EQUILIBRIUM,
            lower_ratio=0.5,
            upper_ratio=0.5,
            anchor=anchor,
            request=request,
        )
        zones.append(equilibrium)

        zones.append(
            self._zone_from_ratios(
                zone_type=FibonacciZoneType.OTE,
                lower_ratio=request.ote_lower_ratio,
                upper_ratio=request.ote_upper_ratio,
                anchor=anchor,
                request=request,
            )
        )

        zones.append(
            self._zone_from_ratios(
                zone_type=FibonacciZoneType.DEEP_RETRACEMENT,
                lower_ratio=request.ote_upper_ratio,
                upper_ratio=request.deep_retracement_ratio,
                anchor=anchor,
                request=request,
            )
        )

        clustered = self._extension_cluster(
            extensions=extensions,
            tolerance_pct=request.cluster_tolerance_pct,
            current_price=request.market.price or anchor.end_price,
        )
        zones.extend(clustered)
        return zones

    def _zone_from_ratios(
        self,
        *,
        zone_type: FibonacciZoneType,
        lower_ratio: float,
        upper_ratio: float,
        anchor: FibonacciAnchor,
        request: FibonacciRequest,
    ) -> FibonacciZone:
        first = self._retracement_price(
            anchor.direction,
            anchor.start_price,
            anchor.end_price,
            lower_ratio,
        )
        second = self._retracement_price(
            anchor.direction,
            anchor.start_price,
            anchor.end_price,
            upper_ratio,
        )
        lower = min(first, second)
        upper = max(first, second)
        midpoint = (lower + upper) / 2

        liquidity = self._zone_has_liquidity(lower, upper, request)
        sd = self._zone_has_supply_demand(lower, upper, anchor.direction, request)
        score = 0.35 + (0.30 if liquidity else 0) + (0.30 if sd else 0)

        reasons: list[str] = []
        if liquidity:
            reasons.append("zone overlaps mapped liquidity")
        if sd:
            reasons.append("zone overlaps supply or demand")
        if not reasons:
            reasons.append("zone has no external confluence")

        current = request.market.price or midpoint
        return FibonacciZone(
            zone_type=zone_type,
            lower_price=lower,
            upper_price=upper,
            midpoint=midpoint,
            current_price_inside=lower <= current <= upper,
            liquidity_confluence=liquidity,
            supply_demand_confluence=sd,
            score=round(min(1.0, score), 4),
            reasons=tuple(reasons),
        )

    def _extension_cluster(
        self,
        *,
        extensions: tuple[FibonacciLevel, ...],
        tolerance_pct: float,
        current_price: float,
    ) -> list[FibonacciZone]:
        zones: list[FibonacciZone] = []
        ordered = sorted(extensions, key=lambda level: level.price)
        used: set[int] = set()

        for i, first in enumerate(ordered):
            if i in used:
                continue
            group = [first]
            for j in range(i + 1, len(ordered)):
                if j in used:
                    continue
                second = ordered[j]
                anchor = mean(level.price for level in group)
                if anchor > 0 and abs(second.price - anchor) / anchor <= tolerance_pct:
                    group.append(second)
                    used.add(j)

            if len(group) < 2:
                continue

            lower = min(level.price for level in group)
            upper = max(level.price for level in group)
            score = min(
                1.0,
                mean(level.score for level in group) + 0.10,
            )
            zones.append(
                FibonacciZone(
                    zone_type=FibonacciZoneType.EXTENSION_CLUSTER,
                    lower_price=lower,
                    upper_price=upper,
                    midpoint=(lower + upper) / 2,
                    current_price_inside=lower <= current_price <= upper,
                    liquidity_confluence=any(
                        level.liquidity_confluence for level in group
                    ),
                    supply_demand_confluence=any(
                        level.zone_confluence for level in group
                    ),
                    score=round(score, 4),
                    reasons=(
                        f"{len(group)} extension ratios cluster in this area",
                    ),
                    metadata={
                        "ratios": tuple(level.ratio for level in group),
                    },
                )
            )

        return zones

    def _invalidation_level(
        self,
        *,
        request: FibonacciRequest,
        anchor: FibonacciAnchor,
    ) -> FibonacciLevel:
        if anchor.direction is FibonacciDirection.BULLISH:
            price = anchor.start_price * (
                1 - request.invalidation_buffer_pct
            )
        else:
            price = anchor.start_price * (
                1 + request.invalidation_buffer_pct
            )

        current = request.market.price or price
        return FibonacciLevel(
            ratio=0.0,
            price=price,
            level_type=FibonacciLevelType.INVALIDATION,
            distance_pct=abs(price - current) / current,
            liquidity_confluence=False,
            zone_confluence=False,
            structure_confluence=True,
            reclaim_confluence=anchor.reclaim_aligned,
            score=anchor.score,
            reasons=(
                "anchor invalidation boundary with configured buffer",
            ),
        )

    @staticmethod
    def _retracement_price(
        direction: FibonacciDirection,
        start: float,
        end: float,
        ratio: float,
    ) -> float:
        move = abs(end - start)
        if direction is FibonacciDirection.BULLISH:
            return end - move * ratio
        return end + move * ratio

    @staticmethod
    def _extension_price(
        direction: FibonacciDirection,
        start: float,
        end: float,
        ratio: float,
    ) -> float:
        move = abs(end - start)
        if direction is FibonacciDirection.BULLISH:
            return start + move * ratio
        return start - move * ratio

    @staticmethod
    def _reclaim_aligned(
        direction: FibonacciDirection,
        request: FibonacciRequest,
    ) -> bool:
        if (
            request.reclaim is None
            or request.reclaim.strongest_event is None
            or request.reclaim.strongest_event.status
            is not ReclaimStatus.CONFIRMED
        ):
            return False

        reclaim_direction = request.reclaim.strongest_event.direction
        return (
            direction is FibonacciDirection.BULLISH
            and reclaim_direction is ReclaimDirection.BULLISH_RECLAIM
        ) or (
            direction is FibonacciDirection.BEARISH
            and reclaim_direction is ReclaimDirection.BEARISH_RECLAIM
        )

    @staticmethod
    def _structure_confluence(
        ratio: float,
        level_type: FibonacciLevelType,
        request: FibonacciRequest,
    ) -> bool:
        latest = request.structure.latest_event
        if latest is None or not latest.confirmed:
            return False

        if level_type is FibonacciLevelType.RETRACEMENT:
            return latest.break_type in {
                BreakType.BULLISH_BOS,
                BreakType.BEARISH_BOS,
                BreakType.BULLISH_CHOCH,
                BreakType.BEARISH_CHOCH,
            } and ratio in {0.5, 0.618, 0.705, 0.786}

        return latest.break_type in {
            BreakType.BULLISH_BOS,
            BreakType.BEARISH_BOS,
        } and ratio in {1.272, 1.414, 1.618}

    @staticmethod
    def _liquidity_confluence(
        price: float,
        direction: FibonacciDirection,
        level_type: FibonacciLevelType,
        request: FibonacciRequest,
    ) -> bool:
        if request.liquidity is None:
            return False

        if level_type is FibonacciLevelType.RETRACEMENT:
            levels = (
                request.liquidity.sell_side_levels
                if direction is FibonacciDirection.BULLISH
                else request.liquidity.buy_side_levels
            )
        else:
            levels = (
                request.liquidity.buy_side_levels
                if direction is FibonacciDirection.BULLISH
                else request.liquidity.sell_side_levels
            )

        return any(
            price > 0
            and abs(level.price - price) / price
            <= request.confluence_tolerance_pct
            for level in levels
        )

    @staticmethod
    def _zone_confluence(
        price: float,
        direction: FibonacciDirection,
        level_type: FibonacciLevelType,
        request: FibonacciRequest,
    ) -> bool:
        if request.zones is None:
            return False

        if level_type is FibonacciLevelType.RETRACEMENT:
            zones = (
                request.zones.demand_zones
                if direction is FibonacciDirection.BULLISH
                else request.zones.supply_zones
            )
        else:
            zones = (
                request.zones.supply_zones
                if direction is FibonacciDirection.BULLISH
                else request.zones.demand_zones
            )

        for zone in zones:
            if zone.lower_bound <= price <= zone.upper_bound:
                return True
            midpoint = (zone.lower_bound + zone.upper_bound) / 2
            if (
                midpoint > 0
                and abs(midpoint - price) / price
                <= request.confluence_tolerance_pct
            ):
                return True
        return False

    @staticmethod
    def _zone_has_liquidity(
        lower: float,
        upper: float,
        request: FibonacciRequest,
    ) -> bool:
        if request.liquidity is None:
            return False
        levels = (
            *request.liquidity.buy_side_levels,
            *request.liquidity.sell_side_levels,
        )
        return any(lower <= level.price <= upper for level in levels)

    @staticmethod
    def _zone_has_supply_demand(
        lower: float,
        upper: float,
        direction: FibonacciDirection,
        request: FibonacciRequest,
    ) -> bool:
        if request.zones is None:
            return False

        zones = (
            request.zones.demand_zones
            if direction is FibonacciDirection.BULLISH
            else request.zones.supply_zones
        )
        return any(
            min(upper, zone.upper_bound)
            >= max(lower, zone.lower_bound)
            for zone in zones
        )

    @staticmethod
    def _atr(
        candles: list[Candle],
        window: int,
    ) -> float:
        segment = candles[-(window + 1):]
        ranges: list[float] = []

        for previous, current in zip(segment, segment[1:]):
            ranges.append(
                max(
                    current.high - current.low,
                    abs(current.high - previous.close),
                    abs(current.low - previous.close),
                )
            )

        return mean(ranges) if ranges else 0.0

    @staticmethod
    def _empty(
        symbol: str,
        reason: str,
        prior_reasons: list[str] | None = None,
    ) -> FibonacciAssessment:
        return FibonacciAssessment(
            symbol=symbol,
            direction=FibonacciDirection.UNKNOWN,
            primary_anchor=None,
            alternate_anchors=(),
            retracement_levels=(),
            extension_levels=(),
            zones=(),
            invalidation_level=None,
            nearest_retracement=None,
            nearest_extension=None,
            active_zone=None,
            reasons=tuple([*(prior_reasons or []), reason]),
            metadata={"engine_scope": "crypto_only"},
        )
