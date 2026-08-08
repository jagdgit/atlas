"""LQ.9 — AtlasNet §8.2 hard gate (block train beyond prep)."""

from __future__ import annotations

import pytest

from atlas.investment.atlasnet_prep import (
    AtlasNetTrainBlocked,
    assert_atlasnet_train_allowed,
    evaluate_atlasnet_hard_gate,
    refuse_atlasnet_beyond_prep,
    request_atlasnet_train,
)
from atlas.investment.laboratory import DEFAULT_SWING_LAB
from atlas.investment.reports import format_evening_report


def test_hard_gate_fails_closed_on_empty():
    gate = evaluate_atlasnet_hard_gate(rows=[], packets=[], attributions=[])
    assert gate["train_allowed"] is False
    assert gate["paper_nn_allowed"] is False
    assert gate["live_nn_trading"] is False
    assert gate["atlasnet_status"] == "prep_only"
    assert "closed_500" in gate["blocking"]
    assert gate["force_override_bypasses_train"] is False


def test_assert_raises_until_cleared():
    gate = evaluate_atlasnet_hard_gate(rows=[])
    with pytest.raises(AtlasNetTrainBlocked) as ei:
        assert_atlasnet_train_allowed(gate, intent="paper_nn")
    assert "blocking" in str(ei.value).lower() or "blocked" in str(ei.value).lower()


def test_force_override_cannot_unlock_train(tmp_path):
    out = request_atlasnet_train(
        data_dir=tmp_path,
        laboratory_id=DEFAULT_SWING_LAB,
        force_override=True,
        override_note="please train anyway",
    )
    assert out["train_allowed"] is False
    assert out["started"] is False
    assert out["force_override_ignored"] is True
    assert "force_override" in (out.get("blocked") or "").lower()


def test_refuse_helper_raises():
    with pytest.raises(AtlasNetTrainBlocked):
        refuse_atlasnet_beyond_prep(intent="train", rows=[])


def test_cleared_gate_allows_assert_but_live_stays_false():
    # Construct a synthetic cleared gate (unit-level — not inventing live data)
    gate = evaluate_atlasnet_hard_gate(rows=[])
    gate = {
        **gate,
        "train_allowed": True,
        "paper_nn_allowed": True,
        "blocking": [],
        "atlasnet_status": "train_eligible",
        "live_nn_trading": False,
    }
    assert assert_atlasnet_train_allowed(gate)["train_allowed"] is True
    assert gate["live_nn_trading"] is False


def test_evening_mail_surfaces_hard_gate():
    _subj, body = format_evening_report(
        plan={"as_of": "2026-08-08", "summary": "x", "phase": "learning", "confidence": "low"},
        portfolio={
            "cash": 1,
            "atlasnet_prep": {
                "atlasnet_status": "prep_only",
                "train_allowed": False,
                "export_allowed": False,
                "hard_gate": {
                    "atlasnet_status": "prep_only",
                    "train_allowed": False,
                    "blocking": ["closed_500", "regimes_10"],
                },
            },
        },
    )
    assert "AtlasNet hard gate" in body
    assert "closed_500" in body
    assert "train_allowed=False" in body
