"""Read-only Postgres backend — Atlas inspecting its own database (J0a).

Why this exists: until now no capability could reach Atlas's own Postgres. ``sql.query``
spoke SQLite inside a sandbox, so when Atlas was asked "why did your scheduler fail
today, use the database" it was *structurally incapable* of looking, and silently ran a
web search instead. A system that cannot query its own state cannot diagnose itself.

This is the ``SQLBackend`` protocol from ``atlas.sql.client`` over the live Atlas
database. Four layers keep it safe, because this one reaches real operational data:

  1. ``SQLClient``'s existing ``is_read_only`` statement guard (single SELECT/WITH/
     EXPLAIN/VALUES, no mutating keyword) runs *before* the backend is reached;
  2. the session is opened ``READ ONLY`` — a guard bypass still cannot write;
  3. ``statement_timeout`` is set per query, so a bad join cannot pin a connection
     needed by the live service; and
  4. credential relations are refused and secret-looking *columns* are redacted, so
     introspection output can never carry a secret into a log, report or LLM prompt.

Atlas's database holds no credentials today (``system.settings`` is empty and the only
secret-shaped column name in all 70 tables is ``knowledge.chunks.token_count``, a
count). Layer 4 exists so that stays true if a future migration adds one.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from atlas.sql.client import SQLBackendError, SQLExecError

# Relations that expose password hashes / mapping credentials. Refused outright: there
# is no legitimate self-diagnosis reason to read them.
_DENIED_RELATIONS = re.compile(
    r"\b(pg_authid|pg_shadow|pg_user_mapping|pg_statistic)\b",
    re.IGNORECASE,
)

# Columns whose *name* suggests a secret. Values are replaced, never emitted. The
# lookahead keeps size/count fields readable: ``token_count`` and ``token_len`` are
# diagnostics the operator relies on, not secrets.
_TOKEN_SIZE_SUFFIX = r"count|len|length|size|total|usage|budget|limit|num"
_SECRET_COLUMN = re.compile(
    r"(password|passwd|secret|credential|private_key|access_key|api_key|"
    rf"(^|_)token(?!_(?:{_TOKEN_SIZE_SUFFIX}))($|_)|"
    r"refresh_token|access_token|session_token)",
    re.IGNORECASE,
)
_REDACTED = "[redacted]"

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_secret_column(name: str) -> bool:
    """True iff a column name looks like it carries a secret (``token_count`` does not)."""
    return bool(_SECRET_COLUMN.search(str(name or "")))


class PostgresBackend:
    """Read-only access to Atlas's own Postgres.

    ``source`` is accepted and ignored for ``query`` (there is one Atlas database); for
    ``tables``/``schema`` it is an optional schema-name filter.
    """

    name = "postgres"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        dbname: str,
        user: str,
        password: str,
        statement_timeout: float = 15.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._conn_kwargs = {
            "host": host,
            "port": port,
            "dbname": dbname,
            "user": user,
            "password": password,
        }
        self._statement_timeout = float(statement_timeout)
        self._logger = logger or logging.getLogger("atlas.sql.postgres")

    # --- internals ------------------------------------------------------
    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - driver always present in prod
            raise SQLBackendError("psycopg is not installed") from exc
        try:
            # autocommit=False so the explicit READ ONLY transaction below applies.
            return psycopg.connect(**self._conn_kwargs, autocommit=False)
        except Exception as exc:  # noqa: BLE001 - never surface the DSN/password
            raise SQLBackendError(f"cannot reach the Atlas database: {type(exc).__name__}") from exc

    def _begin_read_only(self, conn) -> Any:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        timeout_ms = max(int(self._statement_timeout * 1000), 1)
        cur.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
        return cur

    @staticmethod
    def _guard(sql: str) -> None:
        if _DENIED_RELATIONS.search(sql or ""):
            raise SQLExecError(
                "that relation is refused: credential and statistics catalogs are not "
                "readable through self-inspection"
            )

    # --- SQLBackend protocol -------------------------------------------
    def query(
        self, source: str, sql: str, params: Any, *, max_rows: int, timeout: float
    ) -> tuple[list[str], list[tuple], bool]:
        self._guard(sql)
        conn = self._connect()
        try:
            cur = self._begin_read_only(conn)
            try:
                cur.execute(sql, params or None)
            except Exception as exc:  # noqa: BLE001 - a bad query is `error`, not a crash
                raise SQLExecError(str(exc).strip().splitlines()[0]) from exc
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchmany(max_rows + 1) if columns else []
            truncated = len(rows) > max_rows
            rows = rows[:max_rows]
            secret_at = [i for i, c in enumerate(columns) if is_secret_column(c)]
            if secret_at:
                rows = [
                    tuple(_REDACTED if i in secret_at else v for i, v in enumerate(r))
                    for r in rows
                ]
            else:
                rows = [tuple(r) for r in rows]
            return columns, rows, truncated
        finally:
            conn.rollback()  # read-only: nothing to commit
            conn.close()

    def tables(self, source: str) -> list[str]:
        sql = (
            "SELECT table_schema || '.' || table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog', 'information_schema')"
        )
        params: list[Any] = []
        schema = (source or "").strip()
        if schema:
            sql += " AND table_schema = %s"
            params.append(schema)
        sql += " ORDER BY 1"
        conn = self._connect()
        try:
            cur = self._begin_read_only(conn)
            cur.execute(sql, params or None)
            return [r[0] for r in cur.fetchall()]
        except Exception as exc:  # noqa: BLE001
            raise SQLExecError(str(exc).strip().splitlines()[0]) from exc
        finally:
            conn.rollback()
            conn.close()

    def schema(self, source: str, table: str) -> list[dict[str, Any]]:
        raw = (table or "").strip()
        if "." in raw:
            schema_name, _, table_name = raw.partition(".")
        else:
            schema_name, table_name = (source or "public").strip() or "public", raw
        if not _IDENT.match(schema_name) or not _IDENT.match(table_name):
            raise SQLExecError(f"invalid table name: {table!r}")
        conn = self._connect()
        try:
            cur = self._begin_read_only(conn)
            cur.execute(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s "
                "ORDER BY ordinal_position",
                (schema_name, table_name),
            )
            return [
                {
                    "name": r[0],
                    "type": r[1],
                    "notnull": str(r[2]).upper() == "NO",
                    "default": r[3],
                    "secret": is_secret_column(r[0]),
                }
                for r in cur.fetchall()
            ]
        except Exception as exc:  # noqa: BLE001
            raise SQLExecError(str(exc).strip().splitlines()[0]) from exc
        finally:
            conn.rollback()
            conn.close()


class RoutingBackend:
    """Dispatch on ``source``: one reserved name reaches Atlas's own database.

    Keeps the existing SQLite sandbox as the default so no current caller changes
    behaviour; ``source="atlas"`` (``self_source``) routes to Postgres instead.
    """

    def __init__(self, default: Any, self_backend: Any, *, self_source: str = "atlas") -> None:
        self._default = default
        self._self = self_backend
        self._self_source = self_source

    @property
    def name(self) -> str:
        return f"{getattr(self._default, 'name', '?')}+{getattr(self._self, 'name', '?')}"

    def _pick(self, source: str | None) -> tuple[Any, str]:
        raw = (source or "").strip()
        head, _, rest = raw.partition(".")
        if raw == self._self_source or head == self._self_source:
            # "atlas" -> whole db; "atlas.scheduler" -> schema filter
            return self._self, rest
        return self._default, raw

    def query(self, source: str, sql: str, params: Any, *, max_rows: int, timeout: float):
        backend, resolved = self._pick(source)
        return backend.query(resolved, sql, params, max_rows=max_rows, timeout=timeout)

    def tables(self, source: str) -> list[str]:
        backend, resolved = self._pick(source)
        return backend.tables(resolved)

    def schema(self, source: str, table: str) -> list[dict[str, Any]]:
        backend, resolved = self._pick(source)
        return backend.schema(resolved, table)
