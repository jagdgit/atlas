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
    CLAIM_TYPE_PARAMETER,
    CONFIDENCE_HIGH,
    CONFIDENCE_INSUFFICIENT,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_NOT_APPLICABLE,
    CONFIDENCE_UNVERIFIED,
    HEADLINE_CLAIM_TYPES,
    level_name,
)

if TYPE_CHECKING:
    from atlas.llm.service import LLMService

REPORT_SECTIONS = [
    "executive_summary",
    "answer",
    "confidence",
    "methodology",
    "funnel",
    "pipeline_trace",
    "evidence",
    "parameters",
    "references",
    "conflicting_views",
    "weakly_supported",
    "patterns",
    "opportunities",
    "hypotheses",
    "limitations",
    "next_research",
]

# Authoritative acquisition/extraction funnel: (pipeline key, display label).
# Rendered deterministically so report counts can never disagree with the run.
_FUNNEL_ROWS = [
    ("found", "Sources found"),
    ("acquired", "Documents acquired"),
    ("read", "Successfully read"),
    ("reader_failures", "Reader failures"),
    ("paywalled", "Paywalled / blocked"),
    ("extract_ok", "Produced ≥1 claim"),
    ("extract_failed", "Read but no claims"),
    ("extracted", "Claims extracted"),
    ("numeric_claims", "— numeric"),
    ("prose_claims", "— qualitative (prose)"),
    ("inferred_claims", "— Atlas-inferred"),
    ("claims", "Distinct claims"),
    ("verified", "Verified claims"),
    ("findings", "Findings"),
    ("patterns", "Patterns"),
    ("contradictions", "Contradictions"),
    ("hypotheses", "Hypotheses"),
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

_METHODOLOGY_ACQUIRE_STOP = (
    "Pipeline terminated during acquisition. Verification was not executed. "
    "No Evidence Budget or convergence assessment was performed because no documents "
    "were read."
)

_METHODOLOGY_ACQUIRE_WAITING = (
    "Pipeline terminated during acquisition (waiting for operator). "
    "Verification was not executed. No Evidence Budget or convergence assessment "
    "was performed because no media was acquired."
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
        findings: list[dict[str, Any]] | None = None,
        sources: list[dict[str, Any]] | None = None,
        answer: str = "",
        notes: str = "",
        reasoning: dict[str, Any] | None = None,
        pipeline: dict[str, Any] | None = None,
        termination: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Prefer findings when present (A3B.9); fall back to claims.
        body = list(findings) if findings else list(claims or [])
        sources = list(sources or [])
        reasoning = dict(reasoning or {})
        termination = dict(termination or {})
        acquire_stop = (
            str(termination.get("stage") or "") == "acquire"
            and not body
        )

        if acquire_stop:
            term_status = str(termination.get("status") or "blocked")
            term_reason = (
                termination.get("reason")
                or termination.get("reason_code")
                or "unknown"
            )
            overall = CONFIDENCE_NOT_APPLICABLE
            distribution: dict[str, int] = {}
            confidence_block: dict[str, Any] = {
                "overall": overall,
                "distribution": distribution,
                "stage": "acquire",
                "status": term_status,
                "reason": term_reason,
                "reason_code": termination.get("reason_code") or term_reason,
                "result": (
                    "waiting"
                    if term_status == "waiting"
                    else "acquisition_failed"
                ),
                "knowledge_produced": int(termination.get("knowledge_produced") or 0),
                "reasoning": termination.get("reasoning") or "not_started",
                "verification": termination.get("verification") or "not_executed",
                "waiting_for": termination.get("waiting_for"),
            }
            methodology = (
                _METHODOLOGY_ACQUIRE_WAITING
                if term_status == "waiting"
                else _METHODOLOGY_ACQUIRE_STOP
            )
            from atlas.transcripts.acquisition import format_next_action

            audience = str(termination.get("audience") or "research")
            next_research = format_next_action(
                termination.get("suggested_next_strategies") or (),
                speech_status=termination.get("speech_to_text_status"),
                audience=audience,
                status=term_status,
            )
            if term_status == "waiting":
                default_answer = (
                    "Interactive recovery required — no media was acquired, so "
                    "reasoning and verification did not start. No knowledge was fabricated."
                )
                limitations = (
                    "Job stopped at the Acquire stage waiting for operator input "
                    "(upload transcript/media or enable a recovery path)."
                )
            else:
                default_answer = (
                    "Acquisition failed before read — no documents were obtained, so no "
                    "claims were verified. No knowledge was fabricated."
                )
                limitations = (
                    "Research stopped at the Acquire stage. Reader, Extractor, Candidate, "
                    "Consolidator, and Knowledge stages did not run."
                )
        else:
            overall, distribution = self._overall_confidence(body)
            confidence_block = {"overall": overall, "distribution": distribution}
            methodology = _METHODOLOGY
            next_research = self._next_research(body, reasoning)
            default_answer = self._answer(body)
            limitations = self._limitations(body, self._conflicting(body))

        conflicting = self._conflicting(body)
        weakly_supported = self._weakly_supported(body)
        references = self._references(body, sources)

        sections: dict[str, Any] = {
            "answer": answer.strip() or default_answer,
            "confidence": confidence_block,
            "methodology": methodology,
            "funnel": {k: v for k, v in (pipeline or {}).items() if k != "trace"},
            "pipeline_trace": list((pipeline or {}).get("trace") or []),
            "evidence": [
                self._evidence_row(c) for c in body
                if str(c.get("claim_type", "")) != CLAIM_TYPE_PARAMETER
            ],
            "parameters": [
                self._evidence_row(c) for c in body
                if str(c.get("claim_type", "")) == CLAIM_TYPE_PARAMETER
            ],
            "references": references,
            "conflicting_views": conflicting,
            "weakly_supported": weakly_supported,
            "patterns": list(reasoning.get("patterns") or []),
            "opportunities": list(reasoning.get("opportunities") or []),
            "hypotheses": list(reasoning.get("hypotheses") or []),
            "limitations": limitations,
            "next_research": next_research,
            "next_section_title": (
                "Next Action"
                if acquire_stop
                and str(termination.get("audience") or "research") == "job"
                else "Next Research"
            ),
            "termination": termination or None,
        }
        sections["executive_summary"] = self._executive_summary(
            objective, sections, overall, notes, acquire_stop=acquire_stop
        )
        # Optional LLM polish of the free-text sections (best-effort).
        if not acquire_stop:
            self._polish(objective, sections, body, notes)

        report = {
            "objective": objective,
            "overall_confidence": overall,
            "sections": sections,
            "used_findings": bool(findings),
            "reasoning": reasoning,
            "termination": termination or None,
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

        def _rank(c: dict[str, Any]) -> int:
            ct = str(c.get("claim_type", ""))
            if ct in HEADLINE_CLAIM_TYPES:
                return 0
            if ct == CLAIM_TYPE_PARAMETER:
                return 2  # config detail — never lead with it
            return 1

        # Lead with results/conclusions/comparisons/limitations; drop parameters
        # from the headline answer (they live in their own section).
        ordered = sorted(
            (c for c in claims if str(c.get("claim_type", "")) != CLAIM_TYPE_PARAMETER),
            key=_rank,
        )
        if not ordered:
            ordered = list(claims)
        lines = [
            f"- {c.get('statement', '').strip()} [{c.get('confidence')}]"
            for c in ordered
        ]
        return "\n".join(lines)

    @staticmethod
    def _evidence_row(claim: dict[str, Any]) -> dict[str, Any]:
        supporting = claim.get("supporting_sources", []) or []
        # Report honesty (§3B): distinguish quotes from the source ("extracted")
        # from Atlas paraphrases/inferences ("inferred"). A claim is inferred only
        # if it has support and *all* of it is Atlas-generated.
        origins = {str(s.get("origin", "extracted")) for s in supporting}
        inferred = bool(supporting) and origins == {"inferred"}
        return {
            "statement": claim.get("statement", ""),
            "value": claim.get("value"),
            "confidence": claim.get("confidence"),
            "convergence": claim.get("convergence"),
            "verification_method": claim.get("verification_method", ""),
            "supporting": len(supporting),
            "contradicting": len(claim.get("contradicting_sources", [])),
            "reasoning_trace": claim.get("reasoning_trace", []),
            "inferred": inferred,
            "claim_type": str(claim.get("claim_type", "")),
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
        """Real conflicts only: sources that actually disagree (§3B: weak ≠ conflict)."""
        out = []
        for c in claims:
            contra = c.get("contradicting_sources", [])
            if contra:
                out.append(
                    {
                        "statement": c.get("statement", ""),
                        "confidence": c.get("confidence"),
                        "contradicting": len(contra),
                        "note": f"{len(contra)} source(s) disagree with this finding",
                    }
                )
        return out

    @staticmethod
    def _weakly_supported(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """LOW/INSUFFICIENT findings with NO contradiction — a diversity gap, not a
        conflict. Kept distinct so users don't read thin evidence as disagreement."""
        out = []
        for c in claims:
            if c.get("contradicting_sources"):
                continue
            if c.get("confidence") not in {CONFIDENCE_LOW, CONFIDENCE_INSUFFICIENT}:
                continue
            n = len({
                str(s.get("source_id", ""))
                for s in c.get("supporting_sources", []) if s.get("source_id")
            })
            reason = (
                "only 1 independent source"
                if n <= 1
                else f"only {n} independent sources / limited authority"
            )
            out.append(
                {
                    "statement": c.get("statement", ""),
                    "confidence": c.get("confidence"),
                    "independent_sources": n,
                    "note": reason,
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
    def _next_research(
        claims: list[dict[str, Any]], reasoning: dict[str, Any] | None = None
    ) -> str:
        parts: list[str] = []
        reasoning = reasoning or {}
        for opp in reasoning.get("opportunities") or []:
            title = opp.get("title") if isinstance(opp, dict) else None
            why = opp.get("why") if isinstance(opp, dict) else None
            if title:
                parts.append(f"{title}: {why}" if why else str(title))
        for hyp in reasoning.get("hypotheses") or []:
            stmt = hyp.get("statement") if isinstance(hyp, dict) else None
            if stmt:
                parts.append(f"Open hypothesis — {stmt}")
        gaps = [
            c.get("statement", "")
            for c in claims
            if c.get("confidence") in {CONFIDENCE_LOW, CONFIDENCE_INSUFFICIENT}
            or (c.get("convergence") is not None and c["convergence"] < 0.9)
        ]
        if gaps:
            head = "; ".join(g for g in gaps[:3] if g)
            parts.append(f"Gather stronger/converging sources for: {head}.")
        if not parts:
            return "No further research required for the current objective."
        return " ".join(parts[:6])

    def _executive_summary(
        self,
        objective: str,
        sections: dict[str, Any],
        overall: str,
        notes: str,
        *,
        acquire_stop: bool = False,
    ) -> str:
        if acquire_stop:
            conf = sections.get("confidence") or {}
            code = conf.get("reason") or conf.get("reason_code") or "unknown"
            status = conf.get("status") or "blocked"
            next_title = sections.get("next_section_title") or "Next Research"
            if status == "waiting":
                return (
                    f"Objective: {objective.strip()}. Acquire stage is waiting "
                    f"({code}). Knowledge produced: 0. Reasoning was not started; "
                    f"verification was not executed. Confidence is {overall}. "
                    f"See {next_title} for operator recovery strategies."
                )
            return (
                f"Objective: {objective.strip()}. Acquisition failed before read "
                f"({code}). Knowledge produced: 0. Reasoning was not started; "
                f"verification was not executed. Confidence is {overall} — this is "
                f"an acquire-stage stop, not thin evidence. See {next_title} for "
                "operator recovery strategies."
            )
        evidence = sections["evidence"]
        n = len(evidence)
        conflicts = len(sections["conflicting_views"])
        weak = len(sections.get("weakly_supported") or [])
        # Honesty guard (§3B hardening): a report summarizes what Atlas *verified*
        # this run, not what is true in general. With zero verified findings we must
        # NOT assert a conclusion — say plainly that nothing was extractable and
        # point to the funnel for where the pipeline stopped.
        if n == 0:
            funnel = sections.get("funnel") or {}
            found = int(funnel.get("found", 0) or 0)
            read = int(funnel.get("read", 0) or 0)
            if found or read:
                return (
                    f"Objective: {objective.strip()}. Atlas identified {found} "
                    f"candidate source(s) and read {read}, but was unable to extract "
                    "any verifiable claims from the acquired material. No conclusion "
                    "can be drawn for this objective from the current evidence set — "
                    "see the Research Funnel for where the pipeline stopped."
                )
            return (
                f"Objective: {objective.strip()}. No sources yielded verifiable "
                "claims, so no conclusion can be drawn for this objective from the "
                "current evidence set."
            )
        base = (
            f"Objective: {objective.strip()}. {n} finding(s) assessed; overall "
            f"confidence {overall}."
        )
        # Synthesis-oriented: lead with the top result/comparison, not raw config.
        if evidence:
            head = str(evidence[0].get("statement", "")).strip().rstrip(".")
            if head:
                base += f" Key finding: {head}."
        if conflicts:
            base += f" {conflicts} finding(s) have unresolved conflicts."
        if weak:
            base += f" {weak} finding(s) are weakly supported (diversity gap)."
        if notes and "Unmet gaps:" in notes:
            base += " " + ("Unmet gaps:" + notes.split("Unmet gaps:", 1)[1])[:200]
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
        # No verified claims → do not let the summarizer invent a conclusion from
        # world knowledge. Keep the honest deterministic "nothing extractable" text.
        if not claims:
            return
        facts = self._facts_block(objective, sections, claims, notes)
        try:
            prose = self._llm.for_role("summarizer").chat(
                [
                    _msg("system", _SUMMARY_SYSTEM),
                    _msg(
                        "user",
                        "Write a 2-4 sentence executive summary grounded ONLY in these "
                        "facts. Do NOT state any counts, totals, or numbers about how "
                        "many sources/documents/claims were processed — those live in a "
                        "separate funnel table. Focus on what the evidence says and how "
                        f"confident it is.\n\n{facts}",
                    ),
                ]
            ).text.strip()
            if prose:
                # Keep the authoritative deterministic count sentence in front of the
                # LLM narrative so the summary can never contradict the funnel.
                sections["executive_summary"] = (
                    sections.get("executive_summary", "").strip() + " " + prose
                ).strip()
        except Exception:  # noqa: BLE001 - polish is best-effort; keep deterministic text
            self._logger.debug("report LLM polish failed; using deterministic summary")

    @staticmethod
    def _facts_block(
        objective: str, sections: dict[str, Any], claims: list[dict[str, Any]], notes: str
    ) -> str:
        lines = [f"Objective: {objective}", f"Overall confidence: {sections['confidence']['overall']}"]
        for c in claims:
            lines.append(f"- {c.get('statement')} [{c.get('confidence')}]")
        # Only feed the LLM the *qualitative* notes (e.g. unmet gaps), never the
        # pipeline counters — the funnel table is the single source of truth.
        gap_note = ""
        if notes and "Unmet gaps:" in notes:
            gap_note = "Unmet gaps:" + notes.split("Unmet gaps:", 1)[1]
        if gap_note:
            lines.append(f"Notes: {gap_note[:600]}")
        return "\n".join(lines)

    # --- markdown render -----------------------------------------------
    def _render_markdown(
        self, objective: str, sections: dict[str, Any], overall: str
    ) -> str:
        lines = [f"# Research Report: {objective.strip()}", ""]
        lines += ["## Executive Summary", sections["executive_summary"], ""]
        lines += ["## Answer", sections["answer"], ""]
        conf = sections.get("confidence") or {}
        if conf.get("result") in ("acquisition_failed", "waiting") or conf.get("stage") == "acquire":
            status = conf.get("status") or (
                "waiting" if conf.get("result") == "waiting" else "blocked"
            )
            status_label = "Waiting" if status == "waiting" else "Blocked"
            reason = conf.get("reason") or conf.get("reason_code") or "unknown"
            lines += [
                "## Confidence",
                f"Result: **{status_label}** (acquire)",
                f"Stage: **Acquire**",
                f"Status: **{status}**",
                f"Reason: `{reason}`",
            ]
            if conf.get("waiting_for"):
                lines.append(
                    f"Waiting For: **{str(conf['waiting_for']).replace('_', ' ').title()}**"
                )
            lines += [
                f"Knowledge Produced: **{conf.get('knowledge_produced', 0)}**",
                f"Reasoning: **{str(conf.get('reasoning') or 'not_started').replace('_', ' ').title()}**",
                f"Verification: **{str(conf.get('verification') or 'not_executed').replace('_', ' ').title()}**",
                f"Confidence: **{overall}**",
                "",
            ]
        else:
            dist = ", ".join(
                f"{k}: {v}" for k, v in (conf.get("distribution") or {}).items()
            )
            lines += [
                "## Confidence",
                f"Overall: **{overall}**" + (f" ({dist})" if dist else ""),
                "",
            ]
        lines += ["## Methodology", sections["methodology"], ""]

        funnel = sections.get("funnel") or {}
        if funnel:
            lines.append("## Research Funnel")
            lines.append("| Stage | Count |")
            lines.append("| --- | ---: |")
            for key, label in _FUNNEL_ROWS:
                if key in funnel:
                    lines.append(f"| {label} | {funnel[key]} |")
            lines.append("")

        trace = sections.get("pipeline_trace") or []
        if trace:
            lines.append("## Pipeline Trace (per source)")
            lines.append(
                "| Source | Status | Reader | Chars | Sec | Num | Qual | Inf | "
                "Distinct | Verified | Findings | Note |"
            )
            lines.append(
                "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | "
                "---: | ---: | --- |"
            )
            for t in trace:
                label = str(t.get("title") or t.get("source_id") or "")[:48]
                note = str(t.get("failure_reason") or "")[:80]
                lines.append(
                    f"| {label} | {t.get('status', '')} | {t.get('reader', '') or '—'} "
                    f"| {t.get('chars', 0)} | {t.get('sections', 0)} "
                    f"| {t.get('numeric_claims', 0)} | {t.get('qualitative_claims', 0)} "
                    f"| {t.get('inferred_claims', 0)} | {t.get('distinct_claims', 0)} "
                    f"| {t.get('verified_claims', 0)} | {t.get('findings', 0)} "
                    f"| {note or '—'} |"
                )
            lines.append("")

        lines.append("## Evidence")
        if sections["evidence"]:
            for e in sections["evidence"]:
                val = e["value"]
                val_str = (
                    f" — value {val['number']}{val.get('unit', '')}" if isinstance(val, dict) else ""
                )
                conv = e["convergence"]
                conv_str = f", convergence {conv:.0%}" if isinstance(conv, (int, float)) else ""
                origin_tag = " _(Atlas-inferred)_" if e.get("inferred") else ""
                lines.append(
                    f"- **{e['statement']}**{origin_tag} [{e['confidence']}]{val_str} "
                    f"({e['supporting']} supporting, {e['contradicting']} contradicting"
                    f"{conv_str})"
                )
        else:
            lines.append("_No verified claims._")
        lines.append("")

        if sections.get("parameters"):
            lines.append("## Parameters & Configuration")
            lines.append(
                "_Experiment/config details extracted from sources "
                "(not primary findings):_"
            )
            for e in sections["parameters"]:
                val = e["value"]
                val_str = (
                    f" — {val['number']}{val.get('unit', '')}"
                    if isinstance(val, dict) else ""
                )
                lines.append(f"- {e['statement']}{val_str}")
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
            lines.append("_No conflicting sources detected._")
        lines.append("")

        lines.append("## Weakly Supported Findings")
        if sections.get("weakly_supported"):
            for c in sections["weakly_supported"]:
                lines.append(f"- {c['statement']} [{c['confidence']}] — {c['note']}")
        else:
            lines.append("_No weakly supported findings._")
        lines.append("")

        lines.append("## Patterns")
        if sections.get("patterns"):
            for p in sections["patterns"]:
                lines.append(f"- **{p.get('label', '')}** — {p.get('detail', '')}")
        else:
            lines.append("_No recurring patterns detected._")
        lines.append("")

        lines.append("## Research Opportunities")
        if sections.get("opportunities"):
            for o in sections["opportunities"]:
                lines.append(f"- **{o.get('title', '')}** — {o.get('why', '')}")
        else:
            lines.append("_No open opportunities listed._")
        lines.append("")

        lines.append("## Hypotheses")
        if sections.get("hypotheses"):
            for h in sections["hypotheses"]:
                lines.append(
                    f"- [{h.get('status', 'open')}] {h.get('statement', '')} "
                    f"— {h.get('rationale', '')}"
                )
        else:
            lines.append("_No typed hypotheses._")
        lines.append("")

        lines += ["## Limitations", sections["limitations"], ""]
        next_title = sections.get("next_section_title") or "Next Research"
        lines += [f"## {next_title}", sections["next_research"], ""]
        return "\n".join(lines).strip() + "\n"


def _msg(role: str, content: str):
    from atlas.llm.provider import ChatMessage

    return ChatMessage(role, content)
