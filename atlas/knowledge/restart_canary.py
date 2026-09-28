"""OI-LAB-LOOP0 Step 11 — learning → RAG → LLM after restart.

Day 1 stores one durable finding (not a trade, not a chunk smash).
Day 2 (new process / new KnowledgeService) retrieves it and hands it to RagAgent.
Row counts are not this canary.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "lab.loop0.step11.canary.v1"
CANARY_TOKEN = "LAB-LOOP0-S11-CANARY"
STATEMENT = (
    "Setup X performed poorly when regime Y was present. "
    f"{CANARY_TOKEN}: validated finding for restart recall — not a trade blotter dump."
)
QUERY = "How did setup X perform when regime Y was present?"
STORE_REL = Path("investment") / "learning" / "step11_canary.json"
_log = logging.getLogger("atlas.knowledge.restart_canary")


def marker_path(data_dir: str | Path | None) -> Path | None:
    if not data_dir:
        return None
    return Path(data_dir) / STORE_REL


def load_marker(data_dir: str | Path | None) -> dict[str, Any] | None:
    path = marker_path(data_dir)
    if path is None or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_marker(data_dir: str | Path | None, payload: dict[str, Any]) -> dict[str, Any]:
    path = marker_path(data_dir)
    if path is None:
        return {"ok": False, "reason": "no_data_dir"}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, indent=2, default=str) + "\n"
        path.write_text(text, encoding="utf-8")
        return {"ok": True, "path": str(path)}
    except OSError as exc:
        _log.debug("step11 marker write failed: %s", exc, exc_info=True)
        return {"ok": False, "reason": "persist_error"}


def _finding_id(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("finding_id") or row.get("id") or "")


def store_canary(
    knowledge: Any,
    data_dir: str | Path | None,
    *,
    findings: Any | None = None,
    finding_embeddings: Any | None = None,
) -> dict[str, Any]:
    """Persist the Step 11 finding on the findings index. Never writes chunks."""
    findings = findings if findings is not None else getattr(knowledge, "_findings", None)
    emb = (
        finding_embeddings
        if finding_embeddings is not None
        else getattr(knowledge, "_finding_embeddings", None)
    )
    existing = load_marker(data_dir)
    if existing and existing.get("finding_id") and not existing.get("force"):
        return {**existing, "ok": True, "skipped": True, "reason": "already_stored"}

    n_chunks_before = None
    try:
        n_chunks_before = int(getattr(knowledge._chunks, "count", lambda: None)() or 0)
    except Exception:  # noqa: BLE001
        n_chunks_before = None

    row: dict[str, Any] = {
        "finding_id": "",
        "canonical_id": "F-S11CANARY",
        "statement": STATEMENT,
        "domain": "research",
        "status": "active",
    }
    created: dict[str, Any] | None = None
    if findings is not None and hasattr(findings, "create"):
        try:
            created = findings.create(
                STATEMENT,
                domain="research",
                status="active",
                maturity="candidate",
                provenance={
                    "canary": CANARY_TOKEN,
                    "version": VERSION,
                    "not_a_trade": True,
                },
                identity_key=["lab-loop0-s11-canary"],
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning("step11 finding create failed: %s", exc)
            created = None
        if isinstance(created, dict):
            row["finding_id"] = _finding_id(created)
            row["canonical_id"] = str(created.get("canonical_id") or row["canonical_id"])
            row["id"] = created.get("id") or row["finding_id"]
    if not row["finding_id"]:
        row["finding_id"] = CANARY_TOKEN.lower()
        row["id"] = row["finding_id"]
        if findings is not None and hasattr(findings, "rows"):
            findings.rows = [
                r
                for r in (findings.rows or [])
                if str(r.get("finding_id") or r.get("id")) != row["finding_id"]
            ]
            findings.rows.append(dict(row))

    vector = None
    try:
        vector = knowledge._query_vector(STATEMENT)
    except Exception:  # noqa: BLE001
        vector = None
    if not vector:
        try:
            vector = list(knowledge._llm.embed([STATEMENT]).vectors[0])
        except Exception:  # noqa: BLE001
            vector = None
    if emb is not None and vector:
        try:
            if hasattr(emb, "meta") and isinstance(emb.meta, dict):
                emb.meta[row["finding_id"]] = dict(row)
            emb.upsert(row["finding_id"], getattr(knowledge, "_model", None) or "default", vector)
        except Exception as exc:  # noqa: BLE001
            _log.warning("step11 finding embed failed: %s", exc)

    marker = {
        "ok": True,
        "version": VERSION,
        "phase": "day1_stored",
        "finding_id": row["finding_id"],
        "canonical_id": row.get("canonical_id"),
        "statement": STATEMENT,
        "query": QUERY,
        "token": CANARY_TOKEN,
        "chunk_smash": False,
        "not_a_trade": True,
        "chunks_before": n_chunks_before,
        "stored_at": datetime.now(timezone.utc).isoformat(),
    }
    wrote = _write_marker(data_dir, marker)
    marker["path"] = wrote.get("path")
    marker["persist_ok"] = bool(wrote.get("ok"))
    return marker


def retrieve_canary(knowledge: Any, *, query: str = QUERY) -> dict[str, Any]:
    ranked = knowledge.retrieve(query, k=5, role="research", mode="hybrid")
    hits = []
    found = False
    for hit in list(getattr(ranked, "hits", None) or []):
        content = str(getattr(hit, "content", "") or "")
        chunk_id = str(getattr(hit, "chunk_id", "") or "")
        tier = str(getattr(hit, "tier", "") or "")
        row = {
            "chunk_id": chunk_id,
            "tier": tier,
            "content": content[:400],
            "finding_id": chunk_id.split(":", 1)[1] if chunk_id.startswith("finding:") else None,
            "source": tier,
            "document_id": str(getattr(hit, "document_id", "") or ""),
            "score": getattr(hit, "score", None),
            "similarity": getattr(hit, "similarity", None),
            "timestamp": getattr(hit, "timestamp", None),
        }
        hits.append(row)
        if CANARY_TOKEN in content or STATEMENT[:40] in content:
            found = True
    return {
        "ok": found,
        "retrieved": found,
        "query": query,
        "finding_candidates": (getattr(ranked, "meta", None) or {}).get("finding_candidates"),
        "hits": hits,
        "version": VERSION,
    }


def _prompt_text(rag_agent: Any) -> str:
    llm = getattr(rag_agent, "_llm", None)
    messages = getattr(llm, "last_messages", None)
    if not messages:
        return ""
    parts: list[str] = []
    for msg in messages:
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
        if content:
            parts.append(str(content))
    return "\n".join(parts)


def cite_canary(rag_agent: Any, *, query: str = QUERY) -> dict[str, Any]:
    result = rag_agent.run(query, role="research", similarity_floor=0.0, k=5)
    answer = str(getattr(result, "answer", "") or "")
    citations = list(getattr(result, "citations", None) or [])
    prompt = _prompt_text(rag_agent)
    in_prompt = CANARY_TOKEN in prompt or STATEMENT[:40] in prompt
    in_answer = (
        CANARY_TOKEN in answer
        or "setup x" in answer.lower()
        or "regime y" in answer.lower()
        or "performed poorly" in answer.lower()
    )
    finding_citation = False
    for cit in citations:
        cid = str(getattr(cit, "chunk_id", "") or "")
        snippet = str(getattr(cit, "snippet", "") or "")
        if cid.startswith("finding:") or CANARY_TOKEN in snippet or STATEMENT[:40] in snippet:
            finding_citation = True
            break
    received = in_prompt or finding_citation
    referenced = in_answer or finding_citation
    return {
        "ok": received and referenced,
        "in_prompt": in_prompt,
        "in_answer": in_answer,
        "finding_citation": finding_citation,
        "answer": answer[:800],
        "citation_n": len(citations),
        "version": VERSION,
    }


def evaluate_day2(
    knowledge: Any,
    rag_agent: Any,
    data_dir: str | Path | None,
) -> dict[str, Any]:
    marker = load_marker(data_dir) or {}
    retrieved = retrieve_canary(knowledge)
    cited = {"ok": False, "in_prompt": False, "in_answer": False, "reason": "no_rag_agent"}
    if rag_agent is not None:
        try:
            cited = cite_canary(rag_agent)
        except Exception as exc:  # noqa: BLE001
            cited = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    day2 = {
        "ok": bool(retrieved.get("retrieved"))
        and bool(cited.get("in_prompt") or cited.get("finding_citation")),
        "version": VERSION,
        "phase": "day2_evaluated",
        "retrieved": retrieved,
        "cited": cited,
        "llm_referenced": bool(cited.get("in_answer") or cited.get("finding_citation")),
        "honesty": (
            "Success = Day-1 finding retrieved after restart and present in the LLM "
            "prompt or citations. LLM wording is recorded; a silent model is not a "
            "retrieval failure."
        ),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
    merged = dict(marker)
    merged["day2"] = day2
    merged["phase"] = "day2_evaluated"
    _write_marker(data_dir, merged)
    return day2


def run_tick(
    knowledge: Any,
    data_dir: str | Path | None,
    *,
    rag_agent: Any | None = None,
) -> dict[str, Any]:
    """Scheduler entry: store once, then evaluate retrieve→LLM after restart."""
    marker = load_marker(data_dir)
    if marker and (marker.get("day2") or {}).get("ok"):
        return {
            "ok": True,
            "skipped": True,
            "reason": "canary_complete",
            "phase": "day2_evaluated",
            "llm_referenced": (marker.get("day2") or {}).get("llm_referenced"),
        }
    if marker and marker.get("finding_id"):
        return evaluate_day2(knowledge, rag_agent, data_dir)
    return store_canary(knowledge, data_dir)
