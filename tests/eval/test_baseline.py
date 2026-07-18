"""Hermetic baseline runners for Stage 3B.0 corpora."""

from __future__ import annotations

from atlas.eval.baseline import BASELINE_VERSION, run_baseline_suite
from atlas.eval.benchmark import load_benchmark_set
from atlas.eval.fixtures import load_cases
from atlas.eval.lifecycle import score_freshness_corpus, score_provenance_corpus
from atlas.eval.retrieval import score_retrieval_corpus
from atlas.eval.synthesis import score_synthesis_corpus
from atlas.research.grouping import group_claims
from atlas.evidence.models import Claim


def test_retrieval_hermetic_baseline_scores():
    result = score_retrieval_corpus(load_cases("retrieval_relevant.json"))
    assert result["n_cases"] == 4
    assert result["precision_at_k"] > 0.5
    assert result["recall_at_k"] > 0.5


def test_synthesis_duplicates_baseline_perfect_on_fixtures():
    result = score_synthesis_corpus(load_cases("synthesis_duplicates.json"))
    assert result["n_cases"] == 3
    assert result["merge_accuracy"] == 1.0
    assert result["false_merge_rate"] == 0.0
    assert result["group_count_match_rate"] == 1.0


def test_synthesis_contradictions_baseline():
    result = score_synthesis_corpus(load_cases("synthesis_contradictions.json"))
    assert result["n_cases"] == 2
    assert result["merge_accuracy"] == 1.0
    assert result["contradiction_recall"] == 1.0


def test_group_claims_still_matches_fixture_expectations_directly():
    cases = load_cases("synthesis_contradictions.json")
    claims = [Claim.from_dict(c) for c in cases[0]["claims"]]
    grouped = group_claims(claims)
    assert len(grouped) == 1
    assert {e.source_id for e in grouped[0].contradicting} == {"p3"}


def test_freshness_and_provenance_fixtures():
    fresh = score_freshness_corpus(load_cases("freshness_cases.json"))
    assert fresh["freshness_label_accuracy"] == 1.0
    prov = score_provenance_corpus(load_cases("provenance_cases.json"))
    assert 0.0 < prov["provenance_completeness"] < 1.0


def test_benchmark_set_size():
    problems = load_benchmark_set()
    assert 10 <= len(problems) <= 20
    assert all(p.id.startswith("BM-") for p in problems)
    assert all(p.objective and p.acceptance_notes for p in problems)


def test_run_baseline_suite_versioned():
    report = run_baseline_suite()
    assert report.version == BASELINE_VERSION
    assert report.milestone == "3B.0"
    d = report.as_dict()
    assert d["sections"]["retrieval_hermetic"]["n_cases"] == 4
    assert d["sections"]["synthesis_duplicates"]["merge_accuracy"] == 1.0
    assert d["sections"]["synthesis_contradictions"]["contradiction_recall"] == 1.0
    assert d["sections"]["freshness"]["freshness_label_accuracy"] == 1.0
    assert d["sections"]["supersession"]["supersession_correctness"] == 1.0
    assert d["sections"]["benchmark_set"]["n_problems"] >= 10
