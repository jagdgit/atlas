"""FEL.0 — contracts, four registries, wraps, reserved sockets, no silent swap."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from atlas.investment.fel import BlockedUnavailable, FeatureMatrix, default_fel
from atlas.investment.fel.models.reserved import RESERVED_MODEL_IDS


FEL_ROOT = Path(__file__).resolve().parents[1] / "atlas" / "investment" / "fel"
BANNED_IMPORTS = {"sklearn", "torch", "xgboost", "lightgbm"}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_fel0_core_does_not_import_ml_libraries():
    offenders: list[str] = []
    for path in FEL_ROOT.rglob("*.py"):
        hit = _imported_roots(path) & BANNED_IMPORTS
        if hit:
            offenders.append(f"{path.relative_to(FEL_ROOT)}:{sorted(hit)}")
    assert offenders == []


def test_four_registries_are_independent():
    fel = default_fel()
    assert fel.features.kind != fel.models.kind
    assert "sma" in fel.features
    assert "rules_sma_rsi" in fel.models
    assert "walk_forward" in fel.evaluators
    assert "fwd_ret_5d" in fel.targets
    # Adding a model must not require touching the feature registry.
    n_features = len(fel.features)
    n_models = len(fel.models)

    class FakeConstant:
        plugin_id = "fake_constant"
        version = "test.1"
        tasks = frozenset({"regression"})

        def available(self) -> bool:
            return True

        def fit(self, matrix, target, params=None):
            from atlas.investment.fel.contracts import FittedArtifact

            return FittedArtifact(plugin_id=self.plugin_id, version=self.version)

        def predict(self, artifact, matrix):
            from atlas.investment.fel.contracts import Predictions

            return Predictions(values=[0.0 for _ in matrix.rows])

        def explain(self, artifact, matrix=None):
            return {"plugin_id": self.plugin_id, "kind": "fake"}

    fel.models.register_plugin(FakeConstant())
    assert len(fel.features) == n_features
    assert len(fel.models) == n_models + 1
    plugin, err = fel.models.resolve("fake_constant")
    assert err is None and plugin is not None
    art = plugin.fit(FeatureMatrix(rows=[{"x": 1}]), [0.0])
    pred = plugin.predict(art, FeatureMatrix(rows=[{"x": 1}, {"x": 2}]))
    assert pred.values == [0.0, 0.0]


def test_wraps_call_existing_atlas_methods():
    fel = default_fel()
    closes = [float(i) for i in range(1, 40)]

    sma = fel.features.require("sma")
    rsi = fel.features.require("rsi")
    assert sma.compute({"closes": closes, "period": 20}) == sum(closes[-20:]) / 20
    assert rsi.compute({"closes": closes[:5]}) is None  # missing stays missing

    rules = fel.models.require("rules_sma_rsi")
    art = rules.fit(FeatureMatrix(), None)
    out = rules.predict(
        art,
        FeatureMatrix(
            rows=[
                {
                    "symbol": "AAA",
                    "closes": closes,
                    "price": closes[-1],
                    "cash": 100_000,
                    "equity": 100_000,
                }
            ]
        ),
    )
    assert out.values and out.values[0]["action"] in {"buy", "sell", "hold"}
    assert out.extras.get("wrap") == "StrategyDecisionRule"

    er = fel.models.require("er_prototype_v1")
    er_out = er.predict(
        er.fit(FeatureMatrix(), None),
        FeatureMatrix(rows=[{"score": 0.7, "pct_move": 0.04}]),
    )
    assert er_out.extras.get("er_model") == "prototype_v1"
    assert er_out.values[0] is not None

    rank = fel.models.require("ranking_v1")
    rank_out = rank.predict(
        rank.fit(FeatureMatrix(), None),
        FeatureMatrix(rows=[{"symbol": "AAA"}, {"symbol": "BBB"}]),
    )
    assert len(rank_out.values) == 2


def test_reserved_plugins_are_unavailable_no_silent_swap():
    fel = default_fel()
    ranking = fel.models.require("ranking_v1")
    for pid in RESERVED_MODEL_IDS:
        rec = fel.models.get(pid)
        assert rec is not None, pid
        assert rec.plugin.available() is False
        plugin, err = fel.models.resolve(pid)
        assert plugin is None
        assert err is not None
        assert err["result"] == "blocked_unavailable"
        assert err["requested"] == pid
        assert err["ran"] is None
        with pytest.raises(BlockedUnavailable):
            fel.models.require(pid)
    # The available wrap is still ranking_v1 — requesting torch must not run it.
    assert ranking.plugin_id == "ranking_v1"


def test_plugins_are_not_deleted_on_retire():
    fel = default_fel()
    assert fel.models.retire("ranking_v1")
    rec = fel.models.get("ranking_v1")
    assert rec is not None
    assert rec.status == "retired"
    with pytest.raises(BlockedUnavailable):
        fel.models.require("ranking_v1")


def test_volume_acceleration_is_candidate_not_promoted():
    fel = default_fel()
    rec = fel.features.get("volume_acceleration_20d")
    assert rec is not None
    assert rec.plugin.status == "candidate"
    assert rec.extra.get("hypothesis_id") == "H-buy_name-vol-accel"
    assert rec.plugin.compute({"volumes": [1] * 10}) is None
    acc = rec.plugin.compute({"volumes": [10.0] * 16 + [40.0] * 4})
    assert acc is not None and acc > 0


def test_walk_forward_honest_until_fel3():
    fel = default_fel()
    ev = fel.evaluators.require("walk_forward")
    out = ev.evaluate(predictions=[], targets=[])
    assert out["result"] == "invalid"
    assert out["reason"] == "missing_dataset_or_plugins"
