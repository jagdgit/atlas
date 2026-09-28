"""Deterministic linear feature-score plugins for FEL experiments.

Score = equal-weight mean of cross-sectional ranks of named PIT features.
Missing feature → missing score (never invent 0). No sklearn.
"""

from __future__ import annotations

from typing import Any

from atlas.investment.fel.contracts import FeatureMatrix, FittedArtifact, Predictions


def _rank_unit(values: list[Any]) -> list[float | None]:
    """Map finite values to [0, 1] by rank; None stays None."""
    indexed: list[tuple[int, float]] = []
    for i, v in enumerate(values):
        try:
            if v is None:
                continue
            indexed.append((i, float(v)))
        except (TypeError, ValueError):
            continue
    out: list[float | None] = [None] * len(values)
    if not indexed:
        return out
    indexed.sort(key=lambda it: it[1])
    n = len(indexed)
    if n == 1:
        out[indexed[0][0]] = 0.5
        return out
    for rank, (i, _) in enumerate(indexed):
        out[i] = rank / (n - 1)
    return out


class LinearFeatureScorePlugin:
    """Baseline/candidate seam: same plugin class, different ``feature_ids``."""

    version = "fel.e001.1"
    tasks = frozenset({"ranking", "regression"})

    def __init__(
        self,
        plugin_id: str,
        feature_ids: list[str],
        *,
        weights: dict[str, float] | None = None,
    ) -> None:
        if not plugin_id:
            raise ValueError("plugin_id required")
        if not feature_ids:
            raise ValueError("feature_ids required")
        self.plugin_id = plugin_id
        self.feature_ids = list(feature_ids)
        self.weights = {fid: float((weights or {}).get(fid, 1.0)) for fid in self.feature_ids}

    def available(self) -> bool:
        return True

    def fit(
        self,
        matrix: FeatureMatrix,
        target: list[Any] | None,
        params: dict[str, Any] | None = None,
    ) -> FittedArtifact:
        del matrix, target
        p = dict(params or {})
        p.setdefault("feature_ids", list(self.feature_ids))
        p.setdefault("weights", dict(self.weights))
        return FittedArtifact(
            plugin_id=self.plugin_id,
            version=self.version,
            params=p,
            payload={"kind": "linear_feature_score"},
        )

    def predict(self, artifact: FittedArtifact, matrix: FeatureMatrix) -> Predictions:
        if artifact.plugin_id != self.plugin_id:
            raise ValueError(
                f"artifact {artifact.plugin_id} != plugin {self.plugin_id} "
                "(no silent substitution)"
            )
        ids = list(artifact.params.get("feature_ids") or self.feature_ids)
        weights = dict(artifact.params.get("weights") or self.weights)
        cols = {fid: [row.get(fid) for row in matrix.rows] for fid in ids}
        ranks = {fid: _rank_unit(vals) for fid, vals in cols.items()}
        scores: list[float | None] = []
        for i in range(len(matrix.rows)):
            parts: list[float] = []
            wsum = 0.0
            missing = False
            for fid in ids:
                r = ranks[fid][i]
                if r is None:
                    missing = True
                    break
                w = float(weights.get(fid, 1.0))
                parts.append(r * w)
                wsum += w
            if missing or wsum <= 0:
                scores.append(None)
            else:
                scores.append(sum(parts) / wsum)
        return Predictions(
            values=scores,
            extras={"feature_ids": ids, "method": "cross_section_rank_mean"},
        )

    def explain(self, artifact: FittedArtifact, matrix: FeatureMatrix | None = None) -> dict[str, Any]:
        del matrix
        return {
            "plugin_id": artifact.plugin_id,
            "kind": "linear_feature_score",
            "feature_ids": artifact.params.get("feature_ids") or self.feature_ids,
            "weights": artifact.params.get("weights") or self.weights,
        }


BASELINE_MOM_RS_ID = "lin_mom_rs"
CANDIDATE_MOM_RS_VOL_ID = "lin_mom_rs_volaccel"

BASELINE_FEATURES = ("momentum", "rs_vs_benchmark")
CANDIDATE_FEATURES = ("momentum", "rs_vs_benchmark", "volume_acceleration_20d")


def baseline_mom_rs_plugin() -> LinearFeatureScorePlugin:
    return LinearFeatureScorePlugin(BASELINE_MOM_RS_ID, list(BASELINE_FEATURES))


def candidate_mom_rs_vol_plugin() -> LinearFeatureScorePlugin:
    return LinearFeatureScorePlugin(CANDIDATE_MOM_RS_VOL_ID, list(CANDIDATE_FEATURES))
