"""Hermetic tests for Engineering Intelligence (S19, D11/§5d).

Fakes stand in for the SQL repository and the code toolchain; the *real*
``LearningService`` (with an in-memory ledger) drives governance so the L2→L5 ladder
and the Code-store **sink** are exercised end-to-end without a database or parser.
"""

from __future__ import annotations

import dataclasses

from atlas.config import IntelligenceConfig, LearningConfig
from atlas.intelligence.service import CodeStoreSink, IntelligenceService
from atlas.models.learning import EngineeringPattern, LearnedRepository
from atlas.services.learning_service import LearningService
from tests.test_learning import FakeLearningRepo


class FakeIntelRepo:
    def __init__(self):
        self._repos: dict[str, LearnedRepository] = {}
        self._patterns: list[EngineeringPattern] = []
        self._seq = 0

    def _id(self):
        self._seq += 1
        return f"repo-{self._seq}"

    def add_repository(self, **kw):
        # re-learning retires the previous active row (by repo_uid when known, else root)
        uid = kw.get("repo_uid")
        for rid, r in list(self._repos.items()):
            if r.status != "active":
                continue
            same = (r.repo_uid == uid) if uid else (r.root == kw.get("root"))
            if same:
                self._repos[rid] = dataclasses.replace(r, status="reverted")
        rid = self._id()
        rec = LearnedRepository(
            id=rid, name=kw.get("name", ""), root=kw.get("root", ""),
            languages=kw.get("languages") or {}, frameworks=kw.get("frameworks") or [],
            entry_points=kw.get("entry_points") or [],
            dependencies=kw.get("dependencies") or {},
            file_count=kw.get("file_count", 0), symbol_count=kw.get("symbol_count", 0),
            loc=kw.get("loc", 0), summary=kw.get("summary", ""),
            top_symbols=kw.get("top_symbols") or [], patterns=kw.get("patterns") or [],
            policy=kw.get("policy", "project"),
            repo_uid=kw.get("repo_uid"), root_commit=kw.get("root_commit"),
            normalized_remote=kw.get("normalized_remote"),
            asset_id=kw.get("asset_id"), asset_version=kw.get("asset_version"),
        )
        self._repos[rid] = rec
        return rec

    def get_repository(self, rid):
        return self._repos.get(str(rid))

    def get_by_repo_uid(self, repo_uid):
        for r in self._repos.values():
            if r.status == "active" and r.repo_uid == repo_uid:
                return r
        return None

    def list_repositories(self, *, limit=100):
        return [r for r in self._repos.values() if r.status == "active"][:limit]

    def search_repositories(self, query, *, limit=20):
        q = query.lower()
        hits = [
            r for r in self._repos.values()
            if r.status == "active" and (
                q in r.name.lower() or q in r.root.lower()
                or any(q in f.lower() for f in r.frameworks)
                or any(q in l.lower() for l in r.languages)
            )
        ]
        return hits[:limit]

    def set_repository_status(self, rid, status):
        r = self._repos[str(rid)]
        self._repos[str(rid)] = dataclasses.replace(r, status=status)
        return True

    def count_repositories(self):
        return len(self.list_repositories(limit=10_000))

    def replace_patterns(self, patterns):
        self._patterns = [
            EngineeringPattern(
                id=f"pat-{i}", name=p["name"], category=p["category"],
                description=p["description"], prevalence=p["prevalence"],
                repo_count=p["repo_count"], total_repos=p["total_repos"],
                confidence=p["confidence"], level=p["level"], evidence=p["evidence"],
            )
            for i, p in enumerate(patterns)
        ]
        return len(patterns)

    def list_patterns(self, *, limit=100):
        return self._patterns[:limit]

    def count_patterns(self):
        return len(self._patterns)


