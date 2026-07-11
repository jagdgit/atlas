"""Atlas migration runner.

Plain-SQL migrations, versioned in ``database/migrations/NNNN_name.sql`` and
tracked in ``system.migrations``. We own this runner (no ORM / framework).

Concepts
--------
- version   : the numeric prefix of the filename (e.g. "0002")
- checksum  : sha256 of the file contents, stored to detect drift
- applied   : a row in system.migrations

Commands (see ``atlas/database/__main__`` style CLI at bottom):
    status    : show applied vs pending
    migrate   : apply all pending migrations (as the atlas app role)
    baseline  : record all present migrations as applied WITHOUT running them
                (used once, since 0001-0005 were bootstrapped manually)

Bootstrap note: migrations that require superuser (extensions, REVOKE on
public, ownership reassignment) are applied manually as postgres, then recorded
via ``baseline``. Ordinary table migrations are applied by ``migrate`` as atlas.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from atlas.database.connection import DatabaseManager

MIGRATIONS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "database" / "migrations"
)
_VERSION_RE = re.compile(r"^(\d+)_")


@dataclass(frozen=True)
class Migration:
    version: str
    filename: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


class MigrationRunner:
    def __init__(
        self,
        db: DatabaseManager | None = None,
        migrations_dir: Path = MIGRATIONS_DIR,
    ) -> None:
        self._db = db or DatabaseManager()
        self._dir = migrations_dir

    def discover(self) -> list[Migration]:
        migrations: list[Migration] = []
        for path in sorted(self._dir.glob("*.sql")):
            match = _VERSION_RE.match(path.name)
            if not match:
                continue
            migrations.append(
                Migration(version=match.group(1), filename=path.name, path=path)
            )
        return migrations

    def applied_versions(self) -> set[str]:
        with self._db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version FROM system.migrations")
                return {row[0] for row in cur.fetchall()}

    def pending(self) -> list[Migration]:
        applied = self.applied_versions()
        return [m for m in self.discover() if m.version not in applied]

    def _record(self, conn, migration: Migration) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO system.migrations (version, filename, checksum)
                VALUES (%s, %s, %s)
                ON CONFLICT (version) DO UPDATE
                    SET filename = EXCLUDED.filename,
                        checksum = EXCLUDED.checksum,
                        applied_at = now()
                """,
                (migration.version, migration.filename, migration.checksum),
            )

    def apply(self, migration: Migration) -> None:
        """Apply a single migration transactionally and record it."""
        with self._db.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(migration.sql)
                self._record(conn, migration)

    def migrate(self) -> list[str]:
        """Apply all pending migrations. Returns the versions applied."""
        applied: list[str] = []
        for migration in self.pending():
            self.apply(migration)
            applied.append(migration.version)
        return applied

    def baseline(self) -> list[str]:
        """Record all present migrations as applied without executing them."""
        recorded: list[str] = []
        with self._db.connection() as conn:
            with conn.transaction():
                for migration in self.discover():
                    self._record(conn, migration)
                    recorded.append(migration.version)
        return recorded

    def status(self) -> dict[str, list[str]]:
        applied = self.applied_versions()
        discovered = self.discover()
        return {
            "applied": sorted(m.version for m in discovered if m.version in applied),
            "pending": sorted(m.version for m in discovered if m.version not in applied),
        }


if __name__ == "__main__":
    from atlas.database.cli import main

    raise SystemExit(main())
