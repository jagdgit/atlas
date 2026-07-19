"""Asset-backed repository acquisition (Phase B · §B.1, BB1/BB12).

The **seam** of Engineering Intelligence: given a **local path** or a **remote URL**,
:class:`RepoAcquirer` produces a checked-out working copy and registers/updates a
``git_repo`` **asset** (raw bytes, versioned + checksummed) in the Asset Store, so a better
reader later re-extracts from the *stored asset* rather than re-cloning (P8, Assets ≠
Knowledge). Two identity/versioning ideas make this durable:

- **Tree checksum (BB1/Q-B1)** — a content hash over tracked files (``relative-path + file
  mode + blob sha``, sorted; ``.git``/``__pycache__``/``*.pyc``/``node_modules`` + code
  ignores excluded). Re-ingesting an unchanged tree **reuses** the current asset version;
  only a real change cuts a new version. Git-object-model-like, so permission churn on
  ``.git`` internals never spuriously bumps a version.
- **Repository UUID (BB12)** — a stable ``repo_uid`` independent of path / URL / clone
  location, derived from the git **root-commit** → normalized **remote** → the working
  path. Moving or re-cloning the same repo resolves to the **same** ``repo_uid``.

Per constitution **P11** the acquirer is a stateless translator: it registers an asset and
returns provenance; it never writes findings, missions, or decisions.
"""

from __future__ import annotations

import hashlib
import io
import logging
import shutil
import tarfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from atlas.code.repomap import DEFAULT_IGNORES
from atlas.exceptions import AtlasError
from atlas.vcs.acquire import GitAcquirer, normalize_remote
from atlas.vcs.git import GIT_OK

if TYPE_CHECKING:
    from atlas.assets.service import AssetStore
    from atlas.storage.service import StorageManager

# Stable namespace for deriving repo_uid (BB12) — never change once shipped.
_REPO_NS = uuid.UUID("a7c0de00-0000-4b00-8000-a71a50000001")

# Extra ignores layered on top of the code DEFAULT_IGNORES for checksum/packing (Q-B1).
_EXTRA_IGNORE_DIRS = frozenset({".git", "__pycache__", "node_modules"})
_IGNORE_DIRS = DEFAULT_IGNORES | _EXTRA_IGNORE_DIRS
_IGNORE_SUFFIXES = (".pyc", ".pyo")

ASSET_KIND_REPO = "git_repo"


class RepoAcquireError(AtlasError):
    """A repository could not be acquired (clone failed, path missing, …)."""


def _iter_tracked_files(root: Path) -> list[Path]:
    """Deterministically ordered files under ``root`` minus ignored dirs/suffixes (Q-B1)."""
    out: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root)
        if any(part in _IGNORE_DIRS for part in rel.parts):
            continue
        if path.suffix in _IGNORE_SUFFIXES:
            continue
        out.append(path)
    return out


def _file_mode(path: Path) -> str:
    """Git-like coarse mode: executables vs. regular files (avoids permission churn)."""
    try:
        executable = bool(path.stat().st_mode & 0o111)
    except OSError:
        executable = False
    return "100755" if executable else "100644"


def compute_tree_checksum(root: str | Path) -> str:
    """Content hash of the working tree: ``sha256`` over ``relpath\\0mode\\0blobsha`` lines.

    Mirrors Git's object model closely enough to be stable across clones of the same commit
    and immune to ``.git`` internals / permission-only changes (BB1/Q-B1).
    """
    root = Path(root)
    if not root.is_dir():
        raise RepoAcquireError(f"not a directory: {root}")
    h = hashlib.sha256()
    for path in _iter_tracked_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            blob = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
        h.update(f"{rel}\0{_file_mode(path)}\0{blob}\n".encode("utf-8"))
    return h.hexdigest()


def _pack_tree(root: Path) -> bytes:
    """Deterministic ``.tar.gz`` of tracked files (sorted, zeroed mtime/uid/gid).

    The stored asset is reproducible, so the Storage checksum is meaningful and re-packing an
    unchanged tree yields identical bytes.
    """
    buf = io.BytesIO()
    # mtime=0 in the gzip header keeps the compressed bytes reproducible.
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tar:
        tar.gzip_mtime = 0  # type: ignore[attr-defined]
        for path in _iter_tracked_files(root):
            rel = path.relative_to(root).as_posix()
            info = tarfile.TarInfo(name=rel)
            data = path.read_bytes()
            info.size = len(data)
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = 0o755 if _file_mode(path) == "100755" else 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@dataclass(frozen=True, slots=True)
class AcquiredRepo:
    """The result of acquiring a repo: where it is + its identity/provenance."""

    working_dir: str
    repo_uid: str
    root_commit: str | None
    normalized_remote: str | None
    asset_id: str
    asset_version: int
    tree_checksum: str
    reused: bool
    source: str
    _cleanup: Callable[[], None] | None = None

    def cleanup(self) -> None:
        """Delete the transient clone workspace (no-op for a caller-owned local path)."""
        if self._cleanup is not None:
            self._cleanup()


