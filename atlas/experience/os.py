"""Experience OS — Observation→…→Lesson journal (EX.1 / OI-MP1).

Platform façade over ``learning.experiences`` (via LearningService). Does **not**
invent a second store — Knowledge stays Knowledge; Memory stays Memory.

Mandatory journal shape for decision-bearing missions:

```
Observation → Reasoning → Decision → Outcome → Reflection → Lesson
```

Outcome without Lesson = history. Lesson without Improve = unused wisdom.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any

JOURNAL_STEPS = (
    "observation",
    "reasoning",
    "decision",
    "outcome",
    "reflection",
    "lesson",
)

SHAPE = [
    {
        "field": "observation",
        "role": "What was seen (indicators, events, facts)",
        "required": True,
    },
    {
        "field": "reasoning",
        "role": "Why the situation suggested an action",
        "required": False,
    },
    {
        "field": "decision",
        "role": "What was chosen (sim / recommend / hold)",
        "required": True,
    },
    {
        "field": "outcome",
        "role": "What happened after the decision",
        "required": True,
    },
    {
        "field": "reflection",
        "role": "Honest post-mortem of the outcome",
        "required": True,
    },
    {
        "field": "lesson",
        "role": "Reusable rule for future decisions",
        "required": True,
    },
]

_LABEL_RE = re.compile(
    r"^(Observation|Reasoning|Decision|Outcome|Reflection|Lesson)\s*:\s*(.*)$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass
class ExperienceJournal:
    """Structured Experience Journal entry (MP3 / MI10)."""

    title: str
    observation: str
    decision: str
    outcome: str
    reflection: str
    lesson: str
    reasoning: str = ""
    domain: str = "general"
    tags: list[str] = field(default_factory=list)
    recommendations: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> list[str]:
        """Return missing required field names (empty = ok)."""
        missing: list[str] = []
        for step in SHAPE:
            if not step["required"]:
                continue
            val = getattr(self, step["field"], None)
            if not str(val or "").strip():
                missing.append(str(step["field"]))
        return missing

    def to_store_payload(self) -> dict[str, Any]:
        """Map journal fields onto learning.experiences columns + payload."""
        problem_lines = [f"Observation: {self.observation.strip()}"]
        if self.reasoning.strip():
            problem_lines.append(f"Reasoning: {self.reasoning.strip()}")
        problem_lines.append(f"Decision: {self.decision.strip()}")
        problem_lines.append(f"Outcome: {self.outcome.strip()}")
        solution = f"Reflection: {self.reflection.strip()}"
        lessons = f"Lesson: {self.lesson.strip()}"
        tags = list(dict.fromkeys([*(self.tags or []), "experience_journal"]))
        journal = {
            "observation": self.observation.strip(),
            "reasoning": self.reasoning.strip(),
            "decision": self.decision.strip(),
            "outcome": self.outcome.strip(),
            "reflection": self.reflection.strip(),
            "lesson": self.lesson.strip(),
        }
        payload: dict[str, Any] = {
            "title": self.title.strip() or self.lesson.strip()[:80],
            "problem": "\n".join(problem_lines),
            "solution": solution,
            "lessons": lessons,
            "domain": self.domain or "general",
            "tags": tags,
            "journal": journal,
            "experience_os": True,
        }
        if self.recommendations:
            payload["recommendations"] = list(self.recommendations)
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
            src_ids = self.metadata.get("source_experience_ids")
            if src_ids:
                payload["source_experience_ids"] = list(src_ids)
        return payload


def parse_journal_text(*parts: str) -> dict[str, str]:
    """Extract labeled journal fields from free-form experience text."""
    blob = "\n".join(p for p in parts if p)
    found: dict[str, str] = {k: "" for k in JOURNAL_STEPS}
    if not blob.strip():
        return found
    matches = list(_LABEL_RE.finditer(blob))
    if not matches:
        return found
    for i, m in enumerate(matches):
        key = m.group(1).lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(blob)
        body = (m.group(2) + blob[start:end]).strip()
        if key in found:
            found[key] = body
    return found


def journal_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize a stored experience into a structured journal view."""
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    nested = payload.get("journal") if isinstance(payload.get("journal"), dict) else {}
    if nested.get("observation") or nested.get("lesson"):
        journal = {
            "observation": str(nested.get("observation") or ""),
            "reasoning": str(nested.get("reasoning") or ""),
            "decision": str(nested.get("decision") or ""),
            "outcome": str(nested.get("outcome") or ""),
            "reflection": str(nested.get("reflection") or ""),
            "lesson": str(nested.get("lesson") or ""),
        }
    else:
        journal = parse_journal_text(
            str(row.get("problem") or ""),
            str(row.get("solution") or ""),
            str(row.get("lessons") or ""),
        )
    return {
        "id": row.get("id"),
        "title": row.get("title"),
        "domain": row.get("domain"),
        "tags": list(row.get("tags") or []),
        "journal": journal,
        "complete": all(
            str(journal.get(s) or "").strip()
            for s in ("observation", "decision", "outcome", "reflection", "lesson")
        ),
        "raw": {
            "problem": row.get("problem"),
            "solution": row.get("solution"),
            "lessons": row.get("lessons"),
        },
    }


