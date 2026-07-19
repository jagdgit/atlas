"""RepoWatcher worker + Repository-Learning template tests (Phase B · §B.6).

Hermetic: a fake IntelligenceService records `learn_repository` calls so we verify the
Detect→Compare→Policy→Ingest tick — first ingest, cheap **Detect** no-op on an unchanged tree,
re-ingest after a change, forced re-ingest via live input, versioned-config pickup, and ingest
failure → worker error. A manager-driven test proves checkpoint **resume** + Detect short-circuit.
"""

from __future__ import annotations

import pytest

from atlas.configuration.schemas import ConfigSchemaError, default_registry
from atlas.missions.templates.builtins import BUILTIN_TEMPLATES
from atlas.workers.base import TickContext
from atlas.workers.repo_watcher import (
    POLICY_FULL_INGEST,
    POLICY_SKIP,
    RepoWatcher,
    decide_policy,
)


# --- fakes ---------------------------------------------------------------
def _ok(version=1, reused=False, diff=None, findings=3, design=0, checksum=None, name="svc"):
    return {
        "outcome": "ok",
        "repository": {"name": name, "repo_uid": "uid-1"},
        "findings": findings,
        "design_findings": design,
        "architecture_graph": {"version": version, "reused": reused, "diff": diff},
        "asset": {"reused": reused, "asset_version": version, "tree_checksum": checksum},
    }


class FakeIntel:
    def __init__(self, results=None):
        self._results = list(results or [])
        self.calls: list[dict] = []

    def learn_repository(self, **kw):
        self.calls.append(kw)
        return self._results.pop(0) if self._results else _ok()


def _repo(tmp_path, text="print(1)\n"):
    d = tmp_path / "svc"
    d.mkdir(exist_ok=True)
    (d / "a.py").write_text(text)
    return str(d)


def _ctx(root, *, state=None, config_version=1, inputs=None, embed=False):
    return TickContext(
        worker_id="w1", mission_id="m1",
        config={"repo_path": root, "embed_code": embed, "policy": "project"},
        config_version=config_version, state=state or {}, inputs=inputs or [],
    )


# --- policy hook ---------------------------------------------------------
def test_decide_policy():
    assert decide_policy({"changed": True}) == POLICY_FULL_INGEST
    assert decide_policy({"changed": False}) == POLICY_SKIP
    assert decide_policy({}) == POLICY_FULL_INGEST  # default: ingest when unknown


# --- tick behaviour ------------------------------------------------------
def test_first_tick_ingests_and_records_state(tmp_path):
    root = _repo(tmp_path)
    intel = FakeIntel([_ok(version=1, findings=4, design=2)])
    w = RepoWatcher(intel)
    res = w.do_tick(_ctx(root))
    assert len(intel.calls) == 1
    assert intel.calls[0]["path"] == root
    assert res.state["ingests"] == 1
    assert res.state["last_result"] == "ingested"
    assert res.state["config_version"] == 1
    assert "ingested svc" in res.note and "config v1 picked up" in res.note
    assert res.state["last_tree_checksum"]  # detected checksum stored for next Detect


def test_unchanged_tree_is_cheap_noop(tmp_path):
    root = _repo(tmp_path)
    intel = FakeIntel([_ok()])
    w = RepoWatcher(intel)
    first = w.do_tick(_ctx(root))
    # Second tick, same tree + same config version → Detect short-circuits, no ingest.
    second = w.do_tick(_ctx(root, state=first.state, config_version=1))
    assert len(intel.calls) == 1               # no new learn_repository call
    assert second.state["last_result"] == "no_change"
    assert second.note == ""                    # quiet no-op (nothing journaled)
    assert second.state["ticks"] == first.state["ticks"] + 1


def test_changed_tree_triggers_reingest(tmp_path):
    root = _repo(tmp_path)
    intel = FakeIntel([
        _ok(version=1),
        _ok(version=2, diff={"changed": True, "added_modules": ["b.py"]}),
    ])
    w = RepoWatcher(intel)
    first = w.do_tick(_ctx(root))
    (tmp_path / "svc" / "b.py").write_text("x = 2\n")  # real change → checksum differs
    second = w.do_tick(_ctx(root, state=first.state))
    assert len(intel.calls) == 2
    assert second.state["ingests"] == 2
    assert second.state["last_change_set"]["changed"] is True
    assert second.state["last_policy"] == POLICY_FULL_INGEST
    assert "structural change" in second.note


def test_force_input_reingests_unchanged_tree(tmp_path):
    root = _repo(tmp_path)
    intel = FakeIntel([_ok(), _ok()])
    w = RepoWatcher(intel)
    first = w.do_tick(_ctx(root))
    forced = w.do_tick(_ctx(root, state=first.state, inputs=[{"force": True}]))
    assert len(intel.calls) == 2  # forced past the Detect short-circuit


