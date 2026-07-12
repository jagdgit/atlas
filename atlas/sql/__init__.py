"""Read-only SQL querying (Stage 2, S20b).

A **read-only** SQL capability over local databases (SQLite by default). Read-only by
construction — a statement guard rejects anything but a single `SELECT`/`WITH`/
`EXPLAIN`/`VALUES`, and the SQLite backend opens the file in ``mode=ro`` as
defence-in-depth. Sources are confined to a sandbox root. Every operation returns a
structured outcome and **never raises** into the caller (R2/R3); a computed result set
is L5-quality evidence, mirroring the Python sandbox (§5a.6).
"""

from __future__ import annotations

from atlas.sql.client import (
    SQL_BLOCKED,
    SQL_EMPTY,
    SQL_ERROR,
    SQL_OK,
    SQL_UNAVAILABLE,
    SQLBackend,
    SQLClient,
    SQLiteBackend,
    is_read_only,
)

__all__ = [
    "SQLClient",
    "SQLBackend",
    "SQLiteBackend",
    "is_read_only",
    "SQL_OK",
    "SQL_EMPTY",
    "SQL_BLOCKED",
    "SQL_UNAVAILABLE",
    "SQL_ERROR",
]
