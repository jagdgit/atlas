"""Tests for the deterministic Source Classifier (Stage 3, Step 1 / §5c, C3)."""

from __future__ import annotations

import pytest

from atlas.evidence.models import (
    LEVEL_FIELD_DATA,
    LEVEL_FORUM,
    LEVEL_GOVERNMENT,
    LEVEL_PEER_REVIEWED,
    LEVEL_TECHNICAL,
)
from atlas.research.classifier import (
    ACCESS_DATASET,
    ACCESS_HTML,
    ACCESS_OPEN,
    ACCESS_PAYWALL,
    ACCESS_VIDEO,
    KIND_PEER_REVIEWED,
    classify,
)


@pytest.mark.parametrize(
    "url, level",
    [
        ("https://ieeexplore.ieee.org/document/10847915", LEVEL_PEER_REVIEWED),
        ("https://www.sciencedirect.com/science/article/pii/S2590123025008874", LEVEL_PEER_REVIEWED),
        ("https://onlinelibrary.wiley.com/doi/full/10.1002/solr.202500576", LEVEL_PEER_REVIEWED),
        ("https://www.nature.com/articles/s41560-021", LEVEL_PEER_REVIEWED),
        ("https://www.mdpi.com/1996-1073/14/1/1", LEVEL_PEER_REVIEWED),
        ("https://arxiv.org/abs/2301.12939", LEVEL_GOVERNMENT),          # preprint = L3
        ("https://ar5iv.labs.arxiv.org/html/2301.12939", LEVEL_GOVERNMENT),
        ("https://www.nrel.gov/docs/fy20osti/1234.pdf", LEVEL_GOVERNMENT),
        ("https://energy.gov/report", LEVEL_GOVERNMENT),
        ("https://zenodo.org/record/12345", LEVEL_FIELD_DATA),
        ("https://data.gov/dataset/pv", LEVEL_FIELD_DATA),               # dataset before .gov
        ("https://www.youtube.com/watch?v=abcdefghijk", LEVEL_TECHNICAL),
        ("https://www.reddit.com/r/solar/comments/x", LEVEL_FORUM),
        ("https://www.linkedin.com/posts/x", LEVEL_FORUM),
        ("https://somevendor.com/blog/soiling", LEVEL_TECHNICAL),        # default
    ],
)
def test_evidence_level_by_domain(url, level):
    assert classify(url).evidence_level == level


def test_access_methods():
    assert classify("https://arxiv.org/abs/1").access_method == ACCESS_OPEN
    assert classify("https://ieeexplore.ieee.org/x").access_method == ACCESS_PAYWALL
    assert classify("https://zenodo.org/record/1").access_method == ACCESS_DATASET
    assert classify("https://youtu.be/abcdefghijk").access_method == ACCESS_VIDEO
    assert classify("https://random.example/post").access_method == ACCESS_HTML


def test_open_access_publishers_are_open():
    # MDPI / PMC / PLOS / SpringerOpen are peer-reviewed *and* open access.
    for url in (
        "https://www.mdpi.com/x",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC1",
        "https://journals.plos.org/plosone/article",
    ):
        cls = classify(url)
        assert cls.evidence_level == LEVEL_PEER_REVIEWED
        assert cls.access_method == ACCESS_OPEN


def test_www_and_missing_scheme_normalized():
    assert classify("www.nature.com/articles/x").evidence_level == LEVEL_PEER_REVIEWED
    assert classify("ieeexplore.ieee.org/document/1").evidence_level == LEVEL_PEER_REVIEWED


def test_doi_is_weak_peer_reviewed_signal_when_domain_unknown():
    cls = classify("https://unknown-host.example/paper", doi="10.1000/xyz")
    assert cls.kind == KIND_PEER_REVIEWED
    assert cls.evidence_level == LEVEL_PEER_REVIEWED
    assert cls.matched == "doi"


def test_metadata_doi_also_counts():
    cls = classify("https://unknown.example/p", metadata={"doi": "10.1/abc"})
    assert cls.evidence_level == LEVEL_PEER_REVIEWED


def test_empty_and_garbage_urls_default_safely():
    for url in ("", "   ", "not a url"):
        cls = classify(url)
        assert cls.evidence_level == LEVEL_TECHNICAL
        assert cls.matched == "default"


def test_classification_serializes():
    d = classify("https://arxiv.org/abs/1").as_dict()
    assert d["evidence_level"] == LEVEL_GOVERNMENT
    assert d["level_name"].startswith("L3")
    assert d["access_method"] == ACCESS_OPEN
