"""Hermetic tests for design reasoning — the LLM design review (Phase B · §B.5).

Fakes stand in for the LLM and the architecture-graph store so we verify: the structural-change
gate (BB6/Q-B3), advice-only design/risk findings with rejected alternatives + model provenance
(P9), that a doc-only re-ingest **skips** the LLM and **preserves** prior design findings, that a
missing LLM still yields structural findings, and that on-demand review + revert work.
"""

from __future__ import annotations

from atlas.config import IntelligenceConfig, LearningConfig
from atlas.engineering.design_review import (
    CLAIM_DESIGN,
    CLAIM_RISK,
    DESIGN_REVIEWER_VERSION,
    DesignReviewer,
    should_review,
)
from atlas.engineering.findings import (
    CLAIM_PATTERN,
    CLAIM_STRUCTURE,
    EngineeringFindingWriter,
)
from atlas.intelligence.service import CodeStoreSink, IntelligenceService
from atlas.services.learning_service import LearningService
from tests.test_engineering_findings import FakeFindingRepo
from tests.test_intelligence import FakeCodeService, FakeIntelRepo, _repo_fixture
from tests.test_learning import FakeLearningRepo

_REVIEW_JSON = """
Here is my review:
[
  {"title": "Boundary leak: API imports DB", "type": "risk", "confidence": "high",
   "statement": "The API layer imports the database layer directly.",
   "evidence": ["api/routes.py", "db/pool.py"],
   "rationale": "Couples transport to storage and blocks swapping the store.",
   "rejected_alternatives": ["Add a service layer", "Dependency inversion via a port"]},
  {"title": "Repository pattern", "type": "design", "confidence": "medium",
   "statement": "Data access is centralised behind repository classes.",
   "evidence": ["repos/"],
   "rationale": "Keeps data access testable and swappable.",
   "rejected_alternatives": ["Active Record"]}
]
"""


# --- LLM fake ------------------------------------------------------------
class _Resp:
    def __init__(self, text):
        self.text = text


class _RoleClient:
    def __init__(self, text, model, calls):
        self._text = text
        self.model = model
        self._calls = calls

    def chat(self, messages, **kw):
        self._calls.append(messages)
        return _Resp(self._text)


class FakeLLM:
    def __init__(self, text=_REVIEW_JSON, model="qwen-test:1"):
        self._text = text
        self._model = model
        self.calls: list = []

    def for_role(self, role):
        return _RoleClient(self._text, self._model, self.calls)


class FakeGraphStore:
    """Returns a scripted persist result sequence; stores docs for get()."""

    def __init__(self, results):
        self._results = list(results)
        self._docs: dict[str, dict] = {}

    def persist(self, repo_uid, graph_doc, **kw):
        self._docs[repo_uid] = graph_doc
        res = self._results.pop(0) if self._results else {"reused": True, "diff": None}
        return {"asset_id": "g1", "version": 1, **res}

    def get(self, repo_uid, version=None):
        return self._docs.get(repo_uid)

    def versions(self, repo_uid):
        return []


# --- structural-change gate ----------------------------------------------
def test_should_review_gate():
    assert should_review(None) is True                                  # no gate info
    assert should_review({"reused": True, "diff": None}) is False       # unchanged reuse
    assert should_review({"reused": False, "diff": None}) is True       # first version
    assert should_review({"reused": False, "diff": {"changed": True}}) is True
    assert should_review({"reused": False, "diff": {"changed": False}}) is False


