from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Any


class ReliabilityBand(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT_DATA = "insufficient_data"


class LearningAction(StrEnum):
    KEEP = "keep"
    REVIEW = "review"
    REDUCE_WEIGHT = "reduce_weight"
    INCREASE_WEIGHT = "increase_weight"
    DISABLE_EXPERIMENTALLY = "disable_experimentally"
    REQUIRE_MORE_DATA = "require_more_data"


@dataclass(frozen=True)
class OutcomeRecord:
    record_id: str
    symbol: str
    classification: str
    direction: str
    decision_conviction: float
    risk_score: float
    realized_r_multiple: float | None
    outcome_label: str
    engine_scores: dict[str, float | None]
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    created_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.record_id.strip():
            raise ValueError("record_id is required")
        if not self.symbol.strip():
            raise ValueError("symbol is required")
        if not 0 <= self.decision_conviction <= 1:
            raise ValueError("decision_conviction must be between 0 and 1")
        if not 0 <= self.risk_score <= 1:
            raise ValueError("risk_score must be between 0 and 1")
        if (
            self.realized_r_multiple is not None
            and not isfinite(float(self.realized_r_multiple))
        ):
            raise ValueError("realized_r_multiple must be finite when provided")
        if self.outcome_label not in {
            "win",
            "loss",
            "breakeven",
            "expired",
            "cancelled",
            "no_trade",
        }:
            raise ValueError("unsupported outcome_label")
        for engine_name, score in self.engine_scores.items():
            if not engine_name.strip():
                raise ValueError("engine score names cannot be blank")
            if score is not None and (
                not isfinite(float(score)) or not 0 <= float(score) <= 1
            ):
                raise ValueError(
                    f"engine score {engine_name} must be finite and between 0 and 1"
                )


@dataclass(frozen=True)
class LearningRequest:
    outcomes: tuple[OutcomeRecord, ...]
    minimum_samples: int = 20
    reliability_threshold_high: float = 0.70
    reliability_threshold_medium: float = 0.55
    maximum_calibration_error: float = 0.15
    maximum_loss_cluster_ratio: float = 0.40
    minimum_engine_coverage: int = 10
    calibration_bins: int = 5
    recency_half_life_days: float | None = None
    minimum_recommendation_confidence: float = 0.70

    def validate(self) -> None:
        if self.minimum_samples < 1:
            raise ValueError("minimum_samples must be positive")
        if not 0 <= self.reliability_threshold_medium <= 1:
            raise ValueError("reliability_threshold_medium must be between 0 and 1")
        if not 0 <= self.reliability_threshold_high <= 1:
            raise ValueError("reliability_threshold_high must be between 0 and 1")
        if self.reliability_threshold_high < self.reliability_threshold_medium:
            raise ValueError("high threshold must be >= medium threshold")
        if not 0 <= self.maximum_calibration_error <= 1:
            raise ValueError("maximum_calibration_error must be between 0 and 1")
        if not 0 <= self.maximum_loss_cluster_ratio <= 1:
            raise ValueError("maximum_loss_cluster_ratio must be between 0 and 1")
        if self.minimum_engine_coverage < 1:
            raise ValueError("minimum_engine_coverage must be positive")
        if self.calibration_bins < 2:
            raise ValueError("calibration_bins must be at least 2")
        if self.recency_half_life_days is not None and self.recency_half_life_days <= 0:
            raise ValueError("recency_half_life_days must be positive")
        if not 0 <= self.minimum_recommendation_confidence <= 1:
            raise ValueError("minimum_recommendation_confidence must be between 0 and 1")
        record_ids = [outcome.record_id for outcome in self.outcomes]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("duplicate outcome record_id values are not allowed")
        for outcome in self.outcomes:
            outcome.validate()


@dataclass(frozen=True)
class LearningRecommendation:
    engine_name: str
    action: LearningAction
    confidence: float
    observed_reliability: float | None
    sample_size: int
    reason: str
    proposed_weight_delta: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LearningResult:
    sample_size: int
    win_rate: float | None
    average_r_multiple: float | None
    calibration_error: float | None
    reliability_band: ReliabilityBand
    recommendations: tuple[LearningRecommendation, ...]
    failure_patterns: tuple[str, ...]
    strengths: tuple[str, ...]
    metrics: dict[str, Any]
    brier_score: float | None = None
    profit_factor: float | None = None
    win_rate_confidence_interval: tuple[float, float] | None = None
    calibration_buckets: tuple[dict[str, float | int], ...] = ()
    segments: dict[str, dict[str, float | int | None]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def may_mutate_production_configuration(self) -> bool:
        return False
