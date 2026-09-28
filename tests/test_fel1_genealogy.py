"""FEL.1 — feature genealogy persist, observation vs decision eligibility."""

from __future__ import annotations

from atlas.investment.fel import default_fel
from atlas.investment.fel.features.store import (
    genealogy_from_record,
    is_decision_eligible,
    is_lesson_eligible,
    is_observation_eligible,
    overlay_persisted,
    persist_feature_registry,
    record_evaluation,
)


def test_volume_acceleration_not_decision_eligible():
    fel = default_fel()
    vol = fel.features.get("volume_acceleration_20d")
    sma = fel.features.get("sma")
    assert vol is not None and sma is not None
    assert is_observation_eligible(vol)
    assert not is_decision_eligible(vol)
    assert is_lesson_eligible(vol)
    assert is_decision_eligible(sma)
    gene = genealogy_from_record(vol)
    assert gene.hypothesis_id == "H-buy_name-vol-accel"
    assert "volume_5d" in gene.derived_from
    assert gene.origin == "hypothesis"
    assert gene.decision_eligible is False
    assert gene.lesson_eligible is True


def test_persist_and_overlay_preserves_belief_shaped_result(tmp_path):
    fel = default_fel()
    n = persist_feature_registry(tmp_path, fel.features)
    assert n >= 5
    row = record_evaluation(
        tmp_path,
        fel.features,
        "volume_acceleration_20d",
        result="conditional",
        not_useful_for=["sell_incumbent"],
        tested_model="ranking_v1",
        last_evaluated="2026-09-03",
        status="candidate",
    )
    assert row is not None
    assert row["result"] == "conditional"
    assert row["decision_eligible"] is False

    reloaded = default_fel(str(tmp_path))
    rec = reloaded.features.get("volume_acceleration_20d")
    assert rec is not None
    assert rec.extra.get("result") == "conditional"
    assert rec.extra.get("not_useful_for") == ["sell_incumbent"]
    assert "ranking_v1" in rec.extra.get("tested_models")
    assert is_decision_eligible(rec) is False


def test_retired_feature_stays_on_disk(tmp_path):
    fel = default_fel()
    persist_feature_registry(tmp_path, fel.features)
    overlay_persisted(fel.features, tmp_path)
    rec = fel.features.get("rsi")
    rec.extra["status"] = "retired"
    persist_feature_registry(tmp_path, fel.features)
    again = default_fel(str(tmp_path))
    rsi = again.features.get("rsi")
    assert rsi is not None
    assert rsi.extra.get("status") == "retired"
    assert is_decision_eligible(rsi) is False
    assert is_observation_eligible(rsi) is False
