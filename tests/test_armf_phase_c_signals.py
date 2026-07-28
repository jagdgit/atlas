"""ARMF Phase C — at-risk, next-tick, research progress/velocity."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from atlas.core.resources.arbiter import MissionArbiter, MissionDemand
from atlas.ops.research_signals import (
    next_tick_preview,
    research_progress_snapshot,
    research_velocity_snapshot,
)
from atlas.ops.worker_states import (
    AT_RISK_AFTER_SECONDS,
    STATE_AT_RISK,
    STATE_READY,
    STATE_STARVED,
    classify_worker,
)


def _w(**kwargs):
    now = datetime.now(timezone.utc)
    base = {
        "id": "w1",
        "mission_id": "m1",
        "type": "paper_trading",
        "status": "running",
        "metadata": {"program_id": "market_intelligence"},
        "last_tick_at": now - timedelta(minutes=45),
        "created_at": now - timedelta(days=1),
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_at_risk_before_starved():
    now = datetime.now(timezone.utc)
    row = classify_worker(
        _w(last_tick_at=now - timedelta(seconds=AT_RISK_AFTER_SECONDS + 60)),
        now=now,
    )
    assert row["ops_state"] == STATE_AT_RISK


def test_still_ready_when_fresh():
    now = datetime.now(timezone.utc)
    row = classify_worker(
        _w(last_tick_at=now - timedelta(minutes=5)),
        now=now,
    )
    assert row["ops_state"] == STATE_READY


def test_starved_still_after_6h():
    now = datetime.now(timezone.utc)
    row = classify_worker(
        _w(last_tick_at=now - timedelta(hours=7)),
        now=now,
    )
    assert row["ops_state"] == STATE_STARVED


def test_research_progress_boost_prefers_low_coverage():
    arb = MissionArbiter(research_progress_boost_max=12.0)
    low = MissionDemand(mission_id="a", research_progress=0.1, effective_priority=10)
    high = MissionDemand(mission_id="b", research_progress=0.95, effective_priority=10)
    assert arb.score(low) > arb.score(high)


def test_next_tick_preview_orders_at_risk_first():
    rows = [
        {
            "id": "1",
            "type": "eng",
            "ops_state": STATE_READY,
            "owner": {"program": "engineering_intelligence"},
            "starvation_age_seconds": 100,
        },
        {
            "id": "2",
            "type": "paper_trading",
            "ops_state": STATE_AT_RISK,
            "owner": {"program": "market_intelligence"},
            "starvation_age_seconds": 2000,
        },
    ]
    out = next_tick_preview(rows, arbiter_snap={"effective_global_max": 4, "total_inflight": 1})
    assert out["free_tick_slots"] == 3
    assert out["next"][0]["type"] == "paper_trading"


def test_research_progress_and_velocity(tmp_path: Path):
    root = tmp_path
    ddir = root / "investment" / "research" / "market_intelligence"
    ddir.mkdir(parents=True)
    # Minimal dossier shape for coverage_pct
    doc = {
        "symbol": "TEST",
        "program_id": "market_intelligence",
        "sections": {},
        "mode": "mvr",
    }
    (ddir / "TEST.json").write_text(json.dumps(doc), encoding="utf-8")
    prog = research_progress_snapshot(root)
    assert prog["count"] >= 1
    assert prog["attention"]

    notes = root / "market" / "session_notes" / "india_equity_learner"
    notes.mkdir(parents=True)
    day = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    # Use IST day from velocity helper — write today's note with buys
    from zoneinfo import ZoneInfo

    day = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    (notes / f"{day}.json").write_text(json.dumps({"buys": 2, "fills": []}), encoding="utf-8")
    vel = research_velocity_snapshot(root)
    assert vel["programs"]["market_intelligence"]["dossiers_advanced_today"] >= 1
    assert vel["programs"]["market_intelligence"]["session_buys_today"] == 2
