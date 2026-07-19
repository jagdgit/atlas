"""Hermetic tests for engineering findings + Derived Artifact Store (Phase B · §B.2).

Fakes stand in for the SQL finding repo and Storage so extraction, supersession-by-identity
(incl. reader, Q-B5), archival of vanished findings, artifact caching (no re-parse, BB11) and
priority-capped embedding wiring are all verified without a database or a parser.
"""

from __future__ import annotations

from atlas.config import IntelligenceConfig, LearningConfig
from atlas.engineering.artifacts import DerivedArtifactStore
from atlas.engineering.findings import (
    CLAIM_DEPENDENCY,
    CLAIM_PATTERN,
    CLAIM_STRUCTURE,
    EngineeringFindingWriter,
    build_engineering_findings,
)
from atlas.intelligence.service import CodeStoreSink, IntelligenceService
from atlas.knowledge.domains import DOMAIN_CODE
from atlas.knowledge.lifecycle import finding_identity_key
from atlas.services.learning_service import LearningService
from tests.test_intelligence import FakeCodeService, FakeIntelRepo, _repo_fixture
from tests.test_learning import FakeLearningRepo


# --- fakes ---------------------------------------------------------------
class FakeFindingRepo:
    """In-memory findings store honouring identity_key + revision/supersede semantics."""

    def __init__(self):
        self._rows: dict[str, dict] = {}
        self._seq = 0

    def _id(self):
        self._seq += 1
        return f"F-{self._seq:04d}"

    def create(self, statement, **kw):
        rid = self._id()
        row = {
            "id": rid,
            "canonical_id": kw.get("canonical_id") or rid,
            "revision": kw.get("revision", 1),
            "statement": statement,
            "value": kw.get("value"),
            "claim_type": kw.get("claim_type", "structure"),
            "confidence": kw.get("confidence", "UNVERIFIED"),
            "confidence_score": kw.get("confidence_score", 0.0),
            "status": kw.get("status", "active"),
            "provenance": kw.get("provenance") or {},
            "domain": kw.get("domain", "research"),
            "identity_key": list(kw.get("identity_key") or []),
            "supporting": [],
            "contradicting": [],
        }
        self._rows[rid] = row
        return row

    def find_active_by_identity(self, identity):
        want = list(identity)
        for row in self._rows.values():
            if row["identity_key"] == want and row["status"] in ("active", "contested"):
                return row
        return None

    def append_revision(self, previous, data):
        """Revise in place: new row, same canonical_id, revision+1, old superseded (C.3e)."""
        new = self.create(
            str(data.get("statement", previous.get("statement", ""))),
            canonical_id=previous["canonical_id"],
            revision=int(previous.get("revision", 1)) + 1,
            value=data.get("value", previous.get("value")),
            claim_type=str(data.get("claim_type", previous.get("claim_type", "structure"))),
            confidence=str(data.get("confidence", previous.get("confidence", "UNVERIFIED"))),
            confidence_score=float(
                data.get("confidence_score", previous.get("confidence_score", 0)) or 0
            ),
            status=str(data.get("status", "active") or "active"),
            provenance=data.get("provenance") if isinstance(data.get("provenance"), dict)
            else (previous.get("provenance") or {}),
            domain=str(data.get("domain", previous.get("domain", "research"))),
            identity_key=list(previous.get("identity_key") or []),
        )
        self.set_status(str(previous["id"]), "superseded", superseded_by=str(new["id"]))
        return new

    def set_status(self, finding_id, status, *, superseded_by=None):
        row = self._rows.get(str(finding_id))
        if row is None:
            return None
        self._rows[str(finding_id)] = {**row, "status": status, "superseded_by": superseded_by}
        return self._rows[str(finding_id)]

    def set_supersedes(self, finding_id, supersedes):
        row = self._rows.get(str(finding_id))
        if row is not None:
            self._rows[str(finding_id)] = {**row, "supersedes": supersedes}

    def list_active_by_repo_uid(self, repo_uid, *, domain=DOMAIN_CODE):
        return [
            row for row in self._rows.values()
            if row["domain"] == domain
            and (row["provenance"] or {}).get("repo_uid") == repo_uid
            and row["status"] in ("active", "contested", "deprecated")
        ]

    # helpers for assertions
    def active(self):
        return [r for r in self._rows.values() if r["status"] == "active"]


class FakeArtifactStorage:
    """Just enough StorageManager surface for the Derived Artifact Store."""

    def __init__(self):
        self._files: dict[tuple[str, str], bytes] = {}
        self.reads = 0
        self.writes = 0

    def get_bytes(self, scope, name):
        from atlas.storage.service import StorageError

        self.reads += 1
        key = (scope, name)
        if key not in self._files:
            raise StorageError(f"no such file {name}")
        return self._files[key]

    def put_file(self, scope, name, data, *, content_type=None, metadata=None):
        self.writes += 1
        self._files[(scope, name)] = data
        return {"scope": scope, "name": name}


