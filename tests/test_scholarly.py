"""Scholarly search tests (S18a): arXiv + Semantic Scholar providers, plugin fallback.

Hermetic: a fake FetchClient returns canned Atom XML / JSON per URL, so no network is
touched and parsing + evidence grading are verified deterministically.
"""

from __future__ import annotations

from atlas.net import OUTCOME_BLOCKED, OUTCOME_OK, FetchResult
from atlas.plugins.scholar_plugin import ScholarPlugin
from atlas.search.scholarly import (
    ArxivProvider,
    ScholarlyResponse,
    SemanticScholarProvider,
)

_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2001.00001v1</id>
    <published>2020-01-05T00:00:00Z</published>
    <title>Soiling Losses in PV Systems</title>
    <summary>We quantify soiling.</summary>
    <author><name>Jane Doe</name></author>
    <author><name>John Roe</name></author>
    <arxiv:doi>10.1000/arxiv.1</arxiv:doi>
  </entry>
</feed>"""

_S2_JSON = (
    '{"data":[{"title":"A Review of PV Soiling","abstract":"Broad review.",'
    '"year":2021,"venue":"Solar Energy","authors":[{"name":"A. Smith"},'
    '{"name":"B. Jones"}],"externalIds":{"DOI":"10.1/s2.1"},'
    '"citationCount":123,"url":"https://s2.org/paper/1"}]}'
)


class FakeClient:
    def __init__(self, by_substr: dict[str, FetchResult]):
        self._by_substr = by_substr
        self.calls: list[str] = []

    def get(self, url: str, **kw) -> FetchResult:
        self.calls.append(url)
        for sub, result in self._by_substr.items():
            if sub in url:
                return result
        return FetchResult(url, OUTCOME_OK, text="")


# --- arXiv ----------------------------------------------------------------
def test_paper_as_source_keeps_doi_and_citation():
    from atlas.search.scholarly import Paper

    p = Paper(
        title="Soiling Losses",
        url="https://arxiv.org/abs/1",
        authors=["Jane Doe", "John Roe"],
        year=2020,
        venue="arXiv",
        doi="10.1000/arxiv.1",
        evidence_level=3,
    )
    src = p.as_source()
    assert src["doi"] == "10.1000/arxiv.1"
    assert "Jane Doe" in src["citation"]
    assert src["year"] == 2020
    restored = __import__("atlas.evidence.models", fromlist=["Source"]).Source.from_dict(src)
    assert restored.doi == "10.1000/arxiv.1"
    assert restored.authors == ("Jane Doe", "John Roe")


def test_arxiv_parses_papers_and_grades_l3():
    client = FakeClient({"export.arxiv.org": FetchResult("u", OUTCOME_OK, text=_ARXIV_XML)})
    prov = ArxivProvider(client, evidence_level=3)
    resp = prov.search("pv soiling", max_results=5)
    assert resp.ok
    assert len(resp.papers) == 1
    p = resp.papers[0]
    assert p.title == "Soiling Losses in PV Systems"
    assert p.authors == ["Jane Doe", "John Roe"]
    assert p.year == 2020
    assert p.doi == "10.1000/arxiv.1"
    assert p.evidence_level == 3
    assert p.as_source()["kind"] == "preprint"


def test_arxiv_empty_query_is_ok_no_call():
    client = FakeClient({})
    resp = ArxivProvider(client).search("   ")
    assert resp.ok and resp.papers == []
    assert client.calls == []


def test_arxiv_translates_blocked_outcome():
    client = FakeClient({"arxiv": FetchResult("u", OUTCOME_BLOCKED, reason="robots")})
    resp = ArxivProvider(client).search("x")
    assert resp.outcome == OUTCOME_BLOCKED
    assert resp.reason == "robots"


# --- Semantic Scholar -----------------------------------------------------
def test_semantic_scholar_parses_and_grades_l4():
    client = FakeClient({"semanticscholar.org": FetchResult("u", OUTCOME_OK, text=_S2_JSON)})
    resp = SemanticScholarProvider(client, evidence_level=4).search("pv soiling")
    assert resp.ok
    p = resp.papers[0]
    assert p.venue == "Solar Energy"
    assert p.citation_count == 123
    assert p.doi == "10.1/s2.1"
    assert p.evidence_level == 4
    assert p.as_source()["kind"] == "peer_reviewed"


def test_semantic_scholar_bad_json_is_error_not_raise():
    client = FakeClient({"semanticscholar.org": FetchResult("u", OUTCOME_OK, text="not json")})
    resp = SemanticScholarProvider(client).search("x")
    assert resp.outcome == "error"


# --- plugin fallback ------------------------------------------------------
def test_scholar_plugin_falls_back_to_next_provider():
    # First provider blocked → second returns papers.
    arxiv = ArxivProvider(
        FakeClient({"arxiv": FetchResult("u", OUTCOME_BLOCKED, reason="429")})
    )
    s2 = SemanticScholarProvider(
        FakeClient({"semanticscholar.org": FetchResult("u", OUTCOME_OK, text=_S2_JSON)})
    )
    plugin = ScholarPlugin([arxiv, s2])
    resp = plugin.search_scholar("pv soiling")
    assert resp.ok
    assert resp.provider == "semantic_scholar"


def test_scholar_plugin_no_providers_is_error():
    resp = ScholarPlugin([]).search_scholar("x")
    assert resp.outcome == "error"


def test_scholar_search_tool_returns_sources_for_evidence_graph():
    s2 = SemanticScholarProvider(
        FakeClient({"semanticscholar.org": FetchResult("u", OUTCOME_OK, text=_S2_JSON)})
    )
    out = ScholarPlugin([s2]).scholar_search("pv soiling")
    assert out["outcome"] == "ok"
    assert out["sources"][0]["evidence_level"] == 4
    assert out["sources"][0]["kind"] == "peer_reviewed"


def test_scholar_plugin_health():
    s2 = SemanticScholarProvider(FakeClient({}))
    assert ScholarPlugin([s2]).health_check().healthy
    assert not ScholarPlugin([]).health_check().healthy


def test_response_as_dict_shape():
    resp = ScholarlyResponse("q", "arxiv", OUTCOME_OK, papers=[])
    d = resp.as_dict()
    assert set(d) == {"query", "provider", "outcome", "results", "sources", "reason"}
