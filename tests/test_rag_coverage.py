"""STEP 006 — RAG coverage is a read of the existing service, or NOT_TESTED."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.reports import format_evening_report
from atlas.knowledge.rag_coverage import (
    STATUS_MEASURED,
    STATUS_NOT_TESTED,
    format_rag_coverage_lines,
    measure_rag_coverage,
    record_rag_coverage,
)
from atlas.trading.strategy import StrategyDecisionRule


class _Coverage:
    def __init__(self, coverage, missing):
        self._coverage = coverage
        self._missing = missing

    def embedding_coverage(self):
        return dict(self._coverage)

    def list_documents_missing_embeddings(self, *, limit=20):
        return list(self._missing)[:limit]


class _Boom:
    def embedding_coverage(self):
        raise RuntimeError("db down")

    def list_documents_missing_embeddings(self, *, limit=20):
        raise RuntimeError("db down")


def test_coverage_records_counts_without_inventing_a_failure(tmp_path: Path):
    measured = measure_rag_coverage(
        _Coverage(
            {"model": "fake-embed", "chunks": 10, "embeddings": 7, "unembedded_chunks": 3},
            ["doc-a", "doc-b"],
        )
    )
    assert measured["status"] == STATUS_MEASURED
    assert measured["chunks"] == 10
    assert measured["embeddings"] == 7
    assert measured["unembedded_chunks"] == 3
    assert measured["missing_documents"] == 2
    record_rag_coverage(tmp_path, _Coverage(
        {"model": "fake-embed", "chunks": 10, "embeddings": 7, "unembedded_chunks": 3},
        ["doc-a", "doc-b"],
    ))
    lines = format_rag_coverage_lines(tmp_path)
    text = "\n".join(lines)
    assert "Status: MEASURED" in text
    assert "Chunks: 10" in text
    assert "Embeddings: 7" in text
    assert "Missing documents: 2" in text
    _subj, body = format_evening_report(
        plan={"as_of": "2026-10-05", "phase": "post_close", "confidence": "low"},
        portfolio={"data_dir": str(tmp_path)},
    )
    assert "Chunks: 10" in body
    assert "Embeddings: 7" in body
    assert "Missing documents: 2" in body
    assert StrategyDecisionRule.VERSION == "1.0.0"


def test_failed_coverage_stays_not_tested(tmp_path: Path):
    measured = measure_rag_coverage(_Boom())
    assert measured["status"] == STATUS_NOT_TESTED
    assert measured["error"] == "RuntimeError"
    assert "chunks" not in measured
    assert "embeddings" not in measured
    record_rag_coverage(tmp_path, _Boom())
    text = "\n".join(format_rag_coverage_lines(tmp_path))
    assert "Status: NOT_TESTED" in text
    assert "Chunks:" not in text
    empty = "\n".join(format_rag_coverage_lines(tmp_path / "absent"))
    assert "Status: NOT_TESTED" in empty
