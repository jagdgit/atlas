"""OI-SELF-ID — Living RAG retrieval (Phase 4).

Not library-mode chunk RAG. Bundle for cognition / chat:

1. Identity + Goals
2. Beliefs (active worldview)
3. Experiences (prediction/outcome peers)
4. Knowledge documents / findings
5. Open questions / unknowns
6. Active goals (explicit)
"""

from __future__ import annotations

import logging
from typing import Any

VERSION = "self0.living_rag.v1"
_log = logging.getLogger("atlas.reasoning.retrieval")


def build_living_rag_bundle(
    reasoning: Any,
    query: str,
    *,
    experience_os: Any | None = None,
    knowledge: Any | None = None,
    memory: Any | None = None,
    belief_limit: int = 8,
    experience_limit: int = 5,
    knowledge_limit: int = 5,
    memory_limit: int = 5,
) -> dict[str, Any]:
    """Assemble the Living RAG six-pack. Instruments belief consultations."""
    q = (query or "").strip()
    identity = None
    goals: list[dict[str, Any]] = []
    beliefs: list[dict[str, Any]] = []
    experiences: list[dict[str, Any]] = []
    knowledge_hits: list[dict[str, Any]] = []
    memories: list[dict[str, Any]] = []
    open_questions: list[dict[str, Any]] = []

    if reasoning is not None:
        try:
            identity = reasoning.identity()
        except Exception:  # noqa: BLE001
            _log.debug("identity load failed", exc_info=True)
        try:
            goals = list(reasoning.goals_snapshot(limit=10) or [])
        except Exception:  # noqa: BLE001
            _log.debug("goals snapshot failed", exc_info=True)
        try:
            consulted = reasoning.consult(query=q or None, limit=belief_limit)
            beliefs = list(consulted.get("beliefs") or [])
            if not goals and consulted.get("goals"):
                goals = list(consulted.get("goals") or [])
        except Exception:  # noqa: BLE001
            _log.debug("belief consult failed", exc_info=True)
            try:
                beliefs = reasoning.list_beliefs(
                    statuses=["active", "weakened"], limit=belief_limit
                )
            except Exception:  # noqa: BLE001
                beliefs = []

        for b in beliefs:
            for oq in list(b.get("open_questions") or [])[:3]:
                open_questions.append(
                    {
                        "belief_id": b.get("id"),
                        "domain": b.get("domain"),
                        "question": oq,
                    }
                )

    if experience_os is not None and q:
        try:
            experiences = list(experience_os.recall(q, limit=experience_limit) or [])
        except Exception:  # noqa: BLE001
            _log.debug("experience recall failed", exc_info=True)

    if knowledge is not None and q:
        try:
            if hasattr(knowledge, "search"):
                raw = knowledge.search(q, limit=knowledge_limit)
                if isinstance(raw, dict):
                    knowledge_hits = list(raw.get("results") or raw.get("chunks") or [])
                elif isinstance(raw, list):
                    knowledge_hits = raw
            elif hasattr(knowledge, "ask"):
                # soft: skip full ask (would recurse); use find_documents if present
                pass
            if hasattr(knowledge, "list_documents") and not knowledge_hits:
                docs = knowledge.list_documents(limit=knowledge_limit) or []
                knowledge_hits = [
                    d if isinstance(d, dict) else {"title": str(d)} for d in docs[:knowledge_limit]
                ]
        except Exception:  # noqa: BLE001
            _log.debug("knowledge retrieve failed", exc_info=True)

    if memory is not None and q:
        try:
            recalled = memory.recall(q, limit=memory_limit) or []
            for item in recalled:
                if hasattr(item, "content"):
                    memories.append(
                        {
                            "id": getattr(item, "id", None),
                            "content": item.content,
                            "kind": getattr(item, "kind", None),
                        }
                    )
                elif isinstance(item, dict):
                    memories.append(item)
        except Exception:  # noqa: BLE001
            _log.debug("memory recall failed", exc_info=True)

    citations: list[dict[str, Any]] = []
    for b in beliefs:
        citations.append(
            {
                "type": "belief",
                "belief_id": str(b.get("id") or ""),
                "domain": b.get("domain"),
                "statement": (b.get("statement") or "")[:200],
                "confidence": b.get("effective_confidence", b.get("confidence")),
                "status": b.get("status"),
            }
        )
    for e in experiences:
        citations.append(
            {
                "type": "experience",
                "experience_id": str(e.get("id") or ""),
                "title": e.get("title"),
                "lesson": ((e.get("journal") or {}).get("lesson") if isinstance(e.get("journal"), dict) else e.get("lesson"))
                or "",
            }
        )

    return {
        "version": VERSION,
        "query": q,
        "identity": identity,
        "goals": goals,
        "beliefs": beliefs,
        "experiences": experiences,
        "knowledge": knowledge_hits[:knowledge_limit],
        "memories": memories,
        "open_questions": open_questions[:12],
        "citations": citations,
        "counts": {
            "beliefs": len(beliefs),
            "experiences": len(experiences),
            "knowledge": len(knowledge_hits[:knowledge_limit]),
            "memories": len(memories),
            "open_questions": len(open_questions[:12]),
            "goals": len(goals),
        },
    }


