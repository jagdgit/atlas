"""IR-RO2 — Mission Queue states + owners."""

from __future__ import annotations

from types import SimpleNamespace

from atlas.core.resources.mission_queue import (
    QUEUE_READY,
    QUEUE_WAITING_DEPENDENCY,
    QUEUE_WAITING_HOST,
    MissionQueueService,
    classify_mission,
    summarize_queue,
)


def _mission(**kwargs):
    base = {
        "id": "m1",
        "title": "Archive · certs",
        "status": "active",
        "criticality": "low",
        "scheduling_policy": "batch",
        "metadata": {
            "program_id": "personal_intelligence",
            "service_class": "BATCH",
            "portfolio_key": None,
            "operator": "operator",
        },
    }
    base.update(kwargs)
    if "metadata" in kwargs:
        meta = dict(base["metadata"])
        meta.update(kwargs["metadata"])
        base["metadata"] = meta
    return SimpleNamespace(**base)


def test_classify_ready_active():
    item = classify_mission(_mission())
    assert item is not None
    assert item.state == QUEUE_READY
    assert item.owner.program == "personal_intelligence"
    assert item.owner.mission == "m1"
    assert item.owner.operator == "operator"


def test_classify_draft_excluded():
    assert classify_mission(_mission(status="draft")) is None


def test_classify_waiting_host_from_worker_flag():
    worker = SimpleNamespace(
        id="w1",
        status="paused",
        metadata={"queued_for_capacity": True, "queue_reason": "archive slots full"},
    )
    item = classify_mission(_mission(), [worker])
    assert item.state == QUEUE_WAITING_HOST
    assert "archive" in item.reason
    assert item.owner.worker == "w1"


def test_classify_waiting_dependency_explicit():
    item = classify_mission(
        _mission(
            metadata={
                "program_id": "market_intelligence",
                "queue": {
                    "state": "WAITING_DEPENDENCY",
                    "reason": "needs transcription",
                    "depends_on": ["m-transcribe"],
                    "owner": {"program": "market_intelligence"},
                },
            }
        )
    )
    assert item.state == QUEUE_WAITING_DEPENDENCY
    assert item.depends_on == ["m-transcribe"]


def test_classify_mission_lifecycle_waiting():
    item = classify_mission(_mission(status="waiting"))
    assert item.state == QUEUE_WAITING_DEPENDENCY


def test_summarize_counts():
    items = [
        classify_mission(_mission(id="a")),
        classify_mission(
            _mission(
                id="b",
                metadata={
                    "queued_for_capacity": True,
                    "queue_reason": "host",
                    "program_id": "personal_intelligence",
                },
            ),
            [SimpleNamespace(id="w", metadata={"queued_for_capacity": True})],
        ),
    ]
    items = [i for i in items if i]
    summary = summarize_queue(items)
    assert summary["counts"][QUEUE_READY] == 1
    assert summary["counts"][QUEUE_WAITING_HOST] == 1
    assert summary["waiting"] >= 1


def test_mission_queue_service_snapshot():
    missions = SimpleNamespace(
        list_missions=lambda **k: [
            _mission(id="m1"),
            _mission(
                id="m2",
                metadata={
                    "program_id": "personal_intelligence",
                    "queue": {
                        "state": QUEUE_WAITING_HOST,
                        "reason": "slots",
                        "depends_on": [],
                        "owner": {},
                    },
                },
            ),
        ]
    )
    workers = SimpleNamespace(list_workers=lambda **k: [])
    svc = MissionQueueService(missions=missions, workers=workers)
    snap = svc.snapshot()
    assert snap["counts"][QUEUE_READY] == 1
    assert snap["counts"][QUEUE_WAITING_HOST] == 1
    assert any(i["owner"]["program"] for i in snap["items"])
