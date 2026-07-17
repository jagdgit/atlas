"""End-to-end tests for the deep research pipeline (Stage 3, Step 5 / §5d–5i, C4).

The whole point of Stage 3: Atlas *reads* documents and extracts **structured claims**,
so the report shows real, per-claim, cited findings — never "No verified claims" when
relevant papers were read. Exercised with the real ClaimExtractor + Verification Engine
+ Report Generator and fake providers/librarian, fully offline.
"""

from __future__ import annotations

from atlas.reports.generator import ReportGenerator
from atlas.reports.service import ReportService
from atlas.research.acquire import AcquireResult
from atlas.research.extract import ClaimExtractor
from atlas.research.reader import Reader
from atlas.research.service import RESEARCH_OK, ResearchService
from atlas.search.scholarly import Paper, ScholarlyResponse
from atlas.verification.engine import EvidenceBudget, VerificationEngine
from atlas.verification.service import VerificationService

_ABSTRACT = (
    "In this field study we measured a soiling loss of {v} %/day on photovoltaic "
    "modules across a full year of operation in a desert climate, and found that "
    "data-driven cleaning schedules reduced operational cost by 18 percent. "
    "Measurements used 15-minute inverter telemetry with co-located irradiance and "
    "module temperature sensors, and fifteen supervised cleaning events provided "
    "ground truth for estimator validation. We compare ridge regression, support "
    "vector regression, and a physics-informed baseline under identical hold-out "
    "windows, reporting MAPE and RMSE for each soiling rate estimate. The results "
    "are intended to support open-access evaluation of data-driven soiling methods."
)


class FakeScholar:
    def __init__(self, papers):
        self._papers = papers
        self.calls = 0

    def search_scholar(self, query, max_results=None):
        self.calls += 1
        papers = self._papers if self.calls == 1 else []
        return ScholarlyResponse(query, "fake_scholar", "ok", papers=papers)


def _deep_service(*, scholar=None, librarian=None, extractor_llm=None, budget=None):
    verification = VerificationService(
        VerificationEngine(numeric_tolerance=0.15),
        default_budget=budget or EvidenceBudget(),
    )
    reports = ReportService(verification, ReportGenerator())
    return ResearchService(
        verification, reports,
        scholar=scholar,
        librarian=librarian,
        extractor=ClaimExtractor(extractor_llm),
        reader=Reader(),
        max_documents=12,
    )


def _papers(values, level=4):
    return [
        Paper(title=f"Paper {i}", url=f"https://s2.org/{i}", doi=f"10.1/{i}",
              abstract=_ABSTRACT.format(v=v), evidence_level=level)
        for i, v in enumerate(values)
    ]


def test_deep_pipeline_produces_real_verified_claims():
    scholar = FakeScholar(_papers([0.31, 0.33, 0.30]))
    result = _deep_service(scholar=scholar).research("research PV soiling loss rate")

    assert result["outcome"] == RESEARCH_OK
    pipe = result["pipeline"]
    assert pipe["read"] == 3          # three abstracts read (Tier-1)
    assert pipe["extracted"] >= 3     # ≥1 numeric claim per abstract
    assert pipe["claims"] >= 1
    # The report must contain real evidence, not the old "No verified claims".
    md = result["report"]["markdown"]
    assert "_No verified claims._" not in md
    assert "## Evidence" in md


def test_agreeing_claims_across_papers_merge_and_reach_high_confidence():
    # Three peer-reviewed papers report the same soiling loss → one converged claim.
    scholar = FakeScholar(_papers([0.31, 0.33, 0.30], level=4))
    result = _deep_service(scholar=scholar).research("research soiling loss")

    claims = result["graph"]["claims"]
    soiling = [c for c in claims if len(c["supporting_sources"]) >= 2]
    assert soiling, "the same quantity from ≥2 papers should merge into one claim"
    assert any(c["confidence"] == "HIGH" for c in soiling)


def test_citations_come_from_read_sources():
    scholar = FakeScholar(_papers([0.31, 0.33, 0.30]))
    result = _deep_service(scholar=scholar).research("research soiling")
    refs = result["report"]["sections"]["references"]
    assert refs and all(r["url"].startswith("https://s2.org/") for r in refs)


class FakeLibrarian:
    """Returns full-text Documents for the given source ids; blocks the rest."""

    def __init__(self, reader, full_text_by_id, blocked_ids=()):
        self._reader = reader
        self._full = full_text_by_id
        self._blocked = set(blocked_ids)
        self.called_with = None

    def acquire(self, sources, *, classifications=None, workspace=None, activity=None, top_k=None):
        self.called_with = [s.id for s in sources]
        docs = []
        blocked = []
        for s in sources:
            if s.id in self._full:
                docs.append(self._reader.read_text(
                    self._full[s.id], source_id=s.id, title=s.title, url=s.url))
            elif s.id in self._blocked:
                blocked.append({"source_id": s.id, "reason": "paywall"})
        return AcquireResult(documents=docs, blocked=blocked)


