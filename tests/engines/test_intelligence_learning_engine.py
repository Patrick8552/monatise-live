from datetime import datetime, timedelta, timezone

import pytest

from monatise.engines.intelligence_learning.engine import (
    IntelligenceLearningEngine,
)
from monatise.engines.intelligence_learning.models import (
    LearningAction,
    LearningRequest,
    OutcomeRecord,
    ReliabilityBand,
)


NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)


def outcome(
    index: int,
    label: str,
    conviction: float,
    r_multiple: float,
    structure_score: float,
    order_flow_score: float,
) -> OutcomeRecord:
    return OutcomeRecord(
        record_id=str(index),
        symbol="BTCUSDT",
        classification="trend",
        direction="long",
        decision_conviction=conviction,
        risk_score=0.80,
        realized_r_multiple=r_multiple,
        outcome_label=label,
        engine_scores={
            "market_structure": structure_score,
            "order_flow": order_flow_score,
        },
        created_at=NOW,
    )


def test_insufficient_data_requires_more_samples() -> None:
    result = IntelligenceLearningEngine().assess(
        LearningRequest(
            outcomes=(
                outcome(1, "win", 0.8, 2.0, 0.9, 0.8),
            ),
            minimum_samples=20,
        )
    )

    assert result.reliability_band is ReliabilityBand.INSUFFICIENT_DATA
    assert result.recommendations[0].action is LearningAction.REQUIRE_MORE_DATA
    assert result.metadata["production_configuration_locked"] is True


def test_learning_engine_calculates_performance() -> None:
    outcomes = tuple(
        outcome(
            index,
            "win" if index % 3 != 0 else "loss",
            0.75,
            1.5 if index % 3 != 0 else -1.0,
            0.80,
            0.75,
        )
        for index in range(30)
    )

    result = IntelligenceLearningEngine().assess(
        LearningRequest(
            outcomes=outcomes,
            minimum_samples=20,
            minimum_engine_coverage=10,
        )
    )

    assert result.win_rate is not None
    assert result.average_r_multiple is not None
    assert result.calibration_error is not None
    assert result.sample_size == 30


def test_recommendations_do_not_mutate_production() -> None:
    outcomes = tuple(
        outcome(
            index,
            "loss" if index % 2 == 0 else "win",
            0.80,
            -1.0 if index % 2 == 0 else 1.0,
            0.90,
            0.85,
        )
        for index in range(30)
    )

    result = IntelligenceLearningEngine().assess(
        LearningRequest(
            outcomes=outcomes,
            minimum_samples=20,
            minimum_engine_coverage=10,
        )
    )

    assert result.may_mutate_production_configuration is False
    assert result.metadata["automatic_mutation"] is False
    assert result.metadata["human_review_required"] is True


def test_high_confidence_loss_cluster_can_reduce_weight() -> None:
    outcomes = tuple(
        outcome(
            index,
            "loss" if index < 18 else "win",
            0.85,
            -1.0 if index < 18 else 1.5,
            0.90,
            0.90,
        )
        for index in range(30)
    )

    result = IntelligenceLearningEngine().assess(
        LearningRequest(
            outcomes=outcomes,
            minimum_samples=20,
            minimum_engine_coverage=10,
            maximum_loss_cluster_ratio=0.40,
        )
    )

    assert any(
        recommendation.action is LearningAction.REDUCE_WEIGHT
        for recommendation in result.recommendations
    )


def test_non_tradable_records_do_not_satisfy_minimum_sample() -> None:
    outcomes = tuple(
        outcome(index, "expired", 0.7, 0.0, 0.5, 0.5)
        for index in range(25)
    )

    result = IntelligenceLearningEngine().assess(
        LearningRequest(outcomes=outcomes, minimum_samples=20)
    )

    assert result.reliability_band is ReliabilityBand.INSUFFICIENT_DATA
    assert result.metrics["tradable_sample_size"] == 0.0


def test_duplicate_records_are_rejected() -> None:
    duplicate = outcome(1, "win", 0.8, 1.0, 0.8, 0.8)

    with pytest.raises(ValueError, match="duplicate outcome"):
        IntelligenceLearningEngine().assess(
            LearningRequest(outcomes=(duplicate, duplicate), minimum_samples=1)
        )


def test_engine_scores_must_be_finite_probabilities() -> None:
    invalid = OutcomeRecord(
        **{
            **outcome(1, "win", 0.8, 1.0, 0.8, 0.8).__dict__,
            "engine_scores": {"market_structure": float("nan")},
        }
    )

    with pytest.raises(ValueError, match="finite and between 0 and 1"):
        IntelligenceLearningEngine().assess(
            LearningRequest(outcomes=(invalid,), minimum_samples=1)
        )


def test_upgrade_exposes_calibration_uncertainty_and_segments() -> None:
    outcomes = tuple(
        OutcomeRecord(
            **{
                **outcome(
                    index,
                    "win" if index % 2 else "loss",
                    0.8,
                    1.5 if index % 2 else -1.0,
                    0.8,
                    0.7,
                ).__dict__,
                "created_at": NOW - timedelta(days=30 - index),
            }
        )
        for index in range(30)
    )

    result = IntelligenceLearningEngine().assess(
        LearningRequest(
            outcomes=outcomes,
            minimum_samples=20,
            minimum_engine_coverage=10,
            recency_half_life_days=14,
        )
    )

    assert result.brier_score is not None
    assert result.profit_factor is not None
    assert result.win_rate_confidence_interval is not None
    assert result.calibration_buckets
    assert "classification:trend" in result.segments
    assert result.metadata["recency_weighting_enabled"] is True
