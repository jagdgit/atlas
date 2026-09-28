"""OI-ICR2 — EXIT_REVIEW densify ladder."""

from __future__ import annotations

from atlas.investment.allocation_comparison import (
    DECISION_EXIT_REVIEW,
    DECISION_KEEP,
    DECISION_SWITCH_REVIEW,
    build_allocation_comparison_packet,
)
from atlas.investment.incumbent_review import (
    ACTION_EXIT_TO_CASH,
    ACTION_SWITCH_TO,
    ACTION_WAIT,
    DEFAULT_QUARANTINE_EXIT_DAYS,
    load_quarantine_clock,
    note_quarantine_day,
    resolve_exit_review,
    resolve_lab_exit_reviews,
)


def _acp_avoid(**kw):
    hold = {
        "symbol": "CIPLA.NS",
        "qty": 15,
        "avg_price": 1460.0,
        "mark": 1438.0,
        "score": 0.4,
        "confidence": "very_low",
        "components": {"momentum": 0.4},
        **kw,
    }
    aw = {
        "thesis": {
            "stance": "avoid",
            "summary": "Avoid — MoS deep negative.",
            "id": "th-1",
        },
        "valuation": {"margin_of_safety_pct": -55.0},
    }
    return build_allocation_comparison_packet(
        hold=hold,
        challengers=[
            {
                "symbol": "INFY.NS",
                "score": 0.5,
                "confidence": "medium",
                "components": {"momentum": 0.5},
            }
        ],
        cash=20_000.0,
        laboratory_id="india_equity_learner",
        awareness=aw,
        equity=80_000.0,
    )


def test_avoid_no_challenger_exits_to_cash():
    acp = _acp_avoid()
    assert acp["decision"] == DECISION_EXIT_REVIEW
    res = resolve_exit_review(acp, data_dir=None, cfg={})
    assert res["action"] == ACTION_EXIT_TO_CASH
    assert res["execute"] is True
    assert "cash" in str(res.get("reason_code") or "")


def test_quarantine_waits_then_exits(tmp_path):
    hold = {
        "symbol": "CIPLA.NS",
        "qty": 10,
        "mark": 1400.0,
        "avg_price": 1450.0,
        "score": 0.5,
        "confidence": "low",
        "components": {"momentum": 0.5},
    }
    aw = {
        "thesis": {
            "stance": "WATCH",
            "summary": (
                "CIPLA branded hospital network occupancy ARPOB doctor retention"
            ),
            "id": "th-q",
        }
    }
    acp = build_allocation_comparison_packet(
        hold=hold,
        challengers=[],
        cash=10_000.0,
        laboratory_id="india_equity_learner",
        awareness=aw,
        as_of_ist="2026-08-21",
    )
    assert acp["decision"] == DECISION_EXIT_REVIEW
    r0 = resolve_exit_review(
        acp, data_dir=tmp_path, cfg={"icr2_quarantine_exit_days": 3}, as_of_ist="2026-08-21"
    )
    assert r0["action"] == ACTION_WAIT
    assert r0["curiosity"]
    clock = load_quarantine_clock(tmp_path, "india_equity_learner")
    assert "CIPLA.NS" in (clock.get("symbols") or {})

    # Age the clock
    note_quarantine_day(
        tmp_path, "india_equity_learner", "CIPLA.NS", as_of_ist="2026-08-21"
    )
    # Force first_seen earlier
    from atlas.investment.incumbent_review import quarantine_clock_path
    import json

    path = quarantine_clock_path(tmp_path, "india_equity_learner")
    doc = json.loads(path.read_text())
    doc["symbols"]["CIPLA.NS"]["first_seen_ist"] = "2026-08-18"
    path.write_text(json.dumps(doc))

    r1 = resolve_exit_review(
        acp, data_dir=tmp_path, cfg={"icr2_quarantine_exit_days": 3}, as_of_ist="2026-08-21"
    )
    assert r1["action"] == ACTION_EXIT_TO_CASH
    assert r1["reason_code"] == "exit_quarantine_aged"


def test_switch_review_resolves_to_switch_to():
    acp = {
        "acp_id": "x",
        "laboratory_id": "india_equity_learner",
        "decision": DECISION_SWITCH_REVIEW,
        "as_of_ist": "2026-08-21",
        "incumbent": {"symbol": "CIPLA.NS", "thesis_stance": "WATCH", "identity": "VALID"},
        "challengers": [
            {"symbol": "INFY.NS", "is_best": True, "expected_advantage": 0.05}
        ],
        "provenance": {
            "switch_review": {
                "decision": "switch",
                "challenger_symbol": "INFY.NS",
                "expected_advantage": 0.05,
            }
        },
        "switch_cost": {"min_advantage": 0.02},
        "incumbent_vs_cash": {"ok": True, "advantage": 0.01},
    }
    res = resolve_exit_review(acp, cfg={})
    assert res["action"] == ACTION_SWITCH_TO
    assert res["challenger_symbol"] == "INFY.NS"
    assert res["execute"] is True


def test_keep_not_resolved():
    acp = {
        "decision": DECISION_KEEP,
        "incumbent": {"symbol": "X.NS"},
        "laboratory_id": "india_equity_learner",
    }
    res = resolve_exit_review(acp, cfg={})
    assert res["action"] == ACTION_WAIT
    assert res["reason_code"] == "not_exit_review"


def test_resolve_lab_batch():
    acp = _acp_avoid()
    out = resolve_lab_exit_reviews([acp, {"decision": DECISION_KEEP}], cfg={})
    assert out["count"] == 1
    assert out["execute_n"] == 1
    assert DEFAULT_QUARANTINE_EXIT_DAYS >= 1
