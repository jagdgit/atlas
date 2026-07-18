"""Recovery Manager + Checkpoint Store tests (Phase 0 · §2.8, P1/P4).

Hermetic: fakes stand in for the recovery/checkpoint repositories, storage, backup, task
repo, and event bus so we cover the durable/re-entrant run record, storage-integrity and
backup-verification steps, step isolation, boot-never-blocks guarantee, and the checkpoint
save/load/clear foundation — all without a database.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from atlas.recovery import CheckpointStore, RecoveryManager


# --- fakes ---------------------------------------------------------------


class FakeRecoveryRepo:
    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []

    def mark_stale_running_interrupted(self) -> int:
        n = 0
        for r in self.runs:
            if r["status"] == "running":
                r["status"] = "interrupted"
                n += 1
        return n

    def begin(self, host: str | None) -> dict[str, Any]:
        run = {"id": f"run-{len(self.runs) + 1}", "host": host, "status": "running", "steps": []}
        self.runs.append(run)
        return dict(run)

    def finish(self, run_id: str, status: str, steps: list[dict[str, Any]]) -> dict[str, Any] | None:
        for r in self.runs:
            if r["id"] == run_id:
                r["status"] = status
                r["steps"] = steps
                return dict(r)
        return None

    def last(self) -> dict[str, Any] | None:
        return dict(self.runs[-1]) if self.runs else None


class FakeStorage:
    def __init__(self, report: dict[str, Any] | None = None, *, raises: bool = False) -> None:
        self._report = report or {"checked": 3, "ok": 3, "missing": [], "corrupt": []}
        self._raises = raises

    def integrity_check(self) -> dict[str, Any]:
        if self._raises:
            raise RuntimeError("storage exploded")
        return self._report


class FakeBackup:
    def __init__(self, dumps: list[Path]) -> None:
        self._dumps = dumps

    def list_backups(self) -> list[Path]:
        return self._dumps


class FakeTaskRepo:
    def __init__(self, reset: int = 0) -> None:
        self._reset = reset

    def recover_interrupted(self) -> int:
        return self._reset


class FakeEvents:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, payload: dict[str, Any], *, source: str | None = None) -> None:
        self.emitted.append((event_type, payload))


def _step(report: dict[str, Any], name: str) -> dict[str, Any]:
    return next(s for s in report["steps"] if s["name"] == name)


# --- RecoveryManager -----------------------------------------------------


def test_recovery_completes_and_records_durably():
    repo = FakeRecoveryRepo()
    events = FakeEvents()
    mgr = RecoveryManager(
        repo, storage=FakeStorage(), backup=FakeBackup([]), task_repo=FakeTaskRepo(2),
        events=events,
    )
    report = mgr.run()

    assert report["status"] == "completed"
    assert report["ok"] is True
    assert repo.runs[-1]["status"] == "completed"  # durably finished
    assert _step(report, "task_recovery")["data"]["reset"] == 2
    types = [e[0] for e in events.emitted]
    assert types == ["RecoveryStarted", "RecoveryCompleted"]


def test_recovery_marks_prior_interrupted_run_reentrant():
    repo = FakeRecoveryRepo()
    repo.runs.append({"id": "old", "host": "h", "status": "running", "steps": []})  # crash mid-recovery
    mgr = RecoveryManager(repo, storage=FakeStorage())
    report = mgr.run()

    assert report["prior_interrupted"] == 1
    assert repo.runs[0]["status"] == "interrupted"
    assert report["status"] == "completed"


def test_recovery_fails_when_storage_corrupt():
    repo = FakeRecoveryRepo()
    corrupt = {"checked": 3, "ok": 2, "missing": [], "corrupt": ["a/b v1"]}
    mgr = RecoveryManager(repo, storage=FakeStorage(corrupt))
    report = mgr.run()

    assert report["ok"] is False
    assert report["status"] == "failed"
    assert _step(report, "storage_integrity")["ok"] is False
    assert repo.runs[-1]["status"] == "failed"


def test_recovery_backup_verify_flags_empty_dump(tmp_path):
    empty = tmp_path / "atlas_db_20260101.dump"
    empty.write_bytes(b"")  # zero-byte / corrupt backup
    repo = FakeRecoveryRepo()
    mgr = RecoveryManager(repo, storage=FakeStorage(), backup=FakeBackup([empty]))
    report = mgr.run()

    assert _step(report, "backup_verify")["ok"] is False
    assert report["status"] == "failed"


def test_recovery_backup_verify_ok_with_nonempty_dump(tmp_path):
    dump = tmp_path / "atlas_db_20260101.dump"
    dump.write_bytes(b"PGDMP" * 10)
    repo = FakeRecoveryRepo()
    mgr = RecoveryManager(repo, storage=FakeStorage(), backup=FakeBackup([dump]))
    report = mgr.run()

    step = _step(report, "backup_verify")
    assert step["ok"] is True
    assert step["data"]["latest"] == dump.name


def test_recovery_no_backups_is_ok():
    repo = FakeRecoveryRepo()
    mgr = RecoveryManager(repo, storage=FakeStorage(), backup=FakeBackup([]))
    report = mgr.run()
    step = _step(report, "backup_verify")
    assert step["ok"] is True
    assert "no backups" in step["detail"]


def test_recovery_step_exception_is_isolated():
    repo = FakeRecoveryRepo()
    mgr = RecoveryManager(
        repo, storage=FakeStorage(raises=True), task_repo=FakeTaskRepo(1)
    )
    report = mgr.run()

    assert _step(report, "storage_integrity")["ok"] is False  # exception → not ok
    assert _step(report, "task_recovery")["ok"] is True        # other steps still ran
    assert report["status"] == "failed"


def test_recovery_missing_subsystems_degrade_gracefully():
    repo = FakeRecoveryRepo()
    mgr = RecoveryManager(repo)  # no storage/backup/task_repo
    report = mgr.run()
    assert report["status"] == "completed"
    assert all(s["ok"] for s in report["steps"])


def test_recovery_start_never_blocks_boot():
    class Boom(FakeRecoveryRepo):
        def begin(self, host):
            raise RuntimeError("db down")

    mgr = RecoveryManager(Boom(), storage=FakeStorage())
    mgr.start()  # must not raise
    assert mgr.last_report() is None


def test_recovery_health_reflects_last_run():
    repo = FakeRecoveryRepo()
    mgr = RecoveryManager(repo, storage=FakeStorage())
    assert mgr.health_check().level == "degraded"  # not run yet
    mgr.run()
    assert mgr.health_check().level == "ok"


# --- CheckpointStore -----------------------------------------------------


class FakeCheckpointRepo:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._seq = 0

    def save(self, owner_type, owner_id, state, *, label="default"):
        self._seq += 1
        row = {
            "owner_type": owner_type, "owner_id": owner_id, "label": label,
            "state": dict(state), "seq": self._seq,
        }
        self.rows[(owner_type, owner_id, label)] = row
        return dict(row)

    def load(self, owner_type, owner_id, *, label="default"):
        row = self.rows.get((owner_type, owner_id, label))
        return dict(row) if row else None

    def clear(self, owner_type, owner_id, *, label=None):
        keys = [
            k for k in self.rows
            if k[0] == owner_type and k[1] == owner_id and (label is None or k[2] == label)
        ]
        for k in keys:
            del self.rows[k]
        return len(keys)

    def most_recent(self):
        if not self.rows:
            return None
        return dict(max(self.rows.values(), key=lambda r: r["seq"]))


def test_checkpoint_save_load_roundtrip():
    store = CheckpointStore(FakeCheckpointRepo())
    store.save("job", "j1", {"step": 7, "page": 3})
    assert store.load("job", "j1") == {"step": 7, "page": 3}


def test_checkpoint_upsert_overwrites():
    store = CheckpointStore(FakeCheckpointRepo())
    store.save("job", "j1", {"step": 1})
    store.save("job", "j1", {"step": 9})
    assert store.load("job", "j1") == {"step": 9}


def test_checkpoint_load_missing_is_none():
    store = CheckpointStore(FakeCheckpointRepo())
    assert store.load("job", "nope") is None


def test_checkpoint_clear_one_and_all():
    store = CheckpointStore(FakeCheckpointRepo())
    store.save("job", "j1", {"a": 1}, label="default")
    store.save("job", "j1", {"b": 2}, label="phase2")
    assert store.clear("job", "j1", label="phase2") == 1
    assert store.load("job", "j1", label="phase2") is None
    assert store.load("job", "j1") == {"a": 1}
    assert store.clear("job", "j1") == 1
    assert store.load("job", "j1") is None


def test_checkpoint_most_recent():
    store = CheckpointStore(FakeCheckpointRepo())
    store.save("job", "j1", {"a": 1})
    store.save("worker", "w9", {"b": 2})
    recent = store.most_recent()
    assert recent["owner_type"] == "worker" and recent["owner_id"] == "w9"
