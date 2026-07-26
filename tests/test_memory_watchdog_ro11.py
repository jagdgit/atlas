"""IR-RO11 — Runtime Memory Watchdog + cooperative archive yield."""

from __future__ import annotations

from atlas.core.resources.memory_watchdog import (
    ACTION_PAUSE_WORKER,
    ACTION_YIELD_TICK,
    RuntimeMemoryWatchdog,
)
from atlas.workers.base import TickContext, TickResult
from atlas.workers.owner_knowledge import OwnerKnowledgeWorker


class _FakeVerdict:
    def __init__(self, ok=True, action="continue", reason="ok"):
        self.ok = ok
        self.action = action
        self.reason = reason

    def as_dict(self):
        return {"ok": self.ok, "action": self.action, "reason": self.reason}


def test_watchdog_yields_when_tick_delta_exceeds_budget(monkeypatch):
    dog = RuntimeMemoryWatchdog(
        host_ram_reserve_mb=1,
        process_rss_soft_mb=50_000,
        soft_ratio=0.85,
        min_check_interval_s=0.0,
    )
    rss = {"v": 100.0}

    def fake_rss():
        return rss["v"]

    monkeypatch.setattr(
        "atlas.core.resources.memory_watchdog.process_rss_mb", fake_rss
    )
    monkeypatch.setattr(
        "atlas.core.resources.memory_watchdog.read_snapshot",
        lambda logger=None: type("S", (), {"mem_available_kb": 8_000_000, "ram_used_fraction": 0.2})(),
    )
    session = dog.begin_tick(worker_id="w1", worker_type="owner_knowledge", budget_mb=200)
    assert session.baseline_rss_mb == 100.0
    ok = session.check()
    assert ok.ok
    rss["v"] = 400.0  # +300 MB > 200 budget
    bad = session.check(force=True)
    assert not bad.ok
    assert bad.action == ACTION_YIELD_TICK


def test_watchdog_pauses_when_process_ceiling_hit(monkeypatch):
    dog = RuntimeMemoryWatchdog(
        host_ram_reserve_mb=1,
        process_rss_soft_mb=500,
        soft_ratio=0.85,
        min_check_interval_s=0.0,
    )
    monkeypatch.setattr(
        "atlas.core.resources.memory_watchdog.process_rss_mb", lambda: 600.0
    )
    monkeypatch.setattr(
        "atlas.core.resources.memory_watchdog.read_snapshot",
        lambda logger=None: type("S", (), {"mem_available_kb": 8_000_000, "ram_used_fraction": 0.2})(),
    )
    session = dog.begin_tick(worker_id="w1", budget_mb=512)
    bad = session.check(force=True)
    assert not bad.ok
    assert bad.action == ACTION_PAUSE_WORKER


def test_owner_knowledge_yields_on_memory_signal():
    calls = {"n": 0}

    def memory_check(*, force: bool = False):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeVerdict(ok=False, action=ACTION_YIELD_TICK, reason="test_budget")
        return _FakeVerdict(ok=False, action=ACTION_YIELD_TICK, reason="test_budget")

    worker = OwnerKnowledgeWorker(ingestion=object(), intelligence=object())
    ctx = TickContext(
        worker_id="w",
        mission_id="m",
        config={
            "archive_roots": [{"path": "/tmp/does-not-need-to-exist-yet", "kind": "document"}],
            "archive_mode": "one_shot",
            "build_profile": False,
            "backfill_orphan_assets": False,
            "reextract_stale": False,
        },
        config_version=1,
        state={},
        memory_check=memory_check,
    )
    # Gate runs at start of first root before discover — path may 404; we yield first.
    # Force gate by making check fail before process_root tries the path:
    # Actually gate is called after root_state[path]=entry at start of loop, before _process_root.
    # Path doesn't need to exist until _process_root. Good.
    result = worker.do_tick(ctx)
    assert isinstance(result, TickResult)
    assert result.state.get("memory_action") == ACTION_YIELD_TICK
    assert "IR-RO11" in (result.note or "")
    assert result.state.get("phase") == "memory_budget_pause"


def test_watchdog_snapshot_shape():
    snap = RuntimeMemoryWatchdog().snapshot()
    assert snap["version"] == "ro11.v0"
    assert snap["layer"] == 2
    assert "process_rss_soft_mb" in snap
