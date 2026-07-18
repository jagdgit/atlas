"""Storage Manager (Phase 0 · ATLAS_OS_ROADMAP §5.8, principle P8).

One first-class subsystem through which durable files flow: **versioned, checksummed**
file put/get, workspace allocation, **advisory** per-scope quotas, and backup
orchestration (wrapping the existing ``pg_dump`` BackupManager). Every stored file is
sha256-checksummed on write and verified on read, so silent corruption is caught.

Deferred (R2, hardware-gated): hot/warm/cold **tiering**. The ``tier`` column ships and
``put_file`` accepts a tier, but there is **no tier-move logic** until a second disk is
added — everything lives on the one volume as ``hot``.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from atlas.exceptions import AtlasError
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.ops.backup import BackupManager
    from atlas.storage.repository import StorageRepository

_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")


class StorageError(AtlasError):
    """A storage operation failed (missing file, checksum mismatch, quota, …)."""


def _safe(segment: str) -> str:
    """Filesystem-safe path segment (no traversal, no separators)."""
    cleaned = _SAFE_SEGMENT.sub("_", (segment or "").strip())
    cleaned = cleaned.strip("._") or "unnamed"
    return cleaned[:200]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class StorageManager:
    """The ``storage`` capability/service — durable files with integrity + quotas."""

    name = "storage"

    # Artifact version (P2): bump on a material change to storage behaviour/layout.
    VERSION = "1"

    def __init__(
        self,
        root: Path | str,
        repo: "StorageRepository",
        *,
        backup: "BackupManager | None" = None,
        default_quota_bytes: int = 0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._root = Path(root)
        self._repo = repo
        self._backup = backup
        self._default_quota = max(0, int(default_quota_bytes))
        self._logger = logger or logging.getLogger("atlas.storage")

    # --- versioned, checksummed files ----------------------------------

    def put_file(
        self,
        scope: str,
        name: str,
        data: bytes | str | Path,
        *,
        tier: str = "hot",
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store a new *version* of ``(scope, name)``; checksum + register it.

        ``data`` may be raw ``bytes`` or a path to an existing file. Returns the
        ``storage.files`` row. Quota is **advisory** (over-quota logs a warning but the
        write still succeeds — R2/A2).
        """
        payload = self._as_bytes(data)
        version = self._repo.next_version(scope, name)
        relpath = f"files/{_safe(scope)}/{_safe(name)}.v{version}"
        target = self._root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

        self._advise_quota(scope, extra=len(payload))
        return self._repo.insert_file(
            scope=scope,
            name=name,
            version=version,
            relpath=relpath,
            size_bytes=len(payload),
            checksum=_sha256(payload),
            tier=tier,
            content_type=content_type,
            metadata=metadata,
        )

    def get_bytes(
        self, scope: str, name: str, version: int | None = None
    ) -> bytes:
        """Read a stored file (latest version unless given), verifying its checksum."""
        row = self._require_row(scope, name, version)
        path = self._root / str(row["relpath"])
        if not path.exists():
            raise StorageError(
                f"stored file missing on disk: {scope}/{name} v{row['version']}",
                path=str(path),
            )
        data = path.read_bytes()
        actual = _sha256(data)
        if actual != row["checksum"]:
            raise StorageError(
                f"checksum mismatch for {scope}/{name} v{row['version']}",
                expected=row["checksum"], actual=actual,
            )
        return data

    def path_of(
        self, scope: str, name: str, version: int | None = None
    ) -> Path:
        row = self._require_row(scope, name, version)
        return self._root / str(row["relpath"])

    def verify(
        self, scope: str, name: str, version: int | None = None
    ) -> bool:
        """True if the stored file exists and its checksum matches. Never raises."""
        row = self._repo.get_file(scope, name, version)
        if row is None:
            return False
        path = self._root / str(row["relpath"])
        if not path.exists():
            return False
        try:
            return _sha256(path.read_bytes()) == row["checksum"]
        except OSError:
            return False

    def list_files(self, scope: str) -> list[dict[str, Any]]:
        return self._repo.list_files(scope)

    # --- workspaces -----------------------------------------------------

    def allocate_workspace(self, scope: str) -> Path:
        """Create (if needed) and return a scoped workspace directory under the root."""
        ws = self._root / "workspaces" / _safe(scope)
        ws.mkdir(parents=True, exist_ok=True)
        return ws

    # --- quotas (advisory in Phase 0) ----------------------------------

    def quota_status(self, scope: str) -> dict[str, Any]:
        used = self._repo.scope_size(scope)
        row = self._repo.get_quota(scope)
        limit = int(row["limit_bytes"]) if row else self._default_quota
        enforce = bool(row["enforce"]) if row else False
        return {
            "scope": scope,
            "used_bytes": used,
            "limit_bytes": limit,
            "enforce": enforce,
            "over": bool(limit) and used > limit,
        }

    def set_quota(
        self, scope: str, limit_bytes: int, *, enforce: bool = False
    ) -> dict[str, Any]:
        return self._repo.set_quota(scope, limit_bytes, enforce=enforce)

    def _advise_quota(self, scope: str, *, extra: int) -> None:
        status = self.quota_status(scope)
        limit = status["limit_bytes"]
        if limit and (status["used_bytes"] + extra) > limit:
            # Advisory only in Phase 0 (R2/A2): warn, never block.
            self._logger.warning(
                "storage quota exceeded for scope %r: %d + %d > %d bytes (advisory)",
                scope, status["used_bytes"], extra, limit,
            )

    # --- integrity (Recovery Manager tie-in, §2.8) ----------------------

    def integrity_check(self) -> dict[str, Any]:
        """Verify every registered file's checksum. Reports missing/corrupt files."""
        checked = ok = 0
        missing: list[str] = []
        corrupt: list[str] = []
        for row in self._repo.all_files():
            checked += 1
            ref = f"{row['scope']}/{row['name']} v{row['version']}"
            path = self._root / str(row["relpath"])
            if not path.exists():
                missing.append(ref)
                continue
            try:
                if _sha256(path.read_bytes()) == row["checksum"]:
                    ok += 1
                else:
                    corrupt.append(ref)
            except OSError:
                corrupt.append(ref)
        return {
            "checked": checked,
            "ok": ok,
            "missing": missing,
            "corrupt": corrupt,
        }

    # --- backup orchestration ------------------------------------------

    def run_backup(self) -> Path:
        """Trigger a database backup through the wrapped BackupManager."""
        if self._backup is None:
            raise StorageError("no backup manager configured")
        return self._backup.backup()

    # --- lifecycle ------------------------------------------------------

    def start(self) -> None:
        (self._root / "files").mkdir(parents=True, exist_ok=True)
        (self._root / "workspaces").mkdir(parents=True, exist_ok=True)

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        try:
            root_ok = self._root.exists()
        except OSError:
            root_ok = False
        if not root_ok:
            return HealthStatus.fail(
                "storage root missing", root=str(self._root)
            )
        return HealthStatus.ok(
            "storage ready",
            root=str(self._root),
            tiering="deferred (single disk)",
        )

    # --- helpers --------------------------------------------------------

    def _require_row(
        self, scope: str, name: str, version: int | None
    ) -> dict[str, Any]:
        row = self._repo.get_file(scope, name, version)
        if row is None:
            v = f" v{version}" if version is not None else ""
            raise StorageError(f"no stored file: {scope}/{name}{v}")
        return row

    @staticmethod
    def _as_bytes(data: bytes | str | Path) -> bytes:
        if isinstance(data, bytes):
            return data
        path = Path(data)
        if not path.exists():
            raise StorageError(f"source file not found: {path}")
        return path.read_bytes()
