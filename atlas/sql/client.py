"""Read-only SQL client (S20b).

``SQLClient`` runs a *single* read-only statement against a local database through an
injectable ``SQLBackend`` (default ``SQLiteBackend``) and returns plain dicts. Two
layers keep it read-only:

  1. a **statement guard** (`is_read_only`) that strips comments, rejects multiple
     statements, requires the statement to begin with `SELECT`/`WITH`/`EXPLAIN`/
     `VALUES`, and blocks any mutating keyword; and
  2. the SQLite backend opens the file with ``mode=ro`` (defence-in-depth), so even a
     guard bypass cannot write.

Outcomes are honest and never raise (R2/R3):
  ``ok`` | ``empty`` | ``blocked`` (non-read-only statement) |
  ``unavailable`` (missing driver / source not found) | ``error`` (SQL error).
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Protocol

SQL_OK = "ok"
SQL_EMPTY = "empty"
SQL_BLOCKED = "blocked"
SQL_UNAVAILABLE = "unavailable"
SQL_ERROR = "error"

_ALLOWED_STARTS = ("select", "with", "explain", "values")
# Whole-word mutating/side-effecting keywords rejected anywhere in the statement.
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|"
    r"vacuum|reindex|grant|revoke|pragma|begin|commit|rollback|savepoint)\b",
    re.IGNORECASE,
)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


class SQLBackendError(Exception):
    """A backend failed to *reach* a source (missing file/driver) → unavailable."""


class SQLExecError(Exception):
    """A statement executed but errored (bad SQL, no such table) → error."""


def _strip_comments(sql: str) -> str:
    return _BLOCK_COMMENT.sub(" ", _LINE_COMMENT.sub(" ", sql)).strip()


def is_read_only(sql: str) -> bool:
    """True iff ``sql`` is a single read-only statement (see module docstring)."""
    body = _strip_comments(sql or "")
    if not body:
        return False
    body = body.rstrip(";").strip()
    if not body or ";" in body:  # reject multiple statements
        return False
    if _FORBIDDEN.search(body):
        return False
    first = body.split(None, 1)[0].lower()
    return first in _ALLOWED_STARTS


class SQLBackend(Protocol):
    name: str

    def query(
        self, source: str, sql: str, params: Any, *, max_rows: int, timeout: float
    ) -> tuple[list[str], list[tuple], bool]:
        """Return (columns, rows, truncated). Raise SQLBackendError/SQLExecError."""
        ...

    def tables(self, source: str) -> list[str]: ...

    def schema(self, source: str, table: str) -> list[dict[str, Any]]: ...


class SQLiteBackend:
    """Default backend: query a local SQLite file opened **read-only** (``mode=ro``).

    ``source`` is resolved relative to ``root`` and confined to it (like the filesystem
    sandbox); an absolute path is only allowed if it lives under ``root``.
    """

    name = "sqlite"

    def __init__(self, root: Path | str, *, default_source: str | None = None) -> None:
        self._root = Path(root).resolve()
        self._default_source = default_source

    def _resolve(self, source: str | None) -> Path:
        source = source or self._default_source
        if not source:
            raise SQLBackendError("no database source given")
        candidate = (self._root / source).resolve()
        if candidate != self._root and not candidate.is_relative_to(self._root):
            raise SQLBackendError(f"source escapes sandbox root: {source}")
        if not candidate.is_file():
            raise SQLBackendError(f"database not found: {source}")
        return candidate

    def _connect(self, source: str | None) -> sqlite3.Connection:
        path = self._resolve(source)
        uri = f"file:{path.as_posix()}?mode=ro"
        try:
            return sqlite3.connect(uri, uri=True, timeout=1.0)
        except sqlite3.Error as exc:  # pragma: no cover - defensive
            raise SQLBackendError(str(exc)) from exc

    def query(
        self, source: str, sql: str, params: Any, *, max_rows: int, timeout: float
    ) -> tuple[list[str], list[tuple], bool]:
        conn = self._connect(source)
        # Soft timeout: interrupt the connection from a watchdog thread.
        timer = threading.Timer(timeout, conn.interrupt) if timeout > 0 else None
        try:
            if timer is not None:
                timer.start()
            cur = conn.execute(sql, params or [])
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchmany(max_rows + 1)
            truncated = len(rows) > max_rows
            return columns, [tuple(r) for r in rows[:max_rows]], truncated
        except sqlite3.Error as exc:
            raise SQLExecError(str(exc)) from exc
        finally:
            if timer is not None:
                timer.cancel()
            conn.close()

    def tables(self, source: str) -> list[str]:
        conn = self._connect(source)
        try:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view') "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            return [r[0] for r in cur.fetchall()]
        except sqlite3.Error as exc:
            raise SQLExecError(str(exc)) from exc
        finally:
            conn.close()

    def schema(self, source: str, table: str) -> list[dict[str, Any]]:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table or ""):
            raise SQLExecError(f"invalid table name: {table!r}")
        conn = self._connect(source)
        try:
            cur = conn.execute(f'PRAGMA table_info("{table}")')
            return [
                {"name": r[1], "type": r[2], "notnull": bool(r[3]),
                 "default": r[4], "pk": bool(r[5])}
                for r in cur.fetchall()
            ]
        except sqlite3.Error as exc:
            raise SQLExecError(str(exc)) from exc
        finally:
            conn.close()


class SQLClient:
    def __init__(
        self,
        backend: SQLBackend,
        *,
        max_rows: int = 1000,
        timeout: float = 15.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._backend = backend
        self._max_rows = max_rows
        self._timeout = timeout
        self._logger = logger or logging.getLogger("atlas.sql")

    def query(
        self,
        sql: str,
        *,
        source: str | None = None,
        params: Any = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        base = {"backend": self._backend.name, "source": source, "sql": sql}
        if not is_read_only(sql):
            return {
                **base, "outcome": SQL_BLOCKED,
                "reason": "only a single read-only statement "
                "(SELECT/WITH/EXPLAIN/VALUES) is allowed",
            }
        max_rows = min(limit or self._max_rows, 100_000)
        try:
            columns, rows, truncated = self._backend.query(
                source or "", sql, params, max_rows=max_rows, timeout=self._timeout
            )
        except SQLBackendError as exc:
            return {**base, "outcome": SQL_UNAVAILABLE, "reason": str(exc)}
        except SQLExecError as exc:
            return {**base, "outcome": SQL_ERROR, "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001 - a bad backend must not crash the caller
            self._logger.exception("sql backend crashed")
            return {**base, "outcome": SQL_ERROR, "reason": str(exc)}
        dict_rows = [dict(zip(columns, r)) for r in rows]
        return {
            **base,
            "outcome": SQL_OK if dict_rows else SQL_EMPTY,
            "columns": columns,
            "rows": dict_rows,
            "row_count": len(dict_rows),
            "truncated": truncated,
        }

    def tables(self, source: str | None = None) -> dict[str, Any]:
        base = {"backend": self._backend.name, "source": source}
        try:
            names = self._backend.tables(source or "")
        except SQLBackendError as exc:
            return {**base, "outcome": SQL_UNAVAILABLE, "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001 - never crash the caller
            return {**base, "outcome": SQL_ERROR, "reason": str(exc)}
        return {**base, "outcome": SQL_OK, "tables": names}

    def schema(self, table: str, source: str | None = None) -> dict[str, Any]:
        base = {"backend": self._backend.name, "source": source, "table": table}
        try:
            cols = self._backend.schema(source or "", table)
        except SQLBackendError as exc:
            return {**base, "outcome": SQL_UNAVAILABLE, "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001 - never crash the caller
            return {**base, "outcome": SQL_ERROR, "reason": str(exc)}
        return {
            **base,
            "outcome": SQL_OK if cols else SQL_EMPTY,
            "columns": cols,
        }
