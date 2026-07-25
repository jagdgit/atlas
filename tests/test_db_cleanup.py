"""Hermetic + live-DB tests for OI-T1/T3 pytest residue cleanup."""

from __future__ import annotations

from atlas.testing.db_cleanup import clean_pytest_residue


class _FakeCursor:
    def __init__(self, counts: dict[str, int]):
        self._counts = counts
        self.rowcount = 0
        self._last_sql = ""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self._last_sql = " ".join(sql.split())
        if "SELECT count(*)" in self._last_sql and "learning.repositories" in self._last_sql:
            self._result = (self._counts.get("repositories_reverted", 0),)
            self.rowcount = 0
        elif "SELECT count(*)" in self._last_sql and "asset.assets" in self._last_sql:
            self._result = (self._counts.get("assets_deleted", 0),)
            self.rowcount = 0
        elif "SELECT count(*)" in self._last_sql and "audit.events" in self._last_sql:
            self._result = (self._counts.get("test_events_deleted", 0),)
            self.rowcount = 0
        elif "UPDATE learning.repositories" in self._last_sql:
            self.rowcount = self._counts.get("repositories_reverted", 0)
            self._result = None
        elif "DELETE FROM asset.assets" in self._last_sql:
            self.rowcount = self._counts.get("assets_deleted", 0)
            self._result = None
        elif "DELETE FROM audit.events" in self._last_sql:
            self.rowcount = self._counts.get("test_events_deleted", 0)
            self._result = None
        else:
            self.rowcount = 0
            self._result = None

    def fetchone(self):
        return self._result


class _FakeConn:
    def __init__(self, counts: dict[str, int]):
        self._counts = counts
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return _FakeCursor(self._counts)

    def commit(self):
        self.committed = True


class _FakeDb:
    def __init__(self, counts: dict[str, int]):
        self.conn = _FakeConn(counts)

    def connection(self):
        return self.conn


def test_clean_pytest_residue_dry_run_counts():
    db = _FakeDb({"repositories_reverted": 3, "assets_deleted": 1, "test_events_deleted": 5})
    out = clean_pytest_residue(db, dry_run=True)
    assert out == {"repositories_reverted": 3, "assets_deleted": 1, "test_events_deleted": 5}
    assert db.conn.committed is False


def test_clean_pytest_residue_mutates_and_commits():
    db = _FakeDb({"repositories_reverted": 2, "assets_deleted": 4, "test_events_deleted": 0})
    out = clean_pytest_residue(db, dry_run=False)
    assert out["repositories_reverted"] == 2
    assert out["assets_deleted"] == 4
    assert db.conn.committed is True
