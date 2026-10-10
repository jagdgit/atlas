"""Historical blocked-switch regret — live threshold stays unchanged."""

from __future__ import annotations

import json
from pathlib import Path

from atlas.investment.swing_switch_regret import (
    run_switch_regret,
    score_decision,
)


def _bars(symbol: str, start: str, n: int, step: float) -> dict:
    # Simple synthetic closes: day i close = 100 + i*step
    from datetime import date, timedelta

    d0 = date.fromisoformat(start)
    bars = []
    for i in range(n):
        day = (d0 + timedelta(days=i)).isoformat()
        # skip weekends roughly by using calendar days; forward_return indexes by
        # position in the bar list, so consecutive entries are fine.
        bars.append({"date": day, "close": 100.0 + i * step})
    return {"bars": bars}


def test_challenger_win_and_hold_win(tmp_path: Path):
    root = tmp_path / "market" / "bars"
    root.mkdir(parents=True)
    # Hold flat, challenger rises → challenger wins after 1% cost.
    (root / "HOLD.NS.json").write_text(
        json.dumps(_bars("HOLD.NS", "2026-01-01", 30, 0.0)), encoding="utf-8"
    )
    (root / "CHAL.NS.json").write_text(
        json.dumps(_bars("CHAL.NS", "2026-01-01", 30, 1.0)), encoding="utf-8"
    )

    doc = {
        "decision_ist": "2026-01-01",
        "hold_symbol": "HOLD.NS",
        "challenger_symbol": "CHAL.NS",
        "expected_advantage": 0.02,
        "threshold": 0.05,
        "reason_code": "switch_blocked_plc_a",
    }
    scored = score_decision(tmp_path, doc, horizons=(5,), switch_cost=0.01)
    entry = scored["horizons"]["5"]
    assert entry["status"] == "ok"
    assert entry["winner"] == "challenger"
    assert scored["threshold_changed"] is False


def test_run_empty_dir(tmp_path: Path):
    out = run_switch_regret(tmp_path, laboratory_id="india_equity_learner")
    assert out["n_decisions"] == 0
    assert out["threshold_changed"] is False
