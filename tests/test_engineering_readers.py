"""Hermetic tests for the Reader Registry + JS/TS pipeline (Phase B · §B.4, BB10).

The registry maps extensions → readers and answers coverage questions **honestly** (e.g. no
JS/TS call graph). A real tree-sitter JS/TS repo then flows through the *same* artifact-first
pipeline as Python (repo map + symbols + findings), proving multi-language support.
"""

from __future__ import annotations

import pytest

from atlas.engineering.readers import (
    CAP_CALL_GRAPH,
    CAP_EXPORTS,
    CAP_METADATA,
    CAP_TRANSCRIPT,
    Reader,
    ReaderRegistry,
    default_media_readers,
    default_readers,
)


# --- registry basics -----------------------------------------------------
def test_extension_routing_picks_the_right_reader():
    reg = ReaderRegistry()
    assert reg.reader_for_extension(".py").id == "python"
    assert reg.reader_for_extension(".pyi").id == "python"
    assert reg.reader_for_extension(".ts").id == "jsts"
    assert reg.reader_for_extension(".tsx").id == "jsts"
    assert reg.reader_for_extension(".jsx").id == "jsts"
    assert reg.reader_for_extension("mjs").id == "jsts"  # normalizes missing dot
    assert reg.reader_for_extension(".go").id == "treesitter"
    assert reg.reader_for_extension(".mat") is None  # honest: nobody reads .mat yet


def test_reader_for_path_and_language():
    reg = ReaderRegistry()
    assert reg.reader_for_path("src/app.ts").id == "jsts"
    assert reg.reader_for_language("python").id == "python"
    assert reg.reader_for_language("typescript").id == "jsts"
    assert reg.reader_for_language("cobol") is None


def test_call_graph_supported_only_for_python():
    reg = ReaderRegistry()
    py = reg.can_produce(CAP_CALL_GRAPH, language="python")
    assert py["supported"] is True and py["reader"] == "python"

    js = reg.can_produce(CAP_CALL_GRAPH, language="javascript")
    assert js["supported"] is False and js["reader"] == "jsts"
    assert "call_graph" in js["reason"]  # honest, not silently empty

    unknown = reg.can_produce(CAP_CALL_GRAPH, language="matlab")
    assert unknown["supported"] is False and unknown["reader"] is None


def test_supports_and_coverage_matrix():
    reg = ReaderRegistry()
    assert reg.supports(CAP_EXPORTS, language="typescript") is True
    assert reg.supports(CAP_EXPORTS, language="python") is False
    matrix = reg.coverage_matrix()
    assert matrix["python"][CAP_CALL_GRAPH] is True
    assert matrix["jsts"][CAP_CALL_GRAPH] is False


def test_extension_map_and_metrics_and_health():
    reg = ReaderRegistry()
    emap = reg.extension_map()
    assert emap[".py"] == "python" and emap[".ts"] == "jsts" and emap[".go"] == "treesitter"
    metrics = reg.metrics()
    assert metrics["readers"] == 6  # 3 code + 3 media (M.4)
    assert "python" in metrics["languages"] and "typescript" in metrics["languages"]
    assert emap[".vtt"] == "transcript_file"
    assert reg.health_check().healthy is True


def test_priority_and_disabled_readers():
    reg = ReaderRegistry()
    # A higher-priority reader claims .py.
    reg.register(Reader(
        id="python-next", name="Python Reader NG", version="2.0.0",
        extensions=(".py",), languages=("python",),
        coverage={"symbols": True, "call_graph": True}, priority=200,
    ))
    assert reg.reader_for_extension(".py").id == "python-next"
    # Disabling it falls back to the original.
    reg.register(Reader(
        id="python-next", name="Python Reader NG", version="2.0.0",
        extensions=(".py",), languages=("python",),
        coverage={"symbols": True}, priority=200, enabled=False,
    ))
    assert reg.reader_for_extension(".py").id == "python"


