"""Host Guard — slow-but-reliable admission under machine limits."""

from __future__ import annotations

from types import SimpleNamespace

from atlas.core.resources.host_guard import HostGuardService
from atlas.core.resources.manager import ResourceManager
from atlas.core.resources.monitor import SystemSnapshot


class _FakeResources:
    def __init__(self, *, allow: bool = True, reason: str = "admitted"):
        self.allow = allow
        self.reason = reason
        self.calls = 0

    def can_admit_tick(self, **_kwargs):
        self.calls += 1
        from atlas.core.resources.manager import AdmissionDecision

        return AdmissionDecision(
            allowed=self.allow,
            reason=self.reason,
            cost_units=0,
            expected_ram_mb=512,
            llm_slots=0,
            budget_units=20,
        )

    def host_guard_status(self, **_kwargs):
        return {
            "throttled": not self.allow,
            "tick_would_admit": self.allow,
            "tick_admit_reason": self.reason,
        }


class _FakeWorkers:
    def __init__(self):
        self.rows = []
        self.resumed = []

    def list_workers(self, status=None, **_kwargs):
        rows = list(self.rows)
        if status:
            rows = [w for w in rows if w.status == status]
        return rows

    def resume(self, worker_id, reason=""):
        self.resumed.append((str(worker_id), reason))
        for w in self.rows:
            if str(w.id) == str(worker_id):
                w.status = "running"
                w.metadata = {}
                return w
        raise KeyError(worker_id)


def test_can_run_tick_defers_under_pressure():
    resources = _FakeResources(allow=False, reason="RAM used 90%")
    guard = HostGuardService(resources=resources, max_concurrent_ticks=4)
    ok, reason = guard.can_run_tick()
    assert ok is False
    assert "RAM" in reason
    assert guard.status()["deferred_ticks_total"] == 1


def test_can_run_tick_admits_when_safe():
    resources = _FakeResources(allow=True)
    guard = HostGuardService(resources=resources)
    ok, reason = guard.can_run_tick()
    assert ok is True
    assert reason == "admitted"


def test_archive_slots_and_queue_flag():
    workers = _FakeWorkers()
    workers.rows = [
        SimpleNamespace(
            id="a1", type="owner_knowledge", status="running", metadata={}
        )
    ]
    guard = HostGuardService(
        resources=_FakeResources(), workers=workers, max_archive_workers=1
    )
    assert guard.archive_slots_free() == 0
    assert guard.should_queue_archive_start() is True


def test_host_guard_tick_resumes_queued_worker():
    workers = _FakeWorkers()
    workers.rows = [
        SimpleNamespace(
            id="q1",
            type="owner_knowledge",
            status="paused",
            metadata={"queued_for_capacity": True, "queue_reason": "slots full"},
            created_at="2026-01-01",
        )
    ]
    guard = HostGuardService(
        resources=_FakeResources(allow=True),
        workers=workers,
        max_archive_workers=1,
    )
    out = guard.tick({})
    assert out["resumed"] == 1
    assert workers.resumed[0][0] == "q1"


def test_can_admit_tick_respects_reserve(monkeypatch):
    rm = ResourceManager(profile="balanced", host_ram_reserve_mb=2048)

    def fake_snap(_logger=None):
        return SystemSnapshot(
            load_1m=1.0,
            cpu_count=8,
            load_pressure=0.125,
            mem_total_kb=16 * 1024 * 1024,
            mem_available_kb=1500 * 1024,  # 1.5 GiB free < 2 GiB reserve
            ram_used_fraction=0.9,
        )

    monkeypatch.setattr(
        "atlas.core.resources.manager.read_snapshot", fake_snap
    )
    decision = rm.can_admit_tick(expected_ram_mb=512, reserve_mb=2048)
    assert decision.allowed is False
    assert "reserve" in decision.reason.lower() or "RAM" in decision.reason
