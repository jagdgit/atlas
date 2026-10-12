"""Serve boot guards: L5 manual gate, L1 flock, L2 pre-bound socket (OI-OPS-1INST)."""

from __future__ import annotations

import logging
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas.ops.instance_lock import (
    EXIT_INSTANCE_CONFLICT,
    InstanceConflict,
    InstanceLock,
    acquire_instance_lock,
    override_active,
)

_log = logging.getLogger("atlas.ops.serve_boot")


@dataclass
class ServeBoot:
    lock: InstanceLock
    sock: socket.socket
    host: str
    port: int

    def close_socket(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def release(self) -> None:
        self.close_socket()
        self.lock.release()


def check_manual_gate(*, manual: bool, logger: logging.Logger | None = None) -> None:
    """L5: outside systemd, refuse unless ``--manual``."""
    log = logger or _log
    if os.environ.get("INVOCATION_ID"):
        return
    if manual:
        log.warning("atlas serve --manual: starting outside systemd (L1–L3 still apply)")
        return
    msg = (
        "refusing atlas serve outside systemd (no INVOCATION_ID); "
        "pass --manual if you intend a locked single instance"
    )
    log.error(msg)
    raise InstanceConflict(msg)


def bind_listening_socket(
    host: str,
    port: int,
    *,
    logger: logging.Logger | None = None,
) -> socket.socket:
    """L2: exclusive bind before any service start. Failure → InstanceConflict."""
    log = logger or _log
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(2048)
    except OSError as exc:
        try:
            sock.close()
        except OSError:
            pass
        msg = f"listen socket bind failed on {host}:{port}: {exc}"
        log.error("refusing to start: %s", msg)
        raise InstanceConflict(msg) from exc
    log.info("listen socket bound on %s:%d (fd=%s)", host, port, sock.fileno())
    return sock


def prepare_serve(
    *,
    data_dir: str | Path,
    host: str,
    port: int,
    manual: bool = False,
    logger: logging.Logger | None = None,
) -> ServeBoot:
    """L5 → L1 → L2. Caller must keep the returned object alive while serving."""
    log = logger or _log
    check_manual_gate(manual=manual, logger=log)
    lock = acquire_instance_lock(data_dir, logger=log)
    try:
        sock = bind_listening_socket(host, port, logger=log)
    except InstanceConflict:
        lock.release()
        raise
    if override_active():
        log.critical("instance lock override active — watchdog should raise P1")
    return ServeBoot(lock=lock, sock=sock, host=host, port=port)


def boot_or_exit(
    *,
    data_dir: str | Path,
    host: str,
    port: int,
    manual: bool = False,
    logger: logging.Logger | None = None,
) -> ServeBoot | int:
    """Like prepare_serve but returns EXIT_INSTANCE_CONFLICT on conflict."""
    try:
        return prepare_serve(
            data_dir=data_dir, host=host, port=port, manual=manual, logger=logger
        )
    except InstanceConflict as exc:
        (logger or _log).error("%s", exc)
        return EXIT_INSTANCE_CONFLICT
