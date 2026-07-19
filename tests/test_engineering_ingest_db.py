"""Live-DB smoke for asset-backed repo ingestion (Phase B · §B.1).

Wires the *real* Asset Store + Storage Manager + Intelligence repository against a live
PostgreSQL to prove migration `0026` and the acquire→register→provenance seam hold end to
end: the raw repo lands as a checksum-verified `git_repo` asset, an unchanged re-ingest
reuses the version, and the learned row carries repo_uid + asset id/version. Skipped when
PostgreSQL is unreachable (matches tests/test_phase_a_e2e.py).
"""

from __future__ import annotations

import pytest

from atlas.assets import AssetRepository, AssetStore
from atlas.database.connection import DatabaseManager
from atlas.engineering.architecture import (
    ASSET_KIND_GRAPH,
    ArchitectureGraphStore,
    build_architecture_graph,
)
from atlas.engineering.findings import (
    CLAIM_DEPENDENCY,
    EngineeringFindingWriter,
    build_engineering_findings,
)
from atlas.engineering.ingest import ASSET_KIND_REPO, RepoAcquirer
from atlas.repositories.finding_repo import FindingRepository
from atlas.repositories.intelligence_repo import IntelligenceRepository
from atlas.storage.repository import StorageRepository
from atlas.storage.service import StorageManager
from tests.test_engineering_ingest import FakeGit


@pytest.fixture(scope="module")
def db():
    manager = DatabaseManager()
    try:
        if not manager.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001 - any connection error means skip
        pytest.skip(f"database unreachable: {exc}")
    yield manager
    manager.close()


def _make_repo(root, files):
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


def test_acquire_registers_verifiable_asset_and_reuses(db, tmp_path):
    import uuid

    storage = StorageManager(tmp_path / "storage", StorageRepository(db))
    storage.start()
    assets = AssetStore(storage, AssetRepository(db))
    # A unique commit per run → a fresh repo_uid, so version numbering is hermetic even though
    # the deterministic repo_uid would otherwise persist in the DB across runs.
    acq = RepoAcquirer(assets, storage, git=FakeGit(root_commit=f"db-smoke-{uuid.uuid4()}"))

    repo = tmp_path / "repo"
    _make_repo(repo, {"a.py": "print(1)\n", "pkg/b.py": "x = 2\n"})

    first = acq.acquire(path=str(repo))
    assert first.reused is False
    assert first.asset_version == 1

    # The raw asset is retrievable and checksum-verified (Storage integrity).
    assert assets.verify(first.asset_id) is True
    blob = assets.get_bytes(first.asset_id)
    assert isinstance(blob, bytes) and blob

    # Unchanged tree → reuse the same asset version (no duplicate).
    second = acq.acquire(path=str(repo))
    assert second.reused is True
    assert second.asset_version == 1
    assert second.repo_uid == first.repo_uid

    # A change cuts a new version.
    (repo / "a.py").write_text("print(2)\n")
    third = acq.acquire(path=str(repo))
    assert third.reused is False
    assert third.asset_version == 2

    # The asset is registered under the stable repo_uid, with both versions.
    asset = assets.get_by_name(ASSET_KIND_REPO, first.repo_uid)
    assert asset is not None
    assert len(assets.versions(asset["id"])) == 2


def test_learned_repository_row_carries_provenance(db):
    repo_repo = IntelligenceRepository(db)
    uid = "11111111-2222-3333-4444-555555555555"
    rec = repo_repo.add_repository(
        name="prov-smoke",
        root="https://github.com/x/prov-smoke.git",
        languages={"python": 3},
        repo_uid=uid,
        root_commit="abcdef",
        normalized_remote="github.com/x/prov-smoke",
        asset_id="99999999-8888-7777-6666-555555555555",
        asset_version=1,
    )
    got = repo_repo.get_repository(rec.id)
    assert got is not None
    assert got.repo_uid == uid
    assert got.root_commit == "abcdef"
    assert got.normalized_remote == "github.com/x/prov-smoke"
    assert got.asset_version == 1

    # Re-learning the same identity supersedes (by repo_uid), keeping one active row.
    rec2 = repo_repo.add_repository(
        name="prov-smoke", root="/some/other/path", repo_uid=uid, asset_version=2
    )
    assert repo_repo.get_repository(rec.id).status == "reverted"
    assert repo_repo.get_repository(rec2.id).status == "active"

    # Cleanup so the module leaves no active fixtures behind.
    repo_repo.set_repository_status(rec2.id, "reverted")


