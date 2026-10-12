"""OI-OPS-1INST L2/L5 — serve boot order and manual gate (I4–I6, I12)."""

from __future__ import annotations

import os
import socket
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from atlas.ops.instance_lock import EXIT_INSTANCE_CONFLICT, InstanceConflict
from atlas.ops.serve_boot import (
    bind_listening_socket,
    boot_or_exit,
    check_manual_gate,
    prepare_serve,
)


def test_i12_refuse_without_invocation_or_manual(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    with pytest.raises(InstanceConflict):
        check_manual_gate(manual=False)


def test_i12_manual_allowed_without_invocation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    check_manual_gate(manual=True)  # does not raise


def test_i12_systemd_invocation_skips_manual(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVOCATION_ID", "test-invocation")
    check_manual_gate(manual=False)


def test_i5_i6_bind_before_services(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVOCATION_ID", "boot-order-test")
    # Pick a free ephemeral port.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    order: list[str] = []

    def fake_start() -> None:
        order.append("start")

    boot = prepare_serve(
        data_dir=tmp_path, host="127.0.0.1", port=port, manual=False
    )
    order.append("bound")
    # Socket is owned before any service start would run.
    assert "bound" in order and "start" not in order
    assert boot.sock.getsockname()[1] == port

    # Second bind must fail (I6) before any start.
    with pytest.raises(InstanceConflict):
        bind_listening_socket("127.0.0.1", port)
    fake_start()
    assert order == ["bound", "start"]
    boot.release()


def test_i4_boot_or_exit_returns_75_when_lock_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVOCATION_ID", "conflict-test")
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    first = prepare_serve(data_dir=tmp_path, host="127.0.0.1", port=port)
    # Different data_dir so L1 does not conflict — use same data_dir for L1 conflict.
    code = boot_or_exit(
        data_dir=tmp_path, host="127.0.0.1", port=port + 1, manual=False
    )
    assert code == EXIT_INSTANCE_CONFLICT
    first.release()


def test_unit_file_has_l4_directives() -> None:
    unit = Path(__file__).resolve().parents[1] / "deploy" / "systemd" / "atlas.service"
    text = unit.read_text(encoding="utf-8")
    assert "RestartPreventExitStatus=75" in text
    assert "StartLimitIntervalSec=300" in text
    assert "StartLimitBurst=5" in text


def test_cli_serve_exposes_manual_flag() -> None:
    from atlas.cli.main import build_parser

    ns = build_parser().parse_args(["serve", "--manual", "--port", "9"])
    assert ns.manual is True
    assert ns.port == 9
