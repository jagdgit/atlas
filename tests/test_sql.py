"""Tests for the read-only SQL capability (S20b).

The statement guard and outcome mapping are pure/hermetic; the SQLite backend is
exercised against a real temp database (stdlib `sqlite3`, always available). A fake
backend covers the `unavailable`/`error` translation without touching disk.
"""

from __future__ import annotations

import sqlite3

import pytest

from atlas.plugins.sql_plugin import SQLPlugin
from atlas.sql.client import (
    SQL_BLOCKED,
    SQL_EMPTY,
    SQL_ERROR,
    SQL_OK,
    SQL_UNAVAILABLE,
    SQLBackendError,
    SQLClient,
    SQLExecError,
    SQLiteBackend,
    is_read_only,
)


# --- read-only guard -----------------------------------------------------
@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "select * from t",
    "  WITH c AS (SELECT 1) SELECT * FROM c",
    "EXPLAIN QUERY PLAN SELECT * FROM t",
    "VALUES (1), (2)",
    "SELECT 1; ",  # a single trailing semicolon is fine
    "-- comment\nSELECT 1",
])
def test_guard_allows_read_only(sql):
    assert is_read_only(sql) is True


@pytest.mark.parametrize("sql", [
    "INSERT INTO t VALUES (1)",
    "UPDATE t SET a = 1",
    "DELETE FROM t",
    "DROP TABLE t",
    "CREATE TABLE t (a int)",
    "ATTACH DATABASE 'x' AS y",
    "PRAGMA writable_schema = 1",
    "SELECT 1; DROP TABLE t",  # multiple statements
    "SELECT 1; SELECT 2",
    "",
    "   ",
    "VACUUM",
])
def test_guard_blocks_mutations_and_multi(sql):
    assert is_read_only(sql) is False


# --- SQLite backend against a real temp db -------------------------------
@pytest.fixture
def db(tmp_path):
    path = tmp_path / "shop.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE sales (id INTEGER PRIMARY KEY, product TEXT, amount REAL);"
        "INSERT INTO sales (product, amount) VALUES ('a', 10.0), ('b', 20.0), ('a', 5.0);"
        "CREATE VIEW totals AS SELECT product, sum(amount) t FROM sales GROUP BY product;"
    )
    conn.commit()
    conn.close()
    return tmp_path, "shop.db"


def _client(root, **kw):
    return SQLClient(SQLiteBackend(root), **kw)


def test_query_returns_rows(db):
    root, src = db
    res = _client(root).query("SELECT product, amount FROM sales ORDER BY id", source=src)
    assert res["outcome"] == SQL_OK
    assert res["columns"] == ["product", "amount"]
    assert res["row_count"] == 3
    assert res["rows"][0] == {"product": "a", "amount": 10.0}
    assert res["truncated"] is False


def test_query_aggregate_and_view(db):
    root, src = db
    res = _client(root).query("SELECT * FROM totals ORDER BY product", source=src)
    assert res["outcome"] == SQL_OK
    assert res["rows"][0]["t"] == 15.0


def test_query_empty_result(db):
    root, src = db
    res = _client(root).query("SELECT * FROM sales WHERE amount > 999", source=src)
    assert res["outcome"] == SQL_EMPTY
    assert res["rows"] == []


def test_limit_truncates(db):
    root, src = db
    res = _client(root, max_rows=2).query("SELECT * FROM sales", source=src)
    assert res["row_count"] == 2
    assert res["truncated"] is True


def test_write_is_blocked_before_execution(db):
    root, src = db
    res = _client(root).query("DELETE FROM sales", source=src)
    assert res["outcome"] == SQL_BLOCKED


def test_read_only_connection_rejects_writes_that_slip_the_guard(db):
    # Defence-in-depth: even calling the backend directly with a write fails, because
    # the connection is opened mode=ro.
    root, src = db
    with pytest.raises(SQLExecError):
        SQLiteBackend(root).query(src, "DELETE FROM sales", None, max_rows=10, timeout=5)


def test_missing_source_is_unavailable(db):
    root, _ = db
    res = _client(root).query("SELECT 1", source="nope.db")
    assert res["outcome"] == SQL_UNAVAILABLE


def test_source_escape_is_unavailable(db):
    root, _ = db
    res = _client(root).query("SELECT 1", source="../secret.db")
    assert res["outcome"] == SQL_UNAVAILABLE


def test_bad_sql_is_error(db):
    root, src = db
    res = _client(root).query("SELECT * FROM no_such_table", source=src)
    assert res["outcome"] == SQL_ERROR
    assert "no_such_table" in res["reason"]


def test_tables_and_schema(db):
    root, src = db
    client = _client(root)
    tables = client.tables(source=src)
    assert tables["outcome"] == SQL_OK
    assert "sales" in tables["tables"] and "totals" in tables["tables"]

    schema = client.schema("sales", source=src)
    assert schema["outcome"] == SQL_OK
    names = [c["name"] for c in schema["columns"]]
    assert names == ["id", "product", "amount"]
    assert schema["columns"][0]["pk"] is True


def test_schema_rejects_bad_table_name(db):
    root, src = db
    res = _client(root).schema("sales; DROP TABLE sales", source=src)
    assert res["outcome"] == SQL_ERROR


# --- fake backend: outcome translation -----------------------------------
class _FakeBackend:
    name = "fake"

    def __init__(self, exc):
        self._exc = exc

    def query(self, *a, **k):
        raise self._exc

    def tables(self, source):
        raise self._exc

    def schema(self, source, table):
        raise self._exc


def test_backend_unavailable_translates():
    res = SQLClient(_FakeBackend(SQLBackendError("no driver"))).query("SELECT 1")
    assert res["outcome"] == SQL_UNAVAILABLE


def test_backend_crash_never_raises():
    res = SQLClient(_FakeBackend(RuntimeError("boom"))).query("SELECT 1")
    assert res["outcome"] == SQL_ERROR
    assert "boom" in res["reason"]


# --- plugin wiring -------------------------------------------------------
def test_plugin_delegates_and_health(db):
    root, src = db
    plugin = SQLPlugin(_client(root))
    res = plugin.query("SELECT 1 AS one", source=src)
    assert res["outcome"] == SQL_OK and res["rows"][0]["one"] == 1
    assert plugin.health_check().healthy is True


class _Kernel:
    def __init__(self) -> None:
        caps: dict = {}
        tools: dict = {}
        self.caps = caps
        self.tool_map = tools

        class _Caps:
            def register(self, name, provider, *, contract=None, kind=None):
                caps[name] = provider

        class _Tools:
            def register(self, name, fn, *, description="", params=None, plugin=None):
                tools[name] = fn

        self.capabilities = _Caps()
        self.tools = _Tools()


def test_plugin_registers_capability_and_tools(tmp_path):
    plugin = SQLPlugin(SQLClient(SQLiteBackend(tmp_path)))
    kernel = _Kernel()
    plugin.register(kernel)
    assert "sql" in kernel.caps
    for name in ("sql.query", "sql.tables", "sql.schema"):
        assert name in kernel.tool_map
