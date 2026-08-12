"""UTS.E — Switch Learning Records + counterfactual horizons (hermetic)."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.switch_learning import (
    HORIZON_DAYS,
    build_switch_learning_record,
    list_switch_decisions,
    propose_threshold_adjustments,
    record_switch_decision,
    resolve_horizon,
    run_due_switch_horizons,
)


def test_record_switch_decision_schedules_horizons(tmp_path: Path):
    review = {
        "hold_symbol": "TCS.NS",
        "challenger_symbol": "BEL.NS",
        "decision": "switch",
        "reason_code": "switch_advantage_cleared",
        "expected_advantage": 0.042,
        "threshold": 0.02,
        "exploratory": True,
        "label": "exploratory",
        "hold_metrics": {"expected_return": 0.05, "confidence": 0.55},
        "challenger_metrics": {"expected_return": 0.12, "confidence": 0.75},
        "evaluated_challengers": 3,
    }
    out = record_switch_decision(
        tmp_path,
        review,
        laboratory_id="india_equity_learner",
        portfolio_key="india_equity_learner",
        executed=True,
        decision_ist="2026-08-01",
    )
    assert out["ok"] is True
    row = out["decision"]
    assert row["switch_id"]
    assert row["executed"] is True
    assert {h["horizon_d"] for h in row["horizons"]} == set(HORIZON_DAYS)
    by_cp = {h["horizon_d"]: h for h in row["horizons"]}
    assert by_cp[1]["due_ist"] == "2026-08-02"
    assert by_cp[20]["due_ist"] == "2026-08-21"
    assert by_cp[60]["status"] == "pending"
    listed = list_switch_decisions(
        tmp_path, laboratory_id="india_equity_learner", limit=5
    )
    assert len(listed) == 1


def test_resolve_horizon_fail_closed_missing_prices(tmp_path: Path):
    out = record_switch_decision(
        tmp_path,
        {
            "hold_symbol": "A.NS",
            "challenger_symbol": "B.NS",
            "decision": "switch",
            "reason_code": "switch_advantage_cleared",
            "expected_advantage": 0.03,
            "threshold": 0.02,
            "exploratory": False,
            "hold_metrics": {"expected_return": 0.04, "confidence": 0.6},
            "challenger_metrics": {"expected_return": 0.09, "confidence": 0.7},
        },
        laboratory_id="lab",
        decision_ist="2026-07-01",
        executed=True,
    )
    sid = out["decision"]["switch_id"]
    miss = resolve_horizon(
        tmp_path,
        sid,
        20,
        laboratory_id="lab",
        hold_return=None,
        switched_return=None,
        publish_li=False,
    )
    assert miss["ok"] is False
    assert "missing" in (miss.get("honesty") or "").lower()
    h20 = next(h for h in miss["decision"]["horizons"] if h["horizon_d"] == 20)
    assert h20["status"] == "missing_prices"


def test_resolve_and_learning_record_to_li(tmp_path: Path):
    out = record_switch_decision(
        tmp_path,
        {
            "hold_symbol": "TCS.NS",
            "challenger_symbol": "BEL.NS",
            "decision": "switch",
            "reason_code": "switch_advantage_cleared",
            "expected_advantage": 0.04,
            "threshold": 0.02,
            "exploratory": False,
            "label": "calibrated",
            "hold_metrics": {"expected_return": 0.03, "confidence": 0.6},
            "challenger_metrics": {"expected_return": 0.10, "confidence": 0.8},
        },
        laboratory_id="india_equity_learner",
        decision_ist="2026-07-01",
        executed=True,
    )
    sid = out["decision"]["switch_id"]
    done = resolve_horizon(
        tmp_path,
        sid,
        20,
        laboratory_id="india_equity_learner",
        hold_return=0.01,
        switched_return=0.08,
        publish_li=True,
    )
    assert done["ok"] is True
    assert done["excess_return"] == 0.07
    rec = done["learning_record"]
    assert rec["decision"]["hold_symbol"] == "TCS.NS"
    assert rec["outcome"]["20"]["was_switch_better"] is True
    assert rec["attribution"]["incorrect_assumption"] is None
    li_path = (
        tmp_path
        / "investment"
        / "switch_learning"
        / "india_equity_learner"
        / "learning_records.jsonl"
    )
    assert li_path.is_file()
    built = build_switch_learning_record(done["decision"])
    assert built["switch_id"] == sid


def test_run_due_with_price_fn(tmp_path: Path):
    prices = {
        ("HOLD.NS", "2026-07-01"): 100.0,
        ("HOLD.NS", "2026-07-02"): 101.0,
        ("CHAL.NS", "2026-07-01"): 50.0,
        ("CHAL.NS", "2026-07-02"): 55.0,
    }
    record_switch_decision(
        tmp_path,
        {
            "hold_symbol": "HOLD.NS",
            "challenger_symbol": "CHAL.NS",
            "decision": "switch",
            "reason_code": "switch_advantage_cleared",
            "expected_advantage": 0.05,
            "threshold": 0.02,
            "exploratory": True,
            "hold_metrics": {"expected_return": 0.04, "confidence": 0.5},
            "challenger_metrics": {"expected_return": 0.12, "confidence": 0.7},
        },
        laboratory_id="lab",
        decision_ist="2026-07-01",
        executed=True,
    )

    def price_fn(sym: str, day: str) -> float | None:
        return prices.get((sym, day[:10]))

    result = run_due_switch_horizons(
        tmp_path,
        laboratory_id="lab",
        as_of_ist="2026-07-02",
        price_fn=price_fn,
        publish_li=False,
    )
    assert result["completed"] >= 1  # 1d horizon due


def test_threshold_proposals_gated_and_no_auto_apply():
    thin = propose_threshold_adjustments([], current_threshold=0.02, min_resolved=20)
    assert thin[0]["apply"] is False
    assert thin[0]["proposed"] is None

    fake = []
    for i in range(25):
        fake.append(
            {
                "decision": "switch",
                "horizons": [
                    {
                        "horizon_d": 20,
                        "status": "done",
                        "was_switch_better": i % 5 != 0,  # 80% hit
                    }
                ],
            }
        )
    props = propose_threshold_adjustments(
        fake, current_threshold=0.02, min_resolved=20, horizon_d=20
    )
    assert props[0]["apply"] is False
    assert props[0]["sample"] == 25
    assert props[0]["hit_rate"] >= 0.65