def test_engineering_findings_supersede_and_archive_live(db):
    """Real knowledge.findings: create → revise → archive engineering findings (B.2/Q-B5)."""
    import uuid

    finding_repo = FindingRepository(db)
    writer = EngineeringFindingWriter(finding_repo)
    repo_uid = str(uuid.uuid4())  # unique identity so the run is hermetic across the DB

    def distilled(symbol_count, deps):
        return {
            "name": "eng-smoke", "root": f"repo:{repo_uid}",
            "languages": {"python": 5}, "frameworks": ["FastAPI"],
            "entry_points": [], "dependencies": deps,
            "file_count": 4, "symbol_count": symbol_count, "loc": 100,
            "patterns": [{"name": "Repository pattern", "description": "d", "confidence": 0.9}],
        }

    try:
        first = build_engineering_findings(
            distilled(10, {"pip": ["fastapi", "pydantic"]}), {},
            repo_uid=repo_uid, asset_id="a", asset_version=1,
            reader="code", reader_version="1.0.0",
        )
        r1 = writer.write(first)
        assert r1["created"] == len(first)
        active = finding_repo.list_active_by_repo_uid(repo_uid)
        assert len(active) == len(first)
        assert all(row["domain"] == "code" for row in active)

        # Idempotent re-write of identical content → no-ops (no new revisions).
        r2 = writer.write(first)
        assert r2["created"] == 0 and r2["revised"] == 0 and r2["noop"] == len(first)

        # Changed structure → supersede; dropped dependency → archive.
        second = build_engineering_findings(
            distilled(99, {}), {},
            repo_uid=repo_uid, asset_id="a", asset_version=2,
            reader="code", reader_version="1.0.0",
        )
        r3 = writer.write(second)
        assert r3["revised"] == 1  # the structure finding
        assert r3["archived"] == 1  # the vanished dependency finding
        active2 = finding_repo.list_active_by_repo_uid(repo_uid)
        assert CLAIM_DEPENDENCY not in {row["claim_type"] for row in active2}
    finally:
        for row in finding_repo.list_active_by_repo_uid(repo_uid):
            finding_repo.set_status(str(row["id"]), "archived")


