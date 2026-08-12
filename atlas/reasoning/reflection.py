"""OI-SELF-REFLECT — Nightly Reflection Engine (Phase 3).

Budgeted pass across Belief Core:
- failed / matched learning-loop deltas (when provided)
- candidate promotion heuristics
- aging notes
- Belief Core revision + consultation metrics (JIS)
- optional short LLM narrative via researcher role

Does **not** hard-influence ranking/execution (advice-only).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from atlas.investment.cognitive_budget import DEFAULT_NIGHTLY_LLM_PASSES
from atlas.reasoning.aging import with_effective

VERSION = "self0.reflect.v1"
_log = logging.getLogger("atlas.reasoning.reflection")


def _today_ist() -> str:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return date.today().isoformat()


def promote_ready_candidates(
    reasoning: Any,
    *,
    max_promotions: int = 2,
    min_evidence: int = 2,
    min_confidence: float = 0.45,
    actor: str = "reflection",
) -> list[dict[str, Any]]:
    """Promote candidates that have enough evidence + confidence (deterministic gate)."""
    if reasoning is None:
        return []
    repo = getattr(reasoning, "_repo", None)
    if repo is None:
        return []
    promoted: list[dict[str, Any]] = []
    cands = reasoning.list_beliefs(status="candidate", limit=50)
    # Prefer higher confidence
    cands = sorted(
        cands, key=lambda b: float(b.get("confidence") or 0), reverse=True
    )
    for b in cands:
        if len(promoted) >= max_promotions:
            break
        bid = str(b.get("id") or "")
        if not bid:
            continue
        conf = float(b.get("effective_confidence") or b.get("confidence") or 0)
        if conf < min_confidence:
            continue
        evid = []
        try:
            evid = repo.list_evidence(bid, limit=20)
        except Exception:  # noqa: BLE001
            evid = []
        if len(evid) < min_evidence:
            continue
        try:
            out = reasoning.promote(
                bid,
                reason=(
                    f"Reflection promotion: evidence_n={len(evid)} "
                    f"effective_confidence={conf}"
                ),
                actor=actor,
                confidence=min(0.7, max(conf, min_confidence)),
            )
            promoted.append(
                {
                    "belief_id": bid,
                    "statement": (out.get("belief") or {}).get("statement"),
                    "revision_id": (out.get("revision") or {}).get("id"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            _log.debug("promote candidate failed %s: %s", bid, exc)
    return promoted


def weaken_stale_active(
    reasoning: Any,
    *,
    max_actions: int = 2,
    min_age_days: float = 180.0,
    max_effective: float = 0.35,
    actor: str = "reflection",
) -> list[dict[str, Any]]:
    """Weaken active beliefs whose effective confidence aged below threshold."""
    if reasoning is None:
        return []
    actions: list[dict[str, Any]] = []
    actives = reasoning.list_beliefs(status="active", limit=80)
    stale = []
    for b in actives:
        enriched = with_effective(b)
        age = float(enriched.get("evidence_age_days") or 0)
        eff = float(enriched.get("effective_confidence") or 0)
        if age >= min_age_days and eff <= max_effective:
            stale.append(enriched)
    stale.sort(key=lambda b: float(b.get("effective_confidence") or 0))
    for b in stale[:max_actions]:
        bid = str(b.get("id") or "")
        try:
            out = reasoning.revise(
                bid,
                reason=(
                    f"Reflection aging: evidence_age_days={b.get('evidence_age_days')} "
                    f"effective_confidence={b.get('effective_confidence')}"
                ),
                evidence_summary="Belief aging revalidation (OI-SELF-REFLECT)",
                new_status="weakened",
                new_confidence=float(b.get("effective_confidence") or 0.3),
                actor=actor,
            )
            actions.append(
                {
                    "belief_id": bid,
                    "action": "weaken",
                    "revision_id": (out.get("revision") or {}).get("id"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            _log.debug("aging weaken failed %s: %s", bid, exc)
    return actions


def belief_core_jis(reasoning: Any, *, days: int = 7) -> dict[str, Any]:
    """JIS slice from Belief Core (not only WSO shells)."""
    if reasoning is None:
        return {
            "today": 0,
            "days": days,
            "period": 0,
            "by_status": {},
            "consultations_today": {},
            "source": "belief_core",
            "honesty": "reasoning unavailable",
        }
    revs = reasoning.revision_metrics(days=days)
    consults = reasoning.consultation_metrics()
    # Approximate "today" from 7d material if we lack day filter — use consultations
    # and revision material_total as period; today from repo if possible.
    today_n = 0
    by_action = dict(revs.get("by_action") or {})
    repo = getattr(reasoning, "_repo", None)
    if repo is not None and hasattr(repo, "list_beliefs"):
        # Count today's revisions via raw list if available
        try:
            # Use consultation day as today anchor; revision today via SQL path
            if hasattr(repo, "fetch_all"):
                rows = repo.fetch_all(
                    """
                    SELECT action, COUNT(*)::int AS n
                    FROM beliefs.revisions
                    WHERE created_at::date = CURRENT_DATE
                      AND action IN ('revise','promote','weaken','falsify','supersede')
                    GROUP BY action
                    """
                )
                today_n = sum(int(r.get("n") or 0) for r in (rows or []))
                for r in rows or []:
                    by_action[str(r.get("action"))] = by_action.get(
                        str(r.get("action")), 0
                    ) + 0  # keep week counts from revision_metrics
        except Exception:  # noqa: BLE001
            # InMemory: scan revisions
            try:
                today = _today_ist()
                n = 0
                material = {
                    "revise",
                    "promote",
                    "weaken",
                    "falsify",
                    "supersede",
                }
                for bid_row in reasoning.list_beliefs(limit=200):
                    for rev in repo.list_revisions(bid_row["id"], limit=20):
                        if rev.get("action") not in material:
                            continue
                        at = rev.get("created_at")
                        day = ""
                        if hasattr(at, "strftime"):
                            day = at.strftime("%Y-%m-%d")
                        else:
                            day = str(at or "")[:10]
                        if day == today:
                            n += 1
                today_n = n
            except Exception:  # noqa: BLE001
                today_n = 0
    return {
        "today": today_n,
        "days": int(days),
        "period": int(revs.get("material_total") or 0),
        "by_status": by_action,
        "consultations_today": consults,
        "source": "belief_core",
        "honesty": (
            "Belief Core material revisions (revise/promote/weaken/falsify/supersede). "
            "WSO shell-only edits excluded. Consultations show worldview use."
        ),
    }


def merge_jis(
    wso_jis: dict[str, Any] | None,
    core_jis: dict[str, Any] | None,
) -> dict[str, Any]:
    """Combine WSO + Belief Core JIS for evening honesty."""
    w = wso_jis if isinstance(wso_jis, dict) else {}
    c = core_jis if isinstance(core_jis, dict) else {}
    return {
        "today": int(w.get("today") or 0) + int(c.get("today") or 0),
        "days": int(c.get("days") or w.get("days") or 7),
        "period": int(w.get("period") or 0) + int(c.get("period") or 0),
        "by_status": {
            **dict(w.get("by_status") or {}),
            **{
                f"core:{k}": v for k, v in dict(c.get("by_status") or {}).items()
            },
        },
        "wso": w,
        "belief_core": c,
        "consultations_today": c.get("consultations_today") or {},
        "honesty": (
            "JIS = WSO material revisions + Belief Core revisions. "
            "Consultations/day keeps worldview from being decorative."
        ),
    }


def format_reflection_section(doc: dict[str, Any] | None) -> list[str]:
    d = doc if isinstance(doc, dict) else {}
    lines = ["", "--- Reflection (OI-SELF-REFLECT) ---"]
    if not d:
        lines.append("No reflection run tonight.")
        return lines
    lines.append(
        f"status={d.get('status')} · promoted={len(d.get('promoted') or [])} · "
        f"aged_weaken={len(d.get('aged') or [])}"
    )
    for p in (d.get("promoted") or [])[:3]:
        lines.append(
            f"  · promoted: {(p.get('statement') or p.get('belief_id') or '')[:100]}"
        )
    for a in (d.get("aged") or [])[:3]:
        lines.append(f"  · aged weaken: {a.get('belief_id')}")
    narrative = str(d.get("narrative") or "").strip()
    if narrative:
        lines.append(f"narrative: {narrative[:400]}")
    skip = d.get("skip_reason")
    if skip:
        lines.append(f"note: {skip}")
    consults = (d.get("jis") or {}).get("consultations_today") or {}
    if consults:
        by = consults.get("by_domain") or {}
        lines.append(
            f"Belief Consultations today: {consults.get('total', 0)} "
            f"(M={by.get('market', 0)} E={by.get('engineering', 0)} "
            f"P={by.get('personal', 0)} X={by.get('cross', 0)})"
        )
    return lines


def _optional_llm_narrative(
    reasoning: Any,
    *,
    promoted: list[dict[str, Any]],
    aged: list[dict[str, Any]],
    jis: dict[str, Any],
) -> str | None:
    llm = getattr(reasoning, "_llm", None) if reasoning else None
    if llm is None:
        return None
    try:
        from atlas.llm.provider import ChatMessage

        client = llm.for_role("researcher") if hasattr(llm, "for_role") else llm
        resp = client.chat(
            [
                ChatMessage(
                    role="system",
                    content=(
                        "You are Atlas's nightly reflection. Write 2 short sentences "
                        "on judgment changes tonight. Do not invent evidence. "
                        "If nothing material happened, say so honestly."
                    ),
                ),
                ChatMessage(
                    role="user",
                    content=(
                        f"Promoted: {len(promoted)}; aged_weaken: {len(aged)}; "
                        f"Belief Core revisions 7d: {jis.get('period')}; "
                        f"consultations today: "
                        f"{(jis.get('consultations_today') or {}).get('total')}. "
                        "Narrative:"
                    ),
                ),
            ]
        )
        text = (getattr(resp, "text", None) or str(resp) or "").strip()
        return text[:500] or None
    except Exception:  # noqa: BLE001
        _log.debug("reflection LLM narrative failed", exc_info=True)
        return None


def run_nightly_reflection(
    reasoning: Any,
    *,
    laboratory_id: str | None = None,
    max_promotions: int = 2,
    max_aging: int = 2,
    allow_llm_narrative: bool = True,
    max_llm_passes: int = DEFAULT_NIGHTLY_LLM_PASSES,
) -> dict[str, Any]:
    """Phase 3 nightly reflection. Deterministic core; optional LLM coda."""
    if reasoning is None:
        return {
            "version": VERSION,
            "status": "skipped",
            "skip_reason": "no ReasoningService bound",
            "promoted": [],
            "aged": [],
            "jis": {},
        }
    try:
        reasoning.ensure_seeded()
    except Exception:  # noqa: BLE001
        pass

    promoted = promote_ready_candidates(
        reasoning, max_promotions=max_promotions
    )
    aged = weaken_stale_active(reasoning, max_actions=max_aging)
    core_jis = belief_core_jis(reasoning, days=7)

    narrative = None
    llm_used = False
    # Budget: only spend LLM narrative if we have headroom conceptually
    if allow_llm_narrative and max_llm_passes > 0:
        narrative = _optional_llm_narrative(
            reasoning, promoted=promoted, aged=aged, jis=core_jis
        )
        llm_used = bool(narrative)

    status = "ok"
    skip_reason = None
    if not promoted and not aged and int(core_jis.get("period") or 0) == 0:
        status = "thin"
        skip_reason = (
            "No promotions/aging and zero Belief Core material revisions in 7d — "
            "honest thin reflection (need evidence densify)."
        )

    return {
        "version": VERSION,
        "status": status,
        "skip_reason": skip_reason,
        "laboratory_id": laboratory_id,
        "day_ist": _today_ist(),
        "promoted": promoted,
        "aged": aged,
        "jis": core_jis,
        "narrative": narrative,
        "llm_used": llm_used,
        "influence_strength": "advice",
        "max_llm_passes_ref": max_llm_passes,
    }
