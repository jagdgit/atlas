"""Equity horizon audit first slice."""

from __future__ import annotations

import json
from pathlib import Path

from atlas.investment.equity_horizon_audit import (
    build_equity_horizon_audit,
    persist_equity_horizon_audit,
)


def test_horizon_audit_holding_consistent(tmp_path: Path):
    lab = "india_equity_learner"
    day = "2026-09-29"
    kpi = tmp_path / "market" / "trading_kpis" / lab
    kpi.mkdir(parents=True)
    (kpi / f"{day}.json").write_text(
        json.dumps(
            {
                "ist_date": day,
                "kpis": {
                    "open_positions": 2,
                    "fills_today": 0,
                    "buys_today": 0,
                    "sells_today": 0,
                    "day_pnl": 324.0,
                    "total_pnl": -9000.0,
                    "holdings_value": 18000.0,
                },
            }
        ),
        encoding="utf-8",
    )
    alloc = tmp_path / "investment" / "allocation" / lab
    alloc.mkdir(parents=True)
    (alloc / "COALINDIA.NS_latest.json").write_text(
        json.dumps({"symbol": "COALINDIA.NS", "acp": "HOLD"}),
        encoding="utf-8",
    )
    doc = build_equity_horizon_audit(tmp_path, laboratory_id=lab, as_of_ist=day)
    assert doc["verdict"] == "HOLDING_CONSISTENT"
    assert doc["gates_preserved"]["strategy_mutation"] is False
    out = persist_equity_horizon_audit(tmp_path, doc)
    assert out["persisted"] is True
    assert (tmp_path / "investment" / "equity_horizon_audit" / f"{day}.json").is_file()
