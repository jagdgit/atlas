"""BRE.5 / OI-LLM-OS0 — Global mind from revision history.

Distills per-symbol WSO revision logs into a lab-level global WSO + mentor
digest. Deterministic first (honest patterns); optional 1 budgeted LLM
narrative. Mentors read advice-only (A7 — no soft-bias from this path).
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import Any

from atlas.investment.cognitive_budget import DEFAULT_NIGHTLY_LLM_PASSES
from atlas.investment.world_state import (
    append_revision,
    ensure_global_wso,
    list_lab_wsos,
    load_global_wso,
    save_global_wso,
)

_log = logging.getLogger("atlas.investment.global_mind")
VERSION = "bre5.global_mind.v1"
DEFAULT_GLOBAL_LLM_PASSES = 1

_JSON_RE = re.compile(r"\{[\s\S]*\}")

_MATERIAL_STATUSES = frozenset(
    {"strengthened", "weakened", "falsified", "insufficient_evidence"}
)


def _parse_json_blob(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        m = _JSON_RE.search(raw)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None


def collect_revision_patterns(
    wsos: list[dict[str, Any]] | None,
    *,
    limit_per_symbol: int = 5,
    max_patterns: int = 40,
) -> list[dict[str, Any]]:
    """Flatten recent material revisions across symbol WSOs (deterministic)."""
    patterns: list[dict[str, Any]] = []
    for w in wsos or []:
        if not isinstance(w, dict):
            continue
        if w.get("kind") == "global" or str(w.get("symbol") or "") == "_GLOBAL":
            continue
        sym = str(w.get("symbol") or "").strip()
        if not sym:
            continue
        hist = list(w.get("revision_history") or [])
        taken = 0
        for rec in reversed(hist):
            if not isinstance(rec, dict):
                continue
            status = str(rec.get("status") or "").lower()
            if status not in _MATERIAL_STATUSES and not rec.get("llm"):
                continue
            if status == "unchanged" and not rec.get("llm"):
                continue
            patterns.append(
                {
                    "symbol": sym,
                    "status": status,
                    "reason": str(rec.get("reason") or "")[:300],
                    "at": rec.get("at"),
                    "llm": bool(rec.get("llm")),
                }
            )
            taken += 1
            if taken >= limit_per_symbol:
                break
        if len(patterns) >= max_patterns:
            break
    return patterns[:max_patterns]


def build_mentor_digest(patterns: list[dict[str, Any]]) -> dict[str, Any]:
    """Structured advice-only digest for Investment Mentor (no soft-bias)."""
    by_status = Counter(str(p.get("status") or "unknown") for p in patterns)
    strengthened = [p for p in patterns if p.get("status") == "strengthened"]
    weakened = [p for p in patterns if p.get("status") == "weakened"]
    falsified = [p for p in patterns if p.get("status") == "falsified"]
    linked = sorted({str(p.get("symbol")) for p in patterns if p.get("symbol")})

    bullets: list[str] = []
    if strengthened:
        bullets.append(
            f"{len(strengthened)} belief(s) strengthened — e.g. "
            f"{strengthened[0].get('symbol')}: {str(strengthened[0].get('reason') or '')[:80]}"
        )
    if weakened:
        bullets.append(
            f"{len(weakened)} belief(s) weakened — e.g. "
            f"{weakened[0].get('symbol')}: {str(weakened[0].get('reason') or '')[:80]}"
        )
    if falsified:
        bullets.append(
            f"{len(falsified)} belief(s) falsified — review exits / sizing"
        )
    if not bullets:
        bullets.append("No material mind-changes in revision history yet")

    recommendations: list[str] = []
    if falsified or weakened:
        recommendations.append(
            "Re-check falsifiers on weakened/falsified names before adding size"
        )
    if strengthened:
        recommendations.append(
            "Prefer evidence-backed strengthens; do not auto-raise size (advice-only)"
        )
    if not recommendations:
        recommendations.append("Keep logging revisions — mentors need sample growth")

    return {
        "version": VERSION,
        "linked_symbols": linked[:40],
        "status_counts": dict(by_status),
        "bullets": bullets[:8],
        "recommendations": recommendations[:6],
        "pattern_count": len(patterns),
        "advice_only": True,  # A7
        "enable_soft_bias": False,
    }


def distill_global_mind(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    wsos: list[dict[str, Any]] | None = None,
    llm: Any | None = None,
    allow_llm_narrative: bool = False,
    domain: str = "market",
) -> dict[str, Any]:
    """Refresh lab global WSO from symbol revision history.

    Path may be ``str | Path``; imported lazily in type-checker-friendly way.
    """
    from pathlib import Path  # noqa: F401 — used by callers via Path|str

    lab = laboratory_id or "india_equity_learner"
    rows = list(wsos) if wsos is not None else list_lab_wsos(data_dir, lab)
    patterns = collect_revision_patterns(rows)
    digest = build_mentor_digest(patterns)
    linked = list(digest.get("linked_symbols") or [])

    doc = ensure_global_wso(data_dir, lab, domain=domain)
    doc["patterns"] = patterns
    doc["linked_symbols"] = linked
    doc["mentor_digest"] = digest
    doc["unknowns"] = []
    if not patterns:
        doc["status"] = "insufficient_evidence"
        reason = "BRE.5 distill — no material symbol revisions yet"
        append_revision(doc, status="insufficient_evidence", reason=reason, llm=False)
    else:
        doc["status"] = "unchanged"
        reason = (
            f"BRE.5 distill — {len(patterns)} revision patterns across "
            f"{len(linked)} symbols (deterministic)"
        )
        append_revision(
            doc,
            status="unchanged",
            reason=reason,
            evidence_delta={"patterns": len(patterns), "symbols": len(linked)},
            llm=False,
        )

    # Optional single LLM narrative (semantic text only; A7 still advice-only)
    if allow_llm_narrative and llm is not None and patterns:
        try:
            busy = hasattr(llm, "lane_busy") and llm.lane_busy()
        except Exception:  # noqa: BLE001
            busy = False
        if not busy:
            narrative = _llm_global_narrative(llm, patterns=patterns, digest=digest)
            if narrative:
                doc["thesis_text"] = str(narrative.get("thesis_text") or "")[:2000]
                if isinstance(narrative.get("patterns_named"), list):
                    # Keep deterministic patterns; store named tags separately
                    doc["beliefs"] = {
                        "cross_symbol": {
                            "confidence": None,
                            "note": str(narrative.get("notes") or "")[:500],
                            "evidence_ids": [],
                            "assumption": True,
                        }
                    }
                append_revision(
                    doc,
                    status=str(narrative.get("status") or "unchanged"),
                    reason=str(narrative.get("reason") or "BRE.5 LLM global narrative")[:500],
                    llm=True,
                )
                digest = dict(digest)
                if narrative.get("mentor_bullets"):
                    digest["bullets"] = [
                        str(x)[:200] for x in narrative["mentor_bullets"] if x
                    ][:8]
                doc["mentor_digest"] = digest

    if data_dir:
        save_global_wso(data_dir, doc)
    return doc


def _llm_global_narrative(
    llm: Any,
    *,
    patterns: list[dict[str, Any]],
    digest: dict[str, Any],
) -> dict[str, Any] | None:
    prompt = {
        "task": "global_mind_narrative",
        "patterns": patterns[:20],
        "digest": digest,
        "instructions": (
            "Return JSON with keys: status (unchanged|strengthened|weakened), "
            "thesis_text (2-4 sentences on cross-symbol judgment patterns), "
            "reason, notes, mentor_bullets (list of short advice strings). "
            "Do not invent prices/PE/FCF. Advice-only — no size commands."
        ),
    }
    try:
        client = llm.for_role("researcher") if hasattr(llm, "for_role") else llm
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Atlas's global investment cortex. Summarize revision "
                    "patterns across symbols. One JSON object only."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, default=str)},
        ]
        resp = client.chat(messages)
        text = getattr(resp, "text", None) or getattr(resp, "content", None) or str(resp)
    except Exception:  # noqa: BLE001
        _log.debug("BRE.5 LLM narrative failed", exc_info=True)
        return None
    return _parse_json_blob(str(text))


def format_global_mind_section(global_wso: dict[str, Any] | None) -> list[str]:
    """Evening: lab-level mind from revision history."""
    lines = ["", "--- Global mind (BRE.5) ---"]
    if not isinstance(global_wso, dict):
        lines.append("No lab-level global WSO yet.")
        return lines
    digest = global_wso.get("mentor_digest")
    if not isinstance(digest, dict):
        digest = {}
    n = int(digest.get("pattern_count") or len(global_wso.get("patterns") or []) or 0)
    linked = list(digest.get("linked_symbols") or global_wso.get("linked_symbols") or [])
    lines.append(
        f"patterns={n} · symbols={len(linked)} · advice_only="
        f"{bool(digest.get('advice_only', True))}"
    )
    thesis = str(global_wso.get("thesis_text") or "").strip()
    if thesis:
        lines.append(f"  thesis: {thesis[:220]}{'…' if len(thesis) > 220 else ''}")
    for b in list(digest.get("bullets") or [])[:5]:
        lines.append(f"  · {b}")
    for r in list(digest.get("recommendations") or [])[:3]:
        lines.append(f"  advice: {r}")
    if n == 0 and not thesis:
        lines.append("  No material cross-symbol revisions to teach from yet.")
    return lines


def mentor_lesson_from_digest(
    global_wso: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Build an Experience-shaped lesson dict for Investment Mentor (advice-only)."""
    if not isinstance(global_wso, dict):
        return None
    digest = global_wso.get("mentor_digest")
    if not isinstance(digest, dict):
        return None
    if int(digest.get("pattern_count") or 0) <= 0:
        return None
    bullets = list(digest.get("bullets") or [])
    recs = list(digest.get("recommendations") or [])
    linked = list(digest.get("linked_symbols") or [])[:8]
    title = "WSO revision patterns — laboratory judgment digest"
    observation = (
        f"Reviewed {digest.get('pattern_count')} belief revisions across "
        f"{len(digest.get('linked_symbols') or [])} symbols: {', '.join(linked) or '—'}"
    )
    lesson = bullets[0] if bullets else "Track mind-changes; sample still thin"
    return {
        "title": title,
        "observation": observation,
        "decision_summary": "BRE.5 global distill (deterministic patterns)",
        "outcome_summary": "; ".join(str(b) for b in bullets[:3]) or "no material changes",
        "reflection": str(global_wso.get("thesis_text") or "")[:500]
        or "Semantic thesis awaits budgeted LLM narrative when patterns exist.",
        "lesson": lesson[:500],
        "recommendations": [str(r) for r in recs[:4]],
        "tags": [
            "markets",
            "bre5",
            "wso_revision",
            "advice_only",
            "investment_mentor",
        ],
        "source_experience_ids": [],
        "enable_soft_bias": False,
        "advice_only": True,
        "domain": "markets",
    }


# Fix forward ref used in signature without importing Path at module top for distill
from pathlib import Path  # noqa: E402  — used in type hints / callers

__all__ = [
    "VERSION",
    "DEFAULT_GLOBAL_LLM_PASSES",
    "DEFAULT_NIGHTLY_LLM_PASSES",
    "collect_revision_patterns",
    "build_mentor_digest",
    "distill_global_mind",
    "format_global_mind_section",
    "mentor_lesson_from_digest",
    "load_global_wso",
    "Path",
]
