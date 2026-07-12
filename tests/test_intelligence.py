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
        # re-learning a root retires the previous active row
        for rid, r in list(self._repos.items()):
            if r.root == kw.get("root") and r.status == "active":
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
        )
        self._repos[rid] = rec
        return rec

    def get_repository(self, rid):
        return self._repos.get(str(rid))

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
