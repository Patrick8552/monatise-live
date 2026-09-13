"""Adapters from observed provider/engine evidence into the common TP builder.

Confidence defaults here are Monatise evidence weights, not claimed provider
probabilities. Unknown provider fields and scalar OI/CVD totals are never prices.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence
from types import SimpleNamespace

from monatise.application.take_profit import (
    MultiTPConfiguration,
    TargetCandidate,
    build_plan,
    decimal,
    plan_fields,
    timestamp,
)


def candidate(
    price: Any,
    *,
    provider: str,
    kind: str,
    timeframe: str,
    observed: datetime,
    confidence: Any = ".6",
    significance: Any = ".5",
    relevance: Any = ".7",
) -> TargetCandidate:
    return TargetCandidate(
        decimal(price),
        "Monatise " + kind.lower().replace("_", " "),
        provider,
        kind,
        decimal(confidence),
        timeframe,
        observed,
        decimal(relevance),
        decimal(significance),
        decimal(
            ".9" if timeframe in {"4h", "1d"} else ".6" if timeframe == "1h" else ".4"
        ),
    )


def flashalpha_candidates(context: Mapping[str, Any]) -> list[TargetCandidate]:
    observed = timestamp(context.get("as_of"))
    result = []
    for field, kind in (
        ("call_wall", "CALL_WALL"),
        ("put_wall", "PUT_WALL"),
        ("gamma_flip", "GAMMA_LEVEL"),
    ):
        if context.get(field) is not None:
            result.append(
                candidate(
                    context[field],
                    provider="flashalpha",
                    kind=kind,
                    timeframe="snapshot",
                    observed=observed,
                    confidence=".75",
                    significance=".9",
                )
            )
    # These scalar strike fields are documented in /v1/exposure/levels. A net
    # gamma or OI amount is not a price and is deliberately never used here.
    for field, kind in (
        ("max_positive_gamma", "GAMMA_LEVEL"),
        ("max_negative_gamma", "GAMMA_LEVEL"),
        ("highest_oi_strike", "OI_CONCENTRATION"),
        ("zero_dte_magnet", "ZERO_DTE_MAGNET"),
    ):
        if context.get(field) is not None:
            result.append(
                candidate(
                    context[field],
                    provider="flashalpha",
                    kind=kind,
                    timeframe="snapshot",
                    observed=observed,
                    confidence=".65",
                    significance=".8",
                )
            )
    levels = context.get("positioning_levels") or {}
    if not isinstance(levels, Mapping):
        raise ValueError("malformed FlashAlpha positioning levels")
    for field, kind in (
        ("resistance_levels", "POSITIONING_RESISTANCE"),
        ("support_levels", "POSITIONING_SUPPORT"),
        ("gamma_levels", "GAMMA_LEVEL"),
    ):
        values = levels.get(field) or []
        if not isinstance(values, (list, tuple)) or len(values) > 256:
            raise ValueError("malformed FlashAlpha secondary levels")
        for value in values:
            row = value if isinstance(value, Mapping) else {"price": value}
            result.append(
                candidate(
                    row.get("price"),
                    provider="flashalpha",
                    kind=kind,
                    timeframe=str(row.get("timeframe") or "snapshot"),
                    observed=timestamp(row.get("as_of") or observed),
                    confidence=row.get("confidence", ".6"),
                    significance=row.get("significance", ".5"),
                )
            )
    return [
        replace(
            c,
            opposing_positioning=c.evidence_type
            in {
                "CALL_WALL",
                "PUT_WALL",
                "POSITIONING_RESISTANCE",
                "POSITIONING_SUPPORT",
            },
        )
        for c in result
    ]


def candle_candidates(
    bars: Sequence[Mapping[str, Any]], *, provider: str, timeframe: str, now: datetime
) -> list[TargetCandidate]:
    """Only confirmed two-sided pivots and completed-candle session extrema."""
    if len(bars) < 5:
        return []
    clean = []
    duration = timedelta(
        minutes={"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}[
            timeframe
        ]
    )
    for row in bars[-240:]:
        opened = timestamp(row.get("t"))
        high, low, close = (decimal(row.get(k)) for k in ("h", "l", "c"))
        if low <= 0 or not low <= close <= high:
            raise ValueError("malformed target candles")
        if opened + duration <= now:
            clean.append((opened, high, low))
    if not clean:
        return []
    result = []
    observed = clean[-1][0] + duration
    for i in range(2, len(clean) - 2):
        _, high, low = clean[i]
        neighbors = clean[i - 2 : i] + clean[i + 1 : i + 3]
        if high > max(v[1] for v in neighbors):
            result.append(
                candidate(
                    high,
                    provider=provider,
                    kind="SWING_HIGH",
                    timeframe=timeframe,
                    observed=observed,
                )
            )
        if low < min(v[2] for v in neighbors):
            result.append(
                candidate(
                    low,
                    provider=provider,
                    kind="SWING_LOW",
                    timeframe=timeframe,
                    observed=observed,
                )
            )
    session = [v for v in clean if v[0].date() == clean[-1][0].date()]
    for price, kind in (
        (max(v[1] for v in session), "SESSION_HIGH"),
        (min(v[2] for v in session), "SESSION_LOW"),
    ):
        result.append(
            candidate(
                price,
                provider=provider,
                kind=kind,
                timeframe=timeframe,
                observed=observed,
            )
        )
    return result


def apply_flashalpha_plan(
    analysis: dict[str, Any],
    context: Mapping[str, Any],
    *,
    config: MultiTPConfiguration,
    route: str,
    now: datetime,
    bars: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    if not config.permits(route) or analysis.get("setup_status") != "confirmed":
        return analysis
    try:
        if analysis.get("provider_consensus") == "CONFLICT":
            raise ValueError("provider disagreement blocks multi-target qualification")
        candidates = flashalpha_candidates(context)
        if bars:
            structure = candle_candidates(
                bars, provider="alpaca", timeframe="1h", now=now
            )
            candidates += structure
            highs = [c for c in structure if c.evidence_type == "SWING_HIGH"]
            lows = [c for c in structure if c.evidence_type == "SWING_LOW"]
            if structure:
                analysis["management_structure"] = {
                    "source": "monatise.alpaca.confirmed_pivots",
                    "confirmed": True,
                    "direction": str(analysis["direction"]).lower(),
                    "observed_at": structure[-1].observed_at.isoformat(),
                    "confirmed_higher_low": str(lows[-1].price)
                    if len(lows) > 1 and lows[-1].price > lows[-2].price
                    else None,
                    "confirmed_lower_high": str(highs[-1].price)
                    if len(highs) > 1 and highs[-1].price < highs[-2].price
                    else None,
                }
        plan = build_plan(
            candidates=candidates,
            direction=str(analysis["direction"]).lower(),
            entry=analysis["entry"],
            stop=analysis["stop_loss"],
            now=now,
            expires_at=timestamp(
                analysis.get("expires_at")
                or analysis.get("valid_until")
                or now + timedelta(minutes=30)
            ),
            config=config,
        )
        analysis.update(plan_fields(plan))
        # Keep original directional qualification; quality can improve only for
        # independent evidence supporting destinations, never for target count.
        confluence = any(
            t.agreement and set(t.agreement) - {t.source_provider} for t in plan.targets
        )
        analysis["target_quality"] = {
            "tp1_rr": str(plan.targets[0].rr),
            "cross_provider_confluence": confluence,
            "candidate_count": len(candidates),
            "rejections": list(plan.rejection_log),
        }
        score = abs(int(analysis.get("score") or 0))
        analysis["score"] = min(10, score + int(confluence)) * (
            1 if plan.direction == "long" else -1
        )
    except (ValueError, TypeError, ArithmeticError, KeyError) as exc:
        analysis.update(
            decision="NO_TRADE",
            setup_status="invalid_targets",
            target=None,
            targets=[],
            take_profit_plan=None,
            publication_valid=False,
            target_rejection=str(exc),
        )
    return analysis


def crypto_layer_candidates(
    layer: Any, *, timeframe: str, observed: datetime
) -> list[TargetCandidate]:
    """Use the existing liquidity, structure, zone and Fibonacci assessments."""
    from monatise.engines.fibonacci_liquidity import (
        FibonacciLiquidityEngine,
        FibonacciRequest,
    )

    result = []
    for level in (*layer.liquidity.buy_side_levels, *layer.liquidity.sell_side_levels):
        weight = {"high": ".85", "medium": ".65", "low": ".4"}[level.strength.value]
        result.append(
            candidate(
                level.price,
                provider="monatise_crypto",
                kind="LIQUIDITY_POOL",
                timeframe=timeframe,
                observed=observed,
                confidence=weight,
                significance=weight,
            )
        )
    for points, kind in (
        (layer.structure.swing_highs, "SWING_HIGH"),
        (layer.structure.swing_lows, "SWING_LOW"),
    ):
        for _, price in points[-8:]:
            result.append(
                candidate(
                    price,
                    provider="monatise_crypto",
                    kind=kind,
                    timeframe=timeframe,
                    observed=observed,
                )
            )
    for zones, kind in (
        (layer.zones.supply_zones, "SUPPLY_ZONE"),
        (layer.zones.demand_zones, "DEMAND_ZONE"),
    ):
        for zone in zones:
            price = zone.lower_bound if kind == "SUPPLY_ZONE" else zone.upper_bound
            result.append(
                candidate(
                    price,
                    provider="monatise_crypto",
                    kind=kind,
                    timeframe=timeframe,
                    observed=observed,
                )
            )
    fib = FibonacciLiquidityEngine().assess(
        FibonacciRequest(
            layer.market,
            layer.structure,
            liquidity=layer.liquidity,
            zones=layer.zones,
            reclaim=layer.reclaim,
            extension_ratios=(1.272, 1.414, 1.618),
        )
    )
    if fib.primary_anchor is not None:
        for level in fib.extension_levels:
            if level.ratio not in {1.272, 1.414, 1.618}:
                continue
            if not (
                level.liquidity_confluence
                or level.zone_confluence
                or level.structure_confluence
            ):
                continue
            result.append(
                candidate(
                    level.price,
                    provider="monatise_crypto",
                    kind="FIB_" + str(level.ratio).replace(".", "_"),
                    timeframe=timeframe,
                    observed=observed,
                    confidence=str(min(1, fib.primary_anchor.structure_confidence)),
                )
            )
    return result


def apply_crypto_output_plan(
    analysis: dict[str, Any],
    outputs: Mapping[str, Any],
    *,
    config: MultiTPConfiguration,
    now: datetime,
) -> dict[str, Any]:
    """Use the same engine adapter for on-demand/scheduled directional output.

    The existing decision, confirmation and stop remain authoritative. No grid
    output or scalar derivatives metric can be promoted into a price target.
    """
    if not config.permits("crypto"):
        return analysis
    analysis.update(target=None, targets=[], take_profit_plan=None)
    if (
        analysis.get("classification") in {None, "no_trade", "grid", "two_sided"}
        or analysis.get("direction") not in {"long", "short"}
        or analysis.get("entry_confirmation_status") != "confirmed"
    ):
        return analysis
    try:
        market = outputs["market_data"]
        layer = SimpleNamespace(
            market=market,
            liquidity=outputs["liquidity"],
            zones=outputs["supply_demand"],
            structure=outputs["market_structure"],
            reclaim=outputs.get("reclaim"),
        )
        observed = timestamp(
            analysis.get("market_observed_at") or analysis["generated_at"]
        )
        timeframe = str(analysis.get("interval") or "1h")
        candidates = crypto_layer_candidates(
            layer, timeframe=timeframe, observed=observed
        )
        entry = analysis.get("entry")
        if entry is None:
            zone = analysis["entry_zone"]
            entry = (decimal(zone["low"]) + decimal(zone["high"])) / 2
        plan = build_plan(
            candidates=candidates,
            direction=analysis["direction"],
            entry=entry,
            stop=analysis["invalidation"],
            now=now,
            expires_at=timestamp(analysis["expires_at"]),
            config=config,
        )
        analysis.update(plan_fields(plan))
        lows, highs = layer.structure.swing_lows, layer.structure.swing_highs
        analysis["management_structure"] = {
            "source": "monatise.crypto.directional_engines",
            "confirmed": True,
            "direction": plan.direction,
            "observed_at": observed.isoformat(),
            "confirmed_higher_low": str(lows[-1][1])
            if len(lows) > 1 and lows[-1][1] > lows[-2][1]
            else None,
            "confirmed_lower_high": str(highs[-1][1])
            if len(highs) > 1 and highs[-1][1] < highs[-2][1]
            else None,
        }
    except (ValueError, TypeError, ArithmeticError, KeyError, AttributeError) as exc:
        analysis.update(
            classification="no_trade",
            direction="none",
            target_rejection=str(exc),
            publication_valid=False,
        )
    return analysis


def format_crypto_output_plan(analysis: Mapping[str, Any]) -> str:
    lines = [
        f"Monatise crypto — {analysis.get('symbol', '')}",
        f"{analysis.get('classification', 'no_trade').upper()} | {analysis.get('direction', 'none').upper()}",
    ]
    if analysis.get("take_profit_plan"):
        from monatise.application.take_profit import TakeProfitPlan, format_targets

        plan = TakeProfitPlan.from_dict(analysis["take_profit_plan"])
        lines += [
            f"Entry: {plan.entry} | SL: {plan.stop}",
            *format_targets(plan),
            f"Setup expiry: {plan.expires_at.isoformat()}",
            "Source: Monatise crypto evidence engines | Execution requires separate FTMO approval",
        ]
    else:
        lines.append(
            str(
                analysis.get("target_rejection")
                or "Waiting for a confirmed directional setup with valid target evidence"
            )
        )
    return "\n".join(lines)
