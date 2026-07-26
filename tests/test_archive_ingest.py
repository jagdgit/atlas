"""Archive ingest — parallel Owner Knowledge jobs + worker progress enrichment."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from atlas.missions.archive import ArchiveIngestService
from atlas.workers.manager import WorkerManager


class _FakeTemplates:
    def __init__(self):
        self.calls: list[dict] = []

    def instantiate(self, name, **kwargs):
        self.calls.append({"name": name, **kwargs})
        mid = str(uuid4())
        wid = str(uuid4())
        return {
            "mission": SimpleNamespace(id=mid, title=kwargs.get("title")),
            "workers": [SimpleNamespace(id=wid, type="owner_knowledge")],
        }


class _FakeWorkers:
    def __init__(self):
        self.inputs: list[tuple[str, dict]] = []
        self._rows: list[dict] = []
        self.paused: list = []

    def enqueue_input(self, worker_id, payload):
        self.inputs.append((str(worker_id), dict(payload)))

    def pause(self, worker_id, reason=""):
        self.paused.append((str(worker_id), reason))

    def list_workers(self, **_kwargs):
        return list(self._rows)

    def enrich_worker(self, worker):
        data = dict(worker) if isinstance(worker, dict) else worker.to_dict()
        data["checkpoint"] = {"roots": [], "progress": None}
        data["is_archive"] = data.get("type") == "owner_knowledge"
        data["has_progress"] = False
        return data

    def list_workers_enriched(self, **kwargs):
        return [self.enrich_worker(w) for w in self.list_workers(**kwargs)]


class _FakeMaterials:
    def __init__(self):
        self.shares: list[dict] = []
        self._personal = _FakePersonal()

    def share(self, path, **kwargs):
        out = {"ok": True, "path": path, **kwargs}
        self.shares.append(out)
        return out


class _FakePersonal:
    def __init__(self):
        self.notes: list[dict] = []

    def note_project_period(self, **kwargs):
        self.notes.append(kwargs)
        return {"ok": True, **kwargs}


def test_archive_start_parallel_new_mission(tmp_path: Path):
    archive = tmp_path / "Certificates"
    archive.mkdir()
    (archive / "a.pdf").write_bytes(b"%PDF")
    templates = _FakeTemplates()
    workers = _FakeWorkers()
    materials = _FakeMaterials()
    svc = ArchiveIngestService(
        templates=templates, workers=workers, materials=materials
    )
    out = svc.start(
        str(archive),
        kind="document",
        parallel=True,
        note="work 2022-2025",
        period_start="2022",
        period_end="2025-03",
    )
    assert out["ok"] is True
    assert out["mode"] == "parallel_mission"
    assert out["admission"]["status"] == "accepted"
    assert out["mission_id"]
    assert out["worker_ids"]
    assert templates.calls and templates.calls[0]["name"] == "owner_knowledge"
    assert "archive_ingest" in templates.calls[0]["labels"]
    assert workers.inputs  # force nudge
    assert materials._personal.notes


def test_archive_start_shared_uses_materials(tmp_path: Path):
    archive = tmp_path / "notes"
    archive.mkdir()
    templates = _FakeTemplates()
    materials = _FakeMaterials()
    svc = ArchiveIngestService(templates=templates, materials=materials)
    out = svc.start(str(archive), parallel=False, kind="document")
    assert out["mode"] == "shared_mission"
    assert materials.shares
    assert not templates.calls


def test_archive_status_filters_owner_knowledge():
    workers = _FakeWorkers()
    workers._rows = [
        {"id": "1", "type": "paper_trading", "status": "running"},
        {"id": "2", "type": "owner_knowledge", "status": "running", "mission_id": "m"},
    ]
    svc = ArchiveIngestService(workers=workers)
    out = svc.status(limit=10)
    assert out["count"] == 1
    assert out["workers"][0]["type"] == "owner_knowledge"


def test_enrich_worker_surfaces_root_progress():
    class _Repo:
        def __init__(self, worker):
            self.worker = worker

        def get(self, _id):
            return self.worker

        def list(self, **_kwargs):
            return [self.worker]

    class _Ckpt:
        def load(self, _owner, _wid):
            return {
                "roots": {
                    "/media/usb/Certificates": {
                        "kind": "document",
                        "complete": False,
                        "progress": {
                            "done": 12,
                            "total": 100,
                            "pending": 88,
                            "last_file": "a.pdf",
                        },
                    }
                },
                "ticks": 3,
            }

    wid = uuid4()

    def to_dict():
        return {
            "id": str(wid),
            "type": "owner_knowledge",
            "status": "running",
            "health": "healthy",
            "worker_version": 2,
            "restart_count": 0,
            "mission_id": "m1",
        }

    worker = SimpleNamespace(
        id=wid,
        type="owner_knowledge",
        status="running",
        health="healthy",
        worker_version=2,
        restart_count=0,
        mission_id="m1",
        to_dict=to_dict,
    )
    mgr = WorkerManager.__new__(WorkerManager)
    mgr._repo = _Repo(worker)
    mgr._checkpoints = _Ckpt()
    enriched = mgr.enrich_worker(worker)
    assert enriched["is_archive"] is True
    assert enriched["has_progress"] is True
    roots = enriched["checkpoint"]["roots"]
    assert len(roots) == 1
    assert roots[0]["done"] == 12
    assert roots[0]["total"] == 100
    assert roots[0]["name"] == "Certificates"