# --- reviewer parsing ----------------------------------------------------
def test_reviewer_parses_findings_with_provenance_and_alternatives():
    reviewer = DesignReviewer(FakeLLM())
    assert reviewer.available() is True
    distilled = {"name": "api", "root": "/repos/api", "languages": {"python": 9},
                 "frameworks": ["FastAPI"], "patterns": []}
    graph = {"modules": ["api/routes.py"], "import_edges": [["api/routes.py", "db/pool.py"]],
             "entry_points": ["run.py"], "counts": {}}
    findings = reviewer.review(
        distilled=distilled, graph_doc=graph, diff={"changed": True},
        repo_uid="uid-1", asset_id="a", asset_version=2,
        reader="code", reader_version="1.0.0",
    )
    assert len(findings) == 2
    kinds = {f["claim_type"] for f in findings}
    assert kinds == {CLAIM_RISK, CLAIM_DESIGN}
    risk = next(f for f in findings if f["claim_type"] == CLAIM_RISK)
    assert risk["confidence"] == "HIGH"
    assert risk["value"]["rejected_alternatives"]              # P9
    assert risk["value"]["evidence"]
    prov = risk["provenance"]
    assert prov["repo_uid"] == "uid-1"
    assert prov["model"] == "qwen-test:1"                      # P9: model version recorded
    assert prov["extractor_version"] == DESIGN_REVIEWER_VERSION
    assert prov["symbol"]                                      # stable slug identity
    # Distinct concerns ⇒ distinct symbol slugs ⇒ distinct identities.
    assert len({f["provenance"]["symbol"] for f in findings}) == 2


def test_reviewer_stamps_mission_provenance():
    """C.1/P12: design findings carry who discovered them (mission/job/source)."""
    reviewer = DesignReviewer(FakeLLM())
    findings = reviewer.review(
        distilled={"name": "api", "root": "/repos/api"},
        graph_doc={"modules": [], "import_edges": [], "counts": {}},
        diff={"changed": True}, repo_uid="uid-1",
        reader="code", reader_version="1.0.0",
        mission_id="m-1", job_id="j-1", source="repository",
    )
    assert findings
    for f in findings:
        assert f["provenance"]["mission_id"] == "m-1"
        assert f["provenance"]["job_id"] == "j-1"
        assert f["provenance"]["source"] == "repository"
    # Without mission/job the keys are omitted.
    plain = reviewer.review(
        distilled={"name": "api", "root": "/repos/api"},
        graph_doc={"modules": [], "import_edges": [], "counts": {}},
        diff={"changed": True}, repo_uid="uid-1",
    )
    assert plain and "mission_id" not in plain[0]["provenance"]


def test_reviewer_without_llm_skips_cleanly():
    reviewer = DesignReviewer(None)
    assert reviewer.available() is False
    assert reviewer.review(distilled={}, graph_doc={}, repo_uid="x") == []


def test_reviewer_bad_json_returns_empty():
    reviewer = DesignReviewer(FakeLLM(text="sorry, no JSON here"))
    out = reviewer.review(distilled={"name": "x"}, graph_doc={}, repo_uid="x")
    assert out == []


# --- end-to-end through IntelligenceService ------------------------------
def _acquirer(tmp_path):
    from atlas.engineering.ingest import RepoAcquirer
    from tests.test_engineering_ingest import FakeAssetStore, FakeGit, FakeStorage

    return RepoAcquirer(
        FakeAssetStore(), FakeStorage(tmp_path), git=FakeGit(root_commit="abc")
    )


def _service(tmp_path, *, llm, graph_results):
    repo = tmp_path / "api"
    repo.mkdir()
    (repo / "a.py").write_text("print(1)\n")
    root = str(repo)
    fixture = _repo_fixture("api", ["FastAPI"], {"python": 3}, ["Repository pattern"])
    fixture[0]["root"] = root
    fixture[0]["dependencies"] = {"pip": ["fastapi"]}
    code = FakeCodeService({root: fixture})

    intel_repo = FakeIntelRepo()
    finding_repo = FakeFindingRepo()
    learning = LearningService(FakeLearningRepo(), LearningConfig(auto_apply=False))
    writer = EngineeringFindingWriter(finding_repo)
    sink = CodeStoreSink(intel_repo, findings=writer)
    learning.register_sink("code", sink)
    reviewer = DesignReviewer(llm) if llm is not None else None
    svc = IntelligenceService(
        code, intel_repo, learning, IntelligenceConfig(),
        acquirer=_acquirer(tmp_path),
        graph_store=FakeGraphStore(graph_results),
        design_reviewer=reviewer, findings=writer,
    )
    return svc, finding_repo, root, sink


