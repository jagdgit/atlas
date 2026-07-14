"""Promote completed research into Knowledge + Learning (Stage 3, C6 / RS / A6).

After a research job finishes, Atlas should *learn from what it did*:

- **Read documents** → Knowledge, ``domain=external`` (real sources Atlas read).
- **Verified claims + evidence graph** → Knowledge, ``domain=research``.
- **Experience** is proposed separately by ``LearningService.observe_job`` and
  tagged ``domain=experience`` (``provisional`` when overall confidence < MEDIUM).

Everything is best-effort and governed — never fails a job; never auto-applies
unless the LearningService is configured for ``auto_apply``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from atlas.knowledge.domains import DOMAIN_EXTERNAL, DOMAIN_RESEARCH

_logger = logging.getLogger("atlas.research.learn")


def promote_research(
    *,
    knowledge: Any | None,
    learning: Any | None = None,
    workspace: Any | None = None,
    job_id: str | None = None,
    objective: str = "",
    graph: dict[str, Any] | None = None,
    claims: list[dict[str, Any]] | None = None,
    embed: bool = False,
) -> dict[str, Any]:
    """Ingest research artifacts into Knowledge (domain-tagged). Best-effort.

    Prefers workspace files (``documents/``, ``claims.json``, ``evidence.json``)
    when present; falls back to the in-memory ``graph``/``claims`` payloads.
    Returns a small summary of what was promoted (counts only).
    """
    summary: dict[str, Any] = {
        "external_docs": 0,
        "research_docs": 0,
        "events": 0,
        "errors": 0,
    }
    meta_base = {"job_id": job_id, "objective": (objective or "")[:200]}

    if knowledge is not None:
        summary["external_docs"] = _ingest_read_documents(
            knowledge, workspace, meta_base, embed=embed
        )
        summary["research_docs"] = _ingest_claims_graph(
            knowledge, workspace, graph, claims, meta_base, embed=embed
        )

    # Optional governed proposals into the learning ledger for the research store,
    # so promotion stays explainable/reversible even when auto_apply is off.
    if learning is not None and (graph or claims or workspace is not None):
        try:
            payload = {
                "objective": objective,
                "job_id": job_id,
                "graph": graph or (workspace.read_json("evidence.json") if workspace else None),
                "claims": claims or (workspace.read_json("claims.json") if workspace else None),
                "domain": DOMAIN_RESEARCH,
            }
            event = learning.propose(
                "job",
                "knowledge",
                source_id=str(job_id) if job_id else None,
                summary=f"Research graph from job: {(objective or '')[:100]}",
                reason="Verified claims + evidence graph from a completed research job (A6).",
                origin=f"job {job_id}" if job_id else "research",
                payload=payload,
            )
            if event:
                summary["events"] += 1
        except Exception:  # noqa: BLE001
            summary["errors"] += 1
            _logger.debug("research learning propose failed", exc_info=True)

    return summary


def _ingest_read_documents(
    knowledge: Any, workspace: Any, meta: dict[str, Any], *, embed: bool
) -> int:
    if workspace is None or not hasattr(workspace, "documents_dir"):
        return 0
    docs_dir: Path = workspace.documents_dir
    if not docs_dir.is_dir():
        return 0
    count = 0
    for path in sorted(docs_dir.iterdir()):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if len(text) < 40:
            continue
        try:
            knowledge.ingest_text(
                "research",
                text,
                uri=str(path),
                title=path.stem,
                metadata={**meta, "artifact": "read_document"},
                domain=DOMAIN_EXTERNAL,
                embed=embed,
            )
            count += 1
        except Exception:  # noqa: BLE001
            _logger.debug("ingest read doc %s failed", path, exc_info=True)
    return count


def _ingest_claims_graph(
    knowledge: Any,
    workspace: Any,
    graph: dict[str, Any] | None,
    claims: list[dict[str, Any]] | None,
    meta: dict[str, Any],
    *,
    embed: bool,
) -> int:
    count = 0
    if workspace is not None:
        claims = claims or workspace.read_json("claims.json")
        graph = graph or workspace.read_json("evidence.json")
    if claims:
        try:
            body = json.dumps(claims, indent=2, ensure_ascii=False)
            knowledge.ingest_text(
                "research",
                body,
                uri=f"job:{meta.get('job_id')}:claims" if meta.get("job_id") else None,
                title=f"Claims — {meta.get('objective', '')[:80]}",
                content_type="application/json",
                metadata={**meta, "artifact": "claims"},
                domain=DOMAIN_RESEARCH,
                embed=embed,
            )
            count += 1
        except Exception:  # noqa: BLE001
            _logger.debug("ingest claims failed", exc_info=True)
    if graph:
        try:
            body = json.dumps(graph, indent=2, ensure_ascii=False)
            knowledge.ingest_text(
                "research",
                body,
                uri=f"job:{meta.get('job_id')}:evidence" if meta.get("job_id") else None,
                title=f"Evidence graph — {meta.get('objective', '')[:80]}",
                content_type="application/json",
                metadata={**meta, "artifact": "evidence_graph"},
                domain=DOMAIN_RESEARCH,
                embed=embed,
            )
            count += 1
        except Exception:  # noqa: BLE001
            _logger.debug("ingest evidence graph failed", exc_info=True)
    return count
