"""FEL.3 — walk-forward runner, required baseline, no silent swap, no live promotion."""

from __future__ import annotations

from atlas.investment.fel import FeatureMatrix, FittedArtifact, Predictions, default_fel
from atlas.investment.fel.experiments.runner import run_experiment
from atlas.investment.fel.promotion import promotion_for


class _FeatureReader:
    """Hermetic plugin: score = named PIT feature (proves the runner seam)."""

    version = "test.1"
    tasks = frozenset({"regression"})

    def __init__(self, plugin_id: str, feature_id: str) -> None:
        self.plugin_id = plugin_id
        self.feature_id = feature_id

    def available(self) -> bool:
        return True

    def fit(self, matrix, target, params=None):
        return FittedArtifact(plugin_id=self.plugin_id, version=self.version)

    def predict(self, artifact, matrix: FeatureMatrix) -> Predictions:
        vals = [row.get(self.feature_id) for row in matrix.rows]
        return Predictions(values=vals)

    def explain(self, artifact, matrix=None):
        return {"plugin_id": self.plugin_id, "feature_id": self.feature_id}


def _dataset() -> dict:
    rows = []
    for i, day in enumerate(("2026-07-10", "2026-07-11", "2026-07-12", "2026-07-13")):
        for j, sym in enumerate(("AAA.NS", "BBB.NS")):
            vol_acc = 0.1 * (i + 1) + 0.05 * j
            rows.append(
                {
                    "as_of": day,
                    "symbol": sym,
                    "laboratory_id": "india_equity_learner",
                    "features": {
                        "volume_acceleration_20d": vol_acc,
                        "momentum": 0.01 * j,
                    },
                    "target": {"target_id": "fwd_ret_5d", "value": vol_acc - 0.001},
                }
            )
    return {
        "dataset_id": "test-pit",
        "laboratory_id": "india_equity_learner",
        "feature_ids": ["volume_acceleration_20d", "momentum"],
        "rows": rows,
    }


def test_runner_requires_baseline_and_does_not_swap_unavailable(tmp_path):
    fel = default_fel()
    missing = run_experiment(
        _dataset(),
        hypothesis_id="H-buy_name-vol-accel",
        candidate_plugin_id="torch_mlp",
        baseline_plugin_id="ranking_v1",
        data_dir=str(tmp_path),
        fel=fel,
    )
    assert missing["result"] == "blocked_unavailable"
    assert missing["requested"] == "torch_mlp"
    assert missing.get("ran") is None
    assert missing["promotion"] == "never"

    no_base = run_experiment(
        _dataset(),
        hypothesis_id="H-buy_name-vol-accel",
        candidate_plugin_id="ranking_v1",
        baseline_plugin_id="",
        fel=fel,
    )
    assert no_base["result"] == "invalid"
    assert no_base["reason"] == "baseline_required"


def test_walk_forward_compares_candidate_to_baseline(tmp_path):
    fel = default_fel()
    fel.models.register_plugin(_FeatureReader("vol_reader", "volume_acceleration_20d"))
    fel.models.register_plugin(_FeatureReader("mom_reader", "momentum"))
    out = run_experiment(
        _dataset(),
        hypothesis_id="H-buy_name-vol-accel",
        candidate_plugin_id="vol_reader",
        baseline_plugin_id="mom_reader",
        data_dir=str(tmp_path),
        costs={"round_trip": 0.001},
        fel=fel,
        feature_ids=["volume_acceleration_20d", "momentum"],
    )
    assert out["ran"] == {"candidate": "vol_reader", "baseline": "mom_reader"}
    assert out["baseline_plugin_id"] == "mom_reader"
    assert out["promotion"] != "live_control"
    assert out["result"] in {"improve", "no_significant", "worse", "invalid"}
    assert out["evaluation"]["n_folds"] >= 2
    saved = list(
        (tmp_path / "investment" / "fel" / "experiments" / "india_equity_learner").glob("*.json")
    )
    assert saved


def test_promotion_never_live_control():
    assert promotion_for(result="improve") == "candidate"
    assert promotion_for(result="worse") == "never"
