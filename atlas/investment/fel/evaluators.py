"""Evaluator plugins. Walk-forward is the required evaluator (FEL.3)."""

from __future__ import annotations

from typing import Any


class WalkForwardEvaluator:
    evaluator_id = "walk_forward"
    version = "fel.3"

    def available(self) -> bool:
        return True

    def evaluate(self, **kwargs: Any) -> dict[str, Any]:
        dataset = kwargs.get("dataset")
        candidate = kwargs.get("candidate")
        baseline = kwargs.get("baseline")
        if dataset is None or candidate is None or baseline is None:
            return {
                "evaluator_id": self.evaluator_id,
                "version": self.version,
                "result": "invalid",
                "reason": "missing_dataset_or_plugins",
            }
        from atlas.investment.fel.evaluation.walk_forward import evaluate_walk_forward

        return evaluate_walk_forward(
            dataset=dataset,
            candidate=candidate,
            baseline=baseline,
            costs=kwargs.get("costs"),
            min_train=int(kwargs.get("min_train") or 2),
        )
