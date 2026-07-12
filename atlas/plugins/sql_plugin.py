"""SQL plugin (S20b): read-only querying over a local database.

Exposes tools (registered as the ``sql`` capability):
    sql.query(sql, source=?, params=?, limit=?)  -> columns + rows (capped) + truncated
    sql.tables(source=?)                          -> table/view names
    sql.schema(table, source=?)                   -> column definitions

Read-only by construction (a statement guard + a ``mode=ro`` SQLite connection) and
confined to a sandbox root. Every tool returns a structured outcome
(`ok`/`empty`/`blocked`/`unavailable`/`error`) and never raises (R2/R3). Default backend
is stdlib SQLite; the backend seam lets Postgres/others drop in later via config.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.plugins.base import BasePlugin
from atlas.services.base import HealthStatus
from atlas.sql.client import SQLClient, SQLiteBackend

if TYPE_CHECKING:
    from atlas.config import AtlasConfig
    from atlas.kernel.application import Application


class SQLPlugin(BasePlugin):
    name = "sql"
    version = "0.1.0"

    def __init__(self, client: SQLClient, *, logger: logging.Logger | None = None) -> None:
        self._client = client
        self._logger = logger or logging.getLogger("atlas.plugins.sql")

    def register(self, kernel: "Application") -> None:
        from atlas.capabilities import CAP_SQL, SQLCapability

        kernel.capabilities.register(
            CAP_SQL, self, contract=SQLCapability, kind="plugin"
        )
        kernel.tools.register(
            "sql.query", self.query,
            description="Run a single read-only SQL query (SELECT/WITH/EXPLAIN) on a "
            "local database.",
            params={
                "sql": "a read-only SQL statement",
                "source": "database file under the sandbox root (optional if a default is set)",
                "limit": "max rows to return",
            },
            plugin=self.name,
        )
        kernel.tools.register(
            "sql.tables", self.tables,
            description="List tables/views in a local database.",
            params={"source": "database file under the sandbox root"},
            plugin=self.name,
        )
        kernel.tools.register(
            "sql.schema", self.schema,
            description="Describe a table's columns.",
            params={"table": "table name", "source": "database file under the root"},
            plugin=self.name,
        )

    # --- capability -----------------------------------------------------
    def query(
        self, sql: str, source: str | None = None, params: Any = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        return self._client.query(sql, source=source, params=params, limit=limit)

    def tables(self, source: str | None = None) -> dict[str, Any]:
        return self._client.tables(source=source)

    def schema(self, table: str, source: str | None = None) -> dict[str, Any]:
        return self._client.schema(table, source=source)

    def health_check(self) -> HealthStatus:
        return HealthStatus.ok("sql (read-only) ready")


def build(config: "AtlasConfig") -> SQLPlugin:
    sql = config.plugins.sql
    root = sql.root or config.paths.data
    backend = SQLiteBackend(root, default_source=sql.default_source or None)
    client = SQLClient(backend, max_rows=sql.max_rows, timeout=sql.timeout)
    return SQLPlugin(client)
