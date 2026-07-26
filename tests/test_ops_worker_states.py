"""IR-OPS1 — Ops worker state classification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from atlas.ops.worker_states import (
    STATE_COMPLETED,
    STATE_PAUSED,
    STATE_READY,
    STATE_RUNNING_TICK,
    STATE_SLEEPING,
    STATE_SLOW,
    STATE_STARVED,
    STATE_WAITING_HOST,
    STATE_WAITING_SCHEDULE,
    classify_worker,
    summarize_workers,
    update_timing_ops,
    update_wait_ops,
)


def _w(**kwargs):
    base = {
        "id": "w1",
        "mission_id": "m1",
        "type": "market_observer",
        "status": "running",
        "metadata": {},
        "last_tick_at": datetime.now(timezone.utc) - timedelta(seconds=5),
        "created_at": datetime.now(timezone.utc) - timedelta(days=1),
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_capacity_queue_is_waiting_host():
    w = _w(status="paused", metadata={"queued_for_capacity": True, "queue_reason": "archive_slots"})
    row = classify_worker(w)
    assert row["ops_state"] == STATE_WAITING_HOST
    assert "archive" in (row["wait_reason"] or "")


def test_operator_pause():
    row = classify_worker(_w(status="paused", metadata={}))
    assert row["ops_state"] == STATE_PAUSED


def test_recovering_is_waiting_schedule():
    row = classify_worker(_w(status="recovering"))
    assert row["ops_state"] == STATE_WAITING_SCHEDULE


def test_inflight_is_running_ticks():
    row = classify_worker(_w(), inflight_mission_ids={"m1"})
    assert row["ops_state"] == STATE_RUNNING_TICK


def test_recent_tick_is_sleeping():
    now = datetime.now(timezone.utc)
    row = classify_worker(
        _w(last_tick_at=now - timedelta(seconds=5)),
        now=now,
    )
    assert row["ops_state"] == STATE_SLEEPING


def test_eligible_is_ready():
    now = datetime.now(timezone.utc)
    row = classify_worker(
        _w(last_tick_at=now - timedelta(minutes=10)),
        now=now,
    )
    assert row["ops_state"] == STATE_READY


def test_starved_after_long_wait():
    now = datetime.now(timezone.utc)
    row = classify_worker(
        _w(last_tick_at=now - timedelta(hours=7)),
        now=now,
    )
    assert row["ops_state"] == STATE_STARVED


def test_slow_when_last_tick_exceeds_expected():
    now = datetime.now(timezone.utc)
    w = _w(
        last_tick_at=now - timedelta(minutes=2),
        metadata={"ops": {"last_tick_ms": 30_000, "expected_tick_ms": 2_000}},
    )
    row = classify_worker(w, now=now)
    assert row["ops_state"] == STATE_SLOW


def test_stopped_is_completed():
    assert classify_worker(_w(status="stopped"))["ops_state"] == STATE_COMPLETED


def test_host_pressure_wait_recent():
    now = datetime.now(timezone.utc)
    w = _w(
        last_tick_at=now - timedelta(minutes=2),
        metadata={
            "ops": {
                "wait_reason": "host_pressure",
                "wait_since": (now - timedelta(seconds=30)).isoformat(),
            }
        },
    )
    row = classify_worker(w, now=now)
    assert row["ops_state"] == STATE_WAITING_HOST


def test_summarize_counts():
    now = datetime.now(timezone.utc)
    workers = [
        _w(id="a", status="paused", metadata={"queued_for_capacity": True}),
        _w(id="b", status="stopped"),
        _w(id="c", last_tick_at=now - timedelta(hours=8)),
    ]
    summary = summarize_workers(workers, now=now)
    assert summary["counts"][STATE_WAITING_HOST] == 1
    assert summary["counts"][STATE_COMPLETED] == 1
    assert summary["counts"][STATE_STARVED] == 1
    assert any(r["ops_state"] == STATE_STARVED for r in summary["notable"])


def test_update_timing_ops_averages():
    ops = update_timing_ops({}, duration_ms=100, expected_ms=50)
    ops = update_timing_ops(ops, duration_ms=300, expected_ms=50)
    assert ops["tick_count"] == 2
    assert ops["last_tick_ms"] == 300
    assert ops["max_tick_ms"] == 300
    assert ops["avg_tick_ms"] == 200.0
    assert "wait_reason" not in ops


def test_update_wait_ops():
    ops = update_wait_ops({}, reason="budget")
    assert ops["wait_reason"] == "budget"
    assert ops["wait_since"]
