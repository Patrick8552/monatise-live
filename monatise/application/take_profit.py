"""Versioned, evidence-backed profit plans. Decimal values cross the wire as strings.

R describes a destination, never creates it. The nearest credible objective must
clear the minimum R; v1 explicitly rejects weak first objectives (no skipping).
Legacy ``take_profit`` is the last available target, including a one-target plan.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
from typing import Any, Mapping, Sequence

ZERO, HUNDRED = Decimal(0), Decimal(100)
NAMES = ("tp1", "tp2", "tp3", "final_target")
LOGGER = logging.getLogger("monatise.take_profit")


def decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("boolean is not a price/quantity")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("non-finite price/quantity")
    return result


def timestamp(value: Any) -> datetime:
    result = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return result.astimezone(timezone.utc)


def encode(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    return value


@dataclass(frozen=True)
class MultiTPConfiguration:
    enabled: bool = False
    routes: frozenset[str] = frozenset()
    auto_partial_close: bool = False
    auto_breakeven: bool = False
    auto_trailing: bool = False
    allocations: tuple[Decimal, ...] = (Decimal(25),) * 4
    minimum_rr: Decimal = Decimal("1.5")
    minimum_increment_r: Decimal = Decimal("0.1")
    breakeven_mode: str = "NONE"
    breakeven_minimum_rr: Decimal = Decimal(1)
    trail_mode: str = "OFF"
    max_relative_target_distance: Decimal = Decimal("0.25")

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "MultiTPConfiguration":
        def get(key: str, default: str = "false") -> str:
            return str(
                environment.get(key, environment.get("MONATISE_" + key, default))
            )

        def flag(key: str) -> bool:
            return get(key).lower() in {"true", "1", "yes", "on"}

        result = cls(
            enabled=flag("MULTI_TP_ENABLED"),
            routes=frozenset(
                name
                for name in ("stocks", "futures", "indices", "gold", "crypto")
                if flag(f"MULTI_TP_{name.upper()}_ENABLED")
            ),
            auto_partial_close=flag("AUTO_PARTIAL_CLOSE_ENABLED"),
            auto_breakeven=flag("AUTO_BREAKEVEN_ENABLED"),
            auto_trailing=flag("AUTO_TRAILING_ENABLED"),
            allocations=tuple(
                decimal(v)
                for v in get("MULTI_TP_ALLOCATIONS", "25,25,25,25").split(",")
            ),
            minimum_rr=decimal(get("MULTI_TP_MINIMUM_RR", "1.5")),
            minimum_increment_r=decimal(get("MULTI_TP_MINIMUM_INCREMENT_R", "0.1")),
            breakeven_mode=get("MULTI_TP_BREAKEVEN_MODE", "NONE").upper(),
            breakeven_minimum_rr=decimal(get("MULTI_TP_BREAKEVEN_MINIMUM_RR", "1")),
            trail_mode=get("MULTI_TP_TRAIL_MODE", "OFF").upper(),
            max_relative_target_distance=decimal(
                get("MULTI_TP_MAX_TARGET_DISTANCE_FRACTION", "0.25")
            ),
        )
        if (
            len(result.allocations) != 4
            or min(result.allocations) <= 0
            or sum(result.allocations) != HUNDRED
        ):
            raise ValueError(
                "MULTI_TP_ALLOCATIONS must contain four positive percentages totaling 100"
            )
        if (
            result.minimum_rr <= 0
            or result.minimum_increment_r <= 0
            or result.breakeven_minimum_rr < 0
            or not 0 < result.max_relative_target_distance <= 1
        ):
            raise ValueError("invalid multi-TP risk policy")
        if result.breakeven_mode not in {
            "NONE",
            "AFTER_TP1",
            "AFTER_TP2",
            "STRUCTURE_BASED",
        }:
            raise ValueError("invalid breakeven mode")
        if result.trail_mode not in {
            "OFF",
            "STRUCTURE_TRAIL",
            "ATR_TRAIL",
            "LIQUIDITY_TRAIL",
        }:
            raise ValueError("invalid trail mode")
        return result

    def permits(self, route: str) -> bool:
        return self.enabled and route in self.routes


def route_for(instrument: Any) -> str:
    asset_class = str(getattr(instrument, "asset_class", ""))
    if asset_class == "stock":
        return "stocks"
    if asset_class == "crypto":
        return "crypto"
    root = str(getattr(instrument, "futures_symbol", ""))
    if root in {"GC", "MGC"}:
        return "gold"
    if root in {"ES", "MES", "NQ", "MNQ", "YM", "RTY"}:
        return "indices"
    return "futures"


@dataclass(frozen=True)
class TargetCandidate:
    price: Decimal
    source: str
    source_provider: str
    evidence_type: str
    confidence: Decimal
    timeframe: str
    observed_at: datetime
    structural_relevance: Decimal = Decimal("0.7")
    liquidity_significance: Decimal = Decimal("0.5")
    higher_timeframe_relevance: Decimal = Decimal("0.5")
    opposing_positioning: bool = False
    agreement: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.price <= 0
            or not self.price.is_finite()
            or not all(
                (self.source, self.source_provider, self.evidence_type, self.timeframe)
            )
        ):
            raise ValueError("target requires positive price and provenance")
        timestamp(self.observed_at)
        for value in (
            self.confidence,
            self.structural_relevance,
            self.liquidity_significance,
            self.higher_timeframe_relevance,
        ):
            if not value.is_finite() or not 0 <= value <= 1:
                raise ValueError("invalid target confidence/relevance")

    @property
    def score(self) -> Decimal:
        # Count independent providers, never duplicate raw levels.
        return (
            self.confidence * Decimal(".35")
            + self.structural_relevance * Decimal(".3")
            + self.liquidity_significance * Decimal(".2")
            + self.higher_timeframe_relevance * Decimal(".15")
            + min(Decimal(".1"), Decimal(".025") * len(set(self.agreement)))
        )


@dataclass(frozen=True)
class TakeProfitTarget:
    name: str
    price: Decimal
    analysis_price: Decimal
    broker_price: Decimal | None
    rr: Decimal
    allocation_pct: Decimal
    source: str
    source_provider: str
    evidence_type: str
    confidence: Decimal
    timeframe: str
    observed_at: datetime
    status: str = "PENDING"
    hit_at: datetime | None = None
    closed_volume: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    allocated_volume: Decimal = ZERO
    agreement: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TakeProfitTarget":
        fields = dict(value)
        for key in (
            "price",
            "analysis_price",
            "rr",
            "allocation_pct",
            "confidence",
            "closed_volume",
            "realized_pnl",
            "allocated_volume",
        ):
            if key in fields:
                fields[key] = decimal(fields[key])
        fields["broker_price"] = (
            decimal(fields["broker_price"])
            if fields.get("broker_price") is not None
            else None
        )
        fields["observed_at"] = timestamp(fields["observed_at"])
        fields["hit_at"] = timestamp(fields["hit_at"]) if fields.get("hit_at") else None
        fields["agreement"] = tuple(fields.get("agreement") or ())
        return cls(**fields)


@dataclass(frozen=True)
class TakeProfitPlan:
    targets: tuple[TakeProfitTarget, ...]
    direction: str
    entry: Decimal
    stop: Decimal
    created_at: datetime
    expires_at: datetime
    minimum_rr: Decimal = Decimal("1.5")
    minimum_increment_r: Decimal = Decimal("0.1")
    management_mode: str = "APPROVAL_PER_EXIT"
    breakeven_policy: str = "NONE"
    trail_policy: str = "OFF"
    original_position_size: Decimal = ZERO
    remaining_position_size: Decimal = ZERO
    version: int = 1
    rejection_log: tuple[str, ...] = ()
    qualification_policy: str = "REJECT_WEAK_FIRST_OBJECTIVE"

    @property
    def blended_expected_rr(self) -> Decimal:
        """Allocation-weighted planned R, not a probability/return forecast."""
        if self.original_position_size > 0:
            return sum(
                (
                    t.rr * t.allocated_volume / self.original_position_size
                    for t in self.targets
                ),
                ZERO,
            )
        return sum((t.rr * t.allocation_pct / HUNDRED for t in self.targets), ZERO)

    @property
    def maximum_available_rr(self) -> Decimal:
        return max(t.rr for t in self.targets)

    @property
    def legacy_take_profit(self) -> Decimal:
        return self.targets[-1].price

    def to_dict(self) -> dict[str, Any]:
        return encode(asdict(self))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TakeProfitPlan":
        fields = dict(value)
        fields["targets"] = tuple(
            TakeProfitTarget.from_dict(t) for t in fields["targets"]
        )
        for key in (
            "entry",
            "stop",
            "minimum_rr",
            "minimum_increment_r",
            "original_position_size",
            "remaining_position_size",
        ):
            if key in fields:
                fields[key] = decimal(fields[key])
        for key in ("created_at", "expires_at"):
            fields[key] = timestamp(fields[key])
        fields["rejection_log"] = tuple(fields.get("rejection_log") or ())
        result = cls(**fields)
        result.validate()
        return result

    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def validate(
        self,
        *,
        now: datetime | None = None,
        tick_size: Decimal = Decimal("0.00000001"),
        minimum_distance: Decimal = ZERO,
    ) -> None:
        if (
            self.version != 1
            or self.direction not in {"long", "short"}
            or not 1 <= len(self.targets) <= 4
        ):
            raise ValueError("unsupported target plan")
        if (
            self.management_mode not in {"APPROVAL_PER_EXIT", "APPROVED_PLAN"}
            or self.breakeven_policy
            not in {"NONE", "AFTER_TP1", "AFTER_TP2", "STRUCTURE_BASED"}
            or self.trail_policy
            not in {"OFF", "STRUCTURE_TRAIL", "ATR_TRAIL", "LIQUIDITY_TRAIL"}
        ):
            raise ValueError("invalid management policy")
        if (
            self.entry <= 0
            or self.stop <= 0
            or self.minimum_rr <= 0
            or self.minimum_increment_r <= 0
            or tick_size <= 0
        ):
            raise ValueError("invalid target geometry")
        sign = Decimal(1 if self.direction == "long" else -1)
        risk = (self.entry - self.stop) * sign
        if risk <= 0 or self.expires_at <= self.created_at:
            raise ValueError("invalid stop or setup expiry")
        if now is not None and timestamp(now) >= self.expires_at:
            raise ValueError("SETUP_STALE: target plan expired")
        if sum(t.allocation_pct for t in self.targets) != HUNDRED:
            raise ValueError("target allocations must total 100")
        if not ZERO <= self.remaining_position_size <= self.original_position_size:
            raise ValueError("invalid managed position size")
        if (
            self.original_position_size
            and sum(t.allocated_volume for t in self.targets)
            != self.original_position_size
        ):
            raise ValueError("allocated target volume does not match original size")
        previous = self.entry
        for index, target in enumerate(self.targets):
            if target.name != NAMES[index] or not all(
                (
                    target.source,
                    target.source_provider,
                    target.evidence_type,
                    target.timeframe,
                )
            ):
                raise ValueError("target order or provenance is invalid")
            if (
                not 0 < target.allocation_pct <= HUNDRED
                or not 0 <= target.confidence <= 1
                or target.analysis_price <= 0
            ):
                raise ValueError("invalid target allocation or evidence")
            if (
                target.status
                not in {"PENDING", "PARTIAL_FILL", "HIT", "BYPASSED", "CANCELLED"}
                or target.closed_volume < 0
                or target.allocated_volume < 0
            ):
                raise ValueError("invalid target lifecycle state")
            distance = (target.price - self.entry) * sign
            incremental = (target.price - previous) * sign
            required = (
                max(tick_size, risk * self.minimum_increment_r)
                if index
                else max(tick_size, minimum_distance)
            )
            if incremental < required or distance < minimum_distance:
                raise ValueError("target reversed, duplicated or insufficiently spaced")
            if abs(distance / risk - target.rr) > Decimal("0.000001"):
                raise ValueError("target R disagrees with geometry")
            if target.broker_price is not None and (
                target.broker_price != target.price or target.price % tick_size != 0
            ):
                raise ValueError("broker target is not tick normalized")
            previous = target.price
        if self.targets[0].rr < self.minimum_rr:
            raise ValueError(
                "insufficient TP1 reward/risk; cannot skip first objective"
            )


def build_plan(
    *,
    candidates: Sequence[TargetCandidate],
    direction: str,
    entry: Any,
    stop: Any,
    now: datetime,
    expires_at: datetime,
    config: MultiTPConfiguration,
    tick_size: Any = "0.00000001",
    max_age: timedelta = timedelta(hours=5),
) -> TakeProfitPlan:
    entry, stop, tick = decimal(entry), decimal(stop), decimal(tick_size)
    risk = abs(entry - stop)
    sign = Decimal(1 if direction == "long" else -1)
    if direction not in {"long", "short"} or entry <= 0 or risk <= 0 or tick <= 0:
        raise ValueError("invalid direction, entry or stop")
    accepted: list[TargetCandidate] = []
    rejected: list[str] = []
    LOGGER.info(
        "target candidates generated",
        extra={
            "direction": direction,
            "candidate_evidence": encode([asdict(c) for c in candidates]),
        },
    )
    for candidate in candidates:
        reason = None
        if (candidate.price - entry) * sign <= 0:
            reason = "wrong_side"
        elif (
            candidate.observed_at > now + timedelta(seconds=5)
            or now - candidate.observed_at > max_age
        ):
            reason = "stale_or_future"
        elif candidate.confidence < Decimal(
            ".35"
        ) or candidate.structural_relevance < Decimal(".4"):
            reason = "insufficient_evidence"
        elif abs(candidate.price - entry) / entry > config.max_relative_target_distance:
            reason = "outside_mapping_safety"
        if reason:
            rejected.append(candidate.evidence_type + ":" + reason)
            LOGGER.info(
                "target candidate rejected",
                extra={
                    "evidence_type": candidate.evidence_type,
                    "target_price": str(candidate.price),
                    "rejection_reason": reason,
                },
            )
        else:
            accepted.append(candidate)
    accepted.sort(key=lambda c: (c.price - entry) * sign)
    merged: list[TargetCandidate] = []
    for candidate in accepted:
        if merged and abs(candidate.price - merged[-1].price) < max(
            tick * 2, risk * config.minimum_increment_r
        ):
            first = merged[-1]
            # Preserve the nearer obstacle; distant confluence must not move TP1.
            merged[-1] = replace(
                first,
                source=first.source
                + f"; confluence {candidate.source_provider}/{candidate.evidence_type}@{candidate.price}",
                confidence=max(first.confidence, candidate.confidence),
                agreement=tuple(
                    sorted(
                        set(
                            first.agreement
                            + candidate.agreement
                            + (candidate.source_provider,)
                        )
                        - {first.source_provider}
                    )
                ),
            )
            rejected.append(candidate.evidence_type + ":merged_nearby")
        else:
            merged.append(candidate)
    if not merged:
        raise ValueError("insufficient target evidence")

    # The nearest credible opposing level is mandatory. Rank remaining levels
    # by evidence, then keep their price order; never award points for quantity.
    def rank(candidate: TargetCandidate) -> tuple[Decimal, Decimal]:
        age = max(0, (now - candidate.observed_at).total_seconds())
        freshness = max(ZERO, Decimal(1) - decimal(age / max_age.total_seconds()))
        reward = min(Decimal(4), abs(candidate.price - entry) / risk)
        obstruction = any(
            c.opposing_positioning
            and 0 < (c.price - entry) * sign < (candidate.price - entry) * sign
            for c in merged
        )
        quality = (
            candidate.score
            + freshness * Decimal(".05")
            + reward * Decimal(".01")
            - (Decimal(".05") if obstruction else ZERO)
        )
        return -quality, abs(candidate.price - entry)

    chosen = [merged[0], *sorted(merged[1:], key=rank)[:3]]
    chosen.sort(key=lambda c: (c.price - entry) * sign)
    weights = config.allocations[: len(chosen)]
    allocation = [w / sum(weights) * HUNDRED for w in weights]
    allocation[-1] = HUNDRED - sum(allocation[:-1])
    targets = tuple(
        TakeProfitTarget(
            NAMES[i],
            c.price,
            c.price,
            None,
            (c.price - entry) * sign / risk,
            allocation[i],
            c.source,
            c.source_provider,
            c.evidence_type,
            c.confidence,
            c.timeframe,
            c.observed_at,
            agreement=c.agreement,
        )
        for i, c in enumerate(chosen)
    )
    plan = TakeProfitPlan(
        targets,
        direction,
        entry,
        stop,
        now,
        expires_at,
        minimum_rr=config.minimum_rr,
        minimum_increment_r=config.minimum_increment_r,
        management_mode="APPROVED_PLAN"
        if config.auto_partial_close
        else "APPROVAL_PER_EXIT",
        breakeven_policy=config.breakeven_mode if config.auto_breakeven else "NONE",
        trail_policy=config.trail_mode if config.auto_trailing else "OFF",
        rejection_log=tuple(rejected),
    )
    try:
        plan.validate(now=now, tick_size=tick)
    except ValueError as exc:
        LOGGER.info("target plan rejected", extra={"rejection_reason": str(exc)})
        raise
    LOGGER.info(
        "target plan constructed",
        extra={"plan_digest": plan.digest(), "target_plan": plan.to_dict()},
    )
    return plan


def convert_plan(
    plan: TakeProfitPlan,
    *,
    broker_entry: Any,
    broker_stop: Any,
    tick_size: Any,
    minimum_distance: Any = 0,
    now: datetime | None = None,
) -> TakeProfitPlan:
    entry, stop, tick = decimal(broker_entry), decimal(broker_stop), decimal(tick_size)
    ratio = entry / plan.entry
    if not Decimal(".5") <= ratio <= Decimal(2):
        raise ValueError("analysis/broker mapping outside verified ratio safety")
    risk, sign = abs(entry - stop), Decimal(1 if plan.direction == "long" else -1)
    targets = []
    for target in plan.targets:
        price = (target.price * ratio / tick).to_integral_value(
            rounding=ROUND_FLOOR
        ) * tick
        targets.append(
            replace(
                target,
                price=price,
                broker_price=price,
                rr=(price - entry) * sign / risk,
            )
        )
    result = replace(plan, targets=tuple(targets), entry=entry, stop=stop)
    result.validate(now=now, tick_size=tick, minimum_distance=decimal(minimum_distance))
    return result


def revalidate_plan(
    plan: TakeProfitPlan,
    *,
    entry: Any,
    stop: Any,
    tick_size: Any,
    minimum_distance: Any = 0,
    now: datetime | None = None,
) -> TakeProfitPlan:
    """Keep all destinations fixed; only recompute R at the fresh quote."""
    entry, stop = decimal(entry), decimal(stop)
    risk, sign = abs(entry - stop), Decimal(1 if plan.direction == "long" else -1)
    if risk <= 0:
        raise ValueError("PRICE_MOVED_BEYOND_VALIDATION: invalid risk")
    result = replace(
        plan,
        entry=entry,
        stop=stop,
        targets=tuple(
            replace(t, rr=(t.price - entry) * sign / risk) for t in plan.targets
        ),
    )
    result.validate(
        now=now,
        tick_size=decimal(tick_size),
        minimum_distance=decimal(minimum_distance),
    )
    return result


def allocate_volume(
    plan: TakeProfitPlan, *, volume: Any, minimum: Any, step: Any
) -> TakeProfitPlan:
    volume, minimum, step = decimal(volume), decimal(minimum), decimal(step)
    if step <= 0 or minimum <= 0 or volume < minimum or volume % step != 0:
        raise ValueError("invalid broker volume")
    sizes = [
        (volume * t.allocation_pct / HUNDRED / step).to_integral_value(
            rounding=ROUND_FLOOR
        )
        * step
        for t in plan.targets
    ]
    sizes[-1] = volume - sum(sizes[:-1])
    if any(v < minimum or v % step != 0 for v in sizes):
        # Reject explicitly instead of silently changing an approved exit profile.
        raise ValueError("position too small for requested partial-close allocation")
    return replace(
        plan,
        targets=tuple(
            replace(t, allocated_volume=v) for t, v in zip(plan.targets, sizes)
        ),
        original_position_size=volume,
        remaining_position_size=volume,
    )


def plan_fields(plan: TakeProfitPlan) -> dict[str, Any]:
    result = {
        "take_profit_plan": plan.to_dict(),
        "targets": [float(t.price) for t in plan.targets],
        "target": float(plan.legacy_take_profit),
        "blended_expected_rr": float(plan.blended_expected_rr),
        "maximum_available_rr": float(plan.maximum_available_rr),
        "reward_risk": float(plan.targets[0].rr),
    }
    for name in NAMES:
        target = next((t for t in plan.targets if t.name == name), None)
        result[name] = float(target.price) if target else None
        result[name + "_rr"] = float(target.rr) if target else None
    return result


def format_targets(plan: TakeProfitPlan) -> list[str]:
    return [
        f"{'Final' if t.name == 'final_target' else t.name.upper()}: {t.price} | {t.rr:.2f}R | close {t.allocation_pct:.2f}% | {t.evidence_type} ({t.source_provider})"
        + (f" | {t.allocated_volume} lots after rounding" if t.allocated_volume else "")
        + (
            f" | {t.status}: {t.closed_volume} lots filled"
            if t.status != "PENDING"
            else ""
        )
        for t in plan.targets
    ]
