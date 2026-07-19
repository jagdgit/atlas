"""Hermetic tests for the versioned architecture graph (Phase B · §B.3, BB3).

Pure builders (graph doc / checksum / diff) plus the ``ArchitectureGraphStore`` over a fake
Asset Store prove content-addressed versioning (unchanged → reuse, changed → new version + diff)
and retrieval by version — without a database. An end-to-end learn wires it through
``IntelligenceService``.
"""

from __future__ import annotations

import json

from atlas.config import IntelligenceConfig, LearningConfig
from atlas.engineering.architecture import (
    ASSET_KIND_GRAPH,
    ArchitectureGraphStore,
    build_architecture_graph,
    diff_graphs,
    graph_checksum,
)
from atlas.intelligence.service import CodeStoreSink, IntelligenceService
from atlas.services.learning_service import LearningService
from tests.test_engineering_findings import FakeArtifactStorage
from tests.test_engineering_ingest import FakeAssetStore
from tests.test_intelligence import FakeCodeService, FakeIntelRepo, _repo_fixture
from tests.test_learning import FakeLearningRepo


# --- fakes ---------------------------------------------------------------
class FakeAssetStoreBytes(FakeAssetStore):
    """FakeAssetStore + get_bytes, enough for the ArchitectureGraphStore."""

    def get_bytes(self, asset_id, version=None):
        rows = self._versions.get(asset_id, [])
        if not rows:
            raise KeyError(asset_id)
        if version is None:
            return rows[-1]["bytes"]
        for row in rows:
            if row["version"] == version:
                return row["bytes"]
        raise KeyError(f"{asset_id} v{version}")


def _artifact(modules, import_edges, entry_points=(), call_edges=()):
    return {
        "repo_map": {
            "root": "/repos/x",
            "files": [{"path": m} for m in modules],
            "entry_points": list(entry_points),
            "languages": {"python": len(modules)},
            "frameworks": ["FastAPI"],
        },
        "graph": {
            "import_edges": [list(e) for e in import_edges],
            "call_edges": [list(e) for e in call_edges],
        },
    }


# --- pure builders -------------------------------------------------------
def test_build_graph_normalizes_and_counts():
    art = _artifact(
        ["b.py", "a.py"], [("a.py", "b.py")], entry_points=["run.py"],
        call_edges=[("a.py::f", "b.py::g")],
    )
    doc = build_architecture_graph(art, repo_uid="uid-1")
    assert doc["repo_uid"] == "uid-1"
    assert doc["modules"] == ["a.py", "b.py"]  # sorted
    assert doc["import_edges"] == [["a.py", "b.py"]]
    assert doc["entry_points"] == ["run.py"]
    assert doc["counts"] == {
        "modules": 2, "import_edges": 1, "call_edges": 1, "entry_points": 1
    }


def test_graph_checksum_stable_and_content_sensitive():
    a = build_architecture_graph(_artifact(["a.py"], []), repo_uid="u")
    b = build_architecture_graph(_artifact(["a.py"], []), repo_uid="u")
    assert graph_checksum(a) == graph_checksum(b)
    c = build_architecture_graph(_artifact(["a.py", "c.py"], []), repo_uid="u")
    assert graph_checksum(c) != graph_checksum(a)


def test_diff_graphs_reports_structural_delta():
    old = build_architecture_graph(_artifact(["a.py", "b.py"], [("a.py", "b.py")]), repo_uid="u")
    new = build_architecture_graph(
        _artifact(["a.py", "c.py"], [("a.py", "c.py")], entry_points=["run.py"]), repo_uid="u"
    )
    d = diff_graphs(old, new)
    assert d["changed"] is True
    assert d["added_modules"] == ["c.py"]
    assert d["removed_modules"] == ["b.py"]
    assert d["added_import_edges"] == [["a.py", "c.py"]]
    assert d["removed_import_edges"] == [["a.py", "b.py"]]
    assert d["added_entry_points"] == ["run.py"]


def test_diff_identical_graphs_is_unchanged():
    doc = build_architecture_graph(_artifact(["a.py"], []), repo_uid="u")
    assert diff_graphs(doc, doc)["changed"] is False