def test_librarian_full_text_is_used_and_paywalls_reported():
    reader = Reader()
    papers = _papers([0.31, 0.33], level=4)
    # scholar Source ids are the DOI (Paper.source_id = doi or url or title).
    full = {
        "10.1/0": "Results\nThe measured soiling loss was 0.32 %/day in the field.",
    }
    lib = FakeLibrarian(reader, full, blocked_ids={"10.1/1"})
    svc = _deep_service(scholar=FakeScholar(papers), librarian=lib)
    result = svc.research("research soiling loss")

    assert lib.called_with is not None  # the librarian was asked to acquire
    assert result["pipeline"]["acquired"] >= 1
    assert {b["source_id"] for b in result["blocked"]} == {"10.1/1"}
    # Paywalled sources must not become Tier-1 abstract stubs (0-claim noise).
    assert result["pipeline"]["read"] == 1


class _Recorder:
    def __init__(self):
        self.events = []

    def record(self, phase, message, **data):
        self.events.append((phase, message))
        return {}


def test_activity_feed_records_phases():
    rec = _Recorder()
    svc = _deep_service(scholar=FakeScholar(_papers([0.31, 0.33, 0.30])))
    svc.research("research soiling", activity=rec)
    phases = {p for p, _ in rec.events}
    assert "search" in phases
    assert "extract" in phases
    assert "verify" in phases


def test_workspace_gets_claims_and_evidence(tmp_path):
    from atlas.jobs.workspace import JobWorkspace

    ws = JobWorkspace.for_job(tmp_path, "deep-1")
    ws.init_manifest(objective="soiling")
    svc = _deep_service(scholar=FakeScholar(_papers([0.31, 0.33, 0.30])))
    result = svc.research("research soiling", workspace=ws)

    assert result["outcome"] == RESEARCH_OK
    assert ws.claims_path.is_file()
    assert ws.evidence_path.is_file()
    claims = ws.read_json("claims.json")
    assert isinstance(claims, list) and len(claims) >= 1
    evidence = ws.read_json("evidence.json")
    assert evidence["sources"] and evidence["claims"]


class _GapScholar:
    """Yields a different paper set depending on how many times it was queried."""

    def __init__(self, waves):
        self._waves = list(waves)
        self.calls = 0
        self.queries = []

    def search_scholar(self, query, max_results=None):
        self.queries.append(query)
        idx = min(self.calls, len(self._waves) - 1)
        self.calls += 1
        return ScholarlyResponse(query, "fake_scholar", "ok", papers=self._waves[idx])


def test_gap_driven_followup_query_is_not_a_synonym():
    # Round 1: only L2-grade abstracts → peer/gov gaps → round 2 must ask for peers.
    weak = [
        Paper(title="Blog", url="https://blog.ex/1", doi="10.weak/1",
              abstract=_ABSTRACT.format(v=0.3), evidence_level=2)
    ]
    peers = [
        Paper(title=f"Peer {i}", url=f"https://ieee.org/{i}", doi=f"10.peer/{i}",
              abstract=_ABSTRACT.format(v=0.31), evidence_level=4)
        for i in range(3)
    ]
    scholar = _GapScholar([weak, peers])
    budget = EvidenceBudget(
        min_sources=3, min_peer_reviewed=2, min_government=0, convergence=0.5,
        max_search_iterations=4,
    )
    result = _deep_service(scholar=scholar, budget=budget).research("research soiling")
    assert result["outcome"] == RESEARCH_OK
    assert scholar.calls >= 2  # followed up on the named gap
    # The follow-up query mentions peer-reviewed / IEEE — not a vague synonym.
    followups = " ".join(scholar.queries[1:]).lower()
    assert "peer" in followups or "ieee" in followups or "elsevier" in followups


def test_document_cap_surfaces_recommendations():
    # Cap at 1 document; leave unread candidates → recommendations for unmet gaps.
    papers = _papers([0.31, 0.33, 0.30, 0.32], level=2)  # all L2 → gaps remain
    verification = VerificationService(
        VerificationEngine(),
        default_budget=EvidenceBudget(
            min_sources=5, min_peer_reviewed=3, min_government=1, convergence=0.9,
            max_search_iterations=2,
        ),
    )
    reports = ReportService(verification, ReportGenerator())
    svc = ResearchService(
        verification, reports,
        scholar=FakeScholar(papers),
        extractor=ClaimExtractor(),
        reader=Reader(),
        max_documents=1,
    )
    result = svc.research("research soiling")
    assert result["outcome"] == RESEARCH_OK
    assert result["pipeline"]["read"] == 1
    # Cap with unmet gaps → ranked further reading from unread candidates
    assert result["recommendations"]
    assert "Recommended Further Reading" in (result["report"].get("markdown") or "")
