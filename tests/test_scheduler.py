"""Tests for the scheduler service.

The retry/failure logic is tested with a fake repo (no DB). Integration tests
exercise real workers against ``scheduler.*`` tables and skip if the DB is down.
"""

from __future__ import annotations

import time
import uuid

import psycopg
import pytest

from atlas.config import get_config
from atlas.database.connection import DatabaseManager
from atlas.repositories.task_repo import TaskRepository
from atlas.scheduler.handlers import HandlerRegistry
from atlas.scheduler.service import SchedulerService


# --- HandlerRegistry -----------------------------------------------------
def test_handler_registry():
    reg = HandlerRegistry()
    assert not reg.has("embed")
    reg.register("embed", lambda p: {"ok": True})
    assert reg.has("embed")
    assert reg.get("embed")({}) == {"ok": True}
    assert reg.types() == ["embed"]


# --- failure / retry logic (no DB) ---------------------------------------
class FakeRepo:
    def __init__(self) -> None:
        self.runs: list[dict] = []
        self.finished: list[tuple] = []
        self.completed: list = []
        self.failed: list[tuple] = []
        self.rescheduled: list[tuple] = []
        self._retry_counts: dict = {}

    def start_run(self, task_id, worker_id):
        run = {"id": uuid.uuid4(), "task_id": task_id}
        self.runs.append(run)
        return run

    def finish_run(self, run_id, status, result=None, error=None):
        self.finished.append((run_id, status, result, error))
        return True

    def mark_completed(self, task_id):
        self.completed.append(task_id)
        return True

    def mark_failed_permanent(self, task_id, error=None):
        self.failed.append((task_id, error))
        return True

    def reschedule_for_retry(self, task_id, delay_seconds, error=None):
        count = self._retry_counts.get(task_id, 0) + 1
        self._retry_counts[task_id] = count
        self.rescheduled.append((task_id, delay_seconds, error))
        return count


def _task(**over):
    base = {
        "id": uuid.uuid4(),
        "task_type": "demo",
        "payload": {},
        "retry_count": 0,
        "max_retries": 3,
    }
    base.update(over)
    return base


def _service(repo, handlers=None):
    return SchedulerService(repo, handlers or HandlerRegistry(), events=None)


def test_success_marks_completed():
    repo = FakeRepo()
    handlers = HandlerRegistry()
    handlers.register("demo", lambda p: {"done": True})
    svc = _service(repo, handlers)

    task = _task()
    svc._run_task(task, "worker-0")

    assert repo.completed == [task["id"]]
    assert repo.finished[0][1] == "completed"
    assert repo.finished[0][2] == {"done": True}


def test_missing_handler_fails_permanently():
    repo = FakeRepo()
    svc = _service(repo)  # empty registry

    task = _task(task_type="unknown")
    svc._run_task(task, "worker-0")

    assert repo.failed and repo.failed[0][0] == task["id"]
    assert not repo.rescheduled


def test_failure_reschedules_when_retries_left():
    repo = FakeRepo()
    handlers = HandlerRegistry()
    handlers.register("demo", lambda p: (_ for _ in ()).throw(ValueError("boom")))
    svc = _service(repo, handlers)

    task = _task(retry_count=0, max_retries=2)
    svc._run_task(task, "worker-0")

    assert repo.rescheduled and not repo.failed
    assert repo.finished[0][1] == "failed"
    assert "boom" in repo.finished[0][3]


def test_failure_permanent_when_exhausted():
    repo = FakeRepo()
    handlers = HandlerRegistry()
    handlers.register("demo", lambda p: (_ for _ in ()).throw(ValueError("boom")))
    svc = _service(repo, handlers)

    task = _task(retry_count=2, max_retries=2)  # no retries left
    svc._run_task(task, "worker-0")

    assert repo.failed and not repo.rescheduled


def test_backoff_grows_exponentially():
    repo = FakeRepo()
    handlers = HandlerRegistry()
    handlers.register("demo", lambda p: (_ for _ in ()).throw(RuntimeError("x")))
    svc = SchedulerService(repo, handlers, events=None, backoff_base=2.0)

    svc._run_task(_task(retry_count=0, max_retries=5), "w")
    svc._run_task(_task(retry_count=3, max_retries=5), "w")

    delays = [r[1] for r in repo.rescheduled]
    assert delays == [2.0, 16.0]  # 2*2^0, 2*2^3


