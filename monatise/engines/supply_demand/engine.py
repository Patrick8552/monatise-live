from __future__ import annotations

from dataclasses import replace
from statistics import mean

from monatise.core.models import Candle
from monatise.engines.liquidity.models import LiquidityAssessment, LiquiditySide
from monatise.engines.market_data.models import DataStatus
from monatise.engines.regime.models import RegimeState
from monatise.engines.supply_demand.models import (
    SupplyDemandZone,
    ZoneAssessment,
    ZoneDirection,
    ZoneFreshness,
    ZoneRequest,
    ZoneStrength,
    ZoneType,
)


class SupplyDemandEngine:
    """Maps institutional-style crypto supply and demand zones.

    Zones are confluence and risk-mapping inputs. They are not standalone
    entry signals and must not override liquidity, structure, or risk engines.
    """

    def assess(self, request: ZoneRequest) -> ZoneAssessment:
        request.validate()
        market = request.market
        reasons: list[str] = []

        if market.quality.status is DataStatus.NO_DATA:
            raise ValueError("market data unavailable")
        if market.price is None:
            raise ValueError("market snapshot price is required")

        candles = list(market.candles)
        minimum_history = (
            request.impulse_window * 2
            + request.base_max_candles
            + 3
        )
        if len(candles) < minimum_history:
            raise ValueError(
                f"insufficient candles: required at least {minimum_history}, "
                f"received {len(candles)}"
            )

        if market.quality.status is DataStatus.DEGRADED:
            reasons.append("zones mapped from degraded market data")

        informational_only = False
        if request.regime is not None:
            if request.regime.state in {
                RegimeState.UNKNOWN,
                RegimeState.UNSTABLE,
            }:
                informational_only = True
                reasons.append(
                    f"regime is {request.regime.state.value}; zones are informational only"
                )
            elif request.regime.state is RegimeState.HIGH_VOLATILITY:
                reasons.append(
                    "high-volatility regime reduces zone reliability"
                )

        atr = self._atr(candles, 14)
        if atr <= 0:
            raise ValueError("ATR must be positive to detect supply and demand zones")

        detected = self._detect_zones(
            candles=candles,
            current_price=market.price,
            atr=atr,
            request=request,
        )

        evaluated = [
            self._evaluate_zone(
                zone=zone,
                candles=candles,
                current_price=market.price,
                request=request,
                liquidity=request.liquidity,
            )
            for zone in detected
        ]

        valid = [
            zone for zone in evaluated
            if zone.freshness is not ZoneFreshness.INVALIDATED
        ]

        merged = self._merge_overlapping(valid, market.price)

        demand = sorted(
            (
                zone for zone in merged
                if zone.zone_type is ZoneType.DEMAND
                and zone.upper_bound <= market.price
                or (
                    zone.zone_type is ZoneType.DEMAND
                    and zone.contains(market.price)
                )
            ),
            key=lambda zone: (
                zone.distance_pct,
                -self._strength_priority(zone.strength),
                zone.touches,
            ),
        )[: request.max_zones_per_type]

        supply = sorted(
            (
                zone for zone in merged
                if zone.zone_type is ZoneType.SUPPLY
                and zone.lower_bound >= market.price
                or (
                    zone.zone_type is ZoneType.SUPPLY
                    and zone.contains(market.price)
                )
            ),
            key=lambda zone: (
                zone.distance_pct,
                -self._strength_priority(zone.strength),
                zone.touches,
            ),
        )[: request.max_zones_per_type]

        active_demand = next(
            (zone for zone in demand if zone.contains(market.price)),
            None,
        )
        active_supply = next(
            (zone for zone in supply if zone.contains(market.price)),
            None,
        )

        if not demand:
            reasons.append("no valid demand zone mapped")
        if not supply:
            reasons.append("no valid supply zone mapped")
        if active_demand:
            reasons.append("price is currently inside a demand zone")
        if active_supply:
            reasons.append("price is currently inside a supply zone")
        if demand and supply:
            reasons.append("two-sided institutional zone map available")

        return ZoneAssessment(
            symbol=market.symbol,
            current_price=market.price,
            demand_zones=tuple(demand),
            supply_zones=tuple(supply),
            nearest_demand=demand[0] if demand else None,
            nearest_supply=supply[0] if supply else None,
            active_demand=active_demand,
            active_supply=active_supply,
            reasons=tuple(reasons),
            metadata={
                "engine_scope": "crypto_only",
                "detected_zone_count": len(detected),
                "valid_zone_count": len(valid),
                "merged_zone_count": len(merged),
                "atr": atr,
                "informational_only": informational_only,
            },
        )

    def _detect_zones(
        self,
        *,
        candles: list[Candle],
        current_price: float,
        atr: float,
        request: ZoneRequest,
    ) -> list[SupplyDemandZone]:
        zones: list[SupplyDemandZone] = []

        for base_start in range(
            request.impulse_window,
            len(candles) - request.impulse_window - 1,
        ):
            for base_length in range(1, request.base_max_candles + 1):
                base_end = base_start + base_length - 1
                departure_start = base_end + 1
                departure_end = departure_start + request.impulse_window

                if departure_end > len(candles):
                    break

                base = candles[base_start:base_end + 1]
                if not self._is_base(base, request.base_body_ratio_max):
                    continue

                arrival = candles[
                    base_start - request.impulse_window:base_start
                ]
                departure = candles[departure_start:departure_end]

                arrival_move = arrival[-1].close - arrival[0].open
                departure_move = departure[-1].close - departure[0].open
                departure_multiple = abs(departure_move) / atr

                if departure_multiple < request.minimum_impulse_atr:
                    continue

                direction = self._direction(arrival_move, departure_move)
                if direction is None:
                    continue

                zone_type = (
                    ZoneType.DEMAND
                    if departure_move > 0
                    else ZoneType.SUPPLY
                )
                proximal, distal = self._zone_bounds(base, zone_type)

                zones.append(
                    SupplyDemandZone(
                        zone_type=zone_type,
                        direction=direction,
                        proximal=proximal,
                        distal=distal,
                        created_index=base_start,
                        base_start_index=base_start,
                        base_end_index=base_end,
                        departure_index=departure_start,
                        strength=self._initial_strength(
                            departure_multiple,
                            len(base),
                        ),
                        freshness=ZoneFreshness.FRESH,
                        departure_atr_multiple=departure_multiple,
                        touches=0,
                        distance_pct=self._distance_pct(
                            current_price,
                            proximal,
                            distal,
                        ),
                        liquidity_confluence=False,
                        reasons=(
                            f"departure measured {departure_multiple:.2f} ATR",
                            f"base contains {len(base)} candle(s)",
                        ),
                    )
                )

        return zones

    @staticmethod
    def _is_base(
        candles: list[Candle],
        body_ratio_max: float,
    ) -> bool:
        if not candles:
            return False
        for candle in candles:
            full_range = candle.high - candle.low
            if full_range <= 0:
                return False
            body = abs(candle.close - candle.open)
            if body / full_range > body_ratio_max:
                return False
        return True

    @staticmethod
    def _direction(
        arrival_move: float,
        departure_move: float,
    ) -> ZoneDirection | None:
        if arrival_move > 0 and departure_move > 0:
            return ZoneDirection.RALLY_BASE_RALLY
        if arrival_move < 0 and departure_move > 0:
            return ZoneDirection.DROP_BASE_RALLY
        if arrival_move > 0 and departure_move < 0:
            return ZoneDirection.RALLY_BASE_DROP
        if arrival_move < 0 and departure_move < 0:
            return ZoneDirection.DROP_BASE_DROP
        return None

    @staticmethod
    def _zone_bounds(
        base: list[Candle],
        zone_type: ZoneType,
    ) -> tuple[float, float]:
        if zone_type is ZoneType.DEMAND:
            proximal = max(max(candle.open, candle.close) for candle in base)
            distal = min(candle.low for candle in base)
        else:
            proximal = min(min(candle.open, candle.close) for candle in base)
            distal = max(candle.high for candle in base)
        return proximal, distal

    def _evaluate_zone(
        self,
        *,
        zone: SupplyDemandZone,
        candles: list[Candle],
        current_price: float,
        request: ZoneRequest,
        liquidity: LiquidityAssessment | None,
    ) -> SupplyDemandZone:
        post_creation = candles[zone.departure_index + 1:]
        touches = 0
        invalidated = False

        for candle in post_creation:
            if self._candle_touches_zone(
                candle,
                zone,
                request.zone_touch_tolerance_pct,
            ):
                touches += 1

            if self._candle_invalidates_zone(
                candle,
                zone,
                request.invalidation_tolerance_pct,
            ):
                invalidated = True
                break

        if invalidated:
            freshness = ZoneFreshness.INVALIDATED
        elif touches == 0:
            freshness = ZoneFreshness.FRESH
        elif touches == 1:
            freshness = ZoneFreshness.TESTED
        else:
            freshness = ZoneFreshness.MITIGATED

        confluence = self._liquidity_confluence(zone, liquidity)
        strength = self._adjust_strength(
            initial=zone.strength,
            touches=touches,
            liquidity_confluence=confluence,
            invalidated=invalidated,
        )

        reasons = list(zone.reasons)
        reasons.append(f"zone has {touches} post-departure touch(es)")
        if confluence:
            reasons.append("zone aligns with mapped liquidity")
        if invalidated:
            reasons.append("zone invalidated by a close beyond its distal boundary")

        return replace(
            zone,
            strength=strength,
            freshness=freshness,
            touches=touches,
            distance_pct=self._distance_pct(
                current_price,
                zone.proximal,
                zone.distal,
            ),
            liquidity_confluence=confluence,
            reasons=tuple(reasons),
        )

    @staticmethod
    def _candle_touches_zone(
        candle: Candle,
        zone: SupplyDemandZone,
        tolerance_pct: float,
    ) -> bool:
        tolerance = zone.upper_bound * tolerance_pct
        return (
            candle.low <= zone.upper_bound + tolerance
            and candle.high >= zone.lower_bound - tolerance
        )

    @staticmethod
    def _candle_invalidates_zone(
        candle: Candle,
        zone: SupplyDemandZone,
        tolerance_pct: float,
    ) -> bool:
        if zone.zone_type is ZoneType.DEMAND:
            threshold = zone.distal * (1 - tolerance_pct)
            return candle.close < threshold
        threshold = zone.distal * (1 + tolerance_pct)
        return candle.close > threshold

    @staticmethod
    def _liquidity_confluence(
        zone: SupplyDemandZone,
        liquidity: LiquidityAssessment | None,
    ) -> bool:
        if liquidity is None:
            return False

        levels = (
            liquidity.sell_side_levels
            if zone.zone_type is ZoneType.DEMAND
            else liquidity.buy_side_levels
        )

        for level in levels:
            if zone.lower_bound <= level.price <= zone.upper_bound:
                return True

            zone_mid = (zone.lower_bound + zone.upper_bound) / 2
            if zone_mid > 0 and abs(level.price - zone_mid) / zone_mid <= 0.003:
                return True

        return False

    @staticmethod
    def _initial_strength(
        departure_atr_multiple: float,
        base_candles: int,
    ) -> ZoneStrength:
        if departure_atr_multiple >= 2.5 and base_candles <= 2:
            return ZoneStrength.HIGH
        if departure_atr_multiple >= 1.75:
            return ZoneStrength.MEDIUM
        return ZoneStrength.LOW

    @staticmethod
    def _adjust_strength(
        *,
        initial: ZoneStrength,
        touches: int,
        liquidity_confluence: bool,
        invalidated: bool,
    ) -> ZoneStrength:
        if invalidated:
            return ZoneStrength.LOW

        score = {
            ZoneStrength.LOW: 1,
            ZoneStrength.MEDIUM: 2,
            ZoneStrength.HIGH: 3,
        }[initial]

        if liquidity_confluence:
            score += 1
        if touches == 1:
            score -= 1
        elif touches >= 2:
            score -= 2

        if score >= 3:
            return ZoneStrength.HIGH
        if score == 2:
            return ZoneStrength.MEDIUM
        return ZoneStrength.LOW

    @staticmethod
    def _merge_overlapping(
        zones: list[SupplyDemandZone],
        current_price: float,
    ) -> list[SupplyDemandZone]:
        merged: list[SupplyDemandZone] = []

        for zone in sorted(
            zones,
            key=lambda item: (
                item.zone_type.value,
                item.lower_bound,
                item.created_index,
            ),
        ):
            match_index = None
            for index, existing in enumerate(merged):
                if existing.zone_type is not zone.zone_type:
                    continue
                overlap = min(
                    existing.upper_bound,
                    zone.upper_bound,
                ) - max(
                    existing.lower_bound,
                    zone.lower_bound,
                )
                if overlap >= 0:
                    match_index = index
                    break

            if match_index is None:
                merged.append(zone)
                continue

            existing = merged[match_index]
            lower = min(existing.lower_bound, zone.lower_bound)
            upper = max(existing.upper_bound, zone.upper_bound)

            if zone.zone_type is ZoneType.DEMAND:
                proximal, distal = upper, lower
            else:
                proximal, distal = lower, upper

            preferred = (
                existing
                if SupplyDemandEngine._strength_priority(existing.strength)
                >= SupplyDemandEngine._strength_priority(zone.strength)
                else zone
            )

            merged[match_index] = replace(
                preferred,
                proximal=proximal,
                distal=distal,
                touches=max(existing.touches, zone.touches),
                distance_pct=SupplyDemandEngine._distance_pct(
                    current_price,
                    proximal,
                    distal,
                ),
                liquidity_confluence=(
                    existing.liquidity_confluence
                    or zone.liquidity_confluence
                ),
                reasons=tuple(dict.fromkeys(
                    (*existing.reasons, *zone.reasons, "overlapping zones merged")
                )),
            )

        return merged

    @staticmethod
    def _distance_pct(
        current_price: float,
        proximal: float,
        distal: float,
    ) -> float:
        lower = min(proximal, distal)
        upper = max(proximal, distal)
        if lower <= current_price <= upper:
            return 0.0
        boundary = upper if current_price > upper else lower
        return abs(current_price - boundary) / current_price

    @staticmethod
    def _atr(candles: list[Candle], window: int) -> float:
        segment = candles[-(window + 1):]
        true_ranges: list[float] = []

        for previous, current in zip(segment, segment[1:]):
            true_ranges.append(
                max(
                    current.high - current.low,
                    abs(current.high - previous.close),
                    abs(current.low - previous.close),
                )
            )

        return mean(true_ranges) if true_ranges else 0.0

    @staticmethod
    def _strength_priority(strength: ZoneStrength) -> int:
        return {
            ZoneStrength.HIGH: 3,
            ZoneStrength.MEDIUM: 2,
            ZoneStrength.LOW: 1,
        }[strength]