def test_structural_change_triggers_design_findings(tmp_path):
    llm = FakeLLM()
    svc, finding_repo, root, _sink = _service(
        tmp_path, llm=llm, graph_results=[{"reused": False, "diff": None}],
    )
    out = svc.learn_repository(path=root)
    assert out["outcome"] == "ok"
    assert out["design_review"]["ran"] is True
    assert out["design_findings"] == 2
    assert len(llm.calls) == 1
    active_kinds = [f["claim_type"] for f in finding_repo.active()]
    assert CLAIM_STRUCTURE in active_kinds
    assert CLAIM_DESIGN in active_kinds and CLAIM_RISK in active_kinds


def test_doc_only_reingest_skips_llm_and_preserves_design(tmp_path):
    llm = FakeLLM()
    # First ingest: new graph version → review runs. Second: reused → skip.
    svc, finding_repo, root, _sink = _service(
        tmp_path, llm=llm,
        graph_results=[{"reused": False, "diff": None}, {"reused": True, "diff": None}],
    )
    first = svc.learn_repository(path=root)
    assert first["design_findings"] == 2
    design_before = [f for f in finding_repo.active()
                     if f["claim_type"] in (CLAIM_DESIGN, CLAIM_RISK)]
    assert len(design_before) == 2

    second = svc.learn_repository(path=root)
    assert second["design_review"]["ran"] is False       # structural gate skipped it
    assert second["design_findings"] == 0
    assert len(llm.calls) == 1                            # no new token spend
    design_after = [f for f in finding_repo.active()
                    if f["claim_type"] in (CLAIM_DESIGN, CLAIM_RISK)]
    assert len(design_after) == 2                         # preserved, not archived


def test_without_llm_structural_findings_still_land(tmp_path):
    svc, finding_repo, root, _sink = _service(
        tmp_path, llm=None, graph_results=[{"reused": False, "diff": None}],
    )
    out = svc.learn_repository(path=root)
    assert out["outcome"] == "ok"
    assert out["design_findings"] == 0
    active_kinds = {f["claim_type"] for f in finding_repo.active()}
    assert CLAIM_STRUCTURE in active_kinds and CLAIM_PATTERN in active_kinds
    assert CLAIM_DESIGN not in active_kinds


def test_on_demand_review_writes_design_findings(tmp_path):
    llm = FakeLLM()
    # No auto review (graph reused), then run it on demand.
    svc, finding_repo, root, _sink = _service(
        tmp_path, llm=llm, graph_results=[{"reused": True, "diff": None}],
    )
    out = svc.learn_repository(path=root)
    assert out["design_findings"] == 0                   # gate skipped auto review
    repo_uid = out["repository"]["repo_uid"]

    on_demand = svc.review_design(repo_uid)
    assert on_demand["outcome"] == "ok"
    assert on_demand["design_findings"] == 2
    design = [f for f in finding_repo.active()
              if f["claim_type"] in (CLAIM_DESIGN, CLAIM_RISK)]
    assert len(design) == 2
    # Structure/pattern findings are untouched by the scoped design write.
    assert any(f["claim_type"] == CLAIM_STRUCTURE for f in finding_repo.active())


def test_revert_archives_design_findings(tmp_path):
    llm = FakeLLM()
    svc, finding_repo, root, sink = _service(
        tmp_path, llm=llm, graph_results=[{"reused": False, "diff": None}],
    )
    out = svc.learn_repository(path=root)
    ref = out["repository"]["id"]
    assert len(finding_repo.active()) >= 3

    # Reverting the learn archives *all* code findings for the repo, design included (BB9).
    sink.revert(ref)
    assert finding_repo.active() == []