def test_design_findings_persist_and_survive_docs_only_reingest_live(db):
    """Real knowledge.findings: design/risk findings land (domain=code) and a claim-type-scoped
    re-write (doc-only re-ingest that skips the LLM, B.5) preserves them (BB9)."""
    import uuid

    from atlas.engineering.design_review import CLAIM_DESIGN, CLAIM_RISK, DesignReviewer
    from atlas.engineering.findings import (
        CLAIM_PATTERN,
        CLAIM_STRUCTURE,
        build_engineering_findings,
    )

    class _Resp:
        text = (
            '[{"title":"API imports DB","type":"risk","confidence":"high",'
            '"statement":"API imports the DB layer directly.","evidence":["api.py"],'
            '"rationale":"Coupling.","rejected_alternatives":["service layer"]}]'
        )

    class _Client:
        model = "qwen-test:1"

        def chat(self, messages, **kw):
            return _Resp()

    class _LLM:
        def for_role(self, role):
            return _Client()

    finding_repo = FindingRepository(db)
    writer = EngineeringFindingWriter(finding_repo)
    reviewer = DesignReviewer(_LLM())
    repo_uid = str(uuid.uuid4())

    distilled = {
        "name": "design-smoke", "root": f"repo:{repo_uid}",
        "languages": {"python": 5}, "frameworks": ["FastAPI"], "entry_points": [],
        "dependencies": {"pip": ["fastapi"]}, "file_count": 4, "symbol_count": 10, "loc": 100,
        "patterns": [{"name": "Repository pattern", "description": "d", "confidence": 0.9}],
    }
    try:
        base = build_engineering_findings(
            distilled, {}, repo_uid=repo_uid, asset_id="a", asset_version=1,
            reader="code", reader_version="1.0.0",
        )
        design = reviewer.review(
            distilled=distilled, graph_doc={"import_edges": [], "counts": {}},
            diff={"changed": True}, repo_uid=repo_uid, asset_id="a", asset_version=1,
            reader="code", reader_version="1.0.0",
        )
        assert design and design[0]["claim_type"] == CLAIM_RISK

        # Structural change ingest: all claim types covered (design/risk included).
        writer.write(
            base + design,
            archive_claim_types={CLAIM_STRUCTURE, "dependency", CLAIM_PATTERN,
                                 CLAIM_DESIGN, CLAIM_RISK},
        )
        active = finding_repo.list_active_by_repo_uid(repo_uid)
        kinds = {row["claim_type"] for row in active}
        assert CLAIM_RISK in kinds and CLAIM_STRUCTURE in kinds
        assert all(row["domain"] == "code" for row in active)

        # Doc-only re-ingest skips the LLM: only structure/dependency/pattern are covered,
        # so the design/risk finding is NOT archived.
        writer.write(
            base,
            archive_claim_types={CLAIM_STRUCTURE, "dependency", CLAIM_PATTERN},
        )
        after = finding_repo.list_active_by_repo_uid(repo_uid)
        assert CLAIM_RISK in {row["claim_type"] for row in after}  # preserved
    finally:
        for row in finding_repo.list_active_by_repo_uid(repo_uid):
            finding_repo.set_status(str(row["id"]), "archived")


def test_architecture_graph_versions_and_diff_live(db, tmp_path):
    """Real Asset Store: persist → reuse → new version + diff for the architecture graph (B.3)."""
    import uuid

    storage = StorageManager(tmp_path / "storage", StorageRepository(db))
    storage.start()
    assets = AssetStore(storage, AssetRepository(db))
    store = ArchitectureGraphStore(assets)
    repo_uid = str(uuid.uuid4())  # unique per run → hermetic version numbering

    def artifact(modules, edges):
        return {
            "repo_map": {
                "root": f"/repos/{repo_uid}",
                "files": [{"path": m} for m in modules],
                "entry_points": [], "languages": {"python": len(modules)}, "frameworks": [],
            },
            "graph": {"import_edges": [list(e) for e in edges], "call_edges": []},
        }

    doc1 = build_architecture_graph(artifact(["a.py", "b.py"], [("a.py", "b.py")]), repo_uid=repo_uid)
    r1 = store.persist(repo_uid, doc1, repo_asset_id="repo-asset", repo_asset_version=1)
    assert r1["version"] == 1 and r1["reused"] is False

    # Unchanged → reuse.
    assert store.persist(repo_uid, doc1)["reused"] is True

    # Changed → new version + diff.
    doc2 = build_architecture_graph(artifact(["a.py", "c.py"], [("a.py", "c.py")]), repo_uid=repo_uid)
    r2 = store.persist(repo_uid, doc2)
    assert r2["version"] == 2 and r2["reused"] is False
    assert r2["diff"]["added_modules"] == ["c.py"]
    assert r2["diff"]["removed_modules"] == ["b.py"]

    # Retrievable by version; checksum-verified bytes round-trip.
    assert store.get(repo_uid, 1) == doc1
    assert store.get(repo_uid) == doc2
    assert len(store.versions(repo_uid)) == 2
    asset = assets.get_by_name(ASSET_KIND_GRAPH, repo_uid)
    assert assets.verify(str(asset["id"])) is True
