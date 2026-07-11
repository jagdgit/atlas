"""Scientific-review report generator (§5a.5).

Pure, deterministic assembly of the report structure from *verified* claim dicts (the
shape ``Claim.as_dict`` produces) + source dicts; an optional LLM (summarizer role)
only polishes prose sections (executive summary, methodology, limitations, next
research). No LLM ⇒ sensible deterministic text, so a report is always producible.

Overall confidence is derived from the claims, never guessed: it is the **most common**
claim confidence, tie-broken toward the *more conservative* level — a report is only as
strong as the body of claims behind it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.evidence.models import (
    CONFIDENCE_HIGH,
    CONFIDENCE_INSUFFICIENT,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_UNVERIFIED,
    level_name,
)

if TYPE_CHECKING:
    from atlas.llm.service import LLMService

REPORT_SECTIONS = [
    "executive_summary",
    "answer",
    "confidence",
    "methodology",
    "evidence",
    "references",
    "conflicting_views",
    "limitations",
    "next_research",
]

# Most → least conservative (for overall-confidence tie-breaking and ordering).
_CONF_ORDER = [
    CONFIDENCE_INSUFFICIENT,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_HIGH,
]

_METHODOLOGY = (
    "Each claim was assessed by the Verification Engine: sources were graded by "
    "quality (L1 forum → L5 measured field data), numeric estimates were tested for "
    "convergence (agreement, not count), and a confidence was calculated from evidence "
    "quality, convergence, and any contradictions. The stopping rule is convergence, "
    "governed by a per-job Evidence Budget."
)

_SUMMARY_SYSTEM = (
    "You are Atlas, writing the prose sections of an evidence-backed research report. "
    "Be precise and non-committal beyond the evidence. Never invent sources or numbers; "
    "use only the claims and confidences provided."
)


class ReportGenerator:
    def __init__(
        self, llm: "LLMService | None" = None, logger: logging.Logger | None = None
    ) -> None:
        self._llm = llm
        self._logger = logger or logging.getLogger("atlas.reports")

    def generate(
        self,
        objective: str,
        *,
        claims: list[dict[str, Any]] | None = None,
        sources: list[dict[str, Any]] | None = None,
        answer: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        claims = list(claims or [])
        sources = list(sources or [])
        overall, distribution = self._overall_confidence(claims)
        conflicting = self._conflicting(claims)
        references = self._references(claims, sources)

        sections: dict[str, Any] = {
            "answer": answer.strip() or self._answer(claims),
            "confidence": {"overall": overall, "distribution": distribution},
            "methodology": _METHODOLOGY,
            "evidence": [self._evidence_row(c) for c in claims],
            "references": references,
            "conflicting_views": conflicting,
            "limitations": self._limitations(claims, conflicting),
            "next_research": self._next_research(claims),
        }
        sections["executive_summary"] = self._executive_summary(
            objective, sections, overall, notes
        )
        # Optional LLM polish of the free-text sections (best-effort).
        self._polish(objective, sections, claims, notes)

        report = {
            "objective": objective,
            "overall_confidence": overall,
            "sections": sections,
        }
        report["markdown"] = self._render_markdown(objective, sections, overall)
        return report

    # --- confidence -----------------------------------------------------
    @staticmethod
    def _overall_confidence(claims: list[dict[str, Any]]) -> tuple[str, dict[str, int]]:
        dist: dict[str, int] = {}
        for c in claims:
            conf = c.get("confidence", CONFIDENCE_UNVERIFIED)
            dist[conf] = dist.get(conf, 0) + 1
        graded = {k: v for k, v in dist.items() if k in _CONF_ORDER}
        if not graded:
            return CONFIDENCE_INSUFFICIENT, dist
        # Most common; ties → the more conservative (lower in _CONF_ORDER).
        best = max(graded, key=lambda k: (graded[k], -_CONF_ORDER.index(k)))
        return best, dist

    # --- section builders ----------------------------------------------
    @staticmethod
    def _answer(claims: list[dict[str, Any]]) -> str:
        if not claims:
            return "No verifiable claims were established for this objective."
        lines = []
        for c in claims:
            lines.append(f"- {c.get('statement', '').strip()} [{c.get('confidence')}]")
        return "\n".join(lines)

    @staticmethod
    def _evidence_row(claim: dict[str, Any]) -> dict[str, Any]:
        return {
            "statement": claim.get("statement", ""),
            "value": claim.get("value"),
            "confidence": claim.get("confidence"),
            "convergence": claim.get("convergence"),
            "verification_method": claim.get("verification_method", ""),
            "supporting": len(claim.get("supporting_sources", [])),
            "contradicting": len(claim.get("contradicting_sources", [])),
            "reasoning_trace": claim.get("reasoning_trace", []),
        }

    @staticmethod
    def _references(
        claims: list[dict[str, Any]], sources: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        refs: dict[str, dict[str, Any]] = {}
        for s in sources:
            sid = str(s.get("id", ""))
            if sid:
                refs[sid] = {
                    "id": sid,
                    "title": s.get("title", ""),
                    "url": s.get("url", ""),
                    "level": s.get("evidence_level"),
                    "level_name": s.get("level_name")
                    or (level_name(s["evidence_level"]) if s.get("evidence_level") else ""),
                }
        # Surface source ids referenced by claims even if not in the sources list.
        for c in claims:
            for e in c.get("supporting_sources", []) + c.get("contradicting_sources", []):
                sid = str(e.get("source_id", ""))
                if sid and sid not in refs:
                    refs[sid] = {
                        "id": sid, "title": "", "url": "",
                        "level": e.get("evidence_level"),
                        "level_name": e.get("level_name", ""),
                    }
        return sorted(refs.values(), key=lambda r: (-(r["level"] or 0), r["id"]))

    @staticmethod
    def _conflicting(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for c in claims:
            contra = c.get("contradicting_sources", [])
            low = c.get("confidence") in {CONFIDENCE_LOW, CONFIDENCE_INSUFFICIENT}
            if contra or low:
                out.append(
                    {
                        "statement": c.get("statement", ""),
                        "confidence": c.get("confidence"),
                        "contradicting": len(contra),
                        "note": (
                            "contradicting sources present"
                            if contra
                            else "weak/insufficient evidence"
                        ),
                    }
                )
        return out

    @staticmethod
    def _limitations(
        claims: list[dict[str, Any]], conflicting: list[dict[str, Any]]
    ) -> str:
        parts = []
        if not claims:
            parts.append("No claims were verified; findings are provisional.")
        weak = [c for c in claims if c.get("confidence") in {CONFIDENCE_LOW, CONFIDENCE_INSUFFICIENT}]
        if weak:
            parts.append(
                f"{len(weak)} of {len(claims)} claim(s) rest on weak or insufficient "
                "evidence."
            )
        if conflicting:
            parts.append(f"{len(conflicting)} claim(s) have unresolved conflicts.")
        if not parts:
            parts.append(
                "Evidence converged for the assessed claims; residual uncertainty is "
                "bounded by source coverage."
            )
        return " ".join(parts)

    @staticmethod
    def _next_research(claims: list[dict[str, Any]]) -> str:
        gaps = [
            c.get("statement", "")
            for c in claims
            if c.get("confidence") in {CONFIDENCE_LOW, CONFIDENCE_INSUFFICIENT}
            or (c.get("convergence") is not None and c["convergence"] < 0.9)
        ]
        if not gaps:
            return "No further research required for the current objective."
        head = "; ".join(g for g in gaps[:3] if g)
        return f"Gather stronger/converging sources for: {head}."

    def _executive_summary(
        self, objective: str, sections: dict[str, Any], overall: str, notes: str
    ) -> str:
        n = len(sections["evidence"])
        conflicts = len(sections["conflicting_views"])
        base = (
            f"Objective: {objective.strip()}. {n} claim(s) assessed; overall "
            f"confidence {overall}."
        )
        if conflicts:
            base += f" {conflicts} claim(s) show conflicting or weak evidence."
        return base

    # --- optional LLM polish -------------------------------------------
    def _polish(
        self,
        objective: str,
        sections: dict[str, Any],
        claims: list[dict[str, Any]],
        notes: str,
    ) -> None:
        if self._llm is None:
            return
        facts = self._facts_block(objective, sections, claims, notes)
        try:
            prose = self._llm.for_role("summarizer").chat(
                [
                    _msg("system", _SUMMARY_SYSTEM),
                    _msg(
                        "user",
                        "Write a 2-4 sentence executive summary grounded ONLY in these "
                        f"facts. Do not add sources or numbers.\n\n{facts}",
                    ),
                ]
            ).text.strip()
            if prose:
                sections["executive_summary"] = prose
        except Exception:  # noqa: BLE001 - polish is best-effort; keep deterministic text
            self._logger.debug("report LLM polish failed; using deterministic summary")

    @staticmethod
    def _facts_block(
        objective: str, sections: dict[str, Any], claims: list[dict[str, Any]], notes: str
    ) -> str:
        lines = [f"Objective: {objective}", f"Overall confidence: {sections['confidence']['overall']}"]
        for c in claims:
            lines.append(f"- {c.get('statement')} [{c.get('confidence')}]")
        if notes:
            lines.append(f"Notes: {notes[:800]}")
        return "\n".join(lines)

    # --- markdown render -----------------------------------------------
    def _render_markdown(
        self, objective: str, sections: dict[str, Any], overall: str
    ) -> str:
        lines = [f"# Research Report: {objective.strip()}", ""]
        lines += ["## Executive Summary", sections["executive_summary"], ""]
        lines += ["## Answer", sections["answer"], ""]
        dist = ", ".join(f"{k}: {v}" for k, v in sections["confidence"]["distribution"].items())
        lines += ["## Confidence", f"Overall: **{overall}**" + (f" ({dist})" if dist else ""), ""]
        lines += ["## Methodology", sections["methodology"], ""]

        lines.append("## Evidence")
        if sections["evidence"]:
            for e in sections["evidence"]:
                val = e["value"]
                val_str = (
                    f" — value {val['number']}{val.get('unit', '')}" if isinstance(val, dict) else ""
                )
                conv = e["convergence"]
                conv_str = f", convergence {conv:.0%}" if isinstance(conv, (int, float)) else ""
                lines.append(
                    f"- **{e['statement']}** [{e['confidence']}]{val_str} "
                    f"({e['supporting']} supporting, {e['contradicting']} contradicting"
                    f"{conv_str})"
                )
        else:
            lines.append("_No verified claims._")
        lines.append("")

        lines.append("## References")
        if sections["references"]:
            for i, r in enumerate(sections["references"], start=1):
                label = r["title"] or r["url"] or r["id"]
                lvl = f" [{r['level_name']}]" if r.get("level_name") else ""
                url = f" — {r['url']}" if r.get("url") else ""
                lines.append(f"{i}. {label}{lvl}{url}")
        else:
            lines.append("_No sources cited._")
        lines.append("")

        lines.append("## Conflicting Views")
        if sections["conflicting_views"]:
            for c in sections["conflicting_views"]:
                lines.append(f"- {c['statement']} [{c['confidence']}] — {c['note']}")
        else:
            lines.append("_No conflicts detected._")
        lines.append("")

        lines += ["## Limitations", sections["limitations"], ""]
        lines += ["## Next Research", sections["next_research"], ""]
        return "\n".join(lines).strip() + "\n"


def _msg(role: str, content: str):
    from atlas.llm.provider import ChatMessage

    return ChatMessage(role, content)
