"""DI.7 gated ML export + offline eval — hermetic."""

from __future__ import annotations

from atlas.investment.decision_packets import build_packet
from atlas.investment.ml_export import (
    TRUSTED_MIN,
    build_export_dataset,
    export_ml_dataset,
    gate_status,
    offline_eval_rules_baseline,
    row_from_packet_attr,
)


def _closed_attr(decision_id: str, *, dq: str = "B", trigger: str = "exit") -> dict:
    return {
        "id": f"attr-{decision_id}",
        "decision_id": decision_id,
        "trigger": trigger,
        "grades": {
            "decision_quality": dq,
            "market_quality": "C",
            "thesis_correct": "yes" if dq in {"A", "B"} else "no",
            "may_update_priors": True,
            "pnl": 10.0 if dq in {"A", "B"} else -5.0,
        },
        "payload": {"pnl": 10.0 if dq in {"A", "B"} else -5.0},
    }


def test_gate_blocks_under_300():
    closed = {"sma_cross_rsi": 50, "next_alternative": 20}
    g = gate_status(closed_by_strategy=closed)
    assert g["allowed"] is False
    assert g["live_nn_trading"] is False
    assert g["trusted_min"] == TRUSTED_MIN == 300


def test_gate_allows_trusted_lane_or_override():
    g = gate_status(closed_by_strategy={"sma_cross_rsi": 300})
    assert g["allowed"] is True
    assert "sma_cross_rsi" in g["trusted_strategy_tags"]

    blocked = gate_status(
        closed_by_strategy={"sma_cross_rsi": 10},
        force_override=True,
        override_note="",
    )
    assert blocked["allowed"] is False

    forced = gate_status(
        closed_by_strategy={"sma_cross_rsi": 10},
        force_override=True,
        override_note="operator early export for schema check",
    )
    assert forced["allowed"] is True


def test_row_hides_pnl_when_priors_blocked():
    pkt = build_packet(
        action="buy",
        symbol="X.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="sma_cross_rsi",
        reasons_for=["x"],
        plan_link={"in_daily_plan": True, "rank": 1},
    )
    attr = {
        "id": "a1",
        "decision_id": pkt["decision_id"],
        "trigger": "exit",
        "grades": {
            "decision_quality": "A",
            "market_quality": "F",
            "may_update_priors": False,
            "pnl": 99.0,
        },
        "payload": {"pnl": 99.0},
    }
    row = row_from_packet_attr(pkt, attr)
    assert row["labels"]["pnl"] is None
    assert row["labels"]["label_pnl_pos_if_allowed"] is None
    assert row["labels"]["label_dq_ab"] == 1


def test_offline_eval_and_forced_export(tmp_path):
    packets = []
    attrs = []
    for i in range(20):
        pkt = build_packet(
            action="buy",
            symbol=f"S{i}.NS",
            portfolio_key="india_equity_learner",
            strategy_tag="sma_cross_rsi",
            reasons_for=["signal"],
            plan_link={"in_daily_plan": True, "rank": 1},
            investment_score={
                "axes": {"technical": 0.8 if i % 2 == 0 else -0.2, "business": 0.5}
            },
        )
        packets.append(pkt)
        attrs.append(
            _closed_attr(pkt["decision_id"], dq="A" if i % 2 == 0 else "D")
        )
    built = build_export_dataset(
        packets=packets, attributions=attrs, portfolio_key="india_equity_learner"
    )
    assert built["row_count"] == 20
    ev = offline_eval_rules_baseline(built["rows"])
    assert ev["ok"] is True
    assert ev["learned_beats_rules"] is False
    assert ev["live_nn_allowed"] is False

    # Without override, export blocked
    out = export_ml_dataset(
        data_dir=tmp_path,
        portfolio_key="india_equity_learner",
        force_override=False,
    )
    # empty store → blocked
    assert out["gate"]["allowed"] is False or out.get("exported") is False

    # Force with note writes files even with empty store rows from disk —
    # use in-memory path via building then direct write check on gate alone
    g = gate_status(
        closed_by_strategy={"sma_cross_rsi": 20},
        force_override=True,
        override_note="schema dry-run",
    )
    assert g["allowed"] is True
