"""IR-RO1 — Resource Planner + Admission Contracts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from atlas.core.resources.admission import (
    STATUS_ACCEPTED,
    STATUS_DEFERRED,
    STATUS_NEEDS_CONFIRMATION,
    STATUS_REJECTED,
    ResourcePlanner,
    WorkEstimate,
)
from atlas.missions.archive import ArchiveIngestService


class _FakeTemplates:
    def __init__(self):
        self.calls: list[dict] = []

    def instantiate(self, name, **kwargs):
        self.calls.append({"name": name, **kwargs})
        return {
            "mission": SimpleNamespace(id="m-1", title=kwargs.get("title")),
            "workers": [SimpleNamespace(id="w-1", type="owner_knowledge")],
        }


class _FakeWorkers:
    def __init__(self):
        self.inputs: list = []
        self.paused: list = []

    def enqueue_input(self, worker_id, payload):
        self.inputs.append((str(worker_id), dict(payload)))

    def pause(self, worker_id, reason=""):
        self.paused.append((str(worker_id), reason))


class _FakeGuard:
    def __init__(self, *, queue: bool = False, admit: bool = True, reason: str = "ok"):
        self.queue = queue
        self.admit = admit
        self.reason = reason
        self.marked = 0

    def should_queue_archive_start(self):
        return self.queue

    def can_run_tick(self, **_kwargs):
        return self.admit, self.reason

    def mark_queued_start(self):
        self.marked += 1


def test_estimate_archive_counts_files(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    for i in range(5):
        (root / f"f{i}.txt").write_text("hello")
    planner = ResourcePlanner()
    est = planner.estimate_archive(root, files_per_tick=40)
    assert est.file_count == 5
    assert est.duration_seconds is not None
    assert est.storage_growth_mb is not None
    assert est.risk in {"low", "medium", "high"}


def test_admit_small_archive_accepted(tmp_path: Path):
    root = tmp_path / "small"
    root.mkdir()
    (root / "a.pdf").write_bytes(b"%PDF")
    planner = ResourcePlanner(host_guard=_FakeGuard())
    contract = planner.admit_archive(path=str(root), kind="document")
    assert contract.status == STATUS_ACCEPTED
    assert contract.run_mode == "immediate"
    assert contract.allows_create


def test_admit_deferred_when_slots_full(tmp_path: Path):
    root = tmp_path / "q"
    root.mkdir()
    (root / "a.txt").write_text("x")
    planner = ResourcePlanner(host_guard=_FakeGuard(queue=True))
    contract = planner.admit_archive(path=str(root))
    assert contract.status == STATUS_DEFERRED
    assert "slots" in contract.reason
    assert contract.allows_create


def test_admit_needs_confirmation_for_large_estimate(tmp_path: Path):
    root = tmp_path / "big"
    root.mkdir()
    (root / "a.txt").write_text("x")
    planner = ResourcePlanner(
        host_guard=_FakeGuard(),
        confirm_file_count=1,  # force confirm even for 1 file
    )
    # file_count will be 1 >= 1
    contract = planner.admit_archive(path=str(root))
    assert contract.status == STATUS_NEEDS_CONFIRMATION
    assert contract.confirmation_token
    assert not contract.allows_create


def test_confirm_token_then_accepted(tmp_path: Path):
    root = tmp_path / "big2"
    root.mkdir()
    (root / "a.txt").write_text("x")
    planner = ResourcePlanner(host_guard=_FakeGuard(), confirm_file_count=1)
    first = planner.admit_archive(path=str(root))
    assert first.status == STATUS_NEEDS_CONFIRMATION
    second = planner.admit_archive(
        path=str(root),
        confirmation_token=first.confirmation_token,
    )
    assert second.status == STATUS_ACCEPTED


def test_reject_missing_path():
    planner = ResourcePlanner()
    contract = planner.admit_archive(path="/no/such/archive/path-xyz")
    assert contract.status == STATUS_REJECTED


def test_realtime_fast_path():
    planner = ResourcePlanner()
    c = planner.admit_realtime(
        program_id="market_intelligence",
        mission_template="market_observer",
    )
    assert c.status == STATUS_ACCEPTED
    assert c.run_mode == "immediate"


def test_archive_start_returns_needs_confirmation(tmp_path: Path):
    root = tmp_path / "certs"
    root.mkdir()
    (root / "a.pdf").write_bytes(b"%PDF")
    planner = ResourcePlanner(host_guard=_FakeGuard(), confirm_file_count=1)
    templates = _FakeTemplates()
    svc = ArchiveIngestService(
        templates=templates,
        workers=_FakeWorkers(),
        resource_planner=planner,
        host_guard=_FakeGuard(),
    )
    out = svc.start(str(root), parallel=True)
    assert out["ok"] is False
    assert out["mode"] == "needs_confirmation"
    assert out["confirmation_token"]
    assert not templates.calls


def test_archive_start_confirm_creates_mission(tmp_path: Path):
    root = tmp_path / "certs2"
    root.mkdir()
    (root / "a.pdf").write_bytes(b"%PDF")
    planner = ResourcePlanner(host_guard=_FakeGuard(), confirm_file_count=1)
    templates = _FakeTemplates()
    workers = _FakeWorkers()
    svc = ArchiveIngestService(
        templates=templates,
        workers=workers,
        resource_planner=planner,
        host_guard=_FakeGuard(),
    )
    first = svc.start(str(root), parallel=True)
    token = first["confirmation_token"]
    out = svc.start(str(root), parallel=True, confirm=True, confirmation_token=token)
    assert out["ok"] is True
    assert out["mode"] == "parallel_mission"
    assert out["admission"]["status"] == STATUS_ACCEPTED
    assert templates.calls


def test_archive_start_deferred_pauses_worker(tmp_path: Path):
    root = tmp_path / "q2"
    root.mkdir()
    (root / "a.txt").write_text("x")
    guard = _FakeGuard(queue=True)
    planner = ResourcePlanner(host_guard=guard, confirm_file_count=999999)
    templates = _FakeTemplates()
    workers = _FakeWorkers()
    svc = ArchiveIngestService(
        templates=templates,
        workers=workers,
        resource_planner=planner,
        host_guard=guard,
    )
    out = svc.start(str(root), parallel=True)
    assert out["ok"] is True
    assert out["mode"] == "queued_for_capacity"
    assert out["admission"]["status"] == STATUS_DEFERRED
    assert workers.paused
    assert guard.marked == 1


def test_work_estimate_dict_roundtrip():
    est = WorkEstimate(file_count=10, duration_seconds=120.0, notes=("a",))
    d = est.as_dict()
    assert d["file_count"] == 10
    assert d["notes"] == ["a"]