class ExperienceOS:
    """First-class Experience OS over LearningService (EX.1)."""

    name = "experience_os"
    VERSION = "ex.1"

    def __init__(
        self,
        learning: Any,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._learning = learning
        self._logger = logger or logging.getLogger("atlas.experience.os")

    def shape(self) -> dict[str, Any]:
        return {
            "steps": list(JOURNAL_STEPS),
            "fields": list(SHAPE),
            "rule": (
                "Observation→Reasoning→Decision→Outcome→Reflection→Lesson; "
                "Outcome without Lesson = history; Lesson unused without Improve"
            ),
            "store": "learning.experiences",
            "version": self.VERSION,
        }

    def journal(
        self,
        *,
        title: str,
        observation: str,
        decision: str,
        outcome: str,
        reflection: str,
        lesson: str,
        reasoning: str = "",
        domain: str = "general",
        tags: list[str] | None = None,
        recommendations: list[Any] | None = None,
        metadata: dict[str, Any] | None = None,
        strict: bool = True,
    ) -> dict[str, Any]:
        """Write a structured Experience Journal entry."""
        entry = ExperienceJournal(
            title=title,
            observation=observation,
            decision=decision,
            outcome=outcome,
            reflection=reflection,
            lesson=lesson,
            reasoning=reasoning,
            domain=domain,
            tags=list(tags or []),
            recommendations=list(recommendations or []),
            metadata=dict(metadata or {}),
        )
        missing = entry.validate()
        if missing and strict:
            return {
                "ok": False,
                "error": "incomplete_journal",
                "missing": missing,
                "shape": self.shape(),
            }
        if self._learning is None:
            return {"ok": False, "error": "learning_unavailable"}
        payload = entry.to_store_payload()
        try:
            result = self._learning.remember_experience(**payload)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("journal write failed: %s", exc)
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "journal": entry.as_dict(),
            "result": result if isinstance(result, dict) else {"applied": True},
            "version": self.VERSION,
        }

    def recall(self, query: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        if self._learning is None:
            return []
        rows = self._learning.recall(query, limit=limit) if query.strip() else (
            self._learning.list_experiences(limit=limit or 50)
        )
        return [journal_from_row(r if isinstance(r, dict) else {}) for r in (rows or [])]

    def advice_for(self, query: str, *, limit: int | None = None) -> dict[str, Any]:
        if self._learning is None:
            return {"query": query, "count": 0, "advice": "", "journals": [], "mutating": False}
        base = self._learning.advice_for(query, limit=limit)
        journals = self.recall(query, limit=limit)
        out = dict(base) if isinstance(base, dict) else {}
        out["journals"] = journals
        out["experience_os"] = self.VERSION
        return out

    def list_journals(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if self._learning is None:
            return []
        rows = self._learning.list_experiences(limit=limit) or []
        return [journal_from_row(r if isinstance(r, dict) else {}) for r in rows]