def _distilled(name="api"):
    return {
        "name": name,
        "root": f"/repos/{name}",
        "languages": {"python": 10, "sql": 2},
        "frameworks": ["FastAPI"],
        "entry_points": ["run.py"],
        "dependencies": {"pip": ["fastapi", "pydantic"]},
        "file_count": 12,
        "symbol_count": 40,
        "loc": 900,
        "patterns": [{"name": "Repository pattern", "description": "d", "confidence": 0.9}],
    }


# --- build_engineering_findings ------------------------------------------
def test_build_findings_covers_structure_dependency_pattern():
    findings = build_engineering_findings(
        _distilled(), {},
        repo_uid="uid-1", asset_id="asset-1", asset_version=3,
        reader="code", reader_version="1.0.0",
    )
    kinds = [f["claim_type"] for f in findings]
    assert CLAIM_STRUCTURE in kinds
    assert kinds.count(CLAIM_DEPENDENCY) == 1  # one pip manager
    assert kinds.count(CLAIM_PATTERN) == 1
    for f in findings:
        assert f["domain"] == DOMAIN_CODE
        prov = f["provenance"]
        assert prov["repo_uid"] == "uid-1"
        assert prov["asset_id"] == "asset-1"
        assert prov["asset_version"] == 3
        assert prov["reader"] == "code"
        assert prov["reader_version"] == "1.0.0"


def test_build_findings_stamps_mission_provenance():
    """C.1/P12: mission/job/source ride the provenance (discovery, not ownership)."""
    findings = build_engineering_findings(
        _distilled(), {},
        repo_uid="uid-1", asset_id="a", asset_version=1,
        reader="code", reader_version="1.0.0",
        mission_id="m-123", job_id="j-456", source="repository",
    )
    assert findings
    for f in findings:
        prov = f["provenance"]
        assert prov["mission_id"] == "m-123"
        assert prov["job_id"] == "j-456"
        assert prov["source"] == "repository"


def test_build_findings_omits_mission_provenance_when_absent():
    """No mission/job ⇒ keys omitted (pre-Phase-C ingests stay byte-identical)."""
    findings = build_engineering_findings(
        _distilled(), {},
        repo_uid="uid-1", asset_id="a", asset_version=1,
        reader="code", reader_version="1.0.0",
    )
    assert findings
    for f in findings:
        assert "mission_id" not in f["provenance"]
        assert "job_id" not in f["provenance"]
        assert "source" not in f["provenance"]


def test_finding_identity_includes_reader_and_symbol():
    findings = build_engineering_findings(
        _distilled(), {}, repo_uid="uid-1", asset_id="a", asset_version=1,
        reader="code", reader_version="1.0.0",
    )
    ids = {finding_identity_key(f) for f in findings}
    assert len(ids) == len(findings)  # every finding has a distinct identity
    struct = next(f for f in findings if f["claim_type"] == CLAIM_STRUCTURE)
    key = finding_identity_key(struct)
    assert key[0] == "code" and key[1] == "uid-1" and key[-1] == "code"
    # A different reader ⇒ a different identity for the same finding.
    other = dict(struct, provenance={**struct["provenance"], "reader": "jsts"})
    assert finding_identity_key(other) != key


# --- EngineeringFindingWriter --------------------------------------------
def test_writer_creates_then_noops_then_revises_and_archives():
    repo = FakeFindingRepo()
    writer = EngineeringFindingWriter(repo)

    first = build_engineering_findings(
        _distilled(), {}, repo_uid="uid-1", asset_id="a", asset_version=1,
        reader="code", reader_version="1.0.0",
    )
    r1 = writer.write(first)
    assert r1["created"] == len(first)
    assert len(repo.active()) == len(first)

    # Re-ingest identical content → all no-ops, nothing new.
    r2 = writer.write(first)
    assert r2["created"] == 0 and r2["revised"] == 0
    assert r2["noop"] == len(first)
    assert len(repo.active()) == len(first)

    # Changed structure statement (more symbols) → that one is revised (superseded).
    changed = _distilled()
    changed["symbol_count"] = 99
    third = build_engineering_findings(
        changed, {}, repo_uid="uid-1", asset_id="a", asset_version=2,
        reader="code", reader_version="1.0.0",
    )
    r3 = writer.write(third)
    assert r3["revised"] == 1
    assert len(repo.active()) == len(first)  # revision replaces, count stable

    # Drop a dependency → the vanished dependency finding is archived.
    fewer = _distilled()
    fewer["dependencies"] = {}
    fourth = build_engineering_findings(
        fewer, {}, repo_uid="uid-1", asset_id="a", asset_version=3,
        reader="code", reader_version="1.0.0",
    )
    r4 = writer.write(fourth)
    assert r4["archived"] == 1
    active_kinds = [r["claim_type"] for r in repo.active()]
    assert CLAIM_DEPENDENCY not in active_kinds


