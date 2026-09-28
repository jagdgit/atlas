"""OI-CHAT-INFER0 Stage 3 — compact scientist evidence packet.

Feeds decide-time / research LLM calls with bounded evidence context.
Deterministic controller still owns the decision; LLM is advice-only.

NOW #5 densifies via ``atlas.reasoning.cognitive_core`` /
``ReasoningService.reason_scientist`` (full scientist schema + UNREVIEWED on fail).
"""

from __future__ import annotations

from typing import Any

VERSION = "chat_infer0.scientist_packet.v1"


def build_scientist_packet(
    *,
    laboratory_id: str | None = None,
    decision_id: str | None = None,
    packet_summary: dict[str, Any] | None = None,
    evidence_ids: list[Any] | None = None,
    unknowns: list[Any] | None = None,
    experiences: list[Any] | None = None,
    wso_status: str | None = None,
    temporal_note: str | None = None,
) -> dict[str, Any]:
    """Stage 3 — knowledge + memory + temporal + WSO pointers into one packet."""
    summary = packet_summary if isinstance(packet_summary, dict) else {}
    evid = [str(x) for x in (evidence_ids or summary.get("evidence_ids") or []) if x]
    unk = [str(x) for x in (unknowns or summary.get("unknowns") or []) if x]
    exps = []
    for e in experiences or summary.get("experiences") or []:
        if isinstance(e, dict):
            exps.append(
                {
                    "id": e.get("id") or e.get("experience_id"),
                    "lesson": str(e.get("lesson") or e.get("title") or "")[:160],
                }
            )
        elif e:
            exps.append({"id": str(e), "lesson": ""})
    return {
        "version": VERSION,
        "kind": "SCIENTIST_PACKET",
        "laboratory_id": laboratory_id,
        "decision_id": decision_id or summary.get("decision_id"),
        "action": summary.get("action") or summary.get("decision"),
        "symbol": summary.get("symbol"),
        "evidence_ids": evid[:40],
        "unknowns": unk[:20],
        "experiences": exps[:8],
        "wso_status": wso_status or summary.get("wso_status"),
        "temporal_note": temporal_note
        or summary.get("temporal_note")
        or (
            "Use only cited evidence_ids. Missing published_at / fundamentals "
            "stay unknown_explicit — never invent PE/FCF/news."
        ),
        "honesty": (
            "Scientist packet — advice-only. Deterministic gates own allocation."
        ),
    }