class RepoAcquirer:
    """Acquire a repo (local path or shallow clone) → register a ``git_repo`` asset (B.1)."""

    def __init__(
        self,
        asset_store: "AssetStore",
        storage: "StorageManager",
        *,
        git: GitAcquirer | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = asset_store
        self._storage = storage
        self._git = git or GitAcquirer()
        self._logger = logger or logging.getLogger("atlas.engineering.ingest")

    def acquire(
        self,
        *,
        path: str | None = None,
        url: str | None = None,
        branch: str | None = None,
        mission_id: str | None = None,
    ) -> AcquiredRepo:
        """Produce a working copy and register/update its ``git_repo`` asset.

        Exactly one of ``path`` / ``url`` is required. For ``url`` a shallow read-only clone
        lands in a Storage workspace (deleted via :meth:`AcquiredRepo.cleanup`); the **asset**
        is the durable copy (Q-B2).
        """
        if bool(path) == bool(url):
            raise RepoAcquireError("acquire requires exactly one of path=… or url=…")

        working_dir, cleanup, source = self._checkout(path=path, url=url, branch=branch)
        try:
            root = Path(working_dir)
            if not root.is_dir():
                raise RepoAcquireError(f"not a directory: {working_dir}")

            root_commit = self._git.root_commit(root)
            remote = normalize_remote(url or self._git.remote_url(root))
            repo_uid = self._resolve_uid(root_commit, remote, root)
            checksum = compute_tree_checksum(root)

            asset_id, version, reused = self._register(
                repo_uid=repo_uid,
                root=root,
                checksum=checksum,
                source=source,
                root_commit=root_commit,
                remote=remote,
                mission_id=mission_id,
            )
        except Exception:
            cleanup()
            raise

        return AcquiredRepo(
            working_dir=str(working_dir),
            repo_uid=repo_uid,
            root_commit=root_commit,
            normalized_remote=remote,
            asset_id=asset_id,
            asset_version=version,
            tree_checksum=checksum,
            reused=reused,
            source=source,
            _cleanup=cleanup,
        )

    # --- checkout -------------------------------------------------------
    def _checkout(
        self, *, path: str | None, url: str | None, branch: str | None
    ) -> tuple[Path, Callable[[], None], str]:
        if path:
            resolved = Path(path).expanduser().resolve()
            if not resolved.is_dir():
                raise RepoAcquireError(f"not a directory: {resolved}")
            return resolved, (lambda: None), str(resolved)

        assert url is not None
        ws = self._storage.allocate_workspace("engineering-clones")
        dest = ws / uuid.uuid4().hex
        result = self._git.clone_shallow(url, dest, branch=branch)
        if result.get("outcome") != GIT_OK:
            shutil.rmtree(dest, ignore_errors=True)
            raise RepoAcquireError(
                f"clone failed for {url}: {result.get('reason', result.get('outcome'))}"
            )

        def _cleanup() -> None:
            shutil.rmtree(dest, ignore_errors=True)

        return dest, _cleanup, url

    # --- identity (BB12) ------------------------------------------------
    @staticmethod
    def _resolve_uid(root_commit: str | None, remote: str | None, root: Path) -> str:
        """Stable repo_uid: root-commit → normalized remote → working path (deterministic)."""
        if root_commit:
            return str(uuid.uuid5(_REPO_NS, f"commit:{root_commit}"))
        if remote:
            return str(uuid.uuid5(_REPO_NS, f"remote:{remote}"))
        return str(uuid.uuid5(_REPO_NS, f"path:{root}"))

    # --- asset registration --------------------------------------------
    def _register(
        self,
        *,
        repo_uid: str,
        root: Path,
        checksum: str,
        source: str,
        root_commit: str | None,
        remote: str | None,
        mission_id: str | None,
    ) -> tuple[str, int, bool]:
        """Reuse the current asset version if the tree is unchanged; else register a new one."""
        existing = self._assets.get_by_name(ASSET_KIND_REPO, repo_uid)
        if existing is not None:
            versions = self._assets.versions(str(existing["id"]))
            if versions:
                current = versions[0]
                if (current.get("metadata") or {}).get("tree_checksum") == checksum:
                    self._logger.info(
                        "repo %s unchanged (tree %s…) — reusing asset v%s",
                        repo_uid, checksum[:12], current["version"],
                    )
                    return str(existing["id"]), int(current["version"]), True

        metadata: dict[str, Any] = {
            "tree_checksum": checksum,
            "repo_uid": repo_uid,
            "source": source,
        }
        if root_commit:
            metadata["root_commit"] = root_commit
        if remote:
            metadata["normalized_remote"] = remote
        if mission_id:
            metadata["mission_id"] = mission_id

        result = self._assets.register(
            ASSET_KIND_REPO,
            repo_uid,
            _pack_tree(root),
            source_uri=source,
            content_type="application/gzip",
            metadata=metadata,
        )
        asset_id = str(result["asset"]["id"])
        version = int(result["version"]["version"])
        self._logger.info(
            "registered repo asset %s v%s (tree %s…)", repo_uid, version, checksum[:12]
        )
        return asset_id, version, False