# --- ArchitectureGraphStore ----------------------------------------------
def test_store_persist_reuse_and_version_diff():
    assets = FakeAssetStoreBytes()
    store = ArchitectureGraphStore(assets)
    uid = "uid-1"

    doc1 = build_architecture_graph(_artifact(["a.py", "b.py"], [("a.py", "b.py")]), repo_uid=uid)
    r1 = store.persist(uid, doc1, repo_asset_id="repo-asset", repo_asset_version=1)
    assert r1["version"] == 1 and r1["reused"] is False and r1["diff"] is None

    # Unchanged graph → reuse the version, no diff.
    r2 = store.persist(uid, doc1)
    assert r2["reused"] is True and r2["version"] == 1 and r2["diff"] is None

    # Changed graph → new version whose diff reflects the change.
    doc2 = build_architecture_graph(_artifact(["a.py", "c.py"], [("a.py", "c.py")]), repo_uid=uid)
    r3 = store.persist(uid, doc2)
    assert r3["version"] == 2 and r3["reused"] is False
    assert r3["diff"]["added_modules"] == ["c.py"]
    assert r3["diff"]["removed_modules"] == ["b.py"]

    # Retrieval by version + explicit diff.
    assert store.get(uid, 1) == doc1
    assert store.get(uid) == doc2  # latest
    assert len(store.versions(uid)) == 2
    assert store.diff(uid, 1, 2)["added_modules"] == ["c.py"]

    # The graph is linked back to the repo asset (BB3): v1 carried the repo asset link,
    # and the latest version's checksum matches the latest doc.
    asset = assets.get_by_name(ASSET_KIND_GRAPH, uid)
    rows = assets.versions(asset["id"])  # newest first
    assert rows[0]["metadata"]["graph_checksum"] == graph_checksum(doc2)
    assert rows[-1]["metadata"]["repo_asset_id"] == "repo-asset"


def test_store_get_missing_returns_none():
    store = ArchitectureGraphStore(FakeAssetStoreBytes())
    assert store.get("nope") is None
    assert store.versions("nope") == []
    assert store.diff("nope", 1, 2) is None


# --- end-to-end through IntelligenceService -------------------------------
def test_learn_repository_persists_and_retrieves_graph(tmp_path):
    from atlas.engineering.ingest import RepoAcquirer
    from tests.test_engineering_ingest import FakeGit, FakeStorage

    repo = tmp_path / "svc"
    repo.mkdir()
    (repo / "a.py").write_text("print(1)\n")
    root = str(repo)

    fixture = _repo_fixture("svc", ["FastAPI"], {"python": 3}, ["Repo"])
    fixture[0]["root"] = root
    fixture[0]["files"] = [{"path": "a.py", "lang": "python", "loc": 5, "symbols": 1}]
    fixture[0]["entry_points"] = ["a.py"]
    code = FakeCodeService({root: fixture})

    intel_repo = FakeIntelRepo()
    learning = LearningService(FakeLearningRepo(), LearningConfig(auto_apply=False))
    learning.register_sink("code", CodeStoreSink(intel_repo))
    acquirer = RepoAcquirer(FakeAssetStore(), FakeStorage(tmp_path), git=FakeGit(root_commit="abc"))
    graph_store = ArchitectureGraphStore(FakeAssetStoreBytes())
    svc = IntelligenceService(
        code, intel_repo, learning, IntelligenceConfig(),
        acquirer=acquirer, graph_store=graph_store,
    )

    out = svc.learn_repository(path=root)
    assert out["outcome"] == "ok"
    assert out["architecture_graph"]["version"] == 1
    assert out["architecture_graph"]["reused"] is False

    repo_uid = out["asset"]["repo_uid"]
    doc = svc.architecture_graph(repo_uid)
    assert doc is not None
    assert doc["modules"] == ["a.py"]
    assert doc["entry_points"] == ["a.py"]
    assert len(svc.architecture_graph_versions(repo_uid)) == 1
    # sanity: the retrieved doc is JSON round-trippable (it came from stored bytes)
    assert json.loads(json.dumps(doc)) == doc
