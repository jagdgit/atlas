"""OI-OPS-1INST L1 — process flock tests (I1–I3, override)."""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import time
from pathlib import Path

import pytest

from atlas.ops.instance_lock import (
    EXIT_INSTANCE_CONFLICT,
    OVERRIDE_ENV,
    OVERRIDE_VALUE,
    InstanceConflict,
    acquire_instance_lock,
    lock_path,
)


def _holder_proc(data_dir: str, ready: mp.Event, release: mp.Event, result: mp.Queue) -> None:
    try:
        lock = acquire_instance_lock(data_dir)
        result.put({"ok": True, "pid": os.getpid(), "inode": lock.path.stat().st_ino})
        ready.set()
        release.wait(timeout=30)
        lock.release()
    except Exception as exc:  # noqa: BLE001
        result.put({"ok": False, "error": str(exc)})
        ready.set()


def test_i1_second_acquire_fails_fast(tmp_path: Path) -> None:
    ready = mp.Event()
    release = mp.Event()
    q: mp.Queue = mp.Queue()
    child = mp.Process(target=_holder_proc, args=(str(tmp_path), ready, release, q))
    child.start()
    assert ready.wait(timeout=10)
    first = q.get(timeout=5)
    assert first["ok"] is True

    with pytest.raises(InstanceConflict) as ei:
        acquire_instance_lock(tmp_path)
    assert ei.value.holder.get("pid") == first["pid"]
    assert EXIT_INSTANCE_CONFLICT == 75

    release.set()
    child.join(timeout=10)
    assert child.exitcode == 0


def _crash_holder(data_dir: str, ready: mp.Event) -> None:
    """Acquire then hard-exit without unlock — kernel drops the flock (I2)."""
    acquire_instance_lock(data_dir)
    ready.set()
    time.sleep(0.3)
    os._exit(1)


def test_i2_holder_crash_releases_lock(tmp_path: Path) -> None:
    ready = mp.Event()
    child = mp.Process(target=_crash_holder, args=(str(tmp_path), ready))
    child.start()
    assert ready.wait(timeout=10)
    child.join(timeout=10)
    assert child.exitcode not in (None, 0)
    time.sleep(0.1)

    lock = acquire_instance_lock(tmp_path)
    assert lock.fd >= 0
    lock.release()


def test_i3_lock_file_inode_stable(tmp_path: Path) -> None:
    lock1 = acquire_instance_lock(tmp_path)
    path = lock_path(tmp_path)
    inode1 = path.stat().st_ino
    lock1.release()

    lock2 = acquire_instance_lock(tmp_path)
    inode2 = path.stat().st_ino
    assert inode1 == inode2
    # File must still exist (never unlinked)
    assert path.is_file()
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["pid"] == os.getpid()
    lock2.release()


def test_override_skips_flock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OVERRIDE_ENV, OVERRIDE_VALUE)
    a = acquire_instance_lock(tmp_path)
    b = acquire_instance_lock(tmp_path)
    assert a.overridden and b.overridden
    a.release()
    b.release()
