"""OI-LEARN-AUDIT0 LA.5 — chat inherits Learning Auditor."""

from __future__ import annotations

import json
from pathlib import Path

from atlas.investment.learning_audit import (
    answer_learning_audit_chat,
    build_and_persist_learning_audit,
    build_and_persist_weekly_learning_report,
    detect_learning_audit_query,
)


def test_detect_learning_audit_queries():
    assert detect_learning_audit_query("What did you learn today?") == "daily"
    assert detect_learning_audit_query("What did you learn this week?") == "weekly"
    assert detect_learning_audit_query("learning audit status") == "daily"
    assert detect_learning_audit_query("weekly learning report") == "weekly"
    assert detect_learning_audit_query("Where does the next rupee go?") is None


def test_answer_daily_inherits_audit_not_throughput(tmp_path: Path):
    lab = "india_equity_learner"
    day = "2026-08-23"
    kpi_dir = tmp_path / "market" / "trading_kpis" / lab
    kpi_dir.mkdir(parents=True)
    (kpi_dir / f"{day}.json").write_text(
        json.dumps({"kpis": {"fills_today": 99, "buys_today": 50}}) + "\n",
        encoding="utf-8",
    )
    build_and_persist_learning_audit(tmp_path, laboratory_id=lab, as_of_ist=day)

    out = answer_learning_audit_chat(
        "What did you learn today?",
        data_dir=tmp_path,
        laboratory_id=lab,
    )
    assert out is not None
    assert out["kind"] == "learning_audit_daily"
    ans = str(out.get("answer") or "")
    assert "Learning Audit" in ans
    assert "chain-complete" in ans
    assert "Not learning today" in ans or "fills=" in ans
    assert "consultation counts" in ans


def test_answer_weekly_inherits_report(tmp_path: Path):
    lab = "india_equity_learner"
    day = "2026-08-23"
    build_and_persist_learning_audit(tmp_path, laboratory_id=lab, as_of_ist=day)
    build_and_persist_weekly_learning_report(
        tmp_path, laboratory_id=lab, as_of_ist=day
    )

    out = answer_learning_audit_chat(
        "What did you learn this week?",
        data_dir=tmp_path,
        laboratory_id=lab,
    )
    assert out is not None
    assert out["kind"] == "learning_audit_weekly"
    assert "Weekly Learning Report" in str(out.get("answer") or "")