def test_default_readers_have_versions_and_coverage():
    for r in default_readers():
        assert r.version
        assert r.extensions
        d = r.as_dict()
        assert "coverage" in d and "call_graph" in d["coverage"]


def test_default_media_readers_registered():
    reg = ReaderRegistry()
    assert reg.get("media_metadata") is not None
    assert reg.get("transcript_file") is not None
    assert reg.get("audio_demux") is not None
    assert reg.reader_for_extension(".vtt").id == "transcript_file"
    assert reg.supports(CAP_TRANSCRIPT, extension=".vtt") is True
    assert reg.supports(CAP_METADATA, extension=".mp3") is True
    for r in default_media_readers():
        assert r.version and r.extensions
        assert CAP_CALL_GRAPH not in r.coverage or r.coverage.get(CAP_CALL_GRAPH) is False


# --- JS/TS end-to-end through the same pipeline ---------------------------
def test_js_ts_repo_ingests_like_python(tmp_path):
    pytest.importorskip("tree_sitter_language_pack")

    from atlas.code.parser import CodeParser
    from atlas.code.service import CodeService
    from atlas.config import IntelligenceConfig, LearningConfig
    from atlas.engineering.findings import EngineeringFindingWriter
    from atlas.engineering.ingest import RepoAcquirer
    from atlas.intelligence.service import CodeStoreSink, IntelligenceService
    from atlas.services.learning_service import LearningService
    from tests.test_engineering_findings import FakeFindingRepo
    from tests.test_engineering_ingest import FakeAssetStore, FakeGit, FakeStorage
    from tests.test_intelligence import FakeIntelRepo
    from tests.test_learning import FakeLearningRepo

    repo = tmp_path / "webapp"
    (repo / "src").mkdir(parents=True)
    (repo / "package.json").write_text(
        '{"name":"webapp","main":"index.js",'
        '"dependencies":{"react":"^18","express":"^4"}}'
    )
    (repo / "src" / "util.ts").write_text("export function foo() { return 42; }\n")
    (repo / "src" / "app.ts").write_text(
        'import { foo } from "./util";\n'
        "export class Widget { render() { return foo(); } }\n"
        "export function make(): Widget { return new Widget(); }\n"
    )
    root = str(repo)

    reg = ReaderRegistry()
    code = CodeService(CodeParser(), readers=reg)

    # The reader that will handle these files is jsts, which honestly lacks a call graph.
    art = code.artifact(root)
    assert "typescript" in art["repo_map"]["languages"]
    assert art["symbol_count"] > 0  # tree-sitter parsed real symbols
    assert "React" in art["repo_map"]["frameworks"]
    assert "Express" in art["repo_map"]["frameworks"]
    ts_attr = next(a for a in art["readers"] if a["language"] == "typescript")
    assert ts_attr["reader"] == "jsts"
    assert ts_attr["call_graph"] is False  # declared, not faked
    assert art["graph"]["call_edges"] == []  # consistent with the coverage matrix

    # Full governed learn → engineering findings, retrievable exactly like a Python repo.
    intel_repo = FakeIntelRepo()
    finding_repo = FakeFindingRepo()
    learning = LearningService(FakeLearningRepo(), LearningConfig(auto_apply=False))
    learning.register_sink(
        "code", CodeStoreSink(intel_repo, findings=EngineeringFindingWriter(finding_repo))
    )
    acquirer = RepoAcquirer(FakeAssetStore(), FakeStorage(tmp_path), git=FakeGit(root_commit="js1"))
    svc = IntelligenceService(code, intel_repo, learning, IntelligenceConfig(), acquirer=acquirer)

    out = svc.learn_repository(path=root)
    assert out["outcome"] == "ok"
    assert out["findings"] >= 2  # structure + node dependency (+ maybe patterns)
    rec = out["repository"]
    assert "typescript" in rec["languages"]
    dep_findings = [f for f in finding_repo.active() if f["claim_type"] == "dependency"]
    assert any((f["provenance"] or {}).get("symbol") == "node" for f in dep_findings)
