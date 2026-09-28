"""OI-CHAT-INFER0 Stage 6 — Cognitive ROI (first slice).

Scores *where* inference seconds went, not whether Atlas should maximize Ollama.
Scientist purposes that finish ok are higher-value than chat timeouts on questions
that should have been deterministic.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

VERSION = "chat_infer0.cognitive_roi.v1"

# Purposes that create learning / judgment value when outcome=ok
_SCIENTIST_PURPOSES = {
    "bre3_decide_rationale",
    "bre4_morning_hypothesis",
    "bre2_belief_revision",
    "bre5_global_mind",
    "mem1_memory_distill",
    "research_scientist",
    "research_claim_extract",
    "self_belief_revise_suggest",
    "self_nightly_reflection",
    "eng_design_review",
    "eng_code_explain",
    "eng_chat_code",
}


def score_day(rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    by_purpose: dict[str, dict[str, Any]] = {}
    scientist_ok_ms = 0.0
    scientist_ok_n = 0
    waste_timeout_ms = 0.0
    waste_timeout_n = 0
    embed_ms = 0.0
    embed_n = 0

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        purpose = str(r.get("purpose") or r.get("role") or "untagged")
        buckets[purpose].append(r)

    for purpose, group in sorted(buckets.items()):
        ok = sum(1 for r in group if r.get("outcome") == "ok")
        fail = sum(
            1
            for r in group
            if r.get("outcome") in {"timeout", "error", "busy", "lane_busy"}
        )
        gens = [
            float(r["generate_ms"]) for r in group if r.get("generate_ms") is not None
        ]
        spent = round(sum(gens), 1) if gens else 0.0
        by_purpose[purpose] = {
            "n": len(group),
            "ok": ok,
            "fail": fail,
            "generate_ms_sum": spent,
            "scientist": purpose in _SCIENTIST_PURPOSES,
        }
        if purpose in _SCIENTIST_PURPOSES:
            for r in group:
                if r.get("outcome") == "ok" and r.get("generate_ms") is not None:
                    scientist_ok_ms += float(r["generate_ms"])
                    scientist_ok_n += 1
        if purpose == "assistant_compose":
            for r in group:
                if (
                    r.get("outcome") in {"timeout", "error"}
                    and r.get("generate_ms") is not None
                ):
                    waste_timeout_ms += float(r["generate_ms"])
                    waste_timeout_n += 1

    for r in rows:
        purpose = str(r.get("purpose") or "")
        kind = str(r.get("call_kind") or r.get("kind") or "")
        if kind == "embed" or "embed" in purpose:
            embed_n += 1
            if r.get("generate_ms") is not None:
                embed_ms += float(r["generate_ms"])

    denom = scientist_ok_ms + waste_timeout_ms
    roi_ratio = round(scientist_ok_ms / denom, 3) if denom > 0 else None

    return {
        "version": VERSION,
        "by_purpose": by_purpose,
        "scientist_ok_n": scientist_ok_n,
        "scientist_ok_generate_ms": round(scientist_ok_ms, 1),
        "compose_timeout_n": waste_timeout_n,
        "compose_timeout_generate_ms": round(waste_timeout_ms, 1),
        "embed_n": embed_n,
        "embed_generate_ms": round(embed_ms, 1),
        "roi_ratio_scientist_vs_compose_timeout": roi_ratio,
        "honesty": (
            "Cognitive ROI first slice — seconds on scientist purposes that finished ok "
            "vs seconds burned on assistant_compose timeouts. Not P&L. "
            "Deterministic glossary/self-model spend $0 inference (correct)."
        ),
    }


def format_cognitive_roi_evening_lines(
    data_dir: Any = None,
    *,
    as_of_ist: str | None = None,
    rows: list[dict[str, Any]] | None = None,
) -> list[str]:
    if rows is None:
        from atlas.llm.fitness_ledger import load_day

        rows = load_day(data_dir, as_of_ist=as_of_ist)
    score = score_day(rows)
    lines = [
        "",
        "── Cognitive ROI (OI-CHAT-INFER0 Stage 6) ──",
        f"  scientist_ok: n={score.get('scientist_ok_n')} · "
        f"ms={score.get('scientist_ok_generate_ms')}",
        f"  compose_timeout_waste: n={score.get('compose_timeout_n')} · "
        f"ms={score.get('compose_timeout_generate_ms')}",
        f"  roi_ratio (scientist_ok / (scientist_ok+compose_timeout)): "
        f"{score.get('roi_ratio_scientist_vs_compose_timeout')}",
        f"  embeds: n={score.get('embed_n')} · ms={score.get('embed_generate_ms')}",
    ]
    by_p = score.get("by_purpose") if isinstance(score.get("by_purpose"), dict) else {}
    ranked = sorted(
        by_p.items(),
        key=lambda kv: float((kv[1] or {}).get("generate_ms_sum") or 0),
        reverse=True,
    )[:6]
    if ranked:
        lines.append("  top spend by purpose:")
        for purpose, st in ranked:
            if not isinstance(st, dict):
                continue
            tag = "scientist" if st.get("scientist") else "other"
            lines.append(
                f"    · {purpose}: {st.get('generate_ms_sum')}ms "
                f"(ok={st.get('ok')} fail={st.get('fail')} · {tag})"
            )
    lines.append(str(score.get("honesty") or ""))
    return lines
