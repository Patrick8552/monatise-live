from __future__ import annotations

from collections import defaultdict
from datetime import timezone
from math import sqrt
from statistics import mean

from monatise.engines.intelligence_learning.models import (
    LearningAction,
    LearningRecommendation,
    LearningRequest,
    LearningResult,
    ReliabilityBand,
)


class IntelligenceLearningEngine:
    """Evaluates historical performance and produces review recommendations.

    The engine never rewrites production weights, thresholds, or configuration
    automatically. Recommendations require explicit human review.
    """

    def assess(self, request: LearningRequest) -> LearningResult:
        request.validate()
        outcomes = list(request.outcomes)
        tradable = [
            item for item in outcomes
            if item.outcome_label in {"win", "loss", "breakeven"}
        ]

        if len(tradable) < request.minimum_samples:
            return LearningResult(
                sample_size=len(outcomes),
                win_rate=None,
                average_r_multiple=None,
                calibration_error=None,
                reliability_band=ReliabilityBand.INSUFFICIENT_DATA,
                recommendations=(
                    LearningRecommendation(
                        engine_name="global",
                        action=LearningAction.REQUIRE_MORE_DATA,
                        confidence=1.0,
                        observed_reliability=None,
                        sample_size=len(tradable),
                        reason=(
                            f"minimum {request.minimum_samples} tradable samples required; "
                            f"received {len(tradable)}"
                        ),
                    ),
                ),
                failure_patterns=(),
                strengths=(),
                metrics={"tradable_sample_size": float(len(tradable))},
                metadata={
                    "engine_scope": "crypto_only",
                    "automatic_mutation": False,
                    "human_review_required": True,
                    "production_configuration_locked": True,
                },
            )

        wins = [item for item in tradable if item.outcome_label == "win"]
        losses = [item for item in tradable if item.outcome_label == "loss"]
        weights = self._sample_weights(tradable, request.recency_half_life_days)

        total_weight = sum(weights.values())
        win_rate = (
            sum(weights[item.record_id] for item in wins) / total_weight
            if total_weight > 0
            else None
        )

        realized = [
            item.realized_r_multiple
            for item in tradable
            if item.realized_r_multiple is not None
        ]
        realized_weight = sum(
            weights[item.record_id]
            for item in tradable
            if item.realized_r_multiple is not None
        )
        average_r = (
            sum(
                float(item.realized_r_multiple) * weights[item.record_id]
                for item in tradable
                if item.realized_r_multiple is not None
            ) / realized_weight
            if realized_weight > 0
            else None
        )

        calibration_error = self._calibration_error(tradable, weights)
        brier_score = self._brier_score(tradable, weights)
        calibration_buckets = self._calibration_buckets(
            tradable,
            request.calibration_bins,
        )
        profit_factor = self._profit_factor(realized)
        win_rate_interval = self._wilson_interval(len(wins), len(tradable))
        reliability_band = self._reliability_band(
            win_rate=win_rate,
            average_r=average_r,
            calibration_error=calibration_error,
            request=request,
        )

        recommendations = self._engine_recommendations(
            outcomes=tradable,
            request=request,
        )
        failure_patterns = self._failure_patterns(
            outcomes=outcomes,
            request=request,
        )
        if (
            calibration_error is not None
            and calibration_error > request.maximum_calibration_error
        ):
            failure_patterns.append(
                f"decision calibration error {calibration_error:.3f} exceeds "
                f"maximum {request.maximum_calibration_error:.3f}"
            )
        strengths = self._strengths(
            outcomes=tradable,
            recommendations=recommendations,
        )

        return LearningResult(
            sample_size=len(outcomes),
            win_rate=round(win_rate, 4) if win_rate is not None else None,
            average_r_multiple=(
                round(average_r, 4) if average_r is not None else None
            ),
            calibration_error=(
                round(calibration_error, 4)
                if calibration_error is not None
                else None
            ),
            brier_score=(round(brier_score, 4) if brier_score is not None else None),
            profit_factor=(
                round(profit_factor, 4) if profit_factor is not None else None
            ),
            win_rate_confidence_interval=(
                tuple(round(value, 4) for value in win_rate_interval)
                if win_rate_interval is not None
                else None
            ),
            calibration_buckets=tuple(calibration_buckets),
            segments=self._segments(tradable),
            reliability_band=reliability_band,
            recommendations=tuple(recommendations),
            failure_patterns=tuple(failure_patterns),
            strengths=tuple(strengths),
            metrics={
                "tradable_sample_size": float(len(tradable)),
                "win_count": float(len(wins)),
                "loss_count": float(len(losses)),
                "breakeven_count": float(
                    sum(
                        item.outcome_label == "breakeven"
                        for item in tradable
                    )
                ),
                "expired_count": float(
                    sum(item.outcome_label == "expired" for item in outcomes)
                ),
                "cancelled_count": float(
                    sum(item.outcome_label == "cancelled" for item in outcomes)
                ),
                "effective_sample_weight": round(total_weight, 4),
            },
            metadata={
                "engine_scope": "crypto_only",
                "automatic_mutation": False,
                "human_review_required": True,
                "production_configuration_locked": True,
                "recency_weighting_enabled": request.recency_half_life_days is not None,
                "recommendations_are_proposals_only": True,
            },
        )

    @staticmethod
    def _calibration_error(outcomes, weights) -> float | None:
        binary = [
            (
                item.decision_conviction,
                1.0 if item.outcome_label == "win" else 0.0,
            )
            for item in outcomes
            if item.outcome_label in {"win", "loss"}
        ]
        if not binary:
            return None
        binary_ids = [
            item.record_id
            for item in outcomes
            if item.outcome_label in {"win", "loss"}
        ]
        total_weight = sum(weights[item_id] for item_id in binary_ids)
        if total_weight <= 0:
            return None
        return sum(
            abs(confidence - result) * weights[item_id]
            for (confidence, result), item_id in zip(binary, binary_ids)
        ) / total_weight

    @staticmethod
    def _sample_weights(outcomes, half_life_days: float | None) -> dict[str, float]:
        if half_life_days is None:
            return {item.record_id: 1.0 for item in outcomes}
        dated = [item.created_at for item in outcomes if item.created_at is not None]
        if not dated:
            return {item.record_id: 1.0 for item in outcomes}
        latest = max(
            value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
            for value in dated
        )
        weights: dict[str, float] = {}
        for item in outcomes:
            if item.created_at is None:
                weights[item.record_id] = 1.0
                continue
            created = (
                item.created_at.replace(tzinfo=timezone.utc)
                if item.created_at.tzinfo is None
                else item.created_at
            )
            age_days = max(0.0, (latest - created).total_seconds() / 86_400)
            weights[item.record_id] = 2.0 ** (-age_days / half_life_days)
        return weights

    @staticmethod
    def _brier_score(outcomes, weights) -> float | None:
        binary = [
            item for item in outcomes
            if item.outcome_label in {"win", "loss"}
        ]
        total_weight = sum(weights[item.record_id] for item in binary)
        if total_weight <= 0:
            return None
        return sum(
            weights[item.record_id]
            * (item.decision_conviction - (1.0 if item.outcome_label == "win" else 0.0)) ** 2
            for item in binary
        ) / total_weight

    @staticmethod
    def _calibration_buckets(outcomes, bin_count: int) -> list[dict[str, float | int]]:
        binary = [
            item for item in outcomes
            if item.outcome_label in {"win", "loss"}
        ]
        buckets: list[dict[str, float | int]] = []
        for index in range(bin_count):
            lower = index / bin_count
            upper = (index + 1) / bin_count
            members = [
                item for item in binary
                if lower <= item.decision_conviction < upper
                or (index == bin_count - 1 and item.decision_conviction == 1.0)
            ]
            if not members:
                continue
            buckets.append({
                "lower": round(lower, 4),
                "upper": round(upper, 4),
                "sample_size": len(members),
                "mean_confidence": round(mean(item.decision_conviction for item in members), 4),
                "observed_win_rate": round(
                    sum(item.outcome_label == "win" for item in members) / len(members),
                    4,
                ),
            })
        return buckets

    @staticmethod
    def _profit_factor(realized: list[float]) -> float | None:
        gains = sum(value for value in realized if value > 0)
        losses = abs(sum(value for value in realized if value < 0))
        if losses == 0:
            return None if gains == 0 else float("inf")
        return gains / losses

    @staticmethod
    def _wilson_interval(wins: int, samples: int) -> tuple[float, float] | None:
        if samples == 0:
            return None
        z = 1.959963984540054
        proportion = wins / samples
        denominator = 1 + z * z / samples
        centre = (proportion + z * z / (2 * samples)) / denominator
        margin = (
            z
            * sqrt(proportion * (1 - proportion) / samples + z * z / (4 * samples * samples))
            / denominator
        )
        return max(0.0, centre - margin), min(1.0, centre + margin)

    @staticmethod
    def _segments(outcomes) -> dict[str, dict[str, float | int | None]]:
        groups: dict[str, list] = defaultdict(list)
        for item in outcomes:
            groups[f"symbol:{item.symbol.upper()}"].append(item)
            groups[f"classification:{item.classification}"].append(item)
            groups[f"direction:{item.direction}"].append(item)
        result: dict[str, dict[str, float | int | None]] = {}
        for name, members in sorted(groups.items()):
            realized = [
                item.realized_r_multiple
                for item in members
                if item.realized_r_multiple is not None
            ]
            result[name] = {
                "sample_size": len(members),
                "win_rate": round(
                    sum(item.outcome_label == "win" for item in members) / len(members),
                    4,
                ),
                "average_r_multiple": (
                    round(mean(realized), 4) if realized else None
                ),
            }
        return result

    @staticmethod
    def _reliability_band(
        *,
        win_rate: float | None,
        average_r: float | None,
        calibration_error: float | None,
        request: LearningRequest,
    ) -> ReliabilityBand:
        if win_rate is None or average_r is None or calibration_error is None:
            return ReliabilityBand.INSUFFICIENT_DATA

        composite = (
            win_rate * 0.45
            + max(0.0, min(1.0, (average_r + 1.0) / 3.0)) * 0.35
            + max(0.0, 1.0 - calibration_error) * 0.20
        )

        if calibration_error > request.maximum_calibration_error:
            return ReliabilityBand.LOW
        if composite >= request.reliability_threshold_high:
            return ReliabilityBand.HIGH
        if composite >= request.reliability_threshold_medium:
            return ReliabilityBand.MEDIUM
        return ReliabilityBand.LOW

    def _engine_recommendations(
        self,
        *,
        outcomes,
        request: LearningRequest,
    ) -> list[LearningRecommendation]:
        engine_samples: dict[str, list[tuple[float, bool]]] = defaultdict(list)

        for outcome in outcomes:
            success = outcome.outcome_label == "win"
            for engine_name, score in outcome.engine_scores.items():
                if score is None:
                    continue
                engine_samples[engine_name].append((score, success))

        recommendations: list[LearningRecommendation] = []

        for engine_name, samples in sorted(engine_samples.items()):
            if len(samples) < request.minimum_engine_coverage:
                recommendations.append(
                    LearningRecommendation(
                        engine_name=engine_name,
                        action=LearningAction.REQUIRE_MORE_DATA,
                        confidence=0.90,
                        observed_reliability=None,
                        sample_size=len(samples),
                        reason="insufficient engine-specific coverage",
                    )
                )
                continue

            weighted_success = sum(
                score * (1.0 if success else 0.0)
                for score, success in samples
            )
            total_score = sum(score for score, _ in samples)
            reliability = (
                weighted_success / total_score
                if total_score > 0
                else 0.0
            )

            high_score_losses = sum(
                score >= 0.70 and not success
                for score, success in samples
            )
            high_score_count = sum(score >= 0.70 for score, _ in samples)
            high_score_loss_ratio = (
                high_score_losses / high_score_count
                if high_score_count > 0
                else 0.0
            )

            if high_score_loss_ratio >= request.maximum_loss_cluster_ratio:
                action = LearningAction.REDUCE_WEIGHT
                delta = -0.10
                reason = (
                    "high-confidence engine signals cluster in losing outcomes"
                )
                confidence = min(1.0, 0.60 + high_score_loss_ratio * 0.40)
            elif reliability >= request.reliability_threshold_high:
                action = LearningAction.INCREASE_WEIGHT
                delta = 0.05
                reason = "engine reliability is consistently strong"
                confidence = min(1.0, 0.60 + reliability * 0.35)
            elif reliability >= request.reliability_threshold_medium:
                action = LearningAction.KEEP
                delta = 0.0
                reason = "engine reliability is acceptable"
                confidence = 0.70
            else:
                action = LearningAction.REVIEW
                delta = None
                reason = "engine reliability is below target"
                confidence = 0.75

            if (
                action in {LearningAction.REDUCE_WEIGHT, LearningAction.INCREASE_WEIGHT}
                and confidence < request.minimum_recommendation_confidence
            ):
                action = LearningAction.REVIEW
                delta = None
                reason = "statistical confidence is too low for a weight-change proposal"

            recommendations.append(
                LearningRecommendation(
                    engine_name=engine_name,
                    action=action,
                    confidence=round(confidence, 4),
                    observed_reliability=round(reliability, 4),
                    sample_size=len(samples),
                    reason=reason,
                    proposed_weight_delta=delta,
                    metadata={
                        "high_score_loss_ratio": round(
                            high_score_loss_ratio, 4
                        )
                    },
                )
            )

        return recommendations

    @staticmethod
    def _failure_patterns(
        *,
        outcomes,
        request: LearningRequest,
    ) -> list[str]:
        patterns: list[str] = []

        losses = [
            item for item in outcomes
            if item.outcome_label == "loss"
        ]
        if not losses:
            return patterns

        classifications: dict[str, int] = defaultdict(int)
        directions: dict[str, int] = defaultdict(int)
        warning_counts: dict[str, int] = defaultdict(int)

        for item in losses:
            classifications[item.classification] += 1
            directions[item.direction] += 1
            for warning in item.warnings:
                warning_counts[warning] += 1

        loss_count = len(losses)

        for classification, count in classifications.items():
            ratio = count / loss_count
            if ratio >= request.maximum_loss_cluster_ratio:
                patterns.append(
                    f"losses cluster in {classification} setups ({ratio:.1%})"
                )

        for direction, count in directions.items():
            ratio = count / loss_count
            if ratio >= request.maximum_loss_cluster_ratio:
                patterns.append(
                    f"losses cluster in {direction} direction ({ratio:.1%})"
                )

        for warning, count in warning_counts.items():
            ratio = count / loss_count
            if ratio >= request.maximum_loss_cluster_ratio:
                patterns.append(
                    f"warning '{warning}' recurs in losses ({ratio:.1%})"
                )

        high_conviction_losses = sum(
            item.decision_conviction >= 0.75
            for item in losses
        )
        if high_conviction_losses / loss_count >= request.maximum_loss_cluster_ratio:
            patterns.append(
                "high-conviction decisions are overrepresented in losses"
            )

        return patterns

    @staticmethod
    def _strengths(
        *,
        outcomes,
        recommendations,
    ) -> list[str]:
        strengths: list[str] = []

        for recommendation in recommendations:
            if recommendation.action is LearningAction.INCREASE_WEIGHT:
                strengths.append(
                    f"{recommendation.engine_name} shows strong reliability"
                )

        winners = [
            item for item in outcomes
            if item.outcome_label == "win"
        ]
        if winners:
            average_conviction = mean(
                item.decision_conviction for item in winners
            )
            if average_conviction >= 0.70:
                strengths.append(
                    "winning outcomes generally carry strong conviction"
                )

        return strengths
