"""OI-SELF-ID — Identity-first chat answers (Phase 4).

You → Atlas identity → Beliefs → Experiences → Memory → Knowledge → model.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from atlas.reasoning.retrieval import build_living_rag_bundle, format_bundle_context

VERSION = "self0.identity_chat.v1"
_log = logging.getLogger("atlas.reasoning.identity_chat")

_WHY_RE = re.compile(
    r"\b("
    r"why\s+do\s+you\s+believe|"
    r"why\s+believe|"
    r"why\s+are\s+you\s+believing|"
    r"what\s+do\s+you\s+believe|"
    r"explain\s+your\s+belief|"
    r"your\s+beliefs?\s+about|"
    r"active\s+beliefs?"
    r")\b",
    re.I,
)
_TIMEOUT_MARKERS = (
    "chat llm timed out",
    "ollama busy",
    "model is busy",
    "timed out",
)
_MIND_RE = re.compile(
    r"\b(what\s+changed\s+your\s+mind|why\s+did\s+you\s+change|"
    r"mind[\s-]?change|when\s+did\s+you\s+revise)\b",
    re.I,
)

_ATLAS_SYSTEM = (
    "You are Atlas — a durable identity with goals and a revisable belief worldview. "
    "You are not a generic chatbot. Answer as Atlas using the Living RAG context. "
    "Rules:\n"
    "1. Prefer Atlas beliefs, experiences, goals, and identity over generic world knowledge.\n"
    "2. When you rely on a belief, cite its belief_id in parentheses, e.g. (belief:UUID).\n"
    "3. When you rely on an experience, cite experience_id, e.g. (experience:ID).\n"
    "4. If context is thin, say what you don't know (open questions) — never invent evidence.\n"
    "5. Keep answers concise. Influence is advice-only; do not claim you changed trading gates.\n"
    "6. Models are replaceable CPUs; you remain Atlas."
)


def detect_belief_benchmark(query: str) -> str | None:
    """Return 'why' | 'mind_change' | None."""
    q = (query or "").strip()
    if not q:
        return None
    if _MIND_RE.search(q):
        return "mind_change"
    if _WHY_RE.search(q):
        return "why"
    return None


def extract_topic(query: str) -> str:
    """Best-effort topic after 'believe …' / 'about …'; keep trailing UUIDs."""
    q = (query or "").strip()
    # Bare / trailing UUID → use as belief id lookup
    uuid_m = re.search(
        r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
        q,
    )
    if uuid_m and not re.search(r"\bbelieve\b", q, re.I):
        return uuid_m.group(1)
    for pat in (
        r"believe\s+(?:about\s+)?(.+)$",
        r"beliefs?\s+about\s+(.+)$",
        r"changed\s+your\s+mind\s+(?:about\s+)?(.+)$",
        r"mind\s+about\s+(.+)$",
    ):
        m = re.search(pat, q, re.I)
        if m:
            return m.group(1).strip(" ?.!")
    return q


def answer_belief_benchmark(reasoning: Any, query: str) -> dict[str, Any] | None:
    kind = detect_belief_benchmark(query)
    if kind is None or reasoning is None:
        return None
    topic = extract_topic(query)
    if kind == "mind_change":
        out = reasoning.what_changed_your_mind(topic)
    else:
        out = reasoning.why(topic)
    if not out.get("ok"):
        # Broad list for "what are your active beliefs about X"
        consulted = reasoning.consult(query=topic, limit=8)
        beliefs = consulted.get("beliefs") or []
        if not beliefs:
            return {
                "ok": False,
                "kind": kind,
                "answer": (
                    f"I don't have an active belief matching {topic!r} yet. "
                    "Nothing invented — seed or reflection may add candidates later."
                ),
                "citations": [],
                "bundle_counts": consulted.get("count"),
            }
        lines = [f"Active beliefs related to {topic!r}:"]
        citations = []
        for b in beliefs:
            lines.append(
                f"- ({b.get('id')}) [{b.get('domain')}] {b.get('statement')} "
                f"(conf={b.get('effective_confidence', b.get('confidence'))})"
            )
            citations.append(
                {
                    "type": "belief",
                    "belief_id": str(b.get("id") or ""),
                    "statement": b.get("statement"),
                }
            )
        return {
            "ok": True,
            "kind": "list",
            "answer": "\n".join(lines),
            "citations": citations,
        }
    citations = [
        {
            "type": "belief",
            "belief_id": str((out.get("belief") or {}).get("id") or ""),
            "statement": (out.get("belief") or {}).get("statement"),
        }
    ]
    return {
        "ok": True,
        "kind": kind,
        "answer": out.get("answer") or "",
        "citations": citations,
        "raw": out,
    }


def _bundle_grounded_answer(bundle: dict[str, Any], *, note: str = "") -> str:
    """Deterministic Living RAG reply when the chat model is unavailable."""
    lines: list[str] = []
    if note:
        lines.append(note)
        lines.append("")
    identity = bundle.get("identity")
    if isinstance(identity, dict) and identity.get("mission"):
        lines.append(f"Identity: {identity.get('mission')}")
    beliefs = list(bundle.get("beliefs") or [])
    if beliefs:
        lines.append("Relevant active beliefs (Belief Core — no free-form LLM):")
        for b in beliefs[:5]:
            lines.append(
                f"- (belief:{b.get('id')}) [{b.get('domain')}] {b.get('statement')} "
                f"(conf={b.get('effective_confidence', b.get('confidence'))})"
            )
    else:
        lines.append(
            "No matching active beliefs yet. Ask “why do you believe <topic>” "
            "after seed/reflection, or try a status phrase that reads the DB."
        )
    goals = list(bundle.get("goals") or [])
    if goals:
        lines.append("Goals:")
        for g in goals[:3]:
            lines.append(f"- {g.get('statement') or g.get('title') or g}")
    return "\n".join(lines).strip()


def _looks_like_timeout(text: str) -> bool:
    low = (text or "").strip().lower()
    return any(m in low for m in _TIMEOUT_MARKERS)


def answer_as_atlas(
    reasoning: Any,
    query: str,
    *,
    compose_fn: Any | None = None,
    experience_os: Any | None = None,
    knowledge: Any | None = None,
    memory: Any | None = None,
    context: Any | None = None,
    timeout: float | None = None,
    fallback: str = "",
    allow_llm: bool = True,
) -> dict[str, Any]:
    """Full identity-first answer path.

    ``compose_fn(system, user, context=, fallback=, timeout=) -> str``
    matches ResponseBuilder.compose. Belief benchmarks never call it.
    """
    # Benchmarks first (deterministic, citeable — never touches Ollama)
    bench = answer_belief_benchmark(reasoning, query)
    if bench is not None:
        return {
            "version": VERSION,
            "mode": "benchmark",
            **bench,
        }

    bundle = build_living_rag_bundle(
        reasoning,
        query,
        experience_os=experience_os,
        knowledge=knowledge,
        memory=memory,
    )
    grounded = _bundle_grounded_answer(
        bundle,
        note=(
            "Chat model unavailable — answering from Atlas Belief Core / Living RAG."
        ),
    )

    if not allow_llm or compose_fn is None:
        return {
            "version": VERSION,
            "mode": "living_rag_deterministic",
            "ok": True,
            "answer": grounded,
            "citations": bundle.get("citations") or [],
            "bundle_counts": bundle.get("counts") or {},
            "identity_version": (bundle.get("identity") or {}).get("version")
            if isinstance(bundle.get("identity"), dict)
            else None,
        }

    ctx_block = format_bundle_context(bundle)
    system = _ATLAS_SYSTEM
    user = (
        f"Living RAG context:\n{ctx_block}\n\n"
        f"User message:\n{query}\n\n"
        "Answer as Atlas. Cite belief_id / experience_id when you use them."
    )
    try:
        text = compose_fn(
            system,
            user,
            context=context,
            fallback=fallback or grounded,
            timeout=timeout,
        )
    except Exception:  # noqa: BLE001
        _log.exception("identity chat compose failed")
        text = fallback or grounded

    answer = (text or "").strip()
    if not answer or _looks_like_timeout(answer):
        answer = grounded
    elif bundle.get("beliefs") and "belief:" not in answer.lower() and "(belief" not in answer.lower():
        top = bundle["beliefs"][0]
        answer = (
            f"{answer}\n\n"
            f"— related belief ({top.get('id')}): {top.get('statement')}"
        ).strip()

    return {
        "version": VERSION,
        "mode": "living_rag",
        "ok": True,
        "answer": answer,
        "citations": bundle.get("citations") or [],
        "bundle_counts": bundle.get("counts") or {},
        "identity_version": (bundle.get("identity") or {}).get("version")
        if isinstance(bundle.get("identity"), dict)
        else None,
    }
