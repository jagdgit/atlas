"""Tests for the per-job Workspace (Stage 3, Step 1 / §5a, C3)."""

from __future__ import annotations

import json

from atlas.jobs.workspace import JobWorkspace


def test_for_job_builds_expected_path(tmp_path):
    ws = JobWorkspace.for_job(tmp_path, "abc123")
    assert ws.root == tmp_path / "jobs" / "job_abc123"
    # Referencing a workspace must not touch disk until a write/ensure.
    assert not ws.root.exists()


def test_ensure_creates_subdirs(tmp_path):
    ws = JobWorkspace.for_job(tmp_path, "1").ensure()
    for d in (ws.root, ws.search_dir, ws.downloads_dir, ws.documents_dir):
        assert d.is_dir()


def test_write_and_read_json_roundtrip(tmp_path):
    ws = JobWorkspace.for_job(tmp_path, "1")
    ws.write_json("claims.json", {"a": 1})
    assert ws.read_json("claims.json") == {"a": 1}
    assert ws.claims_path.is_file()


def test_read_json_missing_returns_default(tmp_path):
    ws = JobWorkspace.for_job(tmp_path, "1")
    assert ws.read_json("nope.json", default=[]) == []


def test_append_note_is_append_only(tmp_path):
    ws = JobWorkspace.for_job(tmp_path, "1")
    ws.append_note("searching scholar")
    ws.append_note("reading 1/12")
    text = ws.notes_path.read_text(encoding="utf-8")
    assert "searching scholar" in text
    assert "reading 1/12" in text
    assert text.count("\n") == 2


def test_download_and_document_paths_are_sandboxed(tmp_path):
    ws = JobWorkspace.for_job(tmp_path, "1")
    dl = ws.download_path("paper 01.pdf")
    assert dl.parent == ws.downloads_dir
    # unsafe characters (spaces) are normalized away
    assert " " not in dl.name
    doc = ws.document_path("https://ex.com/a")
    assert doc.parent == ws.documents_dir
    assert doc.suffix == ".txt"


def test_manifest_records_sources_and_counts(tmp_path):
    ws = JobWorkspace.for_job(tmp_path, "1")
    ws.init_manifest(objective="soiling loss")
    ws.record_source("s1", url="https://arxiv.org/abs/1", evidence_level=3, stage="found")
    ws.record_source("s2", url="https://ieee.org/2", evidence_level=4, stage="found")
    # advancing the same source through stages bumps each count once
    ws.record_source("s1", stage="downloaded")
    ws.record_source("s1", stage="downloaded")  # idempotent

    manifest = ws.load_manifest()
    assert manifest["objective"] == "soiling loss"
    assert manifest["counts"]["found"] == 2
    assert manifest["counts"]["downloaded"] == 1
    s1 = next(s for s in manifest["sources"] if s["id"] == "s1")
    assert set(s1["stages"]) == {"found", "downloaded"}
    assert s1["evidence_level"] == 3


def test_manifest_persists_to_disk(tmp_path):
    ws = JobWorkspace.for_job(tmp_path, "1")
    ws.init_manifest(objective="x")
    ws.record_source("s1", stage="found")
    on_disk = json.loads(ws.manifest_path.read_text(encoding="utf-8"))
    assert on_disk["counts"]["found"] == 1


def test_as_summary(tmp_path):
    ws = JobWorkspace.for_job(tmp_path, "42")
    ws.init_manifest(objective="grid batteries")
    ws.record_source("s1", stage="found")
    summary = ws.as_summary()
    assert summary["job_id"] == "42"
    assert summary["objective"] == "grid batteries"
    assert summary["source_count"] == 1
    assert summary["has_report"] is False
