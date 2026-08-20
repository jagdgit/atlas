"""OI-SELF-ID — day activity brief (what did you do today?)."""

from __future__ import annotations

import json
from pathlib import Path

from atlas.planner.planner import Intent, Planner
from atlas.reasoning.day_activity import (
    build_day_activity_brief,
    detect_day_activity,
)


def test_detect_day_activity_phrases():
    assert detect_day_activity("what did you do today?")
    assert detect_day_activity("What have you done today")
    assert detect_day_activity("how was your day")
    assert not detect_day_activity("why do you believe capital preservation")
    assert not detect_day_activity("market intelligence status")


def test_planner_routes_day_activity():
    plan = Planner().plan("what did you do today?")
    assert plan.steps[0].intent == Intent.DAY_ACTIVITY


def test_build_day_activity_brief_from_artifacts(tmp_path: Path):
    day = "2026-08-12"
    sent = {
        "morning": [f"india_equity_learner|{day}"],
        "evening": [f"india_equity_learner|{day}"],
        "hourly": [f"india_equity_learner|{day}|11"],
    }
    (tmp_path / "market").mkdir(parents=True)
    (tmp_path / "market" / "investor_reports_sent.json").write_text(
        json.dumps(sent), encoding="utf-8"
    )
    lab = "india_equity_learner"
    kpi_dir = tmp_path / "market" / "trading_kpis" / lab
    note_dir = tmp_path / "market" / "session_notes" / lab
    kpi_dir.mkdir(parents=True)
    note_dir.mkdir(parents=True)
    (kpi_dir / f"{day}.json").write_text(
        json.dumps(
            {
                "kpis": {
                    "buys_today": 0,
                    "fills_today": 0,
                    "planned_symbols": ["DEVYANI.NS"],
                }
            }
        ),
        encoding="utf-8",
    )
    (note_dir / f"{day}.json").write_text(
        json.dumps({"feed_gap_days": 5, "reason_counts": {"mark_only": 10}}),
        encoding="utf-8",
    )
    research = tmp_path / "investment" / "research" / "market_intelligence"
    research.mkdir(parents=True)
    (research / "demo.json").write_text("{}", encoding="utf-8")

    out = build_day_activity_brief(data_dir=tmp_path, day=day, reasoning=None)
    assert out["ok"]
    assert out["mode"] == "day_activity"
    assert "Morning investment plan" in out["answer"]
    assert "Evening EOD" in out["answer"]
    assert "buys=0" in out["answer"]
    assert "feed_gap=5d" in out["answer"]
    assert "not introspection" in out["answer"].lower() or "inheritance" in out["answer"].lower()
