"""O6 — retention for the tick tables.

Context: on 2026-10-07 the root filesystem hit 100% with 828 MB free and Postgres
started failing queries with `DiskFull`. `audit.events`, `scheduler.task_runs` and
`scheduler.tasks` held ~37 million rows each, accumulated since 2026-07-11, because
nothing deleted them — `audit.retention_days: 90` was config read by no code.
"""

from __future__ import annotations

import pytest

from atlas.ops.retention import RetentionManager, default_rules

RULES = default_rules(audit_days=30, scheduler_days=14, health_days=30)


class FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql):
        self._conn.sql.append(sql)
        if self._conn.raise_on and self._conn.raise_on in sql:
            raise RuntimeError("boom")
        if sql.strip().upper().startswith("SELECT COUNT"):
            self._result = (self._conn.counts.pop(0) if self._conn.counts else 0,)
        else:
            self.rowcount = self._conn.deletes.pop(0) if self._conn.deletes else 0

    def fetchone(self):
        return self._result


class FakeConn:
    def __init__(self, outer):
        self._outer = outer

    def cursor(self):
        return FakeCursor(self._outer)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeDB:
    def __init__(self, counts=None, deletes=None, raise_on=None):
        self.counts = list(counts or [])
        self.deletes = list(deletes or [])
        self.raise_on = raise_on
        self.sql: list[str] = []

    def connection(self):
        return FakeConn(self)


def _mgr(db, **kw):
    kw.setdefault("enabled", False)
    return RetentionManager(db, RULES, **kw)


# --- dry run ----------------------------------------------------------------


def test_dry_run_counts_but_deletes_nothing():
    db = FakeDB(counts=[100, 200, 300])
    out = _mgr(db).prune()
    assert out.dry_run is True
    assert out.deleted_total == 0
    assert [r["expired"] for r in out.rules] == [100, 200, 300]
    assert not any("DELETE" in s for s in db.sql)


def test_dry_run_is_loud_when_rows_are_expired(caplog):
    db = FakeDB(counts=[36_768_012, 36_695_382, 4_629_957])
    with caplog.at_level("WARNING"):
        _mgr(db).prune()
    assert "DRY RUN" in caplog.text
    assert "retention.enabled=true" in caplog.text


def test_dry_run_stays_quiet_when_nothing_is_expired(caplog):
    db = FakeDB(counts=[0, 0, 0])
    with caplog.at_level("WARNING"):
        _mgr(db).prune()
    assert "DRY RUN" not in caplog.text


# --- deleting ---------------------------------------------------------------


def test_enabled_deletes_in_bounded_batches():
    # 2 full batches then a short one ends the loop for the first rule.
    db = FakeDB(counts=[25, 0, 0], deletes=[10, 10, 5])
    out = _mgr(db, enabled=True, batch_rows=10).prune()
    assert out.dry_run is False
    assert out.deleted_total == 25
    assert sum(1 for s in db.sql if s.startswith("DELETE")) == 3


def test_batch_size_is_honoured_in_the_statement():
    db = FakeDB(counts=[5, 0, 0], deletes=[5])
    _mgr(db, enabled=True, batch_rows=1234).prune()
    delete = next(s for s in db.sql if s.startswith("DELETE"))
    assert "LIMIT 1234" in delete


def test_a_run_cannot_exceed_max_batches():
    # A full-size batch every time would loop forever without the ceiling.
    db = FakeDB(counts=[10_000_000, 0, 0], deletes=[10] * 100)
    out = _mgr(db, enabled=True, batch_rows=10, max_batches=3).prune()
    assert out.deleted_total == 30
    assert sum(1 for s in db.sql if s.startswith("DELETE")) == 3


def test_nothing_expired_means_no_delete_statement():
    db = FakeDB(counts=[0, 0, 0], deletes=[99])
    out = _mgr(db, enabled=True).prune()
    assert out.deleted_total == 0
    assert not any(s.startswith("DELETE") for s in db.sql)


# --- what is eligible -------------------------------------------------------


def test_running_and_pending_tasks_are_never_eligible():
    rule = next(r for r in RULES if r.table == "scheduler.tasks")
    assert "status IN ('completed', 'cancelled')" in rule.where
    assert "running" not in rule.where
    assert "pending" not in rule.where


def test_failed_tasks_are_retained_as_incident_evidence():
    rule = next(r for r in RULES if r.table == "scheduler.tasks")
    assert "failed" not in rule.where


def test_task_runs_has_no_rule_of_its_own_because_the_cascade_covers_it():
    # task_runs.task_id REFERENCES tasks(id) ON DELETE CASCADE.
    assert not any(r.table == "scheduler.task_runs" for r in RULES)
    assert "cascades" in next(r for r in RULES if r.table == "scheduler.tasks").note


def test_audit_retains_decision_history_and_unknown_event_types():
    rule = next(r for r in RULES if r.table == "audit.events")
    # Tick telemetry is listed explicitly, so anything not named is kept.
    assert "TaskCompleted" in rule.where
    assert "DecisionMade" not in rule.where


def test_health_uses_the_column_that_actually_exists():
    # system.health has `checked_at`; `recorded_at` was the plausible guess and wrong.
    rule = next(r for r in RULES if r.table == "system.health")
    assert rule.timestamp_column == "checked_at"


def test_each_rule_carries_the_window_it_was_configured_with():
    db = FakeDB(counts=[1, 1, 1])
    out = _mgr(db).prune()
    assert {r["table"]: r["days"] for r in out.rules} == {
        "scheduler.tasks": 14,
        "audit.events": 30,
        "system.health": 30,
    }
    assert "interval '14 days'" in db.sql[0]


@pytest.mark.parametrize("days", [0, -1])
def test_a_non_positive_window_disables_that_rule(days):
    rules = default_rules(audit_days=days, scheduler_days=days, health_days=days)
    db = FakeDB(counts=[1, 1, 1])
    out = RetentionManager(db, rules, enabled=True).prune()
    assert out.rules == []
    assert db.sql == []


# --- failure handling -------------------------------------------------------


def test_one_failing_table_does_not_stop_the_others():
    db = FakeDB(counts=[5, 5], raise_on="scheduler.tasks")
    out = _mgr(db).prune()
    assert len(out.errors) == 1
    assert "scheduler.tasks" in out.errors[0]
    # The remaining two rules still reported.
    assert len(out.rules) == 3


def test_a_failing_delete_is_recorded_and_the_run_continues():
    db = FakeDB(counts=[5, 0, 0], deletes=[], raise_on="DELETE")
    out = _mgr(db, enabled=True).prune()
    assert out.errors and "DELETE" not in out.errors[0]
    assert out.deleted_total == 0


def test_the_scheduler_entry_point_returns_a_plain_dict():
    db = FakeDB(counts=[1, 2, 3])
    result = _mgr(db).prune_task({})
    assert isinstance(result, dict)
    assert result["dry_run"] is True
    assert result["deleted_total"] == 0
