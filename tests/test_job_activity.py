"""Tests for the live activity feed (Stage 3, Step 2 / RL / C0)."""

from __future__ import annotations

from atlas.jobs.activity import PHASE_SEARCH, PHASE_STEP, ActivityRecorder
from atlas.jobs.workspace import JobWorkspace


class FakeEvents:
    def __init__(self):
        self.events = []

    def emit(self, event_type, payload=None, source=None):
        self.events.append((event_type, payload or {}))


def test_workspace_activity_append_and_read(tmp_path):
    ws = JobWorkspace.for_job(tmp_path, "1")
    ws.append_activity({"phase": "step", "message": "one"})
    ws.append_activity({"phase": "step", "message": "two"})
    events = ws.read_activity()
    assert [e["message"] for e in events] == ["one", "two"]
    # tail limit returns the most recent
    assert [e["message"] for e in ws.read_activity(limit=1)] == ["two"]


def test_read_activity_missing_is_empty(tmp_path):
    assert JobWorkspace.for_job(tmp_path, "1").read_activity() == []


def test_recorder_writes_workspace_and_emits(tmp_path):
    ws = JobWorkspace.for_job(tmp_path, "42")
    events = FakeEvents()
    rec = ActivityRecorder("42", workspace=ws, events=events)
    ev = rec.record(PHASE_SEARCH, "searching scholar: soiling", query="soiling")

    assert ev["phase"] == PHASE_SEARCH
    assert ev["job_id"] == "42"
    assert ev["data"] == {"query": "soiling"}
    # durable in the workspace...
    stored = ws.read_activity()
    assert len(stored) == 1 and stored[0]["message"] == "searching scholar: soiling"
    # ...and pushed on the event bus
    assert events.events[0][0] == "job.activity"
    assert events.events[0][1]["message"] == "searching scholar: soiling"


def test_recorder_without_workspace_or_events_is_safe():
    rec = ActivityRecorder("1")  # no workspace, no events
    ev = rec.record(PHASE_STEP, "no sinks")  # must not raise
    assert ev["message"] == "no sinks"


def test_recorder_survives_failing_sinks(tmp_path):
    class Boom:
        def append_activity(self, event):
            raise RuntimeError("disk full")

    class BoomEvents:
        def emit(self, *a, **k):
            raise RuntimeError("bus down")

    rec = ActivityRecorder("1", workspace=Boom(), events=BoomEvents())
    # best-effort: a failing sink must never propagate
    assert rec.record(PHASE_STEP, "resilient")["message"] == "resilient"
