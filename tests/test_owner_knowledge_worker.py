"""Hermetic tests for the OwnerKnowledgeWorker (C.8c)."""

from __future__ import annotations

from pathlib import Path

from atlas.workers.base import TickContext
from atlas.workers.owner_knowledge import OwnerKnowledgeWorker


class _FakeIngestion:
    def __init__(self):
        self.calls: list[dict] = []

    def ingest_file(self, path, *, kind, domain, embed, extract_findings, reader, source):
        self.calls.append({"path": str(path), "kind": kind, "domain": domain,
                           "source": source, "reader": reader})
        return type("R", (), {"candidates": 2})()


class _FakeIntelligence:
    def __init__(self):
        self.learned: list[str] = []

    def learn_repository(self, *, path, mission_id, policy, embed):
        self.learned.append(path)
        return {"outcome": "ok", "findings": 5, "experiences": 3}


class _FakePersonal:
    def __init__(self):
        self.infers = 0

    def infer(self):
        self.infers += 1
        return {"skills": 7, "identity": 1, "timeline": 2}


class _ConvReader:
    id = "conversation"
    VERSION = "1.0.0"


def _ctx(config, state=None, inputs=None):
    return TickContext(
        worker_id="w1", mission_id="m1", config=config, config_version=1,
        state=state or {}, inputs=inputs or [],
    )


def _worker(**kw):
    return OwnerKnowledgeWorker(
        ingestion=kw.get("ingestion", _FakeIngestion()),
        intelligence=kw.get("intelligence", _FakeIntelligence()),
        personal=kw.get("personal", _FakePersonal()),
        conversation_reader=kw.get("conversation_reader", _ConvReader()),
    )


def _archive(tmp_path: Path) -> dict:
    code = tmp_path / "repo"; code.mkdir()
    (code / "main.py").write_text("def x():\n    return 1\n")
    docs = tmp_path / "docs"; docs.mkdir()
    (docs / "note.md").write_text("# Note\nAtlas uses Redis.\n")
    chats = tmp_path / "chats"; chats.mkdir()
    (chats / "c.jsonl").write_text('{"role":"user","content":"I used Celery"}\n')
    return {
        "archive_roots": [
            {"path": str(code), "kind": "code", "domain": "engineering"},
            {"path": str(docs), "kind": "document", "domain": "personal"},
            {"path": str(chats), "kind": "conversation", "domain": "personal"},
        ],
        "build_profile": True, "embed": False, "policy": "project",
        "tick_interval_seconds": 3600,
    }


def test_idle_when_no_roots():
    result = _worker().do_tick(_ctx({"archive_roots": []}))
    assert result.note == ""


def test_tick_processes_all_kinds_and_builds_profile(tmp_path):
    ing, intel, personal = _FakeIngestion(), _FakeIntelligence(), _FakePersonal()
    worker = _worker(ingestion=ing, intelligence=intel, personal=personal)
    result = worker.do_tick(_ctx(_archive(tmp_path)))

    assert intel.learned  # code root learned
    # doc + chat files ingested through the bridge
    kinds = {c["source"] for c in ing.calls}
    assert kinds == {"document", "conversation"}
    # conversation used the override reader
    conv_call = next(c for c in ing.calls if c["source"] == "conversation")
    assert conv_call["reader"] is not None
    assert personal.infers == 1
    assert "repo" in result.note and "profile skills=7" in result.note
    assert result.state["ticks"] == 1


def test_unchanged_roots_are_skipped_on_second_tick(tmp_path):
    ing, intel = _FakeIngestion(), _FakeIntelligence()
    worker = _worker(ingestion=ing, intelligence=intel)
    config = _archive(tmp_path)
    first = worker.do_tick(_ctx(config))
    calls_after_first = len(ing.calls)
    learned_after_first = len(intel.learned)

    # Second tick with the carried state and nothing changed → all roots skipped, cheap no-op.
    second = worker.do_tick(_ctx(config, state=first.state))
    assert len(ing.calls) == calls_after_first  # no re-ingest of unchanged docs/chats
    assert len(intel.learned) == learned_after_first
    assert second.state["last_totals"]["skipped"] == 3
    assert "no change" in second.note or second.note == ""


def test_reboot_resume_uses_checkpoint_state(tmp_path):
    config = _archive(tmp_path)
    first = _worker().do_tick(_ctx(config))

    # A brand-new worker instance (simulating a reboot) fed the persisted checkpoint state
    # must recognise the roots as unchanged and skip them.
    fresh = _worker()
    resumed = fresh.do_tick(_ctx(config, state=first.state))
    assert resumed.state["last_totals"]["skipped"] == 3


def test_force_input_reprocesses_even_when_unchanged(tmp_path):
    ing = _FakeIngestion()
    worker = _worker(ingestion=ing)
    config = _archive(tmp_path)
    first = worker.do_tick(_ctx(config))
    before = len(ing.calls)
    forced = worker.do_tick(_ctx(config, state=first.state, inputs=[{"force": True}]))
    assert len(ing.calls) > before  # force re-ingests


def test_bad_root_does_not_crash_tick(tmp_path):
    config = {
        "archive_roots": [{"path": str(tmp_path / "missing"), "kind": "document"}],
        "build_profile": False,
    }
    result = _worker().do_tick(_ctx(config))
    assert result.state["last_totals"]["errors"] == 1
