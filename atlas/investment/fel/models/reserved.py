"""Reserved ModelPlugin sockets — architecture now, appliance later.

``available()`` is False until the extra is installed *and* a named experiment
needs it. Callers must get ``blocked_unavailable``, never a silent substitute.
"""

from __future__ import annotations

from typing import Any

from atlas.investment.fel.contracts import (
    BlockedUnavailable,
    FeatureMatrix,
    FittedArtifact,
    Predictions,
)

RESERVED_MODEL_IDS: tuple[str, ...] = (
    "ols",
    "random_forest",
    "xgboost",
    "torch_mlp",
    "torch_sequence",
    "rl_policy",
)


class ReservedUnavailablePlugin:
    version = "reserved.0"
    tasks = frozenset({"regression", "classification", "ranking", "probability"})

    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id

    def available(self) -> bool:
        return False

    def fit(
        self,
        matrix: FeatureMatrix,
        target: list[Any] | None,
        params: dict[str, Any] | None = None,
    ) -> FittedArtifact:
        del matrix, target, params
        raise BlockedUnavailable(self.plugin_id, reason="available_false")

    def predict(self, artifact: FittedArtifact, matrix: FeatureMatrix) -> Predictions:
        del artifact, matrix
        raise BlockedUnavailable(self.plugin_id, reason="available_false")

    def explain(self, artifact: FittedArtifact, matrix: FeatureMatrix | None = None) -> dict[str, Any]:
        del artifact, matrix
        raise BlockedUnavailable(self.plugin_id, reason="available_false")


def reserved_model_plugins() -> list[ReservedUnavailablePlugin]:
    return [ReservedUnavailablePlugin(pid) for pid in RESERVED_MODEL_IDS]