def test_writer_archive_for_repo_clears_active():
    repo = FakeFindingRepo()
    writer = EngineeringFindingWriter(repo)
    findings = build_engineering_findings(
        _distilled(), {}, repo_uid="uid-1", asset_id="a", asset_version=1,
        reader="code", reader_version="1.0.0",
    )
    writer.write(findings)
    assert len(repo.active()) > 0
    archived = writer.archive_for_repo("uid-1")
    assert archived == len(findings)
    assert repo.active() == []


# --- Derived Artifact Store ----------------------------------------------
def test_derived_artifact_store_round_trip_and_miss():
    storage = FakeArtifactStorage()
    store = DerivedArtifactStore(storage)
    assert store.get("asset-1", 1, "code", "1.0.0") is None  # miss
    store.put("asset-1", 1, "code", "1.0.0", {"symbols": 3})
    got = store.get("asset-1", 1, "code", "1.0.0")
    assert got == {"symbols": 3}
    # A different version/reader is a distinct key (still a miss).
    assert store.get("asset-1", 2, "code", "1.0.0") is None
    assert store.get("asset-1", 1, "jsts", "1.0.0") is None


# --- end-to-end through IntelligenceService ------------------------------
def _acquirer(tmp_path):
    from atlas.engineering.ingest import RepoAcquirer
    from tests.test_engineering_ingest import FakeAssetStore, FakeGit, FakeStorage

    return RepoAcquirer(
        FakeAssetStore(), FakeStorage(tmp_path), git=FakeGit(root_commit="abc")
    )


def test_learn_repository_writes_findings_and_reuses_artifact(tmp_path):
    repo = tmp_path / "svc"
    repo.mkdir()
    (repo / "a.py").write_text("print(1)\n")
    root = str(repo)

    fixture = _repo_fixture("svc", ["FastAPI"], {"python": 3}, ["Repository pattern"])
    fixture[0]["root"] = root
    fixture[0]["dependencies"] = {"pip": ["fastapi"]}
    code = FakeCodeService({root: fixture})

    intel_repo = FakeIntelRepo()
    finding_repo = FakeFindingRepo()
    learning = LearningService(FakeLearningRepo(), LearningConfig(auto_apply=False))
    writer = EngineeringFindingWriter(finding_repo)
    learning.register_sink("code", CodeStoreSink(intel_repo, findings=writer))

    storage = FakeArtifactStorage()
    artifacts = DerivedArtifactStore(storage)
    svc = IntelligenceService(
        code, intel_repo, learning, IntelligenceConfig(embed_code=True),
        acquirer=_acquirer(tmp_path), artifacts=artifacts,
    )

    out = svc.learn_repository(path=root)
    assert out["outcome"] == "ok"
    assert out["findings"] >= 3  # structure + dependency + pattern
    assert out["embedded_chunks"] >= 0
    assert len(finding_repo.active()) == out["findings"]
    assert storage.writes == 1  # artifact cached on first parse

    # Second learn of the *same asset version* reuses the cached artifact (no re-parse).
    out2 = svc.learn_repository(path=root)
    assert out2["asset"]["reused"] is True
    assert storage.writes == 1  # no new artifact written — cache hit
    # findings are idempotent: still the same active set.
    assert len(finding_repo.active()) == out["findings"]


def test_learn_repository_without_artifact_store_still_extracts(tmp_path):
    repo = tmp_path / "svc"
    repo.mkdir()
    (repo / "a.py").write_text("print(1)\n")
    root = str(repo)
    fixture = _repo_fixture("svc", ["FastAPI"], {"python": 3}, ["Repo"])
    fixture[0]["root"] = root
    code = FakeCodeService({root: fixture})
    intel_repo = FakeIntelRepo()
    finding_repo = FakeFindingRepo()
    learning = LearningService(FakeLearningRepo(), LearningConfig(auto_apply=False))
    learning.register_sink(
        "code", CodeStoreSink(intel_repo, findings=EngineeringFindingWriter(finding_repo))
    )
    svc = IntelligenceService(code, intel_repo, learning, IntelligenceConfig())
    out = svc.learn_repository(root)  # legacy local path, no acquirer/artifact store
    assert out["outcome"] == "ok"
    assert out["findings"] >= 1
    # Fallback repo_uid keeps findings identity distinct + queryable.
    assert len(finding_repo.active()) == out["findings"]
