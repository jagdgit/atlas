"""LI.6 — AtlasNet prep: lab-partitioned export + walk-forward contract (no NN)."""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.investment.atlasnet_prep import (
    VERSION,
    atlasnet_prep_status,
    build_walk_forward_contract,
    export_atlasnet_prep,
    lane_partition_key,
    write_lab_partitioned_export,
)
from atlas.investment.decision_packets import build_packet
from atlas.investment.laboratory import (
    DEFAULT_INTRADAY_LAB,
    DEFAULT_SWING_LAB,
    LaboratoryContaminationError,
    lane_key,
)
from atlas.investment.ml_export import row_from_packet_attr


def _row(lab: str, tag: str, exp: str = "default", *, dq: str = "B", i: int = 0) -> dict:
    pkt = build_packet(
        action="buy",
        symbol=f"S{i}.NS",
        portfolio_key=lab,
        strategy_tag=tag,
        experiment_id=exp,
        reasons_for=["signal"],
        investment_score={"axes": {"technical": 0.8 if i % 2 == 0 else -0.2}},
        plan_link={"in_daily_plan": True, "rank": 1},
    )
    attr = {
        "id": f"a-{i}",
        "decision_id": pkt["decision_id"],
        "trigger": "exit",
        "portfolio_key": lab,
        "laboratory_id": lab,
        "grades": {
            "decision_quality": dq,
            "market_quality": "C",
            "may_update_priors": True,
            "pnl": 1.0,
        },
        "payload": {"pnl": 1.0, "failure_cause": "evidence_failure"},
    }
    return row_from_packet_attr(pkt, attr)


def test_walk_forward_contract_never_enables_nn():
    rows = [_row(DEFAULT_SWING_LAB, "sma_cross_rsi", i=i) for i in range(12)]
    contract = build_walk_forward_contract(rows, laboratory_id=DEFAULT_SWING_LAB)
    assert contract["version"] == VERSION
    assert contract["live_nn_trading"] is False
    assert contract["live_nn_allowed"] is False
    assert contract["learned_beats_rules"] is False
    assert contract["atlasnet_status"] == "prep_only"
    assert contract["learned_model"] is None
    assert contract["n_labeled"] >= 10


def test_partitioned_export_lab_hermetic(tmp_path: Path):
    swing_rows = [
        _row(DEFAULT_SWING_LAB, "sma_cross_rsi", i=i) for i in range(5)
    ] + [_row(DEFAULT_SWING_LAB, "sma_cross_rsi", "exp_b", i=100 + i) for i in range(3)]
    contract = build_walk_forward_contract(swing_rows, laboratory_id=DEFAULT_SWING_LAB)
    written = write_lab_partitioned_export(
        tmp_path,
        laboratory_id=DEFAULT_SWING_LAB,
        rows=swing_rows,
        manifest_body={"live_nn_trading": False},
        contract=contract,
    )
    assert Path(written["manifest_path"]).is_file()
    assert Path(written["contract_path"]).is_file()
    assert Path(written["all_rows_path"]).is_file()
    assert len(written["lanes_written"]) >= 2
    assert any("sma_cross_rsi" in k for k in written["lanes_written"])
    for path in written["lane_paths"].values():
        assert Path(path).is_file()

    mixed = swing_rows + [_row(DEFAULT_INTRADAY_LAB, "sma_cross_rsi", i=9)]
    with pytest.raises(LaboratoryContaminationError):
        write_lab_partitioned_export(
            tmp_path,
            laboratory_id=DEFAULT_SWING_LAB,
            rows=mixed,
            manifest_body={},
            contract=contract,
        )


def test_export_atlasnet_prep_blocked_without_force(tmp_path: Path):
    st = atlasnet_prep_status(data_dir=tmp_path, laboratory_id=DEFAULT_SWING_LAB)
    assert st["live_nn_trading"] is False
    assert st["atlasnet_status"] == "prep_only"
    assert st["export_allowed"] is False

    out = export_atlasnet_prep(
        data_dir=tmp_path,
        laboratory_id=DEFAULT_SWING_LAB,
        force_override=False,
    )
    assert out["exported"] is False
    assert out["live_nn_trading"] is False


def test_export_atlasnet_prep_force_writes_partitions(tmp_path: Path):
    out = export_atlasnet_prep(
        data_dir=tmp_path,
        laboratory_id=DEFAULT_SWING_LAB,
        force_override=True,
        override_note="schema dry-run for LI.6",
    )
    assert out["live_nn_trading"] is False
    assert out["atlasnet_status"] == "prep_only"
    if out.get("exported"):
        assert Path(out["manifest_path"]).is_file()
        assert Path(out["contract_path"]).is_file()
        assert out["walk_forward_contract"]["learned_beats_rules"] is False


def test_lane_partition_key_stable():
    row = {
        "lane_key": lane_key(DEFAULT_SWING_LAB, "sma_cross_rsi", "default"),
        "laboratory_id": DEFAULT_SWING_LAB,
        "strategy_tag": "sma_cross_rsi",
        "experiment_id": "default",
    }
    key = lane_partition_key(row)
    assert "sma_cross_rsi" in key
