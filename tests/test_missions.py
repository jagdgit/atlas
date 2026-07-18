"""Mission Manager tests (Phase A · §A.1).

Hermetic: a fake repository stands in for ``mission.missions`` / ``mission.journal`` and a
fake event bus captures emissions, so we cover creation, the full lifecycle transition graph
(including illegal transitions), non-destructive archival, the append-only journal, aggregated
reads, label/status filtering, and effective-priority arbitration — all without a database.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest

from atlas.models.mission import (
    CRIT_CRITICAL,
    MISSION_ACTIVE,
    MISSION_ARCHIVED,
    MISSION_COMPLETED,
    MISSION_DRAFT,
    MISSION_PAUSED,
    MISSION_WAITING,
    POLICY_REALTIME,
    Mission,
    MissionJournalEntry,
    compute_effective_priority,
)
from atlas.missions.service import MissionError, MissionService


# --- fakes ---------------------------------------------------------------


class FakeMissionRepo:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.journal: list[dict[str, Any]] = []
        self.job_ids: dict[str, list[str]] = {}

    def create(self, **kw: Any) -> Mission:
        mid = str(uuid4())
        now = datetime.now(timezone.utc)
        row = {
            "id": mid,
            "title": kw["title"],
            "objective": kw.get("objective", ""),
            "status": kw.get("status", MISSION_DRAFT),
            "success_criteria": kw.get("success_criteria") or {},
            "knowledge_domains": list(kw.get("knowledge_domains") or []),
            "active_config_id": None,
            "scheduling_policy": kw["scheduling_policy"],
            "priority": kw["priority"],
            "criticality": kw["criticality"],
            "budget": kw.get("budget") or {},
            "deadline": kw.get("deadline"),
            "importance": kw.get("importance"),
            "labels": list(kw.get("labels") or []),
            "metadata": kw.get("metadata") or {},
            "template_id": kw.get("template_id"),
            "template_version": kw.get("template_version"),
            "created_at": now,
            "updated_at": now,
        }
        self.rows[mid] = row
        return Mission.from_row(row)

    def get(self, mission_id: Any) -> Mission | None:
        row = self.rows.get(str(mission_id))
        return Mission.from_row(row) if row else None

    def list(self, *, status=None, label=None, limit=100) -> list[Mission]:
        out = []
        for row in sorted(self.rows.values(), key=lambda r: r["created_at"], reverse=True):
            if status is not None and row["status"] != status:
                continue
            if label is not None and label not in row["labels"]:
                continue
            out.append(Mission.from_row(row))
        return out[:limit]

    def set_status(self, mission_id: Any, status: str) -> bool:
        row = self.rows.get(str(mission_id))
        if not row:
            return False
        row["status"] = status
        row["updated_at"] = datetime.now(timezone.utc)
        return True

    def set_active_config(self, mission_id: Any, config_id: str) -> bool:
        row = self.rows.get(str(mission_id))
        if not row:
            return False
        row["active_config_id"] = config_id
        return True

    def update_arbitration(
        self, mission_id, *, scheduling_policy=None, priority=None, criticality=None, budget=None
    ) -> bool:
        row = self.rows.get(str(mission_id))
        if not row:
            return False
        if scheduling_policy is not None:
            row["scheduling_policy"] = scheduling_policy
        if priority is not None:
            row["priority"] = priority
        if criticality is not None:
            row["criticality"] = criticality
        if budget is not None:
            row["budget"] = budget
        return True

    def add_journal(self, mission_id, action, reason="", refs=None) -> MissionJournalEntry:
        entry = {
            "id": str(uuid4()),
            "mission_id": str(mission_id),
            "action": action,
            "reason": reason,
            "refs": refs or {},
            "ts": datetime.now(timezone.utc),
        }
        self.journal.append(entry)
        return MissionJournalEntry.from_row(entry)

    def list_journal(self, mission_id, *, limit=100) -> list[MissionJournalEntry]:
        entries = [e for e in self.journal if e["mission_id"] == str(mission_id)]
        entries.sort(key=lambda e: e["ts"], reverse=True)
        return MissionJournalEntry.from_rows(entries[:limit])

    def list_job_ids(self, mission_id) -> list[str]:
        return list(self.job_ids.get(str(mission_id), []))


class FakeEvents:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict[str, Any], str | None]] = []

    def emit(self, event_type: str, payload=None, source=None) -> int:
        self.emitted.append((event_type, payload or {}, source))
        return 1

    def types(self) -> list[str]:
        return [e[0] for e in self.emitted]


@pytest.fixture()
def svc() -> tuple[MissionService, FakeMissionRepo, FakeEvents]:
    repo = FakeMissionRepo()
    events = FakeEvents()
    return MissionService(repo, events=events), repo, events


# --- creation ------------------------------------------------------------


def test_create_defaults_to_draft_and_journals(svc):
    service, repo, events = svc
    m = service.create_mission("Paper Trading", "simulate NSE swing trades")
    assert m.status == MISSION_DRAFT
    assert m.title == "Paper Trading"
    assert any(e["action"] == "created" for e in repo.journal)
    assert "MissionCreated" in events.types()


def test_create_requires_title(svc):
    service, _, _ = svc
    with pytest.raises(MissionError):
        service.create_mission("   ")


def test_create_rejects_bad_enums(svc):
    service, _, _ = svc
    with pytest.raises(MissionError):
        service.create_mission("X", scheduling_policy="turbo")
    with pytest.raises(MissionError):
        service.create_mission("X", criticality="urgent")
    with pytest.raises(MissionError):
        service.create_mission("X", priority=999)


# --- lifecycle -----------------------------------------------------------


def test_full_lifecycle_path(svc):
    service, _, events = svc
    m = service.create_mission("Job Hunt")
    assert service.activate(m.id).status == MISSION_ACTIVE
    assert service.mark_waiting(m.id, "market closed").status == MISSION_WAITING
    assert service.clear_waiting(m.id).status == MISSION_ACTIVE
    assert service.pause(m.id, "operator hold").status == MISSION_PAUSED
    assert service.resume(m.id).status == MISSION_ACTIVE
    assert service.complete(m.id, "criteria met").status == MISSION_COMPLETED
    assert service.archive(m.id).status == MISSION_ARCHIVED
    types = events.types()
    for expected in (
        "MissionActivated",
        "MissionWaiting",
        "MissionPaused",
        "MissionCompleted",
        "MissionArchived",
    ):
        assert expected in types


def test_illegal_transition_rejected(svc):
    service, _, _ = svc
    m = service.create_mission("X")
    with pytest.raises(MissionError):
        service.pause(m.id)  # draft → paused is illegal
    service.activate(m.id)
    service.complete(m.id)
    with pytest.raises(MissionError):
        service.activate(m.id)  # completed → active is illegal


def test_archive_is_non_destructive_keeps_journal(svc):
    service, repo, _ = svc
    m = service.create_mission("Solar Opt")
    service.activate(m.id)
    service.journal(m.id, "finding_produced", "extracted claim", {"finding_id": "f1"})
    service.archive(m.id, "done")
    # journal (provenance) survives archival
    entries = service.journal_entries(m.id)
    assert any(e.action == "finding_produced" for e in entries)


def test_transition_on_missing_mission_raises(svc):
    service, _, _ = svc
    with pytest.raises(MissionError):
        service.activate(str(uuid4()))


# --- reads / arbitration -------------------------------------------------


def test_get_mission_aggregate_shape(svc):
    service, repo, _ = svc
    m = service.create_mission("Research", scheduling_policy=POLICY_REALTIME, priority=5)
    repo.job_ids[m.id] = ["job-1", "job-2"]
    view = service.get_mission(m.id)
    assert view["mission"]["id"] == m.id
    assert view["job_ids"] == ["job-1", "job-2"]
    assert view["workers"] == []
    assert view["effective_priority"] == compute_effective_priority(POLICY_REALTIME, 5, "normal")
    assert any(e["action"] == "created" for e in view["journal"])


def test_list_filters_by_status_and_label(svc):
    service, _, _ = svc
    a = service.create_mission("A", labels=["finance"])
    service.create_mission("B", labels=["career"])
    service.activate(a.id)
    assert [m.id for m in service.list_missions(status=MISSION_ACTIVE)] == [a.id]
    assert [m.id for m in service.list_missions(label="finance")] == [a.id]
    assert [m.id for m in service.list_missions(label="career")][0] != a.id


def test_update_arbitration_and_effective_priority(svc):
    service, _, _ = svc
    m = service.create_mission("Trade")
    updated = service.update_arbitration(
        m.id, scheduling_policy=POLICY_REALTIME, priority=10, criticality=CRIT_CRITICAL
    )
    assert updated.effective_priority == compute_effective_priority(POLICY_REALTIME, 10, CRIT_CRITICAL)


def test_budget_max_concurrent_tasks(svc):
    service, _, _ = svc
    m = service.create_mission("Batch", budget={"max_concurrent_tasks": 3})
    assert m.max_concurrent_tasks == 3
    assert service.create_mission("Uncapped").max_concurrent_tasks is None


def test_health_check_reports_active_count(svc):
    service, _, _ = svc
    m = service.create_mission("A")
    service.activate(m.id)
    status = service.health_check()
    assert status.healthy
    assert status.data["active"] == 1


# --- pure helper ---------------------------------------------------------


def test_effective_priority_bands():
    assert compute_effective_priority("exclusive", 0, "normal") == 80
    assert compute_effective_priority("idle", 0, "low") == -20
    assert compute_effective_priority("background", 5, "high") == 45
    # unknown values fall back to neutral band/weight (never crash scheduling)
    assert compute_effective_priority("bogus", 0, "bogus") == 20
