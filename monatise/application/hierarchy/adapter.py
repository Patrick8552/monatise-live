from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from monatise.application.hierarchy.models import (
    DataQualityState,
    EvidenceBundle,
    FinalOutcome,
    SetupState,
    StrategicState,
    TriggerState,
)


@dataclass(frozen=True)
class HierarchicalAnalysisRequest:
    symbol: str
    evidence_bundle: EvidenceBundle
    requested_at: datetime
    shadow: bool = True
    execution_enabled: bool = False

    def __post_init__(self) -> None:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("requested_at must be timezone-aware")
        if self.symbol.strip().upper() != self.evidence_bundle.symbol:
            raise ValueError("request and bundle symbols differ")
        if not self.shadow or self.execution_enabled:
            raise ValueError("hierarchical analysis is shadow-only")


@dataclass(frozen=True)
class HierarchyValidation:
    outcome: FinalOutcome
    eligible_for_shadow_decision: bool
    reasons: tuple[str, ...]
    evidence_bundle_id: str


class CanonicalEvidenceAdapter:
    """Validates hierarchy evidence before any existing engine request is constructed."""

    def validate(self, request: HierarchicalAnalysisRequest) -> HierarchyValidation:
        bundle = request.evidence_bundle
        contexts = (bundle.macro_context, bundle.regime_4h, bundle.strategy_1h, bundle.setup_15m, bundle.trigger_5m)
        reasons: list[str] = []
        if any(context.identity.strategy_version != bundle.strategy_version for context in contexts):
            reasons.append("strategy_version_mismatch")
        if any(request.requested_at >= context.expires_at for context in contexts) or request.requested_at >= bundle.risk_inputs.expires_at:
            reasons.append("evidence_expired")
        if any(context.data_quality in {DataQualityState.UNAVAILABLE, DataQualityState.REVISED} for context in contexts):
            reasons.append("data_unavailable_or_revised")
        # The 4h regime is advisory for altcoin Signal Core publication. The
        # 1h structure remains directional authority and may still block.
        if bundle.strategy_1h.state is StrategicState.BLOCKED:
            reasons.append("strategic_context_blocked")
        if bundle.setup_15m.state is not SetupState.SETUP_CONFIRMED:
            reasons.append("setup_not_confirmed")
        if bundle.trigger_5m.state is not TriggerState.TRIGGER_CONFIRMED:
            reasons.append("trigger_not_confirmed")
        if bundle.risk_inputs.calculated_reward_to_risk < bundle.risk_inputs.minimum_reward_to_risk:
            reasons.append("reward_to_risk_below_minimum")

        if "evidence_expired" in reasons:
            outcome = FinalOutcome.EXPIRED
        elif "data_unavailable_or_revised" in reasons:
            outcome = FinalOutcome.DATA_UNAVAILABLE
        elif "strategy_version_mismatch" in reasons:
            outcome = FinalOutcome.STALE_CONTEXT
        elif reasons:
            outcome = FinalOutcome.BLOCKED
        else:
            outcome = FinalOutcome.VALID_SIGNAL
        return HierarchyValidation(outcome, not reasons, tuple(reasons), bundle.bundle_id)

    @staticmethod
    def risk_request_values(bundle: EvidenceBundle) -> dict[str, float | datetime]:
        """Bridge values for the existing RiskRequest without changing its contract."""
        risk = bundle.risk_inputs
        return {
            "proposed_entry": risk.reference_entry,
            "proposed_invalidation": risk.final_stop,
            "proposed_target": risk.target_liquidity,
            "minimum_reward_risk": risk.minimum_reward_to_risk,
            "signal_expires_at": risk.expires_at,
        }
