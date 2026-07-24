"""Mission Context API — shared “everything relevant to X” gather (MCA.1 / V7).

Platform service: Knowledge + Verification signals + Graph + World Models +
Experience advice. Missions consume this instead of importing extractors.
"""

from __future__ import annotations

import logging
from typing import Any


class MissionContextService:
    """Gather structured context for a topic across OS layers."""

    name = "mission_context"
    VERSION = "mca.1"

    def __init__(
        self,
        *,
        knowledge: Any | None = None,
        world_models: Any | None = None,
        knowledge_graph: Any | None = None,
        learning: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._knowledge = knowledge
        self._world_models = world_models
        self._knowledge_graph = knowledge_graph
        self._learning = learning
        self._logger = logger or logging.getLogger("atlas.missions.context")

    def gather(
        self,
        topic: str,
        *,
        program_id: str | None = None,
        limit: int = 12,
        include_experience: bool = True,
        include_world: bool = True,
        include_graph: bool = True,
        include_knowledge: bool = True,
    ) -> dict[str, Any]:
        """Return items + a compact citation summary for Decision / Mission loops."""
        topic = (topic or "").strip()
        items: list[dict[str, Any]] = []
        sources_used: list[str] = []

        if include_world and self._world_models is not None and (topic or program_id):
            try:
                wm_limit = max(2, min(8, limit // 2 or 2))
                rows = self._world_models.context_for(
                    topic, program_id=program_id, limit=wm_limit
                )
                if rows:
                    sources_used.append("world_models")
                items.extend(rows)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("world_models context skipped: %s", exc)

        if include_graph and self._knowledge_graph is not None and topic:
            try:
                g_limit = max(2, min(6, limit // 3 or 2))
                rows = self._knowledge_graph.context_nodes(topic, limit=g_limit)
                if rows:
                    sources_used.append("knowledge_graph")
                items.extend(rows)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("knowledge_graph context skipped: %s", exc)

        if include_knowledge and self._knowledge is not None and topic:
            retrieve = getattr(self._knowledge, "retrieve", None)
            if callable(retrieve):
                try:
                    ranked = retrieve(topic, k=max(1, limit // 2))
                    got = False
                    for r in ranked or []:
                        content = getattr(r, "content", None)
                        if content is None and isinstance(r, dict):
                            content = r.get("content")
                        score = getattr(r, "similarity", None)
                        if score is None and isinstance(r, dict):
                            score = r.get("similarity")
                        items.append(
                            {
                                "item_kind": "chunk",
                                "kind": "chunk",
                                "content": content,
                                "score": score,
                            }
                        )
                        got = True
                    if got:
                        sources_used.append("knowledge_retrieve")
                except Exception as exc:  # noqa: BLE001
                    self._logger.debug("knowledge retrieve skipped: %s", exc)
            if len(items) < limit:
                try:
                    findings = self._knowledge.list_findings(
                        limit=max(limit * 3, 30)
                    )
                    needle = topic.lower()
                    found = False
                    for f in findings or []:
                        stmt = str(f.get("statement") or "")
                        if needle not in stmt.lower():
                            continue
                        trust = None
                        quality = f.get("quality") if isinstance(f.get("quality"), dict) else {}
                        if quality:
                            trust = quality.get("trust") or quality.get("confidence_label")
                        items.append(
                            {
                                "item_kind": "finding",
                                "kind": "finding",
                                "id": str(f.get("id") or ""),
                                "statement": stmt,
                                "claim_type": f.get("claim_type"),
                                "domain": f.get("domain"),
                                "trust": trust,
                                "status": f.get("status"),
                            }
                        )
                        found = True
                        if len(items) >= limit:
                            break
                    if found and "knowledge_findings" not in sources_used:
                        sources_used.append("knowledge_findings")
                except Exception as exc:  # noqa: BLE001
                    self._logger.debug("knowledge findings skipped: %s", exc)

        experience_block: dict[str, Any] | None = None
        if include_experience and self._learning is not None and topic:
            try:
                advice = self._learning.advice_for(topic, limit=3)
                text = str((advice or {}).get("advice") or "").strip()
                if text:
                    experience_block = {
                        "item_kind": "experience_advice",
                        "kind": "experience_advice",
                        "advice": text[:800],
                        "count": int((advice or {}).get("count") or 0),
                    }
                    items.append(experience_block)
                    sources_used.append("experience")
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("experience advice skipped: %s", exc)

        clipped = items[:limit]
        citations = _citations(clipped)
        summary = _summary_line(topic, clipped, sources_used)
        return {
            "topic": topic,
            "program_id": program_id,
            "items": clipped,
            "count": len(clipped),
            "sources": sources_used,
            "citations": citations,
            "summary": summary,
            "spike": False,
            "note": (
                "Mission Context API (MCA.1): Knowledge + Graph + World Models + Experience"
            ),
            "version": self.VERSION,
        }


def _citations(items: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for it in items:
        kind = str(it.get("item_kind") or it.get("kind") or "item")
        if kind == "world_fact":
            refs.append(f"wm:{it.get('id') or it.get('label')}")
        elif kind == "graph_node":
            refs.append(f"kg:{it.get('id') or it.get('label')}")
        elif kind == "finding":
            refs.append(f"finding:{it.get('id') or (it.get('statement') or '')[:40]}")
        elif kind == "chunk":
            refs.append("chunk")
        elif kind == "experience_advice":
            refs.append("experience:advice")
        else:
            refs.append(kind)
        if len(refs) >= 12:
            break
    return refs


def _summary_line(
    topic: str, items: list[dict[str, Any]], sources: list[str]
) -> str:
    if not items:
        return f"No Mission Context for {topic!r}" if topic else "No Mission Context"
    bits: list[str] = []
    for it in items[:4]:
        kind = str(it.get("item_kind") or it.get("kind") or "")
        if kind == "world_fact":
            bits.append(f"WM {it.get('label') or it.get('id')}")
        elif kind == "graph_node":
            bits.append(f"KG {it.get('label') or it.get('id')}")
        elif kind == "finding":
            bits.append((it.get("statement") or "")[:60])
        elif kind == "experience_advice":
            bits.append((it.get("advice") or "")[:60])
        elif kind == "chunk":
            bits.append(str(it.get("content") or "")[:60])
    joined = "; ".join(b for b in bits if b)
    src = ",".join(sources) if sources else "none"
    return f"context[{src}]: {joined}"[:400]