def test_config_version_pickup_noted_on_noop(tmp_path):
    root = _repo(tmp_path)
    intel = FakeIntel([_ok()])
    w = RepoWatcher(intel)
    first = w.do_tick(_ctx(root, config_version=1))
    # Unchanged tree but a NEW config version → still a no-op ingest-wise, but journaled.
    second = w.do_tick(_ctx(root, state=first.state, config_version=2))
    assert len(intel.calls) == 1
    assert second.state["config_version"] == 2
    assert "config v2 picked up" in second.note


def test_no_repo_configured_is_quiet_idle():
    intel = FakeIntel()
    w = RepoWatcher(intel)
    ctx = TickContext(worker_id="w", mission_id="m", config={}, config_version=1,
                      state={}, inputs=[])
    res = w.do_tick(ctx)
    assert intel.calls == []
    assert res.note == "" and res.done is False


def test_ingest_failure_raises_for_backoff(tmp_path):
    root = _repo(tmp_path)
    intel = FakeIntel([{"outcome": "error", "reason": "not a directory"}])
    w = RepoWatcher(intel)
    with pytest.raises(RuntimeError, match="repo ingest failed"):
        w.do_tick(_ctx(root))


def test_embed_flag_is_forwarded(tmp_path):
    root = _repo(tmp_path)
    intel = FakeIntel([_ok()])
    RepoWatcher(intel).do_tick(_ctx(root, embed=True))
    assert intel.calls[0]["embed"] is True


# --- config schema (BB7) -------------------------------------------------
def test_repo_watcher_config_registered_and_strict():
    reg = default_registry()
    assert "repo_watcher" in reg.known()
    doc, version = reg.validate("repo_watcher", {"repo_path": "/x", "languages": ["python", "sql"]})
    assert version == 1
    assert doc["repo_path"] == "/x" and doc["embed_code"] is False
    # extra='forbid': a typo'd key is rejected, never stored.
    with pytest.raises(ConfigSchemaError):
        reg.validate("repo_watcher", {"repoo_path": "/x"})
    # bad interval rejected.
    with pytest.raises(ConfigSchemaError):
        reg.validate("repo_watcher", {"tick_interval_seconds": 0})


# --- template wiring -----------------------------------------------------
def test_repository_learning_template_is_real():
    tmpl = next(t for t in BUILTIN_TEMPLATES if t["name"] == "repository_learning")
    assert tmpl["config_schema_type"] == "repo_watcher"
    assert tmpl["template_version"] >= 2
    assert {"type": "repo_watcher", "interval_seconds": 3600} in tmpl["worker_specs"]
    # default_config validates against the strict schema.
    doc, _ = default_registry().validate("repo_watcher", tmpl["default_config"])
    assert doc["languages"] == ["python"]


# --- manager-driven resume + Detect short-circuit ------------------------
def test_manager_resume_and_detect_short_circuit(tmp_path):
    from tests.test_workers import (
        FakeCheckpoints,
        FakeConfigRepo,
        FakeMissionRepo,
        FakeSchedules,
        FakeWorkerRepo,
    )
    from atlas.workers.manager import WorkerManager

    root = _repo(tmp_path)
    intel = FakeIntel([_ok(version=1)])  # one ingest, then default _ok() if called again
    repo = FakeWorkerRepo()
    cps = FakeCheckpoints()
    scheds = FakeSchedules()
    cfg = FakeConfigRepo(version=1, document={
        "repo_path": root, "repo_url": "", "branch": None,
        "languages": ["python"], "embed_code": False, "policy": "project",
        "tick_interval_seconds": 3600,
    })
    missions = FakeMissionRepo()
    mgr = WorkerManager(repo, cps, schedule_service=scheds, config_repo=cfg,
                        mission_repo=missions, clock=None)
    mgr.register_worker_type(RepoWatcher(intel))
    worker = mgr.create_worker("m1", "repo_watcher", interval_seconds=3600)

    r1 = mgr.worker_tick({"worker_id": worker.id})
    assert r1["ticked"] is True
    assert len(intel.calls) == 1
    # Checkpoint persisted the tree checksum — a "reboot" (fresh manager, same stores) resumes it.
    saved = cps.load("worker", worker.id)
    assert saved["ingests"] == 1 and saved["last_tree_checksum"]

    mgr2 = WorkerManager(repo, cps, schedule_service=scheds, config_repo=cfg,
                         mission_repo=missions, clock=None)
    mgr2.register_worker_type(RepoWatcher(intel))
    r2 = mgr2.worker_tick({"worker_id": worker.id})
    assert r2["ticked"] is True
    assert len(intel.calls) == 1  # resumed state → Detect short-circuits → no re-ingest
    assert any(e["action"] == "worker_created" for e in missions.journal)