def format_bundle_context(bundle: dict[str, Any], *, max_chars: int = 3500) -> str:
    """Compact context block for the chat model (Identity → … → RAG)."""
    parts: list[str] = []
    identity = bundle.get("identity") if isinstance(bundle.get("identity"), dict) else {}
    if identity:
        parts.append("## Atlas Identity")
        parts.append(str(identity.get("statement") or "")[:600])
        nn = identity.get("non_negotiables") or []
        if nn:
            parts.append("Non-negotiables:")
            for item in nn[:6]:
                parts.append(f"- {item}")

    goals = bundle.get("goals") or []
    if goals:
        parts.append("## Active Goals")
        for g in goals[:6]:
            title = g.get("title") if isinstance(g, dict) else str(g)
            parts.append(f"- {title}")

    beliefs = bundle.get("beliefs") or []
    if beliefs:
        parts.append("## Active Beliefs (cite belief_id when using)")
        for b in beliefs[:8]:
            parts.append(
                f"- [{b.get('id')}] ({b.get('domain')}/{b.get('status')}, "
                f"conf={b.get('effective_confidence', b.get('confidence'))}) "
                f"{b.get('statement')}"
            )

    experiences = bundle.get("experiences") or []
    if experiences:
        parts.append("## Relevant Experiences (cite experience_id when using)")
        for e in experiences[:5]:
            j = e.get("journal") if isinstance(e.get("journal"), dict) else {}
            lesson = j.get("lesson") or e.get("lesson") or ""
            parts.append(
                f"- [{e.get('id')}] {e.get('title') or ''}: {str(lesson)[:180]}"
            )

    oqs = bundle.get("open_questions") or []
    if oqs:
        parts.append("## Open Questions / Unknowns")
        for o in oqs[:8]:
            parts.append(f"- ({o.get('belief_id')}) {o.get('question')}")

    memories = bundle.get("memories") or []
    if memories:
        parts.append("## Recent Memory")
        for m in memories[:4]:
            parts.append(f"- {m.get('content') or m}")

    knowledge = bundle.get("knowledge") or []
    if knowledge:
        parts.append("## Knowledge hits")
        for k in knowledge[:4]:
            if isinstance(k, dict):
                text = k.get("text") or k.get("title") or k.get("content") or str(k)
            else:
                text = str(k)
            parts.append(f"- {str(text)[:160]}")

    blob = "\n".join(parts)
    if len(blob) > max_chars:
        return blob[: max_chars - 20] + "\n…[truncated]"
    return blob
