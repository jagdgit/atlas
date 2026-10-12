"""Read-only RAG coverage for the evening report.

Uses the process's existing KnowledgeService. Does not build an index or an embedder.
A failed read stays NOT_TESTED. Counts are never filled in as zero.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STATUS_MEASURED = "MEASURED"
STATUS_NOT_TESTED = "NOT_TESTED"
_SNAPSHOT = Path("knowledge") / "rag_coverage.json"
_MISSING_LIMIT = 1000
_service: Any = None


def bind_knowledge_service(service: Any) -> None:
    """Remember the service this process already built."""
    global _service
    _service = service


def measure_rag_coverage(service: Any) -> dict[str, Any]:
    """Call embedding_coverage. On failure, return NOT_TESTED and no counts."""
    try:
        coverage = service.embedding_coverage() or {}
        missing = list(
            service.list_documents_missing_embeddings(limit=_MISSING_LIMIT) or []
        )
    except Exception as exc:  # noqa: BLE001 — diagnostic only; never invent counts
        return {"status": STATUS_NOT_TESTED, "error": type(exc).__name__}
    if "chunks" not in coverage or "embeddings" not in coverage:
        return {
            "status": STATUS_NOT_TESTED,
            "error": "coverage_missing_counts",
            "model": coverage.get("model"),
        }
    truncated = len(missing) >= _MISSING_LIMIT
    return {
        "status": STATUS_MEASURED,
        "model": coverage.get("model"),
        "chunks": int(coverage["chunks"]),
        "embeddings": int(coverage["embeddings"]),
        "unembedded_chunks": int(coverage.get("unembedded_chunks") or 0),
        "missing_documents": len(missing),
        "missing_documents_truncated": truncated,
    }


def snapshot_path(data_dir: str | Path | None) -> Path | None:
    if not data_dir:
        return None
    return Path(data_dir) / _SNAPSHOT


def persist_rag_coverage(data_dir: str | Path | None, measurement: dict[str, Any]) -> None:
    path = snapshot_path(data_dir)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(measurement, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_rag_coverage(data_dir: str | Path | None) -> dict[str, Any] | None:
    path = snapshot_path(data_dir)
    if path is None or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def record_rag_coverage(data_dir: str | Path | None, service: Any = None) -> dict[str, Any]:
    """Measure with the bound service and store the result. Read-only."""
    svc = service if service is not None else _service
    if svc is None:
        measured = {"status": STATUS_NOT_TESTED, "error": "knowledge_service_unbound"}
    else:
        measured = measure_rag_coverage(svc)
    persist_rag_coverage(data_dir, measured)
    return measured


def format_rag_coverage_lines(
    data_dir: str | Path | None = None,
    *,
    refresh: bool = False,
) -> list[str]:
    """Evening-report lines. Prefer the on-disk snapshot so mail is not blocked on DB."""
    if refresh and _service is not None:
        measured = record_rag_coverage(data_dir, _service)
    else:
        measured = load_rag_coverage(data_dir) or {
            "status": STATUS_NOT_TESTED,
            "error": "not_measured",
        }
        if (
            measured.get("status") != STATUS_MEASURED
            and _service is not None
            and refresh
        ):
            measured = record_rag_coverage(data_dir, _service)
    lines = ["", "━━━━━━━━ RAG COVERAGE ━━━━━━━━", f"Status: {measured.get('status') or STATUS_NOT_TESTED}"]
    if measured.get("status") != STATUS_MEASURED:
        lines.append(f"Error: {measured.get('error') or 'not_measured'}")
        return lines
    lines.append(f"Chunks: {measured.get('chunks')}")
    lines.append(f"Embeddings: {measured.get('embeddings')}")
    lines.append(f"Unembedded chunks: {measured.get('unembedded_chunks')}")
    missing = measured.get("missing_documents")
    if measured.get("missing_documents_truncated"):
        lines.append(f"Missing documents: at least {missing}")
    else:
        lines.append(f"Missing documents: {missing}")
    return lines
