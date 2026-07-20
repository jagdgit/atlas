"""ResearchDecisionRule — "what to read next" for the Research Watcher (Phase D · §D.7, BB-D2).

One engine, many missions: this rule scores candidate sources the worker gathered from a
:meth:`~atlas.research.service.ResearchService.research` pass (recommendations + gaps) into
deterministic ``read_next`` / ``hold`` options. The Decision Engine then folds in **policy
influence** (e.g. ``prefer ieee`` / ``avoid paywall`` — DD5) and journals the P9 record.

Pure + deterministic (Q7): no LLM in the choice, no persistence, no call into ResearchService
(that stays in the worker — ``IntelligenceContext.research`` is intentionally unused here).
Recommend-only (P14/DD3): every option is ``side_effecting = False``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from atlas.decision.contracts import DecisionRequest, ScoredOption

if TYPE_CHECKING:
    from atlas.decision.context import IntelligenceContext

MISSION_TYPE_RESEARCH = "research"

_HOLD_SCORE = 0.3
_BASE_READ_SCORE = 1.0
# Evidence-level bump (Source.evidence_level is typically 0–4-ish) keeps peer/gov ahead of web.
_LEVEL_WEIGHT = 0.25
_GAP_FIT_BONUS = 0.5


class ResearchDecisionRule:
    """Deterministic ranking of research candidates → read_next / hold."""

    mission_type = MISSION_TYPE_RESEARCH
    VERSION = "1.0.0"

    def score(
        self, request: DecisionRequest, context: "IntelligenceContext"
    ) -> list[ScoredOption]:
        ctx = request.context or {}
        candidates = list(ctx.get("candidates") or [])
        objective = str(ctx.get("objective") or "").strip()

        # Hold is policy-neutral (no topic/venue tags) so prefer/avoid can arbitrate the reads.
        hold = ScoredOption(
            key="hold",
            score=_HOLD_SCORE,
            text="hold — no further reading this cycle",
            tags=("hold",),
            rationale="no candidate worth prioritizing this cycle",
            payload={"kind": "hold", "objective": objective},
        )
        if not candidates:
            if not objective:
                return []  # nothing configured → engine holds without a rule option set
            hold.rationale = "research produced no further-reading candidates"
            return [hold]

        options: list[ScoredOption] = [hold]
        for cand in candidates:
            opt = self._score_candidate(cand, objective=objective)
            if opt is not None:
                options.append(opt)
        return options

    def _score_candidate(
        self, cand: dict[str, Any], *, objective: str
    ) -> ScoredOption | None:
        cid = str(cand.get("id") or cand.get("url") or "").strip()
        if not cid:
            return None
        title = str(cand.get("title") or cid)
        level = _as_float(cand.get("evidence_level"), default=0.0) or 0.0
        kind = str(cand.get("kind") or "source").lower()
        why = str(cand.get("why") or "additional independent source")
        # Gap-fit signals from recommend_reading ("Could fill the peer-reviewed gap.") etc.
        why_l = why.lower()
        gap_bonus = 0.0
        if "peer-reviewed" in why_l or "peer reviewed" in why_l:
            gap_bonus += _GAP_FIT_BONUS
        if "government" in why_l or "lab" in why_l:
            gap_bonus += _GAP_FIT_BONUS

        score = _BASE_READ_SCORE + _LEVEL_WEIGHT * level + gap_bonus
        # Tags: venue/kind tokens so policy prefer/avoid can bite (DD5). Hold stays untagged.
        tags = ["read", "research", kind]
        for token in _tokenize(title) | _tokenize(str(cand.get("url") or "")):
            if len(token) >= 3:
                tags.append(token)

        return ScoredOption(
            key=f"read:{cid}",
            score=score,
            text=f"read next: {title}",
            tags=tuple(dict.fromkeys(tags)),  # stable unique
            rationale=why,
            evidence_refs=[cand.get("url") or cid],
            payload={
                "kind": "read_next",
                "objective": objective,
                "source": {
                    "id": cid,
                    "title": title,
                    "url": cand.get("url"),
                    "evidence_level": level,
                    "kind": kind,
                    "why": why,
                },
            },
        )


def _as_float(value: Any, *, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _tokenize(text: str) -> set[str]:
    import re
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))
