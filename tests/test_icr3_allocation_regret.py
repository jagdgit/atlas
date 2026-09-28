"""OI-ICR3 — opportunity-cost learning + capital_regret_20d."""

from __future__ import annotations

from atlas.investment.allocation_comparison import (
    DECISION_EXIT_REVIEW,
    build_allocation_comparison_packet,
)
from atlas.investment.allocation_regret import (
    capital_regret_kpi,
    evaluate_due_opportunity_costs,
    legs_from_acp,
    list_opportunity_costs,
    resolve_horizon,
    schedule_opportunity_cost,
    schedule_from_lab_acps,
)
from atlas.investment.capital_allocation import CASH_SYMBOL


def _acp_keep():
    hold = {
        "symbol": "CIPLA.NS",
        "qty": 15,
        "avg_price": 1460.0,
        "mark": 1438.0,
        "score": 0.7,
        "confidence": "high",
        "components": {"momentum": 0.7},
    }
    aw = {
        "thesis": {
            "stance": "BUY",
            "summary": "Strong pharma franchise with clear business identity.",
            "id": "th-ok",
        },
        "valuation": {"margin_of_safety_pct": 12.0},
    }
    return build_allocation_comparison_packet(
        hold=hold,
        challengers=[
            {
                "symbol": "INFY.NS",
                "score": 0.6,
                "confidence": "medium",
                "components": {"momentum": 0.6},
                "mark": 1500.0,
            },
            {
                "symbol": "EICHERMOT.NS",
                "score": 0.55,
                "confidence": "medium",
                "components": {"momentum": 0.55},
                "mark": 4800.0,
            },
        ],
        cash=20_000.0,
        laboratory_id="india_equity_learner",
        awareness=aw,
        equity=80_000.0,
        as_of_ist="2026-08-01",
    )


def test_legs_keep_incumbent_rejects_challengers_and_cash():
    acp = _acp_keep()
    chosen, rejected, kind = legs_from_acp(acp)
    assert chosen["symbol"] == "CIPLA.NS"
    assert kind in {"keep_incumbent", "hold_thin"}
    syms = {r["symbol"] for r in rejected}
    assert "INFY.NS" in syms
    assert "EICHERMOT.NS" in syms
    assert CASH_SYMBOL in syms


def test_legs_exit_to_cash():
    acp = {
        "decision": DECISION_EXIT_REVIEW,
        "incumbent": {"symbol": "CIPLA.NS", "expected_return": -0.1},
        "cash": {"symbol": CASH_SYMBOL, "expected_return": 0.0},
        "challengers": [{"symbol": "INFY.NS", "is_best": True, "expected_return": 0.05}],
    }
    chosen, rejected, kind = legs_from_acp(
        acp, resolution={"action": "EXIT_TO_CASH", "reason_code": "exit_avoid_to_cash"}
    )
    assert kind == "exit_to_cash"
    assert chosen["symbol"] == CASH_SYMBOL
    assert any(r["symbol"] == "CIPLA.NS" for r in rejected)


def test_schedule_and_resolve_capital_regret(tmp_path):
    acp = _acp_keep()
    # CIPLA +1%, EICHER +7%, INFY +2%, cash 0% → regret = 0.01 - 0.07 = -0.06
    marks = {"CIPLA.NS": 100.0, "INFY.NS": 100.0, "EICHERMOT.NS": 100.0}
    row = schedule_opportunity_cost(
        tmp_path,
        acp,
        laboratory_id="india_equity_learner",
        decision_ist="2026-08-01",
        marks=marks,
    )
    assert row is not None
    oc_id = row["oc_id"]

    # Idempotent same day
    row2 = schedule_opportunity_cost(
        tmp_path,
        acp,
        laboratory_id="india_equity_learner",
        decision_ist="2026-08-01",
        marks=marks,
    )
    assert row2["oc_id"] == oc_id

    prices = {
        ("CIPLA.NS", "2026-08-01"): 100.0,
        ("CIPLA.NS", "2026-08-21"): 101.0,  # +1%
        ("INFY.NS", "2026-08-01"): 100.0,
        ("INFY.NS", "2026-08-21"): 102.0,  # +2%
        ("EICHERMOT.NS", "2026-08-01"): 100.0,
        ("EICHERMOT.NS", "2026-08-21"): 107.0,  # +7%
    }

    def price_fn(sym: str, day: str):
        return prices.get((sym, day[:10]))

    # Force 20d horizon due
    for h in row["horizons"]:
        if h["horizon_d"] == 20:
            h["due_ist"] = "2026-08-21"
    path = tmp_path / "investment" / "opportunity_cost" / "india_equity_learner" / "by_id" / f"{oc_id}.json"
    import json

    # Re-read after schedule wrote; update due
    doc = json.loads(path.read_text())
    for h in doc["horizons"]:
        if int(h["horizon_d"]) == 20:
            h["due_ist"] = "2026-08-21"
            h["status"] = "pending"
    path.write_text(json.dumps(doc, indent=2))

    out = resolve_horizon(
        tmp_path,
        oc_id,
        20,
        laboratory_id="india_equity_learner",
        price_fn=price_fn,
    )
    assert out["ok"] is True
    assert abs(float(out["capital_regret"]) - (-0.06)) < 1e-6
    assert abs(float(out["row"]["capital_regret_20d"]) - (-0.06)) < 1e-6

    kpi = capital_regret_kpi(list_opportunity_costs(tmp_path, laboratory_id="india_equity_learner"))
    assert kpi["n"] == 1
    assert abs(kpi["mean"] - (-0.06)) < 1e-6


def test_missing_prices_null_regret(tmp_path):
    acp = _acp_keep()
    row = schedule_opportunity_cost(
        tmp_path,
        acp,
        laboratory_id="india_equity_learner",
        decision_ist="2026-08-01",
        marks={"CIPLA.NS": 100.0},
    )
    oc_id = row["oc_id"]
    import json

    path = (
        tmp_path
        / "investment"
        / "opportunity_cost"
        / "india_equity_learner"
        / "by_id"
        / f"{oc_id}.json"
    )
    doc = json.loads(path.read_text())
    for h in doc["horizons"]:
        if int(h["horizon_d"]) == 20:
            h["due_ist"] = "2026-08-21"
    path.write_text(json.dumps(doc))

    out = resolve_horizon(
        tmp_path,
        oc_id,
        20,
        laboratory_id="india_equity_learner",
        price_fn=lambda *_: None,
    )
    assert out["ok"] is False
    assert "null" in str(out.get("honesty") or "").lower() or "lack" in str(
        out.get("honesty") or ""
    ).lower()


def test_evaluate_due_and_batch_schedule(tmp_path):
    acp = _acp_keep()
    batch = schedule_from_lab_acps(
        tmp_path,
        [acp],
        laboratory_id="india_equity_learner",
        marks={"CIPLA.NS": 100.0, "INFY.NS": 100.0, "EICHERMOT.NS": 100.0},
    )
    assert batch["count"] == 1

    # Nothing due yet on far future as_of before decision? Use past decision + due
    prices = {}

    def price_fn(sym, day):
        return prices.get((sym, day))

    meta = evaluate_due_opportunity_costs(
        tmp_path,
        laboratory_id="india_equity_learner",
        as_of_ist="2026-07-01",
        price_fn=price_fn,
    )
    assert meta["completed"] == 0
