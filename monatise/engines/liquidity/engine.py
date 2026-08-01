from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from statistics import mean

from monatise.core.models import Candle
from monatise.engines.liquidity.models import (
    LiquidityAssessment,
    LiquidityLevel,
    LiquidityLevelType,
    LiquidityRequest,
    LiquiditySide,
    LiquidityStrength,
)
from monatise.engines.market_data.models import DataStatus
from monatise.engines.regime.models import RegimeState


class LiquidityEngine:
    """Maps likely crypto liquidity pools without declaring a sweep.

    The Sweep Engine must determine whether any mapped level was actually taken.
    """

    def assess(self, request: LiquidityRequest) -> LiquidityAssessment:
        request.validate()
        market = request.market
        reasons: list[str] = []

        if market.quality.status is DataStatus.NO_DATA:
            raise ValueError("market data unavailable")

        if market.price is None:
            raise ValueError("market snapshot price is required")

        candles = list(market.candles)
        required = max(
            request.range_window,
            request.recent_window,
            request.swing_window * 2 + 1,
        )
        if len(candles) < required:
            raise ValueError(
                f"insufficient candles: required {required}, received {len(candles)}"
            )

        if market.quality.status is DataStatus.DEGRADED:
            reasons.append("liquidity map built from degraded market data")

        if request.regime is not None:
            if request.regime.state in {RegimeState.UNKNOWN, RegimeState.UNSTABLE}:
                reasons.append(
                    f"regime is {request.regime.state.value}; liquidity map is informational only"
                )
            elif request.regime.prefers_grid_logic:
                reasons.append("range/compression regime supports two-sided liquidity mapping")

        candidates: list[LiquidityLevel] = []
        candidates.extend(
            self._swing_levels(
                candles,
                request.swing_window,
                market.price,
            )
        )
        candidates.extend(
            self._equal_levels(
                candles,
                request.equal_level_tolerance_pct,
                market.price,
            )
        )
        candidates.extend(
            self._cluster_levels(
                candles,
                request.cluster_tolerance_pct,
                request.minimum_cluster_touches,
                market.price,
            )
        )
        candidates.extend(
            self._range_levels(
                candles,
                request.range_window,
                market.price,
            )
        )
        candidates.extend(
            self._recent_levels(
                candles,
                request.recent_window,
                market.price,
            )
        )

        merged = self._merge_levels(
            candidates,
            request.cluster_tolerance_pct,
            market.price,
        )

        buy_side = [
            level for level in merged
            if level.side is LiquiditySide.BUY_SIDE and level.price > market.price
        ]
        sell_side = [
            level for level in merged
            if level.side is LiquiditySide.SELL_SIDE and level.price < market.price
        ]

        buy_side.sort(key=lambda item: (item.distance_pct, -item.touches))
        sell_side.sort(key=lambda item: (item.distance_pct, -item.touches))

        buy_side = buy_side[: request.max_levels_per_side]
        sell_side = sell_side[: request.max_levels_per_side]

        if not buy_side:
            reasons.append("no buy-side liquidity pool mapped above current price")
        if not sell_side:
            reasons.append("no sell-side liquidity pool mapped below current price")
        if buy_side and sell_side:
            reasons.append("two-sided liquidity map available")

        return LiquidityAssessment(
            symbol=market.symbol,
            current_price=market.price,
            buy_side_levels=tuple(buy_side),
            sell_side_levels=tuple(sell_side),
            nearest_buy_side=buy_side[0] if buy_side else None,
            nearest_sell_side=sell_side[0] if sell_side else None,
            reasons=tuple(reasons),
            metadata={
                "engine_scope": "crypto_only",
                "candidate_count": len(candidates),
                "merged_level_count": len(merged),
                "swing_window": request.swing_window,
                "equal_level_tolerance_pct": request.equal_level_tolerance_pct,
                "cluster_tolerance_pct": request.cluster_tolerance_pct,
            },
        )

    @staticmethod
    def _swing_levels(
        candles: list[Candle],
        window: int,
        current_price: float,
    ) -> list[LiquidityLevel]:
        levels: list[LiquidityLevel] = []

        for index in range(window, len(candles) - window):
            candle = candles[index]
            neighbours = candles[index - window:index] + candles[index + 1:index + 1 + window]

            if all(candle.high >= item.high for item in neighbours):
                levels.append(
                    LiquidityLevel(
                        price=candle.high,
                        side=LiquiditySide.BUY_SIDE,
                        level_type=LiquidityLevelType.SWING_HIGH,
                        strength=LiquidityStrength.MEDIUM,
                        touches=1,
                        distance_pct=abs(candle.high - current_price) / current_price,
                        first_index=index,
                        last_index=index,
                    )
                )

            if all(candle.low <= item.low for item in neighbours):
                levels.append(
                    LiquidityLevel(
                        price=candle.low,
                        side=LiquiditySide.SELL_SIDE,
                        level_type=LiquidityLevelType.SWING_LOW,
                        strength=LiquidityStrength.MEDIUM,
                        touches=1,
                        distance_pct=abs(candle.low - current_price) / current_price,
                        first_index=index,
                        last_index=index,
                    )
                )

        return levels

    @staticmethod
    def _equal_levels(
        candles: list[Candle],
        tolerance_pct: float,
        current_price: float,
    ) -> list[LiquidityLevel]:
        levels: list[LiquidityLevel] = []

        highs = [(index, candle.high) for index, candle in enumerate(candles)]
        lows = [(index, candle.low) for index, candle in enumerate(candles)]

        levels.extend(
            LiquidityEngine._group_similar_prices(
                highs,
                tolerance_pct,
                current_price,
                LiquiditySide.BUY_SIDE,
                LiquidityLevelType.EQUAL_HIGHS,
            )
        )
        levels.extend(
            LiquidityEngine._group_similar_prices(
                lows,
                tolerance_pct,
                current_price,
                LiquiditySide.SELL_SIDE,
                LiquidityLevelType.EQUAL_LOWS,
            )
        )
        return [level for level in levels if level.touches >= 2]

    @staticmethod
    def _cluster_levels(
        candles: list[Candle],
        tolerance_pct: float,
        minimum_touches: int,
        current_price: float,
    ) -> list[LiquidityLevel]:
        highs = [(index, candle.high) for index, candle in enumerate(candles)]
        lows = [(index, candle.low) for index, candle in enumerate(candles)]

        levels = LiquidityEngine._group_similar_prices(
            highs,
            tolerance_pct,
            current_price,
            LiquiditySide.BUY_SIDE,
            LiquidityLevelType.CLUSTER_HIGH,
        )
        levels.extend(
            LiquidityEngine._group_similar_prices(
                lows,
                tolerance_pct,
                current_price,
                LiquiditySide.SELL_SIDE,
                LiquidityLevelType.CLUSTER_LOW,
            )
        )
        return [level for level in levels if level.touches >= minimum_touches]

    @staticmethod
    def _group_similar_prices(
        indexed_prices: list[tuple[int, float]],
        tolerance_pct: float,
        current_price: float,
        side: LiquiditySide,
        level_type: LiquidityLevelType,
    ) -> list[LiquidityLevel]:
        groups: list[list[tuple[int, float]]] = []

        for index, price in sorted(indexed_prices, key=lambda item: item[1]):
            matched = False
            for group in groups:
                anchor = mean(value for _, value in group)
                if anchor > 0 and abs(price - anchor) / anchor <= tolerance_pct:
                    group.append((index, price))
                    matched = True
                    break
            if not matched:
                groups.append([(index, price)])

        levels: list[LiquidityLevel] = []
        for group in groups:
            if len(group) < 2:
                continue
            indices = [index for index, _ in group]
            prices = [price for _, price in group]
            level_price = mean(prices)
            levels.append(
                LiquidityLevel(
                    price=level_price,
                    side=side,
                    level_type=level_type,
                    strength=LiquidityEngine._strength(len(group)),
                    touches=len(group),
                    distance_pct=abs(level_price - current_price) / current_price,
                    first_index=min(indices),
                    last_index=max(indices),
                )
            )
        return levels

    @staticmethod
    def _range_levels(
        candles: list[Candle],
        window: int,
        current_price: float,
    ) -> list[LiquidityLevel]:
        segment = candles[-window:]
        start_index = len(candles) - window

        highest_index, highest = max(
            enumerate(segment, start=start_index),
            key=lambda item: item[1].high,
        )
        lowest_index, lowest = min(
            enumerate(segment, start=start_index),
            key=lambda item: item[1].low,
        )

        return [
            LiquidityLevel(
                price=highest.high,
                side=LiquiditySide.BUY_SIDE,
                level_type=LiquidityLevelType.RANGE_HIGH,
                strength=LiquidityStrength.HIGH,
                touches=1,
                distance_pct=abs(highest.high - current_price) / current_price,
                first_index=highest_index,
                last_index=highest_index,
            ),
            LiquidityLevel(
                price=lowest.low,
                side=LiquiditySide.SELL_SIDE,
                level_type=LiquidityLevelType.RANGE_LOW,
                strength=LiquidityStrength.HIGH,
                touches=1,
                distance_pct=abs(lowest.low - current_price) / current_price,
                first_index=lowest_index,
                last_index=lowest_index,
            ),
        ]

    @staticmethod
    def _recent_levels(
        candles: list[Candle],
        window: int,
        current_price: float,
    ) -> list[LiquidityLevel]:
        segment = candles[-window:]
        start_index = len(candles) - window

        highest_index, highest = max(
            enumerate(segment, start=start_index),
            key=lambda item: item[1].high,
        )
        lowest_index, lowest = min(
            enumerate(segment, start=start_index),
            key=lambda item: item[1].low,
        )

        return [
            LiquidityLevel(
                price=highest.high,
                side=LiquiditySide.BUY_SIDE,
                level_type=LiquidityLevelType.RECENT_HIGH,
                strength=LiquidityStrength.MEDIUM,
                touches=1,
                distance_pct=abs(highest.high - current_price) / current_price,
                first_index=highest_index,
                last_index=highest_index,
            ),
            LiquidityLevel(
                price=lowest.low,
                side=LiquiditySide.SELL_SIDE,
                level_type=LiquidityLevelType.RECENT_LOW,
                strength=LiquidityStrength.MEDIUM,
                touches=1,
                distance_pct=abs(lowest.low - current_price) / current_price,
                first_index=lowest_index,
                last_index=lowest_index,
            ),
        ]

    @staticmethod
    def _merge_levels(
        levels: list[LiquidityLevel],
        tolerance_pct: float,
        current_price: float,
    ) -> list[LiquidityLevel]:
        merged: list[LiquidityLevel] = []

        for level in sorted(levels, key=lambda item: (item.side.value, item.price)):
            match_index = None
            for index, existing in enumerate(merged):
                if existing.side is not level.side:
                    continue
                anchor = existing.price
                if anchor > 0 and abs(level.price - anchor) / anchor <= tolerance_pct:
                    match_index = index
                    break

            if match_index is None:
                merged.append(level)
                continue

            existing = merged[match_index]
            combined_touches = existing.touches + level.touches
            combined_price = (
                existing.price * existing.touches + level.price * level.touches
            ) / combined_touches

            preferred_type = LiquidityEngine._preferred_type(
                existing.level_type,
                level.level_type,
            )

            merged[match_index] = replace(
                existing,
                price=combined_price,
                level_type=preferred_type,
                strength=LiquidityEngine._strength(combined_touches),
                touches=combined_touches,
                distance_pct=abs(combined_price - current_price) / current_price,
                first_index=min(existing.first_index, level.first_index),
                last_index=max(existing.last_index, level.last_index),
                metadata={
                    "merged_types": sorted({
                        existing.level_type.value,
                        level.level_type.value,
                    })
                },
            )

        return merged

    @staticmethod
    def _preferred_type(
        first: LiquidityLevelType,
        second: LiquidityLevelType,
    ) -> LiquidityLevelType:
        priority = {
            LiquidityLevelType.EQUAL_HIGHS: 6,
            LiquidityLevelType.EQUAL_LOWS: 6,
            LiquidityLevelType.CLUSTER_HIGH: 5,
            LiquidityLevelType.CLUSTER_LOW: 5,
            LiquidityLevelType.RANGE_HIGH: 4,
            LiquidityLevelType.RANGE_LOW: 4,
            LiquidityLevelType.RECENT_HIGH: 3,
            LiquidityLevelType.RECENT_LOW: 3,
            LiquidityLevelType.SWING_HIGH: 2,
            LiquidityLevelType.SWING_LOW: 2,
        }
        return first if priority[first] >= priority[second] else second

    @staticmethod
    def _strength(touches: int) -> LiquidityStrength:
        if touches >= 4:
            return LiquidityStrength.HIGH
        if touches >= 2:
            return LiquidityStrength.MEDIUM
        return LiquidityStrength.LOW
