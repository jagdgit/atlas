"""Tests for the operations layer (Sprint 9): Prometheus rendering + backups.

Hermetic: pg_dump is monkeypatched so no PostgreSQL is required; retention logic
runs against a tmp directory.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from atlas.config import DatabaseConfig
from atlas.ops.backup import BackupError, BackupManager
from atlas.telemetry.prometheus import render_prometheus


# --- Prometheus renderer ------------------------------------------------
def test_render_counters_and_gauges():
    snap = {
        "counters": {"llm.calls": 5.0, "scheduler.task.completed|type=ingest": 2.0},
        "gauges": {"queue.depth": 3.0},
        "histograms": {},
    }
    text = render_prometheus(snap)
    assert "atlas_llm_calls 5.0" in text
    assert 'atlas_scheduler_task_completed{type="ingest"} 2.0' in text
    assert "atlas_queue_depth 3.0" in text


def test_render_histogram_expands_stats():
    snap = {
        "counters": {},
        "gauges": {},
        "histograms": {
            "llm.latency": {"count": 2, "sum": 4.0, "avg": 2.0, "max": 3.0,
                            "p50": 1.0, "p95": 3.0}
        },
    }
    text = render_prometheus(snap)
    assert "atlas_llm_latency_count 2" in text
    assert "atlas_llm_latency_sum 4.0" in text
    assert "atlas_llm_latency_p95 3.0" in text


def test_render_empty_snapshot():
    assert render_prometheus({"counters": {}, "gauges": {}, "histograms": {}}) == "\n"


def test_render_sanitizes_and_escapes():
    snap = {"counters": {'x|path=a"b': 1.0}, "gauges": {}, "histograms": {}}
    text = render_prometheus(snap)
    assert 'path="a\\"b"' in text


# --- BackupManager ------------------------------------------------------
def _db() -> DatabaseConfig:
    return DatabaseConfig(host="localhost", port=5432, database="atlas",
                          user="atlas", password="secret")


def _touch(dir_: Path, name: str) -> Path:
    p = dir_ / name
    p.write_text("dump")
    return p


def test_backup_invokes_pg_dump_and_returns_path(tmp_path, monkeypatch):
    captured = {}

    def fake_run(cmd, env=None, capture_output=False, text=False, check=False):
        captured["cmd"] = cmd
        captured["env"] = env
        Path(cmd[cmd.index("--file") + 1]).write_text("dump")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    mgr = BackupManager(_db(), tmp_path)
    out = mgr.backup()

    assert out.exists()
    assert out.parent == tmp_path
    assert captured["cmd"][0] == "pg_dump"
    assert "--format=custom" in captured["cmd"]
    assert captured["env"]["PGPASSWORD"] == "secret"


def test_backup_raises_on_failure(tmp_path, monkeypatch):
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    mgr = BackupManager(_db(), tmp_path)
    with pytest.raises(BackupError):
        mgr.backup()


def test_backup_raises_when_pg_dump_missing(tmp_path, monkeypatch):
    def fake_run(cmd, **kw):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(subprocess, "run", fake_run)
    mgr = BackupManager(_db(), tmp_path, pg_dump_path="nope")
    with pytest.raises(BackupError):
        mgr.backup()


def test_prune_keeps_retention_newest(tmp_path):
    for stamp in ("20260101_000000", "20260102_000000", "20260103_000000"):
        _touch(tmp_path, f"atlas_atlas_{stamp}.dump")
    mgr = BackupManager(_db(), tmp_path, retention=2)
    removed = mgr.prune()
    remaining = {p.name for p in mgr.list_backups()}
    assert removed == 1
    assert remaining == {
        "atlas_atlas_20260103_000000.dump",
        "atlas_atlas_20260102_000000.dump",
    }


def test_prune_disabled_when_retention_zero(tmp_path):
    _touch(tmp_path, "atlas_atlas_20260101_000000.dump")
    mgr = BackupManager(_db(), tmp_path, retention=0)
    assert mgr.prune() == 0


def test_backup_task_reenqueues(tmp_path, monkeypatch):
    def fake_run(cmd, **kw):
        Path(cmd[cmd.index("--file") + 1]).write_text("dump")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    calls = []
    mgr = BackupManager(
        _db(), tmp_path, interval_seconds=3600,
        enqueue=lambda *a, **k: calls.append((a, k)),
    )
    result = mgr.backup_task({})
    assert result["kept"] == 1
    assert calls and calls[0][0][0] == "backup"


def test_start_seeds_when_none_pending(tmp_path):
    seeded = []
    mgr = BackupManager(
        _db(), tmp_path, enabled=True, interval_seconds=3600,
        enqueue=lambda *a, **k: seeded.append(a),
        count_pending=lambda t: 0,
    )
    mgr.start()
    assert seeded and seeded[0][0] == "backup"


def test_start_skips_when_already_pending(tmp_path):
    seeded = []
    mgr = BackupManager(
        _db(), tmp_path, enabled=True, interval_seconds=3600,
        enqueue=lambda *a, **k: seeded.append(a),
        count_pending=lambda t: 1,
    )
    mgr.start()
    assert seeded == []


def test_start_skips_when_manual(tmp_path):
    seeded = []
    mgr = BackupManager(
        _db(), tmp_path, enabled=True, interval_seconds=0,
        enqueue=lambda *a, **k: seeded.append(a),
    )
    mgr.start()
    assert seeded == []


def test_health_reports_count(tmp_path):
    _touch(tmp_path, "atlas_atlas_20260101_000000.dump")
    status = BackupManager(_db(), tmp_path, interval_seconds=86400).health_check()
    assert status.healthy is True
    assert status.data["count"] == 1
