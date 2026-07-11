"""Database backups via pg_dump (ADR-0055).

A ``BackupManager`` runs ``pg_dump`` in PostgreSQL's custom format (``-Fc``, restored
with ``pg_restore``) into the configured backups directory, prunes old dumps to a
retention count, and — like ingestion and memory-prune — self-re-enqueues a durable
``backup`` scheduler task so periodic backups survive restarts without external cron.

The DB password is passed via the ``PGPASSWORD`` environment variable (never on the
command line / process list), sourced from config (which loads it from the env per
ADR-0013).
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from atlas.exceptions import AtlasError
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.config import DatabaseConfig

_PREFIX = "atlas_"
_SUFFIX = ".dump"


class BackupError(AtlasError):
    """A backup (pg_dump) or prune operation failed."""


class BackupManager:
    name = "backup"

    def __init__(
        self,
        db: "DatabaseConfig",
        backups_dir: Path | str,
        *,
        enabled: bool = True,
        interval_seconds: int = 86400,
        retention: int = 7,
        pg_dump_path: str = "pg_dump",
        enqueue: "Callable[..., Any] | None" = None,
        count_pending: "Callable[[str], int] | None" = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._db = db
        self._dir = Path(backups_dir)
        self._enabled = enabled
        self._interval = interval_seconds
        self._retention = retention
        self._pg_dump = pg_dump_path
        self._enqueue = enqueue
        self._count_pending = count_pending
        self._logger = logger or logging.getLogger("atlas.ops.backup")

    # --- core -----------------------------------------------------------
    def backup(self) -> Path:
        """Run pg_dump and return the created dump file path."""
        self._dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        target = self._dir / f"{_PREFIX}{self._db.database}_{stamp}{_SUFFIX}"
        cmd = [
            self._pg_dump,
            "--format=custom",
            "--host", self._db.host,
            "--port", str(self._db.port),
            "--username", self._db.user,
            "--dbname", self._db.database,
            "--file", str(target),
        ]
        env = {"PGPASSWORD": self._db.password} if self._db.password else {}
        try:
            result = subprocess.run(
                cmd,
                env={**_os_environ(), **env},
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise BackupError(
                f"pg_dump not found at '{self._pg_dump}'", command=self._pg_dump
            ) from exc
        if result.returncode != 0:
            raise BackupError(
                f"pg_dump failed (exit {result.returncode}): {result.stderr.strip()}",
                returncode=result.returncode,
            )
        self._logger.info("backup written to %s", target)
        self.prune()
        return target

    def prune(self) -> int:
        """Delete dumps beyond the retention count. Returns how many were removed."""
        if self._retention <= 0:
            return 0
        dumps = self.list_backups()
        stale = dumps[self._retention :]
        for path in stale:
            try:
                path.unlink()
            except OSError:  # noqa: PERF203 - best-effort cleanup
                self._logger.exception("failed to remove old backup %s", path)
        if stale:
            self._logger.info("pruned %d old backup(s)", len(stale))
        return len(stale)

    def list_backups(self) -> list[Path]:
        """Return dump files, newest first (by name, which is timestamp-ordered)."""
        if not self._dir.exists():
            return []
        return sorted(
            self._dir.glob(f"{_PREFIX}*{_SUFFIX}"), reverse=True
        )

    # --- scheduler integration -----------------------------------------
    def backup_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Scheduler handler for task_type 'backup'; re-enqueues itself."""
        path = self.backup()
        if self._enqueue is not None and self._interval > 0:
            self._enqueue("backup", {}, delay_seconds=float(self._interval))
        return {"backup": str(path), "kept": len(self.list_backups())}

    # --- Service lifecycle ---------------------------------------------
    def start(self) -> None:
        """Seed a durable backup chain on startup (idempotent across restarts)."""
        if not self._enabled or self._enqueue is None or self._interval <= 0:
            return
        if self._count_pending is not None and self._count_pending("backup") > 0:
            self._logger.info("backup already queued; not seeding another")
            return
        self._enqueue("backup", {}, delay_seconds=float(self._interval))
        self._logger.info("seeded initial backup (interval %ds)", self._interval)

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        backups = self.list_backups()
        mode = "manual" if self._interval <= 0 else f"every {self._interval}s"
        latest = backups[0].name if backups else "none"
        return HealthStatus(
            healthy=True,
            detail=f"{len(backups)} backup(s), latest {latest}; {mode}",
            data={"count": len(backups), "dir": str(self._dir)},
        )


def _os_environ() -> dict[str, str]:
    import os

    return dict(os.environ)
