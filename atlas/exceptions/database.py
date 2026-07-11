"""Database errors (connection, migration, query).

``DatabaseConnectionError`` is named to avoid shadowing the builtin
``ConnectionError``.
"""

from __future__ import annotations

from atlas.exceptions.base import AtlasError


class DatabaseError(AtlasError):
    """Any failure originating in the database/repository layer."""


class DatabaseConnectionError(DatabaseError):
    """Could not connect to, or lost the connection to, PostgreSQL."""


class MigrationError(DatabaseError):
    """A migration failed to apply or its checksum drifted."""


class QueryError(DatabaseError):
    """A SQL statement failed to execute."""