# --- graceful drain (S22, real worker threads, no DB) --------------------
class DrainRepo(FakeRepo):
    """Serves exactly one task, then None — so a worker runs it once and idles."""

    def __init__(self) -> None:
        super().__init__()
        self._served = False

    def recover_interrupted(self) -> int:
        return 0

    def claim_next(self, worker_id):
        if self._served:
            return None
        self._served = True
        return _task(task_type="slow")


def test_stop_drains_inflight_task():
    import threading

    started = threading.Event()
    release = threading.Event()
    repo = DrainRepo()
    handlers = HandlerRegistry()

    def _slow(_payload):
        started.set()
        release.wait(timeout=5)
        return {"done": True}

    handlers.register("slow", _slow)
    svc = SchedulerService(repo, handlers, events=None, workers=1,
                           poll_interval=0.02, drain_timeout=5.0)
    svc.start()
    assert started.wait(timeout=2), "worker never picked up the task"
    release.set()  # let the in-flight task finish during the drain window
    svc.stop()
    # Drain waited for completion rather than abandoning it.
    assert repo.completed, "in-flight task was not allowed to finish"


def test_stop_abandons_after_drain_timeout():
    import threading

    started = threading.Event()
    never = threading.Event()  # never set → the task blocks past the drain budget
    repo = DrainRepo()
    handlers = HandlerRegistry()

    def _stuck(_payload):
        started.set()
        never.wait(timeout=5)
        return {"done": True}

    handlers.register("slow", _stuck)
    svc = SchedulerService(repo, handlers, events=None, workers=1,
                           poll_interval=0.02, drain_timeout=0.2)
    svc.start()
    assert started.wait(timeout=2)
    t0 = time.time()
    svc.stop()  # should give up after ~drain_timeout, not hang
    elapsed = time.time() - t0
    assert elapsed < 2.0
    assert not repo.completed  # task was abandoned (recovered on next boot)
    never.set()  # unblock the abandoned thread so it can exit cleanly


# --- integration (real DB) ----------------------------------------------
def _db_or_skip() -> DatabaseManager:
    # Fast probe (2s) so the suite doesn't hang on the pool's 30s timeout
    # when Postgres is down.
    conninfo = get_config().database.conninfo
    try:
        with psycopg.connect(conninfo, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {exc}")
    return DatabaseManager()


def _wait_for(fn, timeout=5.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn():
            return True
        time.sleep(interval)
    return False


def test_integration_task_completes():
    db = _db_or_skip()
    repo = TaskRepository(db)
    handlers = HandlerRegistry()
    seen: list[dict] = []
    handlers.register("test_echo", lambda p: seen.append(p) or {"echoed": p})

    svc = SchedulerService(
        repo, handlers, events=None, workers=1, poll_interval=0.05
    )
    task = repo.create("test_echo", {"msg": "hi"})
    try:
        svc.start()
        assert _wait_for(lambda: repo.get(task["id"])["status"] == "completed")
    finally:
        svc.stop()
        repo.delete(task["id"])
        db.close()

    assert seen == [{"msg": "hi"}]


def test_integration_retry_then_fail():
    db = _db_or_skip()
    repo = TaskRepository(db)
    handlers = HandlerRegistry()
    handlers.register(
        "test_boom", lambda p: (_ for _ in ()).throw(ValueError("always"))
    )

    svc = SchedulerService(
        repo, handlers, events=None, workers=1, poll_interval=0.05, backoff_base=0.0
    )
    task = repo.create("test_boom", {}, max_retries=2)
    try:
        svc.start()
        assert _wait_for(lambda: repo.get(task["id"])["status"] == "failed")
        row = repo.get(task["id"])
        runs = repo.fetch_all(
            "SELECT * FROM scheduler.task_runs WHERE task_id = %s", (str(task["id"]),)
        )
    finally:
        svc.stop()
        repo.delete(task["id"])
        db.close()

    assert row["retry_count"] == 2
    assert len(runs) == 3  # initial attempt + 2 retries
    assert all(r["status"] == "failed" for r in runs)


def test_integration_crash_recovery():
    db = _db_or_skip()
    repo = TaskRepository(db)
    task = repo.create("test_stuck", {})
    try:
        repo.set_status(task["id"], "running")  # simulate a crash mid-run
        recovered = repo.recover_interrupted()
        assert recovered >= 1
        assert repo.get(task["id"])["status"] == "pending"
    finally:
        repo.delete(task["id"])
        db.close()
