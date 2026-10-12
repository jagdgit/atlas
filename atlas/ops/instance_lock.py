"""L1 single-instance process lock (OI-OPS-1INST / OI-DELI0 Step 0B).

``flock(LOCK_EX|LOCK_NB)`` on ``{data_dir}/run/atlas.lock``. The file is created
once and **never unlinked, renamed, or replaced**. Holder diagnostics are written
through the locked fd.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXIT_INSTANCE_CONFLICT = 75
OVERRIDE_ENV = "ATLAS_INSTANCE_LOCK_OVERRIDE"
OVERRIDE_VALUE = "I_CONFIRM_SINGLE_INSTANCE"
LOCK_REL = Path("run") / "atlas.lock"

_log = logging.getLogger("atlas.ops.instance_lock")


class InstanceConflict(RuntimeError):
    """Another process holds the L1 lock (or bind/manual gate refused)."""

    def __init__(self, message: str, *, holder: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.holder = holder or {}


@dataclass
class InstanceLock:
    """Held L1 flock. Keep this object alive for the process lifetime."""

    path: Path
    fd: int
    overridden: bool = False

    def release(self) -> None:
        if self.fd < 0:
            return
        try:
            import fcntl

            fcntl.flock(self.fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.fd = -1

    def __enter__(self) -> "InstanceLock":
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def lock_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / LOCK_REL


def override_active() -> bool:
    return os.environ.get(OVERRIDE_ENV) == OVERRIDE_VALUE


def _git_sha() -> str | None:
    try:
        import subprocess

        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        sha = (out.stdout or "").strip()
        return sha or None
    except Exception:  # noqa: BLE001
        return None


def _read_holder(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        doc = json.loads(raw)
        return doc if isinstance(doc, dict) else {"raw": raw}
    except Exception:  # noqa: BLE001
        return {}


def _write_diagnostics(fd: int, *, data_dir: Path) -> dict[str, Any]:
    payload = {
        "pid": os.getpid(),
        "started_at": time.time(),
        "started_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "invocation_id": os.environ.get("INVOCATION_ID"),
        "git_sha": _git_sha(),
        "host": socket.gethostname(),
        "data_dir": str(data_dir),
    }
    blob = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, blob)
    os.fsync(fd)
    return payload


def ensure_run_dir(data_dir: str | Path) -> Path:
    run = Path(data_dir) / "run"
    run.mkdir(mode=0o750, parents=True, exist_ok=True)
    try:
        os.chmod(run, 0o750)
    except OSError:
        pass
    return run


def acquire_instance_lock(
    data_dir: str | Path,
    *,
    logger: logging.Logger | None = None,
) -> InstanceLock:
    """Acquire L1. Raises ``InstanceConflict`` on failure (caller exits 75)."""
    log = logger or _log
    data = Path(data_dir)
    ensure_run_dir(data)
    path = lock_path(data)

    if override_active():
        log.critical(
            "ATLAS_INSTANCE_LOCK_OVERRIDE is set — L1 disabled; "
            "operator must confirm no other instance shares this host/DB"
        )
        # Still open/create the file for diagnostics visibility, but do not flock.
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o640)
        try:
            _write_diagnostics(fd, data_dir=data)
        except OSError:
            pass
        return InstanceLock(path=path, fd=fd, overridden=True)

    import fcntl

    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o640)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        holder = _read_holder(path)
        try:
            os.close(fd)
        except OSError:
            pass
        msg = (
            f"instance lock held by pid={holder.get('pid')!r} "
            f"started={holder.get('started_at_iso')!r} "
            f"invocation={holder.get('invocation_id')!r} path={path}"
        )
        log.error("refusing to start: %s", msg)
        raise InstanceConflict(msg, holder=holder) from exc

    diagnostics = _write_diagnostics(fd, data_dir=data)
    log.info(
        "instance lock acquired pid=%s path=%s invocation=%s",
        diagnostics.get("pid"),
        path,
        diagnostics.get("invocation_id"),
    )
    return InstanceLock(path=path, fd=fd, overridden=False)
