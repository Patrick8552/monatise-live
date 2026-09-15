"""Server-owned gamma confidence policy for the shared candle strategy.

Uncertified gamma is never directional evidence. Only full independent candle
confluence can authorize half of the otherwise permitted monetary risk budget.
Unknown and gamma-primary strategy versions require certified gamma.
"""

from decimal import Decimal

from monatise.application.gamma_evidence import (
    CERTIFIED,
    fingerprint,
    validate_certificate,
)
from monatise.application.gamma_reconstruction import GammaQualityError, clock

VERSION = "stock-gamma-confidence-v1"
SUPPLEMENTAL_STRATEGIES = frozenset({"hierarchy-shadow-v1"})
DEGRADED_MULTIPLIER = Decimal("0.50")
CHECKS = (
    "structure",
    "liquidity",
    "value",
    "confirmation",
    "fibonacci",
    "price_action",
)


def requires_gamma(strategy):
    return strategy not in SUPPLEMENTAL_STRATEGIES


def eligible_uncertified(gamma, *, strategy, symbol, now):
    return (
        not requires_gamma(strategy)
        and isinstance(gamma, dict)
        and gamma.get("state") == "UNCERTIFIED"
        and gamma.get("symbol") == symbol
        and gamma.get("degradation_allowed") is True
        and gamma.get("gamma_flip") is None
        and clock(gamma.get("as_of")) <= now < clock(gamma.get("expires_at"))
    )


def independent_checks(result, *, direction):
    core = result.get("signal_core_evidence") or {}
    liquidity = result.get("liquidity") or {}
    trigger = result.get("trigger") or {}
    fibonacci = (result.get("fibonacci") or {}).get("15m") or {}
    return {
        "structure": core.get("structure") is True,
        "liquidity": core.get("liquidity") is True
        and liquidity.get("confirmed_sweep") is True,
        "value": core.get("value") is True,
        "confirmation": core.get("confirmation") is True,
        "fibonacci": fibonacci.get("has_valid_anchor") is True
        and fibonacci.get("direction")
        == {"long": "bullish", "short": "bearish"}.get(direction),
        "price_action": bool(
            trigger.get("confirmed_reclaim") or trigger.get("confirmed_break")
        ),
    }


def confidence_evidence(gamma, *, strategy, symbol, now, checks):
    if not isinstance(gamma, dict):
        raise GammaQualityError("gamma_certificate_missing_or_uncertified")
    if gamma.get("state") in CERTIFIED:
        validate_certificate(gamma, symbol=symbol, now=now)
        state, multiplier = "NORMAL", Decimal("1")
    elif (
        eligible_uncertified(gamma, strategy=strategy, symbol=symbol, now=now)
        and set(checks) == set(CHECKS)
        and all(value is True for value in checks.values())
    ):
        state, multiplier = "DEGRADED", DEGRADED_MULTIPLIER
    else:
        raise GammaQualityError("independent_confluence_or_gamma_required")
    value = {
        "version": VERSION,
        "symbol": symbol,
        "strategy": strategy,
        "state": state,
        "risk_multiplier": str(multiplier),
        "gamma_digest": fingerprint(gamma),
        "independent_checks": dict(checks),
        "expires_at": gamma["expires_at"],
    }
    value["evidence_id"] = fingerprint(value)
    return value


def validate_confidence(value, gamma, *, symbol, now):
    if not isinstance(value, dict) or value.get("version") != VERSION:
        raise GammaQualityError("confidence_evidence_missing")
    expected = confidence_evidence(
        gamma,
        strategy=value.get("strategy"),
        symbol=symbol,
        now=now,
        checks=value.get("independent_checks") or {},
    )
    if value != expected:
        raise GammaQualityError("confidence_evidence_changed")
    return Decimal(value["risk_multiplier"])


def allocation_from_proof(proof, *, symbol, now):
    gamma = proof.get("gamma_evidence")
    confidence = proof.get("confidence_evidence")
    if confidence is None:
        # Pre-upgrade, already persisted proofs retain their existing rules.
        if gamma is not None:
            validate_certificate(gamma, symbol=symbol, now=now)
        return Decimal("1")
    return validate_confidence(confidence, gamma, symbol=symbol, now=now)


def format_confidence(value, gamma):
    if not isinstance(value, dict):
        return []
    if value.get("state") != "DEGRADED":
        return ["Confidence: NORMAL | Risk mode: STANDARD"]
    reason = (gamma.get("quarantined_primary") or {}).get("quality", "unknown")
    return [
        "MONATISE SETUP — REDUCED CONFIDENCE",
        f"Gamma: Uncertified — {reason}",
        "Risk mode: DEGRADED",
        "Position risk: 0.50× standard allocation",
        "Execution requires all independent evidence and broker validations to remain valid.",
    ]
