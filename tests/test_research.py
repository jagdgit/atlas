"""Tests for the autonomous research loop (S21).

The loop is exercised end-to-end with the *real* Verification Engine + Report Generator
and *fake* scholar/search providers (returning real `Paper`/`SearchHit` response objects),
so gather → verify → decide runs fully offline and deterministically.
"""

from __future__ import annotations

import pytest

from atlas.reports.generator import ReportGenerator
from atlas.reports.service import ReportService
from atlas.research.service import (
    RESEARCH_EMPTY,
    RESEARCH_OK,
    RESEARCH_UNAVAILABLE,
    ResearchService,
    clean_objective,
    extract_value,
    query_plan,
)
from atlas.search.providers import SearchHit, SearchResponse
from atlas.search.scholarly import Paper, ScholarlyResponse
from atlas.verification.engine import EvidenceBudget, VerificationEngine
from atlas.verification.service import VerificationService


# --- fakes ----------------------------------------------------------------
class FakeScholar:
    """Returns a fixed set of papers on the first query, empty thereafter."""

    def __init__(self, papers, *, outcome="ok", once=True, raises=False):
        self._papers = papers
        self._outcome = outcome
        self._once = once
        self._raises = raises
        self.calls = 0

    def search_scholar(self, query, max_results=None):
        self.calls += 1
        if self._raises:
            raise RuntimeError("boom")
        papers = self._papers if (self.calls == 1 or not self._once) else []
        return ScholarlyResponse(query, "fake_scholar", self._outcome, papers=papers)


class FakeSearch:
    """Returns one unique hit per query (so sources accumulate across rounds)."""

    def __init__(self, *, outcome="ok", snippet=""):
        self._outcome = outcome
        self._snippet = snippet
        self.calls = 0

    def search_web(self, query, max_results=None):
        self.calls += 1
        hit = SearchHit(
            title=f"Result {self.calls}",
            url=f"https://ex.com/{self.calls}",
            snippet=self._snippet,
        )
        return SearchResponse(query, "fake_web", self._outcome, hits=[hit])


def _service(*, scholar=None, search=None, budget=None, per_query=5):
    verification = VerificationService(
        VerificationEngine(numeric_tolerance=0.15),
        default_budget=budget or EvidenceBudget(),
    )
    reports = ReportService(verification, ReportGenerator())
    return ResearchService(
        verification, reports, scholar=scholar, search=search, per_query=per_query
    )


# --- pure helpers ---------------------------------------------------------
def test_clean_objective_strips_research_verbs():
    assert clean_objective("research solar soiling losses") == "solar soiling losses"
    assert clean_objective("investigate: battery cycle life") == "battery cycle life"
    assert clean_objective("do a deep dive on grid storage") == "grid storage"
    # No verb → returned unchanged.
    assert clean_objective("solar output") == "solar output"


def test_query_plan_interleaves_scholar_then_web_and_caps():
    plan = query_plan("research solar output", max_iterations=4)
    assert plan == [
        ("scholar", "solar output"),
        ("web", "solar output"),
        ("scholar", "solar output data"),
        ("web", "solar output data"),
    ]


def test_extract_value_skips_years_and_parses_numbers():
    assert extract_value("about 42.5 kWh/m2") == 42.5
    assert extract_value("published in 2021") is None  # bare year skipped
    assert extract_value("in 2021 it reached 88 percent") == 88.0
    assert extract_value("1,234 modules") == 1234.0
    assert extract_value("no numbers here") is None


# --- the loop -------------------------------------------------------------
def test_converges_and_stops_on_budget():
    # 5 sources (3×L4 + 2×L3), all reporting the same value → convergence 1.0.
    papers = [
        Paper(title=f"Paper {i}", url=f"https://s2.org/{i}", doi=f"10.1/{i}",
              abstract="the measured value is 42 units", evidence_level=lvl)
        for i, lvl in enumerate([4, 4, 4, 3, 3])
    ]
    svc = _service(scholar=FakeScholar(papers))
    result = svc.research("research the value of X")

    assert result["outcome"] == RESEARCH_OK
    assert result["iterations"] == 1  # everything met on the first round
    assert result["stopped"]["decision"] == "stop"
    assert "all budget criteria met" in result["stopped"]["reasons"]
    assert result["claim"]["confidence"] == "HIGH"
    assert len(result["graph"]["sources"]) == 5
    assert result["report"]["markdown"]


def test_continues_until_iteration_cap():
    # Web-only, low-grade sources that never satisfy peer-reviewed/government criteria.
    svc = _service(search=FakeSearch(snippet="no numbers"))
    result = svc.research("research an unsettled question", max_iterations=3)

    assert result["outcome"] == RESEARCH_OK
    assert result["iterations"] == 3
    assert result["stopped"]["decision"] == "stop"
    assert any("max_search_iterations" in r for r in result["stopped"]["reasons"])
    assert len(result["graph"]["sources"]) == 3  # one unique hit per round


def test_unavailable_when_no_providers():
    svc = _service()  # neither scholar nor search injected, no capability registry
    result = svc.research("research anything")
    assert result["outcome"] == RESEARCH_UNAVAILABLE


def test_empty_when_providers_return_nothing():
    svc = _service(scholar=FakeScholar([], outcome="ok"))
    result = svc.research("research a void", max_iterations=2)
    assert result["outcome"] == RESEARCH_EMPTY
    assert result["iterations"] == 2


def test_provider_error_is_skipped_not_fatal():
    # Scholar raises; the loop must survive and use the web provider (R3).
    svc = _service(scholar=FakeScholar([], raises=True),
                   search=FakeSearch(snippet="value 10"))
    result = svc.research("research resilience", max_iterations=4)
    assert result["outcome"] == RESEARCH_OK
    assert result["graph"]["sources"]  # web sources gathered despite scholar failure


def test_dedupes_sources_across_rounds():
    papers = [Paper(title="P", url="https://s2.org/dup", doi="10.1/dup",
                    abstract="value 7", evidence_level=4)]
    svc = _service(scholar=FakeScholar(papers, once=False), per_query=5)
    result = svc.research("research duplicates", max_iterations=3)
    # Same source id every round → only counted once.
    assert len(result["graph"]["sources"]) == 1


# --- capability resolution via registry -----------------------------------
class FakeCaps:
    def __init__(self, providers):
        self._p = providers

    def has(self, name):
        return name in self._p

    def get(self, name):
        return self._p[name]


def test_resolves_providers_from_capability_registry():
    papers = [Paper(title=f"P{i}", url=f"u{i}", doi=f"d{i}",
                    abstract="value 5", evidence_level=4) for i in range(5)]
    verification = VerificationService(VerificationEngine(), default_budget=EvidenceBudget())
    reports = ReportService(verification, ReportGenerator())
    svc = ResearchService(
        verification, reports, capabilities=FakeCaps({"scholar": FakeScholar(papers)})
    )
    result = svc.research("research via registry")
    assert result["outcome"] == RESEARCH_OK
    assert len(result["graph"]["sources"]) == 5


def test_health_check_reports_providers():
    svc = _service(search=FakeSearch())
    health = svc.health_check()
    assert health.healthy
    assert "search" in health.data["providers"]
