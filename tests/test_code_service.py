"""Tests for CodeService (S14): the `code` capability end to end (hermetic)."""

from __future__ import annotations

import pytest

from atlas.code.parser import CodeParser
from atlas.code.service import CodeService
from atlas.llm.provider import LLMResponse


def _repo(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "util.py").write_text("def helper(x):\n    return x + 1\n", encoding="utf-8")
    (pkg / "main.py").write_text(
        "from pkg.util import helper\n\n\ndef run(n):\n    return helper(n)\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="d"\ndependencies=["pytest"]\n', encoding="utf-8"
    )
    return tmp_path


def _service(**kw):
    return CodeService(CodeParser(), **kw)


def test_supported_languages_includes_python():
    assert "python" in _service().supported()


def test_parse_single_file(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("def foo():\n    return 1\n", encoding="utf-8")
    result = _service().parse(str(f))
    assert result["symbols"][0]["name"] == "foo"


def test_repo_map(tmp_path):
    m = _service().repo_map(str(_repo(tmp_path)))
    assert m["file_count"] >= 3
    assert "pytest" in m["frameworks"]
    assert m["languages"].get("python", 0) >= 3


def test_graph_over_repo(tmp_path):
    g = _service().graph(str(_repo(tmp_path)))
    assert ["pkg/main.py", "pkg/util.py"] in g["import_edges"]
    assert ["pkg/main.py::run", "pkg/util.py::helper"] in g["call_edges"]


def test_search_symbols(tmp_path):
    hits = _service().search_symbols("helper", root=str(_repo(tmp_path)))
    assert any(h["qualname"] == "helper" for h in hits)


def test_search_symbols_kind_filter(tmp_path):
    hits = _service().search_symbols("", root=str(_repo(tmp_path)), kind="function")
    assert hits and all(h["kind"] == "function" for h in hits)


def test_patterns(tmp_path):
    pats = _service().patterns(str(_repo(tmp_path)))
    assert any(p["name"] == "pytest testing" for p in pats)


def test_index_without_ingest(tmp_path):
    summary = _service().index(str(_repo(tmp_path)))
    assert summary["files"] >= 3
    assert summary["symbols"] >= 2
    assert summary["ingested_chunks"] == 0


class _FakeKnowledge:
    def __init__(self):
        self.ingested = []

    def ingest_text(self, source, content, **kw):
        self.ingested.append((source, content, kw))
        return {"document_id": "d", "status": "embedded"}


def test_index_with_ingest_pushes_code_chunks(tmp_path):
    kb = _FakeKnowledge()
    summary = _service(knowledge=kb).index(str(_repo(tmp_path)), ingest=True)
    assert summary["ingested_chunks"] >= 2
    sources = {s for s, _, _ in kb.ingested}
    assert "pkg/util.py::helper" in sources
    meta = kb.ingested[0][2]["metadata"]
    assert meta["code"] is True and meta["lang"] == "python"


class _RoleStub:
    def chat(self, messages, **kw):
        return LLMResponse(text="This module defines helper.", model="fake")


class _FakeLLM:
    def for_role(self, role):
        assert role == "code"
        return _RoleStub()


def test_explain_grounded_with_llm(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("def helper(x):\n    '''Doc.'''\n    return x\n", encoding="utf-8")
    result = _service(llm=_FakeLLM()).explain(str(f))
    assert "helper" in result["outline"]
    assert result["explanation"] == "This module defines helper."
    assert result["grounded"] is True


def test_explain_without_llm_still_returns_outline(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("def helper(x):\n    return x\n", encoding="utf-8")
    result = _service().explain(str(f))
    assert "helper" in result["outline"]
    assert result["explanation"] == ""


def test_scan_missing_dir_raises(tmp_path):
    with pytest.raises(NotADirectoryError):
        _service().repo_map(str(tmp_path / "nope"))


def test_health_ok():
    assert _service().health_check().healthy is True