class FakeCodeService:
    VERSION = "1.0.0"

    def __init__(self, repos=None):
        # root -> (repo_map, patterns, symbols)
        self._repos = repos or {}

    def repo_map(self, root):
        if root not in self._repos:
            raise NotADirectoryError(root)
        return self._repos[root][0]

    def patterns(self, root):
        return self._repos[root][1]

    def search_symbols(self, query, *, root, limit=25):
        return self._repos[root][2][:limit]

    def artifact(self, root, *, symbol_limit=200, refresh=False):
        if root not in self._repos:
            raise NotADirectoryError(root)
        repo_map, patterns, symbols = self._repos[root]
        return {
            "root": repo_map.get("root", root),
            "reader": "code",
            "reader_version": self.VERSION,
            "repo_map": repo_map,
            "graph": {"import_edges": [], "call_edges": []},
            "patterns": patterns,
            "symbols": symbols[:symbol_limit],
            "symbol_count": sum(
                int(f.get("symbols", 0)) for f in repo_map.get("files", [])
            ),
        }

    def index(self, root, *, ingest=False, refresh=False, embed_cap=None):
        # Count non-class symbols as "chunks" so embed wiring is observable in tests.
        _, _, symbols = self._repos[root]
        chunks = [s for s in symbols if s.get("kind") != "class"]
        if embed_cap is not None:
            chunks = chunks[:embed_cap]
        return {"root": root, "ingested_chunks": len(chunks) if ingest else 0}


def _repo_fixture(name, frameworks, languages, patterns, symbols=None):
    return (
        {
            "root": f"/repos/{name}", "file_count": 10, "total_loc": 500,
            "languages": languages, "frameworks": frameworks,
            "entry_points": ["run.py"], "dependencies": {"pip": ["fastapi"]},
            "files": [{"path": "a.py", "lang": "python", "loc": 50, "symbols": 3}],
        },
        [{"name": p, "description": "d", "confidence": 0.9} for p in patterns],
        symbols or [{"qualname": "App", "kind": "class", "file": "a.py"}],
    )


def _svc(code_repos, *, min_repos=2, min_prevalence=0.6, auto_apply=False):
    code = FakeCodeService(code_repos)
    intel_repo = FakeIntelRepo()
    learning = LearningService(FakeLearningRepo(), LearningConfig(auto_apply=auto_apply))
    learning.register_sink("code", CodeStoreSink(intel_repo))
    cfg = IntelligenceConfig(
        generalize_min_repos=min_repos, generalize_min_prevalence=min_prevalence
    )
    svc = IntelligenceService(code, intel_repo, learning, cfg)
    return svc, intel_repo, learning


# --- L2 Understand --------------------------------------------------------
def test_learn_repository_persists_and_records_governed_event():
    code_repos = {
        "/repos/api": _repo_fixture("api", ["FastAPI"], {"python": 10},
                                    ["Repository pattern", "Service layer"])
    }
    svc, intel_repo, learning = _svc(code_repos)
    out = svc.learn_repository("/repos/api")
    assert out["outcome"] == "ok"
    assert out["applied"] is True
    assert out["repository"]["name"] == "api"
    assert out["repository"]["symbol_count"] == 3
    assert intel_repo.count_repositories() == 1
    # governed: an applied L2 code-store event is in the ledger
    events = learning.list_events(store="code")
    assert len(events) == 1
    assert events[0]["level"] == 2
    assert events[0]["status"] == "applied"
    assert events[0]["ref_id"] == out["repository"]["id"]


def test_learn_repository_bad_path_is_error_outcome():
    svc, _, _ = _svc({})
    out = svc.learn_repository("/nope")
    assert out["outcome"] == "error"
    assert "not a directory" in out["reason"]


def test_learn_repository_revert_deactivates_via_sink():
    code_repos = {"/repos/api": _repo_fixture("api", ["FastAPI"], {"python": 10}, ["Repo"])}
    svc, intel_repo, learning = _svc(code_repos)
    out = svc.learn_repository("/repos/api")
    eid = out["event"]["id"]
    assert intel_repo.count_repositories() == 1
    learning.revert(eid)
    assert intel_repo.count_repositories() == 0  # sink deactivated the record


# --- L4 Generalize --------------------------------------------------------
def _three_repos():
    return {
        "/repos/a": _repo_fixture("a", ["FastAPI"], {"python": 10}, ["Repository pattern", "Service layer"]),
        "/repos/b": _repo_fixture("b", ["FastAPI"], {"python": 8}, ["Repository pattern"]),
        "/repos/c": _repo_fixture("c", ["Flask"], {"python": 5}, ["Repository pattern", "Service layer"]),
    }


