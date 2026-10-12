"""OI-OPS-1INST L6 — watchdog single-instance detection (I11)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "ops_watchdog", _ROOT / "scripts" / "ops_watchdog.py"
)
assert _SPEC and _SPEC.loader
wd = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(wd)


def test_i11_multi_instance_finding(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(wd, "_service_active", lambda: (True, "active"))
    monkeypatch.setattr(wd, "_heartbeat_age", lambda _d: 10.0)
    monkeypatch.setattr(wd, "_db_reachable", lambda h, p: (True, "ok"))
    monkeypatch.setattr(wd, "_atlas_serve_pids", lambda: [100, 200])
    monkeypatch.setattr(wd, "_main_pid", lambda: 100)
    monkeypatch.setattr(wd, "_lock_holder_pid", lambda _d: 100)
    monkeypatch.setattr(wd, "_errno98_recent", lambda: False)
    monkeypatch.setattr(wd, "_override_active", lambda: False)

    findings = wd._checks(tmp_path, "127.0.0.1", 5432)
    assert "multi_instance" in findings
    assert findings["multi_instance"]["severity"] == "P0"


def test_i11_lock_pid_mismatch(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(wd, "_service_active", lambda: (True, "active"))
    monkeypatch.setattr(wd, "_heartbeat_age", lambda _d: 10.0)
    monkeypatch.setattr(wd, "_db_reachable", lambda h, p: (True, "ok"))
    monkeypatch.setattr(wd, "_atlas_serve_pids", lambda: [100])
    monkeypatch.setattr(wd, "_main_pid", lambda: 100)
    monkeypatch.setattr(wd, "_lock_holder_pid", lambda _d: 999)
    monkeypatch.setattr(wd, "_errno98_recent", lambda: False)
    monkeypatch.setattr(wd, "_override_active", lambda: False)

    findings = wd._checks(tmp_path, "127.0.0.1", 5432)
    assert "lock_pid_mismatch" in findings


def test_i11_override_is_p1(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(wd, "_service_active", lambda: (True, "active"))
    monkeypatch.setattr(wd, "_heartbeat_age", lambda _d: 10.0)
    monkeypatch.setattr(wd, "_db_reachable", lambda h, p: (True, "ok"))
    monkeypatch.setattr(wd, "_atlas_serve_pids", lambda: [100])
    monkeypatch.setattr(wd, "_main_pid", lambda: 100)
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "atlas.lock").write_text(
        json.dumps({"pid": 100}) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(wd, "_errno98_recent", lambda: False)
    monkeypatch.setattr(wd, "_override_active", lambda: True)

    findings = wd._checks(tmp_path, "127.0.0.1", 5432)
    assert findings["instance_lock_override"]["severity"] == "P1"


def test_lock_holder_pid_reads_file(tmp_path: Path) -> None:
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "atlas.lock").write_text(
        json.dumps({"pid": 4242}) + "\n", encoding="utf-8"
    )
    assert wd._lock_holder_pid(tmp_path) == 4242


def test_serve_pid_detection_ignores_cursor_sandbox(monkeypatch) -> None:
    ps = """\
  100 /data/atlas/.venv/bin/python3 /data/atlas/.venv/bin/atlas serve
  200 /usr/share/cursor/resources/app/resources/helpers/cursorsandbox --policy x -- atlas serve --manual
  300 bash -c echo atlas serve in a script body
"""

    class _Out:
        stdout = ps

    monkeypatch.setattr(
        wd.subprocess,
        "run",
        lambda *a, **k: _Out(),
    )
    assert wd._atlas_serve_pids() == [100]
