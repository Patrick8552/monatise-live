from __future__ import annotations

from monatise.core.models import Candle
from monatise.engines.liquidity_sweep.models import (
    SweepDirection,
    SweepStatus,
)
from monatise.engines.market_data.models import DataStatus
from monatise.engines.reclaim.models import (
    ReclaimAssessment,
    ReclaimDirection,
    ReclaimEvent,
    ReclaimRequest,
    ReclaimStatus,
)
from monatise.engines.regime.models import RegimeState
from monatise.engines.supply_demand.models import ZoneType


class ReclaimEngine:
    """Confirms whether price reclaimed and held a swept liquidity level.

    A reclaim is confirmation evidence only. This engine must not create
    entries, stops, targets, grids, orders, or final trade direction.
    """

    def assess(self, request: ReclaimRequest) -> ReclaimAssessment:
        request.validate()
        market = request.market
        reasons: list[str] = []

        if market.quality.status is DataStatus.NO_DATA:
            return self._empty(market.symbol, "market data unavailable")

        if market.symbol != request.sweep.symbol:
            return self._empty(
                market.symbol,
                "market and sweep symbols do not match",
            )

        if not request.sweep.events:
            return self._empty(
                market.symbol,
                "no sweep events available for reclaim analysis",
            )

        if market.quality.status is DataStatus.DEGRADED:
            reasons.append("reclaim analysis uses degraded market data")

        informational_only = False
        if request.regime is not None and request.regime.state in {
            RegimeState.UNKNOWN,
            RegimeState.UNSTABLE,
        }:
            informational_only = True
            reasons.append(
                f"regime is {request.regime.state.value}; reclaim is informational only"
            )

        candles = list(market.candles)
        events: list[ReclaimEvent] = []

        for sweep_event in request.sweep.events:
            if sweep_event.status not in {
                SweepStatus.CONFIRMED,
                SweepStatus.POSSIBLE,
            }:
                continue

            event = self._evaluate_event(
                candles=candles,
                sweep_event=sweep_event,
                request=request,
            )
            events.append(event)

        events.sort(
            key=lambda event: (
                self._status_priority(event.status),
                int(event.zone_confluence),
                int(event.held_level),
                event.reclaim_index or -1,
            ),
            reverse=True,
        )

        strongest = events[0] if events else None
        if strongest is None:
            reasons.append("no eligible sweep event produced a reclaim assessment")
        elif strongest.status is ReclaimStatus.CONFIRMED:
            reasons.append("confirmed reclaim detected")
        elif strongest.status is ReclaimStatus.POSSIBLE:
            reasons.append("possible reclaim detected without full follow-through")
        elif strongest.status is ReclaimStatus.FAILED:
            reasons.append("reclaim attempt failed")

        return ReclaimAssessment(
            symbol=market.symbol,
            events=tuple(events),
            strongest_event=strongest,
            reasons=tuple(reasons),
            metadata={
                "engine_scope": "crypto_only",
                "informational_only": informational_only,
                "sweep_events_checked": len(request.sweep.events),
            },
        )

    def _evaluate_event(
        self,
        *,
        candles: list[Candle],
        sweep_event,
        request: ReclaimRequest,
    ) -> ReclaimEvent:
        level = sweep_event.level.price
        start = sweep_event.candle_index + 1
        end = min(len(candles), start + request.confirmation_candles)
        confirmation = list(enumerate(candles[start:end], start=start))

        if not confirmation:
            return ReclaimEvent(
                sweep_event=sweep_event,
                direction=self._direction(sweep_event.direction),
                status=ReclaimStatus.NONE,
                reclaim_index=None,
                confirmation_index=None,
                reclaim_price=level,
                close_price=None,
                body_ratio=None,
                held_level=False,
                zone_confluence=self._zone_confluence(
                    level,
                    sweep_event.direction,
                    request,
                ),
                reasons=("no post-sweep candles available",),
            )

        if sweep_event.direction is SweepDirection.SELL_SIDE_TAKEN:
            return self._bullish_reclaim(
                confirmation=confirmation,
                sweep_event=sweep_event,
                level=level,
                request=request,
            )

        return self._bearish_reclaim(
            confirmation=confirmation,
            sweep_event=sweep_event,
            level=level,
            request=request,
        )

    def _bullish_reclaim(
        self,
        *,
        confirmation: list[tuple[int, Candle]],
        sweep_event,
        level: float,
        request: ReclaimRequest,
    ) -> ReclaimEvent:
        reclaim_threshold = level * (1 - request.reclaim_tolerance_pct)
        hold_threshold = level * (1 - request.hold_tolerance_pct)
        reclaim_index = None
        reclaim_candle = None

        for index, candle in confirmation:
            if candle.close >= reclaim_threshold:
                reclaim_index = index
                reclaim_candle = candle
                break

        zone_confluence = self._zone_confluence(
            level,
            sweep_event.direction,
            request,
        )

        if reclaim_candle is None:
            return ReclaimEvent(
                sweep_event=sweep_event,
                direction=ReclaimDirection.BULLISH_RECLAIM,
                status=ReclaimStatus.FAILED,
                reclaim_index=None,
                confirmation_index=confirmation[-1][0],
                reclaim_price=level,
                close_price=confirmation[-1][1].close,
                body_ratio=self._body_ratio(confirmation[-1][1]),
                held_level=False,
                zone_confluence=zone_confluence,
                reasons=("price did not close back above the swept level",),
            )

        body_ratio = self._body_ratio(reclaim_candle)
        body_ok = body_ratio >= request.minimum_body_ratio
        later = [
            (index, candle)
            for index, candle in confirmation
            if index > reclaim_index
        ]
        held = all(candle.close >= hold_threshold for _, candle in later)
        follow_through = (
            any(candle.high > reclaim_candle.high for _, candle in later)
            if later
            else False
        )

        status, reasons = self._status(
            body_ok=body_ok,
            held=held,
            follow_through=follow_through,
            require_follow_through=request.require_follow_through,
        )

        return ReclaimEvent(
            sweep_event=sweep_event,
            direction=ReclaimDirection.BULLISH_RECLAIM,
            status=status,
            reclaim_index=reclaim_index,
            confirmation_index=later[-1][0] if later else reclaim_index,
            reclaim_price=level,
            close_price=reclaim_candle.close,
            body_ratio=body_ratio,
            held_level=held,
            zone_confluence=zone_confluence,
            reasons=reasons,
        )

    def _bearish_reclaim(
        self,
        *,
        confirmation: list[tuple[int, Candle]],
        sweep_event,
        level: float,
        request: ReclaimRequest,
    ) -> ReclaimEvent:
        reclaim_threshold = level * (1 + request.reclaim_tolerance_pct)
        hold_threshold = level * (1 + request.hold_tolerance_pct)
        reclaim_index = None
        reclaim_candle = None

        for index, candle in confirmation:
            if candle.close <= reclaim_threshold:
                reclaim_index = index
                reclaim_candle = candle
                break

        zone_confluence = self._zone_confluence(
            level,
            sweep_event.direction,
            request,
        )

        if reclaim_candle is None:
            return ReclaimEvent(
                sweep_event=sweep_event,
                direction=ReclaimDirection.BEARISH_RECLAIM,
                status=ReclaimStatus.FAILED,
                reclaim_index=None,
                confirmation_index=confirmation[-1][0],
                reclaim_price=level,
                close_price=confirmation[-1][1].close,
                body_ratio=self._body_ratio(confirmation[-1][1]),
                held_level=False,
                zone_confluence=zone_confluence,
                reasons=("price did not close back below the swept level",),
            )

        body_ratio = self._body_ratio(reclaim_candle)
        body_ok = body_ratio >= request.minimum_body_ratio
        later = [
            (index, candle)
            for index, candle in confirmation
            if index > reclaim_index
        ]
        held = all(candle.close <= hold_threshold for _, candle in later)
        follow_through = (
            any(candle.low < reclaim_candle.low for _, candle in later)
            if later
            else False
        )

        status, reasons = self._status(
            body_ok=body_ok,
            held=held,
            follow_through=follow_through,
            require_follow_through=request.require_follow_through,
        )

        return ReclaimEvent(
            sweep_event=sweep_event,
            direction=ReclaimDirection.BEARISH_RECLAIM,
            status=status,
            reclaim_index=reclaim_index,
            confirmation_index=later[-1][0] if later else reclaim_index,
            reclaim_price=level,
            close_price=reclaim_candle.close,
            body_ratio=body_ratio,
            held_level=held,
            zone_confluence=zone_confluence,
            reasons=reasons,
        )

    @staticmethod
    def _status(
        *,
        body_ok: bool,
        held: bool,
        follow_through: bool,
        require_follow_through: bool,
    ) -> tuple[ReclaimStatus, tuple[str, ...]]:
        reasons: list[str] = []

        reasons.append(
            "reclaim candle body meets minimum ratio"
            if body_ok
            else "reclaim candle body is too weak"
        )
        reasons.append(
            "price held the reclaimed level"
            if held
            else "price failed to hold the reclaimed level"
        )
        reasons.append(
            "follow-through confirmed"
            if follow_through
            else "follow-through not confirmed"
        )

        if body_ok and held and (
            follow_through or not require_follow_through
        ):
            return ReclaimStatus.CONFIRMED, tuple(reasons)

        if held and (body_ok or follow_through):
            return ReclaimStatus.POSSIBLE, tuple(reasons)

        return ReclaimStatus.FAILED, tuple(reasons)

    @staticmethod
    def _zone_confluence(
        level: float,
        sweep_direction,
        request: ReclaimRequest,
    ) -> bool:
        if request.zones is None:
            return False

        zones = (
            request.zones.demand_zones
            if sweep_direction is SweepDirection.SELL_SIDE_TAKEN
            else request.zones.supply_zones
        )

        for zone in zones:
            if zone.lower_bound <= level <= zone.upper_bound:
                return True
            midpoint = (zone.lower_bound + zone.upper_bound) / 2
            if midpoint > 0 and abs(level - midpoint) / midpoint <= 0.003:
                return True
        return False

    @staticmethod
    def _body_ratio(candle: Candle) -> float:
        candle_range = candle.high - candle.low
        if candle_range <= 0:
            return 0.0
        return abs(candle.close - candle.open) / candle_range

    @staticmethod
    def _direction(sweep_direction) -> ReclaimDirection:
        if sweep_direction is SweepDirection.SELL_SIDE_TAKEN:
            return ReclaimDirection.BULLISH_RECLAIM
        return ReclaimDirection.BEARISH_RECLAIM

    @staticmethod
    def _status_priority(status: ReclaimStatus) -> int:
        return {
            ReclaimStatus.CONFIRMED: 4,
            ReclaimStatus.POSSIBLE: 3,
            ReclaimStatus.FAILED: 2,
            ReclaimStatus.NONE: 1,
            ReclaimStatus.INVALID: 0,
        }[status]

    @staticmethod
    def _empty(symbol: str, reason: str) -> ReclaimAssessment:
        return ReclaimAssessment(
            symbol=symbol,
            events=(),
            strongest_event=None,
            reasons=(reason,),
            metadata={"engine_scope": "crypto_only"},
        )
