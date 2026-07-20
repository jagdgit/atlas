"""Operations Dashboard + host metrics tests (Phase 0 · ATLAS_OS_ROADMAP §5.11, A4).

Hermetic: host metrics read real stdlib sources (disk/cpu counts) but assertions stay
environment-independent; internet is injected; the dashboard runs over a fake
Application so no kernel/DB is needed.
"""

from __future__ import annotations

from typing import Any

from atlas.ops.dashboard import OperationsDashboard
from atlas.system.host import HostMetrics


# --- host metrics --------------------------------------------------------

def test_host_snapshot_has_all_sections():
    host = HostMetrics(check_internet=lambda: True)
    snap = host.snapshot()
    for key in ("cpu", "memory", "disk", "load", "internet", "temperature", "ups"):
        assert key in snap


def test_host_disk_reports_percent(tmp_path):
    host = HostMetrics(disk_path=tmp_path)
    disk = host.disk()
    assert disk["total"] and disk["total"] > 0
    assert 0.0 <= disk["percent"] <= 100.0


def test_host_cpu_reports_core_count():
    cpu = HostMetrics().cpu()
    assert "percent" in cpu and "count" in cpu


def test_host_internet_injected_and_cached():
    calls = {"n": 0}

    def check() -> bool:
        calls["n"] += 1
        return True

    host = HostMetrics(check_internet=check, internet_cache_seconds=60)
    assert host.internet() == {"reachable": True}
    host.internet()  # cached — no second call
    assert calls["n"] == 1


def test_host_internet_reports_disconnected():
    host = HostMetrics(check_internet=lambda: False)
    assert host.internet() == {"reachable": False}


def test_host_ups_not_present():
    assert HostMetrics().ups() == {"present": False}


def test_host_bad_metric_degrades_to_empty():
    host = HostMetrics()

    def boom() -> dict:
        raise RuntimeError("no sensor")

    # _safe wraps each metric so the snapshot never propagates a failure.
    assert host._safe(boom) == {}


# --- dashboard -----------------------------------------------------------

class FakeCaps:
    def describe(self) -> dict[str, dict[str, Any]]:
        return {"clock": {"kind": "kernel", "version": "0.1.0", "enabled": True}}


class FakeBackup:
    def list_backups(self):
        from pathlib import Path

        return [Path("atlas_20260101.dump"), Path("atlas_20251231.dump")]


class FakeStorage:
    def health_check(self):
        from atlas.services.base import HealthStatus

        return HealthStatus.ok("storage ready", root="/data/storage")


class FakeJobs:
    def list_jobs(self, limit=500):
        return [
            {"status": "running"},
            {"status": "queued"},
            {"status": "completed"},
        ]


class FakeNotifier:
    def __init__(self):
        from atlas.notify import EventBroker

        self.broker = EventBroker()


class FakeContainer:
    def __init__(self, mapping):
        self._mapping = mapping

    def resolve(self, key):
        if key not in self._mapping:
            raise KeyError(key)
        return self._mapping[key]


class FakeApp:
    def __init__(self, mapping):
        self.capabilities = FakeCaps()
        self.container = FakeContainer(mapping)

    def status(self):
        return {
            "version": "0.1.0",
            "uptime_seconds": 5.0,
            "healthy": True,
            "degraded": False,
            "services_total": 3,
            "severity_counts": {"ok": 3, "degraded": 0, "failed": 0},
        }


def _dashboard(mapping=None):
    mapping = mapping if mapping is not None else {
        "jobs": FakeJobs(),
        "backup": FakeBackup(),
        "storage": FakeStorage(),
        "notifier": FakeNotifier(),
    }
    app = FakeApp(mapping)
    host = HostMetrics(check_internet=lambda: True)
    return OperationsDashboard(app, host)


class FakeRecovery:
    def last_report(self):
        return {
            "run_id": "run-1", "status": "completed", "ok": True,
            "steps": [{"name": "storage_integrity", "ok": True, "detail": "3/3 verified"}],
        }


class FakeCheckpoints:
    def most_recent(self):
        return {"owner_type": "job", "owner_id": "j1", "label": "default", "updated_at": "2026-01-01T00:00:00Z"}


def test_dashboard_snapshot_shape():
    snap = _dashboard().snapshot()
    for key in ("atlas", "counts", "host", "backup", "storage", "capabilities",
                "sse_subscribers", "recovery", "last_checkpoint", "self_improvement",
                "generated_at"):
        assert key in snap


def test_dashboard_self_improvement_board(tmp_path):
    from atlas.improvement.board import ImprovementBoard

    board = ImprovementBoard(tmp_path)
    board.record_run(
        metrics={"retrieval_hermetic.precision_at_k": 0.9},
        findings=[{"id": "f1", "metric": "x", "kind": "regression"}],
        recommendation={"kind": "investigate", "finding_id": "f1"},
        milestone="3B.0",
    )
    snap = _dashboard(mapping={"improvement_board": board}).snapshot()
    assert snap["self_improvement"]["finding_count"] == 1
    assert snap["self_improvement"]["last_run"]["milestone"] == "3B.0"


def test_dashboard_reports_recovery_and_checkpoint():
    mapping = {"recovery": FakeRecovery(), "checkpoints": FakeCheckpoints()}
    snap = _dashboard(mapping=mapping).snapshot()
    assert snap["recovery"]["status"] == "completed" and snap["recovery"]["ok"] is True
    assert snap["recovery"]["steps"][0]["name"] == "storage_integrity"
    assert snap["last_checkpoint"]["owner_id"] == "j1"


def test_dashboard_counts_jobs():
    counts = _dashboard().snapshot()["counts"]
    assert counts["jobs_total"] == 3
    assert counts["jobs_active"] == 2   # running + queued
    assert counts["jobs_queued"] == 1
    assert counts["workers"] == 0 and counts["missions"] == 0


def test_dashboard_backup_summary():
    backup = _dashboard().snapshot()["backup"]
    assert backup["count"] == 2
    assert backup["last"] == "atlas_20260101.dump"


def test_dashboard_capabilities_flattened():
    caps = _dashboard().snapshot()["capabilities"]
    assert caps == [{"name": "clock", "kind": "kernel", "version": "0.1.0", "enabled": True}]


def test_dashboard_tolerates_missing_services():
    # No jobs/backup/storage/notifier registered → sections degrade, snapshot still whole.
    snap = _dashboard(mapping={}).snapshot()
    assert snap["counts"]["jobs_total"] == 0
    assert snap["backup"] == {"last": None, "count": 0}
    assert snap["storage"] == {}
    assert snap["sse_subscribers"] == 0


def test_dashboard_atlas_status_passthrough():
    atlas = _dashboard().snapshot()["atlas"]
    assert atlas["version"] == "0.1.0"
    assert atlas["severity_counts"]["ok"] == 3
