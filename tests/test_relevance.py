"""Tests for the relevance filter (Stage 3.1)."""

from __future__ import annotations

from atlas.evidence.models import Source
from atlas.research.relevance import filter_relevant, score_relevance


def test_pv_soiling_paper_scores_high():
    rel = score_relevance(
        "data-driven soiling estimation for solar panels",
        title="Data-driven soiling detection in PV modules",
        snippet="We estimate the soiling ratio on photovoltaic modules.",
    )
    assert rel.relevant
    assert rel.score >= 0.3


def test_astronomy_paper_is_dropped():
    rel = score_relevance(
        "data-driven soiling estimation for solar panels",
        title="SEP environment in the inner heliosphere from Solar Orbiter",
        snippet="Solar energetic particles and the solar wind.",
        url="http://arxiv.org/abs/2408.02330",
    )
    assert not rel.relevant
    assert "astronomy" in rel.reason or rel.score < 0.15


def test_filter_relevant_splits_pool():
    objective = "data-driven soiling estimation for solar panels"
    items = [
        Source(id="1", title="PV soiling loss estimation with CNN",
               url="https://ieeexplore.ieee.org/1", evidence_level=4),
        Source(id="2", title="Solar structure and evolution",
               url="http://arxiv.org/abs/2007.06488", evidence_level=3),
        Source(id="3", title="NREL Efforts to Address Soiling on PV Modules",
               url="https://www.nrel.gov/x", evidence_level=3),
    ]
    # Attach snippets via a thin wrapper using title-only scoring.
    kept, dropped = filter_relevant(
        objective, items,
        title_of=lambda s: s.title,
        snippet_of=lambda s: s.title,
        url_of=lambda s: s.url,
    )
    kept_ids = {s.id for s in kept}
    dropped_ids = {s.id for s, _ in dropped}
    assert "1" in kept_ids and "3" in kept_ids
    assert "2" in dropped_ids
