"""Stock gamma evidence ladder. Only certificates enter strategy context.

Certificates carry direction. Uncertified candidates remain quarantined; a
separate strategy policy controls whether independent confluence may proceed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy
from datetime import timedelta

from monatise.application.gamma_reconstruction import (
    CONVENTION,
    POLICY,
    GammaQualityError,
    clock,
    fresh,
    number,
    reconstruct,
)
from monatise.application.provider_evidence import gamma_status

CERTIFIED = frozenset(
    {"CERTIFIED_PRIMARY", "CERTIFIED_RECONSTRUCTED", "CERTIFIED_CROSS_PROVIDER"}
)
RETRYABLE = frozenset(
    {
        "sensitive_root",
        "uncertain_root_path",
        "quality_budget",
        "search_budget",
        "insufficient_local_coverage",
        "insufficient_quote_quality",
        "no_boundary",
        "stored_sign_mismatch",
    }
)


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def candidate(context):
    if not isinstance(context, dict):
        return {"value": None, "quality": "unknown", "trusted": False}
    try:
        value = number(context.get("gamma_flip"), positive=True)
    except GammaQualityError:
        value = None
    statuses = [context.get("gamma_flip_status")]
    evidence = context.get("provider_evidence")
    statuses += [
        r.get("gamma_flip_status")
        for r in (evidence.values() if isinstance(evidence, dict) else ())
        if isinstance(r, dict)
    ]
    status = next((gamma_status(s) for s in statuses if s != "available"), "available")
    return {"value": value, "quality": status, "trusted": False}


def certificate(state, estimate, *, symbol, attempts, quarantined):
    value = {
        "version": POLICY.version,
        "state": state,
        "symbol": symbol,
        **estimate,
        "attempts": deepcopy(attempts),
        "quarantined_primary": deepcopy(quarantined),
    }
    value["certificate_id"] = fingerprint(value)
    return value


def validate_certificate(value, *, symbol, now):
    if (
        not isinstance(value, dict)
        or value.get("state") not in CERTIFIED
        or value.get("symbol") != symbol
        or value.get("version") != POLICY.version
    ):
        raise GammaQualityError("gamma_certificate_missing_or_uncertified")
    body = {k: v for k, v in value.items() if k != "certificate_id"}
    if value.get("certificate_id") != fingerprint(body):
        raise GammaQualityError("gamma_certificate_changed")
    number(value.get("gamma_flip"), positive=True)
    number(value.get("underlying_price"), positive=True)
    if not clock(value.get("as_of")) <= now < clock(value.get("expires_at")):
        raise GammaQualityError("gamma_certificate_expired_or_future")
    return value


def independent_agreement(estimate, quarantined, context):
    spot = number(context.get("underlying_price"), positive=True)
    other_spot = number(estimate.get("underlying_price"), positive=True)
    flip = number(estimate.get("gamma_flip"), positive=True)
    if abs(spot - other_spot) / spot > POLICY.agreement_fraction:
        raise GammaQualityError("underlying_price_disagreement")
    reference = quarantined.get("value")
    if (
        reference is not None
        and abs(flip - reference) / spot > POLICY.agreement_fraction
    ):
        raise GammaQualityError("independent_gamma_disagreement")
    if "net_gex" in estimate:
        primary_net = number(context.get("net_gex"))
        independent_net = number(estimate["net_gex"])
        if primary_net * independent_net < 0:
            raise GammaQualityError("independent_gex_sign_disagreement")
    return {
        "candidate_comparison": "passed" if reference is not None else "unavailable",
        "tolerance_fraction_of_spot": POLICY.agreement_fraction,
    }


class GammaEvidenceLadder:
    def __init__(self, *, chain_provider=None, cross_providers=()):
        self.chain_provider = chain_provider
        self.cross_providers = tuple(cross_providers)
        if len(self.cross_providers) > 2:
            raise ValueError("at most two independent gamma providers are supported")

    async def resolve(
        self,
        *,
        context,
        primary_error,
        primary,
        symbol,
        now,
        maximum_age,
        validate_primary,
        validate_supporting,
    ):
        attempts = []
        quarantined = candidate(context)

        def unavailable(reason):
            allowed = False
            as_of = expires = None
            try:
                validate_supporting(context, now())
                raw = context.get("provider_evidence") or {}
                if set(raw) == {"gex", "levels"}:
                    stamps = [clock(context["as_of"])] + [
                        clock(row["data_as_of"][key])
                        for row in raw.values()
                        for key in ("equity_feed", "equity_options_feed")
                    ]
                    stamps += [clock(row["as_of"]) for row in raw.values()]
                    as_of = min(stamps).isoformat()
                    expires = (min(stamps) + maximum_age).isoformat()
                    allowed = quarantined["quality"] in (
                        RETRYABLE - {"stored_sign_mismatch"}
                    ) and not any(
                        row.get("reason")
                        in {
                            "independent_gamma_disagreement",
                            "underlying_price_disagreement",
                            "independent_gex_sign_disagreement",
                        }
                        for row in attempts
                    )
            except (ValueError, TypeError, KeyError):
                pass
            return (
                {
                    "version": POLICY.version,
                    "state": "UNCERTIFIED",
                    "symbol": symbol,
                    "gamma_flip": None,
                    "degradation_allowed": allowed,
                    "as_of": as_of,
                    "expires_at": expires,
                    "quarantined_primary": quarantined,
                    "attempts": attempts,
                    "reason": reason,
                },
                context,
                primary_error,
            )

        def primary_certificate(value, stamp):
            evidence = value.get("provider_evidence")
            if not isinstance(evidence, dict) or set(evidence) != {"gex", "levels"}:
                raise GammaQualityError("primary_provenance_incomplete")
            clocks = [stamp]
            for raw in evidence.values():
                clocks += [clock(raw["as_of"])]
                clocks += [
                    clock(raw["data_as_of"][key])
                    for key in ("equity_feed", "equity_options_feed")
                ]
            return certificate(
                "CERTIFIED_PRIMARY",
                {
                    "gamma_flip": number(value.get("gamma_flip"), positive=True),
                    "underlying_price": number(
                        value.get("underlying_price"), positive=True
                    ),
                    "provider": "flashalpha",
                    "as_of": min(clocks).isoformat(),
                    "expires_at": (min(clocks) + maximum_age).isoformat(),
                    "methodology": "flashalpha_certified_primary",
                    "quality": {"provider_certificate": "available"},
                },
                symbol=symbol,
                attempts=attempts,
                quarantined=quarantined,
            )

        if primary_error is None:
            if quarantined["quality"] != "available":
                return unavailable("primary_gamma_certificate_missing")
            try:
                stamp = validate_primary(context, now())
                proof = primary_certificate(context, stamp)
                validate_certificate(proof, symbol=symbol, now=now())
            except (ValueError, TypeError, KeyError):
                return unavailable("primary_certificate_invalid")
            attempts.append(
                {"source": "flashalpha", "stage": "primary", "status": "certified"}
            )
            return primary_certificate(context, stamp), context, None
        attempts.append(
            {
                "source": "flashalpha",
                "stage": "primary",
                "status": "rejected",
                "reason": quarantined["quality"],
            }
        )
        # A fallback gamma number cannot replace a missing wall, stale underlying,
        # symbol mismatch, transport failure or invalid non-gamma evidence.
        try:
            validate_supporting(context, now())
        except ValueError:
            return unavailable("supporting_provider_evidence_invalid")
        if quarantined["quality"] in RETRYABLE:
            # One full re-query; transport retries remain bounded in the adapter.
            # The adapter also reserves quota and serializes context requests.
            quota = (getattr(primary, "telemetry", {}) or {}).get("remaining")
            if isinstance(quota, int) and quota < 4:
                attempts.append(
                    {
                        "source": "flashalpha",
                        "stage": "requery",
                        "status": "skipped",
                        "reason": "quota_reserved",
                    }
                )
            else:
                try:
                    newer = await asyncio.to_thread(primary.context, symbol)
                    stamp = validate_primary(newer, now())
                    if candidate(newer)["quality"] != "available" or stamp <= clock(
                        context.get("as_of")
                    ):
                        raise GammaQualityError("primary_requery_not_newly_certified")
                    attempts.append(
                        {
                            "source": "flashalpha",
                            "stage": "requery",
                            "status": "certified",
                        }
                    )
                    proof = primary_certificate(newer, stamp)
                    validate_certificate(proof, symbol=symbol, now=now())
                    return proof, newer, None
                except Exception:
                    attempts.append(
                        {
                            "source": "flashalpha",
                            "stage": "requery",
                            "status": "uncertified",
                        }
                    )

        def cap_supporting_expiry(estimate):
            # Independent gamma must never outlive the still-required primary
            # underlying, walls and feed provenance.
            raw = context.get("provider_evidence") or {}
            stamps = [clock(context["as_of"])]
            for row in raw.values():
                stamps += [clock(row["as_of"])]
                stamps += [
                    clock(row["data_as_of"][key])
                    for key in ("equity_feed", "equity_options_feed")
                ]
            estimate["expires_at"] = min(
                clock(estimate["expires_at"]), min(stamps) + maximum_age
            ).isoformat()
            return estimate

        if self.chain_provider is not None:
            try:
                chain = await asyncio.to_thread(self.chain_provider.chain, symbol)
                estimate = await asyncio.to_thread(
                    reconstruct, chain, symbol=symbol, now=now()
                )
                estimate = cap_supporting_expiry(estimate)
                estimate["agreement"] = independent_agreement(
                    estimate, quarantined, context
                )
                validate_supporting(context, now())
                attempts.append(
                    {
                        "source": self.chain_provider.name,
                        "stage": "reconstruction",
                        "status": "certified",
                    }
                )
                proof = certificate(
                    "CERTIFIED_RECONSTRUCTED",
                    estimate,
                    symbol=symbol,
                    attempts=attempts,
                    quarantined=quarantined,
                )
                validate_certificate(proof, symbol=symbol, now=now())
                return proof, context, None
            except Exception as exc:
                attempts.append(
                    {
                        "source": self.chain_provider.name,
                        "stage": "reconstruction",
                        "status": "rejected",
                        "reason": str(exc)
                        if isinstance(exc, GammaQualityError)
                        else "independent_provider_unavailable",
                    }
                )
        else:
            attempts.append(
                {
                    "stage": "reconstruction",
                    "status": "unavailable",
                    "reason": "no_qualified_chain_provider",
                }
            )
        for provider in self.cross_providers:
            try:
                estimate = await asyncio.to_thread(provider.gamma_estimate, symbol)
                estimate = self._cross_estimate(
                    estimate, source=provider.name, symbol=symbol, now=now()
                )
                estimate = cap_supporting_expiry(estimate)
                estimate["agreement"] = independent_agreement(
                    estimate, quarantined, context
                )
                validate_supporting(context, now())
                attempts.append(
                    {
                        "source": provider.name,
                        "stage": "cross_provider",
                        "status": "certified",
                    }
                )
                proof = certificate(
                    "CERTIFIED_CROSS_PROVIDER",
                    estimate,
                    symbol=symbol,
                    attempts=attempts,
                    quarantined=quarantined,
                )
                return proof, context, None
            except Exception as exc:
                attempts.append(
                    {
                        "source": provider.name,
                        "stage": "cross_provider",
                        "status": "rejected",
                        "reason": str(exc)
                        if isinstance(exc, GammaQualityError)
                        else "independent_provider_unavailable",
                    }
                )
        if not self.cross_providers:
            attempts.append(
                {
                    "stage": "cross_provider",
                    "status": "unavailable",
                    "reason": "no_independent_provider_configured",
                }
            )
        return unavailable("no_independently_certified_gamma")

    @staticmethod
    def _cross_estimate(value, *, source, symbol, now):
        if (
            source == "flashalpha"
            or not isinstance(value, dict)
            or value.get("provider") != source
        ):
            raise GammaQualityError("independent_gex_provider_required")
        if (
            value.get("symbol") != symbol
            or value.get("status") != "available"
            or value.get("scope") != "full_chain"
            or value.get("sign_convention") != CONVENTION
        ):
            raise GammaQualityError("cross_provider_certificate_invalid")
        if (
            value.get("calculation_owner") != source
            or not isinstance(value.get("data_lineage"), list)
            or not value["data_lineage"]
            or any(
                not isinstance(item, str) or item.casefold() == "flashalpha"
                for item in value["data_lineage"]
            )
        ):
            raise GammaQualityError("cross_provider_independence_unverified")
        if not value.get("snapshot_id") or not value.get("methodology"):
            raise GammaQualityError("cross_provider_provenance_missing")
        stamps = [
            fresh(value.get(k), now, POLICY.maximum_age_seconds)
            for k in ("as_of", "underlying_as_of", "options_as_of")
        ]
        if (
            max(stamps) - min(stamps)
        ).total_seconds() > POLICY.maximum_timestamp_skew_seconds:
            raise GammaQualityError("chain_timestamp_misalignment")
        quality = value.get("quality") or {}
        if (
            number(quality.get("oi_coverage")) != 1
            or quality.get("unique_stable_root") is not True
            or not 0
            <= number(quality.get("maximum_stress_move_fraction"))
            <= POLICY.maximum_stress_move_fraction
        ):
            raise GammaQualityError("cross_provider_quality_insufficient")
        return {
            "provider": source,
            "gamma_flip": number(value.get("gamma_flip"), positive=True),
            "underlying_price": number(value.get("underlying_price"), positive=True),
            "as_of": min(stamps).isoformat(),
            "expires_at": (
                min(stamps) + timedelta(seconds=POLICY.maximum_age_seconds)
            ).isoformat(),
            "scope": "full_chain",
            "sign_convention": CONVENTION,
            "methodology": value["methodology"],
            "snapshot_id": value["snapshot_id"],
            "calculation_owner": source,
            "data_lineage": list(value["data_lineage"]),
            "quality": deepcopy(quality),
        }


def format_gamma_evidence(value):
    if not isinstance(value, dict):
        return None
    if value.get("state") not in CERTIFIED:
        return "Gamma: UNAVAILABLE / UNCERTIFIED — excluded from directional evidence"
    return f"Gamma: {value['gamma_flip']:.4f} — {value['state']} | Source: {value['provider']}"