def test_generalize_finds_prevalent_patterns():
    svc, _, _ = _svc(_three_repos(), min_prevalence=0.6)
    for r in ("/repos/a", "/repos/b", "/repos/c"):
        svc.learn_repository(r)
    out = svc.generalize()
    assert out["outcome"] == "ok"
    assert out["total_repos"] == 3
    names = {p["name"] for p in out["patterns"]}
    # Repository pattern in 3/3, python 3/3, Service layer 2/3, FastAPI 2/3 → all ≥0.6
    assert "Repository pattern" in names
    assert "python" in names
    repo_pat = next(p for p in out["patterns"] if p["name"] == "Repository pattern")
    assert repo_pat["prevalence"] == 1.0
    assert repo_pat["category"] == "pattern"


def test_generalize_insufficient_data():
    code_repos = {"/repos/a": _repo_fixture("a", ["FastAPI"], {"python": 10}, ["Repo"])}
    svc, _, _ = _svc(code_repos, min_repos=2)
    svc.learn_repository("/repos/a")
    out = svc.generalize()
    assert out["outcome"] == "insufficient_data"
    assert out["patterns"] == []


# --- L5 Recommend ---------------------------------------------------------
def test_recommend_auto_generalizes_and_ranks():
    svc, _, _ = _svc(_three_repos())
    for r in ("/repos/a", "/repos/b", "/repos/c"):
        svc.learn_repository(r)
    out = svc.recommend("building a python service")
    assert out["level"] == 5
    assert out["recommendations"]
    top = out["recommendations"][0]
    assert "consider it here" in top["recommendation"]


# --- L3 Connect -----------------------------------------------------------
def test_search_and_connections_link_shared_frameworks():
    svc, _, _ = _svc(_three_repos())
    for r in ("/repos/a", "/repos/b", "/repos/c"):
        svc.learn_repository(r)
    out = svc.search("fastapi")
    names = {r["name"] for r in out["repositories"]}
    assert names == {"a", "b"}
    conns = svc.connections()["connections"]
    # a & b share FastAPI
    assert any({e["a"], e["b"]} == {"a", "b"} for e in conns)


# --- profile + health -----------------------------------------------------
def test_profile_summarizes_engineer():
    svc, _, _ = _svc(_three_repos())
    for r in ("/repos/a", "/repos/b", "/repos/c"):
        svc.learn_repository(r)
    p = svc.profile()
    assert p["repositories"] == 3
    assert "python" in p["languages"]
    assert "FastAPI" in p["frameworks"]
    assert "python" in p["summary"]


def test_health_reports_counts():
    svc, _, _ = _svc(_three_repos())
    svc.learn_repository("/repos/a")
    status = svc.health_check()
    assert status.healthy
    assert "learned repo" in status.detail


def test_relearning_same_root_replaces_active_row():
    code_repos = {"/repos/api": _repo_fixture("api", ["FastAPI"], {"python": 10}, ["Repo"])}
    svc, intel_repo, _ = _svc(code_repos)
    svc.learn_repository("/repos/api")
    svc.learn_repository("/repos/api")
    assert intel_repo.count_repositories() == 1


# --- B.1 asset-backed acquisition ----------------------------------------
def test_learn_repository_with_acquirer_stamps_provenance(tmp_path):
    """When an acquirer is wired, the learned row carries repo_uid + asset id/version (B.1)."""
    from atlas.engineering.ingest import RepoAcquirer
    from tests.test_engineering_ingest import FakeAssetStore, FakeGit, FakeStorage

    repo = tmp_path / "svc"
    repo.mkdir()
    (repo / "a.py").write_text("print(1)\n")
    root = str(repo)

    code = FakeCodeService({root: _repo_fixture("svc", ["FastAPI"], {"python": 3}, ["Repo"])})
    # FakeCodeService keys on root; align the fixture's advertised root with the real path.
    code._repos[root][0]["root"] = root

    intel_repo = FakeIntelRepo()
    learning = LearningService(FakeLearningRepo(), LearningConfig(auto_apply=False))
    learning.register_sink("code", CodeStoreSink(intel_repo))
    acquirer = RepoAcquirer(FakeAssetStore(), FakeStorage(tmp_path), git=FakeGit(root_commit="abc"))
    svc = IntelligenceService(code, intel_repo, learning, IntelligenceConfig(), acquirer=acquirer)

    out = svc.learn_repository(path=root)
    assert out["outcome"] == "ok"
    assert out["asset"]["asset_version"] == 1
    assert out["asset"]["reused"] is False
    rec = out["repository"]
    assert rec["repo_uid"] == out["asset"]["repo_uid"]
    assert rec["root_commit"] == "abc"
    assert rec["asset_id"] == out["asset"]["asset_id"]
    assert rec["asset_version"] == 1


