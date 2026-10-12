"""J0/F2/F3 — Atlas can inspect itself, and the recurring clock cannot be killed.

Three defects found by the 2026-10-06 north-star audit
(``docs/2026-10-06_NORTH_STAR_AUDIT.md``):

* **J0a/J0b** — no capability could read Atlas's own Postgres or its own logs, so asked
  "diagnose yourself from your logs and database" Atlas was *structurally incapable* and
  silently ran a web search instead.
* **F2/F3** — an unknown handler marked a task permanently failed. When the victim was
  ``schedule_tick``, every recurring schedule froze for 45 minutes while the service
  still reported healthy.
"""

from __future__ import annotations

import time

import pytest

from atlas.plugins.logs_plugin import LogsPlugin, redact
from atlas.scheduler.service import SchedulerService
from atlas.sql.client import SQLClient, SQLExecError
from atlas.sql.postgres_backend import PostgresBackend, RoutingBackend, is_secret_column


# --------------------------------------------------------------------------
# J0a — read-only Postgres self-inspection
# --------------------------------------------------------------------------
class _FakeBackend:
    """Minimal SQLBackend recording what it was asked for."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.queries: list[tuple[str, str]] = []

    def query(self, source, sql, params, *, max_rows, timeout):
        self.queries.append((source, sql))
        return ["n"], [(1,)], False

    def tables(self, source):
        self.queries.append((source, "<tables>"))
        return [f"{self.name}.t"]

    def schema(self, source, table):
        self.queries.append((source, f"<schema {table}>"))
        return [{"name": "c"}]


def test_routing_backend_sends_atlas_source_to_postgres_and_rest_to_sqlite():
    sqlite, pg = _FakeBackend("sqlite"), _FakeBackend("postgres")
    router = RoutingBackend(sqlite, pg, self_source="atlas")

    router.query("atlas", "select 1", None, max_rows=10, timeout=1)
    router.query("notes.db", "select 1", None, max_rows=10, timeout=1)

    assert len(pg.queries) == 1, "the reserved source must reach Atlas's own database"
    assert len(sqlite.queries) == 1, "every other source must keep the sandbox default"


def test_routing_backend_treats_atlas_dot_schema_as_a_schema_filter():
    sqlite, pg = _FakeBackend("sqlite"), _FakeBackend("postgres")
    router = RoutingBackend(sqlite, pg, self_source="atlas")

    router.tables("atlas.scheduler")

    assert pg.queries == [("scheduler", "<tables>")]


def test_write_statements_are_blocked_before_reaching_the_database():
    """The statement guard runs in SQLClient, so the backend is never even called."""
    pg = _FakeBackend("postgres")
    client = SQLClient(RoutingBackend(_FakeBackend("sqlite"), pg, self_source="atlas"))

    for sql in (
        "delete from scheduler.tasks",
        "update scheduler.tasks set status='x'",
        "drop table scheduler.tasks",
        "select 1; drop table scheduler.tasks",
    ):
        assert client.query(sql, source="atlas")["outcome"] == "blocked", sql
    assert pg.queries == [], "a mutating statement must never reach the backend"


def test_credential_relations_are_refused():
    backend = PostgresBackend(
        host="localhost", port=1, dbname="x", user="u", password="p"
    )
    for sql in ("select * from pg_authid", "select rolpassword from pg_shadow"):
        with pytest.raises(SQLExecError):
            backend.query("", sql, None, max_rows=1, timeout=1)


def test_secret_column_detection_does_not_treat_sizes_as_secrets():
    assert is_secret_column("access_token")
    assert is_secret_column("api_key")
    assert is_secret_column("password")
    # Sizes and counts are diagnostics, not secrets — the operator relies on these.
    assert not is_secret_column("token_count")
    assert not is_secret_column("token_len")


# --------------------------------------------------------------------------
# J0b — log reading, confined and redacted
# --------------------------------------------------------------------------
@pytest.fixture()
def logs(tmp_path):
    (tmp_path / "atlas.log").write_text(
        "line one\n"
        "2026-10-06 | ERROR | no handler registered for task_type 'schedule_tick'\n"
        "access_token=SUPERSECRETVALUE trailing\n",
        encoding="utf-8",
    )
    (tmp_path / "atlas.log.1").write_text("older rotated line\n", encoding="utf-8")
    return LogsPlugin(tmp_path)


def test_logs_tail_and_search_read_atlas_own_logs(logs):
    assert logs.tail(lines=2)["line_count"] == 2
    found = logs.search(r"no handler registered")
    assert found["outcome"] == "ok" and found["match_count"] == 1
    assert found["matches"][0]["line"] == 2


def test_logs_search_all_covers_rotated_files(logs):
    assert logs.search(r"older rotated", file="all")["match_count"] == 1
    # Scoped to the default file it must not be found.
    assert logs.search(r"older rotated")["outcome"] == "empty"


def test_logs_cannot_escape_the_log_directory(logs):
    assert logs.tail(file="../../../etc/passwd")["outcome"] == "blocked"
    assert logs.search("x", file="../../atlas.env")["outcome"] == "blocked"


def test_log_output_never_carries_a_secret(logs):
    """Logs are quoted into reports and LLM prompts, so redaction is mandatory here."""
    for line in logs.tail(lines=10)["lines"]:
        assert "SUPERSECRETVALUE" not in line
    for match in logs.search("access_token")["matches"]:
        assert "SUPERSECRETVALUE" not in match["text"]


@pytest.mark.parametrize(
    "raw",
    [
        "access_token=abc123def456",
        'request_token: "tok_live_9999"',
        "https://api.example/v1?api_key=SECRETVALUE&z=1",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9abcdef",
        "password = hunter2",
    ],
)
def test_redaction_removes_known_secret_shapes(raw):
    cleaned = redact(raw)
    assert "[redacted]" in cleaned
    for leak in ("abc123def456", "tok_live_9999", "SECRETVALUE", "eyJhbGci", "hunter2"):
        assert leak not in cleaned


def test_redaction_keeps_non_secret_token_sizes():
    assert redact("token_len=32 token_count=9") == "token_len=32 token_count=9"


# --------------------------------------------------------------------------
# F3 — an unknown handler releases the task instead of killing it
# --------------------------------------------------------------------------
class _Repo:
    """Task repo double that records how a task was disposed of."""

    def __init__(self, *, can_release: bool = True) -> None:
        self.can_release = can_release
        self.released: list[tuple[str, float]] = []
        self.failed_permanent: list[str] = []
        self.runs_finished: list[tuple[str, str]] = []

    def start_run(self, task_id, worker_id):
        return {"id": "run-1"}

    def finish_run(self, run_id, status, result=None, error=None):
        self.runs_finished.append((status, error or ""))

    def release_to_pending(self, task_id, delay_seconds=0.0, error=None):
        if not self.can_release:
            return False
        self.released.append((str(task_id), float(delay_seconds)))
        return True

    def mark_failed_permanent(self, task_id, error):
        self.failed_permanent.append(str(task_id))
        return True


def _task(task_type: str = "schedule_tick") -> dict:
    return {
        "id": "t-1",
        "task_type": task_type,
        "payload": {},
        "retry_count": 0,
        "max_retries": 5,
    }


def test_unknown_handler_releases_the_task_and_consumes_no_retry():
    repo = _Repo()
    svc = SchedulerService(task_repo=repo)

    svc._run_task(_task(), "worker-0")

    assert repo.released == [("t-1", 5.0)], "the task must go back to pending"
    assert repo.failed_permanent == [], (
        "marking schedule_tick permanently failed is what froze all 107 schedules"
    )


def test_unknown_handler_falls_back_to_failing_when_it_cannot_be_released():
    repo = _Repo(can_release=False)
    svc = SchedulerService(task_repo=repo)

    svc._run_task(_task(), "worker-0")

    assert repo.failed_permanent == ["t-1"], "a task must not be left claimed forever"


def test_unknown_handler_does_not_record_without_a_failure_dir():
    """Guards the live data dir: tests must never write into /data/atlas_data."""
    repo = _Repo()
    svc = SchedulerService(task_repo=repo)
    assert svc._failure_data_dir is None
    svc._run_task(_task("demo_type"), "worker-0")  # must not raise


# --------------------------------------------------------------------------
# F2 — the recurring clock heals itself after sustained idleness
# --------------------------------------------------------------------------
def test_sustained_idle_reseeds_the_recurring_clock():
    calls: list[int] = []
    svc = SchedulerService(
        task_repo=_Repo(),
        idle_callback=lambda: calls.append(1),
        idle_heal_after=0.05,
    )

    svc._maybe_heal_idle()  # first observation only starts the idle clock
    assert calls == []

    time.sleep(0.06)
    svc._maybe_heal_idle()
    assert calls == [1], "a frozen schedule_tick must be re-seeded by the worker loop"


def test_idle_heal_is_rate_limited():
    calls: list[int] = []
    svc = SchedulerService(
        task_repo=_Repo(),
        idle_callback=lambda: calls.append(1),
        idle_heal_after=0.05,
    )
    svc._maybe_heal_idle()
    time.sleep(0.06)
    svc._maybe_heal_idle()
    svc._maybe_heal_idle()  # immediately again — must not re-fire
    assert calls == [1]


def test_claiming_work_clears_the_idle_clock():
    calls: list[int] = []
    svc = SchedulerService(
        task_repo=_Repo(),
        idle_callback=lambda: calls.append(1),
        idle_heal_after=0.05,
    )
    svc._maybe_heal_idle()
    time.sleep(0.06)
    svc._mark_busy()  # work arrived: Atlas is not stalled
    svc._maybe_heal_idle()
    assert calls == [], "a busy scheduler must never be treated as a frozen clock"


def test_idle_heal_survives_a_failing_callback():
    def boom() -> None:
        raise RuntimeError("no")

    svc = SchedulerService(task_repo=_Repo(), idle_callback=boom, idle_heal_after=0.01)
    svc._maybe_heal_idle()
    time.sleep(0.02)
    svc._maybe_heal_idle()  # must not propagate — the worker loop has to keep running
