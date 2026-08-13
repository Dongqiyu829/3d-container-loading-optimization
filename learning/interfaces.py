"""Minimal framework-neutral protocols for future predictors and scorers."""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


@runtime_checkable
class InstancePredictor(Protocol):
    def predict(self, instance_features: Mapping[str, Any]) -> Mapping[str, Any]: ...


@runtime_checkable
class BudgetPredictor(Protocol):
    def predict_improvement_probability(
        self, instance_features: Mapping[str, Any], budget_seconds: float
    ) -> float: ...


@runtime_checkable
class BoxScorer(Protocol):
    def score_boxes(
        self, box_features: Sequence[Mapping[str, Any]]
    ) -> Sequence[float]: ...


@runtime_checkable
class CandidateScorer(Protocol):
    def score_candidate(
        self,
        instance_features: Mapping[str, Any],
        candidate_features: Mapping[str, Any],
    ) -> float: ...


def checked_probability(value: float) -> float:
    probability = float(value)
    if not 0.0 <= probability <= 1.0:
        raise ValueError("predicted probability must lie in [0, 1]")
    return probability
