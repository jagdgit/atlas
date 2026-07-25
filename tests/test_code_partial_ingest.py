"""OI-B2: partial / per-file re-parse merge into CodeService artifacts."""

from __future__ import annotations

from atlas.code.models import file_parse_from_dict
from atlas.code.service import CodeService


def test_artifact_includes_parses_for_merge(tmp_path):
    (tmp_path / "a.py").write_text("def a():\n    return 1\n")
    (tmp_path / "b.py").write_text("def b():\n    return 2\n")
    svc = CodeService()
    art = svc.artifact(str(tmp_path), refresh=True)
    assert art["partial"] is False
    assert len(art["parses"]) == 2
    paths = {p["path"] for p in art["parses"]}
    assert paths == {"a.py", "b.py"}


def test_partial_merge_reparses_only_changed_file(tmp_path):
    (tmp_path / "a.py").write_text("def a():\n    return 1\n")
    (tmp_path / "b.py").write_text("def b():\n    return 2\n")
    svc = CodeService()
    full = svc.artifact(str(tmp_path), refresh=True)
    prior = [file_parse_from_dict(p) for p in full["parses"]]
    (tmp_path / "b.py").write_text("def b():\n    return 99\n")
    (tmp_path / "c.py").write_text("def c():\n    return 3\n")
    merged = svc.artifact(
        str(tmp_path),
        refresh=True,
        paths=["b.py", "c.py"],
        drop_paths=[],
        prior_parses=prior,
    )
    assert merged["partial"] is True
    assert set(merged["partial_paths"]) == {"b.py", "c.py"}
    by_path = {p["path"]: p for p in merged["parses"]}
    assert set(by_path) == {"a.py", "b.py", "c.py"}
    # a.py kept from prior (still return 1); b.py re-parsed.
    assert any(s["name"] == "a" for s in by_path["a.py"]["symbols"])
    assert any(s["name"] == "c" for s in by_path["c.py"]["symbols"])
    # Call/import graph still spans the merged set.
    assert merged["symbol_count"] >= 3


def test_partial_drop_paths_removes_deleted_file(tmp_path):
    (tmp_path / "a.py").write_text("def a():\n    return 1\n")
    (tmp_path / "b.py").write_text("def b():\n    return 2\n")
    svc = CodeService()
    full = svc.artifact(str(tmp_path), refresh=True)
    prior = [file_parse_from_dict(p) for p in full["parses"]]
    (tmp_path / "b.py").unlink()
    merged = svc.artifact(
        str(tmp_path),
        refresh=True,
        paths=[],
        drop_paths=["b.py"],
        prior_parses=prior,
    )
    assert {p["path"] for p in merged["parses"]} == {"a.py"}