def test_learn_repository_remote_url_requires_acquirer():
    svc, _, _ = _svc({})
    out = svc.learn_repository(url="https://github.com/x/y.git")
    assert out["outcome"] == "error"
    assert "acquirer" in out["reason"]


# --- engineering findings read side (B.7) ---------------------------------
class _FakeFindingRepo:
    def __init__(self, rows):
        self._rows = rows

    def list_active(self, *, domain="code", limit=50, include_archive=False):
        return [r for r in self._rows if r.get("domain") == domain][:limit]

    def list_active_by_repo_uid(self, repo_uid, *, domain="code"):
        return [
            r for r in self._rows
            if r.get("domain") == domain
            and (r.get("provenance") or {}).get("repo_uid") == repo_uid
        ]

    def list_by_mission(self, mission_id, *, limit=100, include_archive=False):
        return [
            r for r in self._rows
            if (r.get("mission_id") or (r.get("provenance") or {}).get("mission_id"))
            == mission_id
        ][:limit]

    def list_by_job(self, job_id, *, limit=100, include_archive=False):
        return [
            r for r in self._rows
            if (r.get("job_id") or (r.get("provenance") or {}).get("job_id")) == job_id
        ][:limit]


def test_list_findings_scopes_by_repo_and_claim_type():
    rows = [
        {"id": "f1", "domain": "code", "claim_type": "structure", "statement": "s1",
         "value": {"rationale": "r"}, "provenance": {"repo_uid": "u1", "reader": "code"}},
        {"id": "f2", "domain": "code", "claim_type": "design", "statement": "s2",
         "value": {}, "provenance": {"repo_uid": "u1"}},
        {"id": "f3", "domain": "code", "claim_type": "structure", "statement": "s3",
         "value": {}, "provenance": {"repo_uid": "u2"}},
        {"id": "f4", "domain": "research", "claim_type": "prose", "statement": "s4"},
    ]
    svc, _, _ = _svc({})
    svc._finding_repo = _FakeFindingRepo(rows)

    # all code findings (research excluded)
    everything = svc.list_findings()
    assert {f["id"] for f in everything} == {"f1", "f2", "f3"}
    assert everything[0]["provenance"]["reader"] == "code"

    # scoped to a repo_uid
    scoped = svc.list_findings(repo_uid="u1")
    assert {f["id"] for f in scoped} == {"f1", "f2"}

    # scoped to a repo + claim type
    design = svc.list_findings(repo_uid="u1", claim_type="design")
    assert [f["id"] for f in design] == ["f2"]


def test_list_findings_scopes_by_mission_and_job():
    """C.1/P12: mission/job are a read-only discovery lens, and surface in the view."""
    rows = [
        {"id": "f1", "domain": "code", "claim_type": "structure", "statement": "s1",
         "value": {}, "mission_id": "m-1", "job_id": "j-1",
         "provenance": {"repo_uid": "u1", "mission_id": "m-1", "job_id": "j-1"}},
        {"id": "f2", "domain": "code", "claim_type": "design", "statement": "s2",
         "value": {}, "mission_id": "m-2",
         "provenance": {"repo_uid": "u1", "mission_id": "m-2"}},
        {"id": "f3", "domain": "code", "claim_type": "structure", "statement": "s3",
         "value": {}, "provenance": {"repo_uid": "u2", "mission_id": "m-1", "job_id": "j-1"}},
    ]
    svc, _, _ = _svc({})
    svc._finding_repo = _FakeFindingRepo(rows)

    by_mission = svc.list_findings(mission_id="m-1")
    assert {f["id"] for f in by_mission} == {"f1", "f3"}
    assert by_mission[0]["mission_id"] == "m-1"          # surfaced in the view

    by_job = svc.list_findings(job_id="j-1")
    assert {f["id"] for f in by_job} == {"f1", "f3"}

    only_m2 = svc.list_findings(mission_id="m-2")
    assert [f["id"] for f in only_m2] == ["f2"]


def test_list_findings_empty_without_finding_repo():
    svc, _, _ = _svc({})
    assert svc.list_findings() == []
