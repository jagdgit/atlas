"""SI.6 — Opportunity Comparison Engine (“Why A vs B?”).

Compares two awareness snapshots using SI identity / packs / distinctiveness /
valuation paths / dual confidence. Never invents a buy winner without MoS.
"""

from __future__ import annotations

from typing import Any

from atlas.investment.research.models import normalize_symbol, utc_now_iso

VERSION = "si.6"

VERDICT_INCOMPARABLE = "incomparable_lenses"
VERDICT_SAME_LENS = "same_lens_need_company_evidence"
VERDICT_INSUFFICIENT = "insufficient_evidence"
VERDICT_RESEARCH = "prefer_deeper_research"


def _snap(aw: dict[str, Any] | None) -> dict[str, Any]:
    aw = aw if isinstance(aw, dict) else {}
    ident = aw.get("business_identity") if isinstance(aw.get("business_identity"), dict) else {}
    dist = aw.get("distinctiveness") if isinstance(aw.get("distinctiveness"), dict) else {}
    strat = aw.get("research_strategy") if isinstance(aw.get("research_strategy"), dict) else {}
    vp = strat.get("valuation_paths") if isinstance(strat.get("valuation_paths"), dict) else {}
    active = vp.get("active") if isinstance(vp.get("active"), dict) else {}
    thesis = aw.get("thesis") if isinstance(aw.get("thesis"), dict) else {}
    val = aw.get("valuation") if isinstance(aw.get("valuation"), dict) else {}
    score = aw.get("investment_score") if isinstance(aw.get("investment_score"), dict) else {}
    return {
        "symbol": normalize_symbol(str(aw.get("symbol") or "")),
        "pack_id": ident.get("pack_id") or aw.get("pack") or strat.get("sector_pack_id"),
        "business_type": ident.get("business_type"),
        "sector": ident.get("sector"),
        "identity_status": ident.get("status"),
        "capital_intensity": ident.get("capital_intensity"),
        "reason_to_exist": dist.get("reason_to_exist"),
        "position": dist.get("position"),
        "distinctiveness_score": dist.get("score_pct"),
        "distinctiveness_gaps": list(dist.get("gaps") or []),
        "value_drivers": list(dist.get("value_drivers") or [])[:4],
        "falsifiers": list(dist.get("falsifiers") or [])[:4],
        "active_valuation_path": active.get("kind") or vp.get("active_path") or vp.get("primary"),
        "valuation_path_label": active.get("label"),
        "next_evidence": list(vp.get("next_evidence") or [])[:3],
        "stance": thesis.get("stance"),
        "confidence": aw.get("confidence"),
        "coverage": aw.get("coverage"),
        "mos": val.get("margin_of_safety_pct"),
        "mos_method": val.get("mos_method"),
        "score_overall": score.get("overall"),
        "mvr_satisfied": bool(aw.get("mvr_satisfied")),
    }


def _held(holdings: dict[str, Any] | None, symbol: str) -> bool:
    if not holdings:
        return False
    sym = normalize_symbol(symbol)
    if sym in holdings:
        try:
            return float(holdings[sym] or 0) != 0
        except (TypeError, ValueError):
            return bool(holdings[sym])
    # also try bare keys
    for k, v in holdings.items():
        if normalize_symbol(str(k)) == sym:
            try:
                return float(v or 0) != 0
            except (TypeError, ValueError):
                return bool(v)
    return False


def compare_opportunities(
    aw_a: dict[str, Any] | None,
    aw_b: dict[str, Any] | None,
    *,
    holdings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return structured Why-A-vs-B comparison (not a buy ticket)."""
    a = _snap(aw_a)
    b = _snap(aw_b)
    axes: list[dict[str, Any]] = []
    why_diff: list[str] = []
    blockers: list[str] = []

    # Identity / pack
    same_pack = bool(a["pack_id"] and a["pack_id"] == b["pack_id"])
    if not a["pack_id"] or not b["pack_id"]:
        blockers.append("identity_or_pack_missing")
    if a["pack_id"] != b["pack_id"]:
        why_diff.append(
            f"Different sector lenses: {a['symbol']}={a['pack_id'] or '?'} vs "
            f"{b['symbol']}={b['pack_id'] or '?'}"
        )
        axes.append(
            {
                "id": "identity",
                "label": "Business identity / pack",
                "a": f"{a['business_type'] or '?'} ({a['pack_id'] or 'no pack'})",
                "b": f"{b['business_type'] or '?'} ({b['pack_id'] or 'no pack'})",
                "delta": "different_packs",
                "note": "Not interchangeable research templates — questions and KPIs differ.",
            }
        )
    else:
        axes.append(
            {
                "id": "identity",
                "label": "Business identity / pack",
                "a": f"{a['business_type'] or '?'} ({a['pack_id'] or 'no pack'})",
                "b": f"{b['business_type'] or '?'} ({b['pack_id'] or 'no pack'})",
                "delta": "same_pack",
                "note": (
                    "Same pack — comparison must rest on company-specific distinctiveness, "
                    "not sector boilerplate."
                ),
            }
        )
        if same_pack:
            why_diff.append(
                f"Same pack ({a['pack_id']}) — sector lens is shared; company evidence must diverge."
            )

    # Distinctiveness
    ra = (a.get("reason_to_exist") or "")[:160]
    rb = (b.get("reason_to_exist") or "")[:160]
    if ra and rb and ra != rb:
        why_diff.append("Distinctiveness reasons differ (why each firm exists).")
    axes.append(
        {
            "id": "distinctiveness",
            "label": "Distinctiveness (SI.5)",
            "a": f"score={a.get('distinctiveness_score')} · {ra or '(gap)'}",
            "b": f"score={b.get('distinctiveness_score')} · {rb or '(gap)'}",
            "delta": "differ" if ra != rb else "similar",
            "note": "Gaps beat boilerplate — do not treat thin scores as conviction.",
        }
    )

    # Valuation path
    if a.get("active_valuation_path") != b.get("active_valuation_path"):
        why_diff.append(
            f"Active valuation paths differ: {a.get('active_valuation_path')} vs "
            f"{b.get('active_valuation_path')}"
        )
    axes.append(
        {
            "id": "valuation_path",
            "label": "Valuation path (SI.4)",
            "a": a.get("valuation_path_label") or a.get("active_valuation_path") or "?",
            "b": b.get("valuation_path_label") or b.get("active_valuation_path") or "?",
            "delta": (
                "differ"
                if a.get("active_valuation_path") != b.get("active_valuation_path")
                else "same"
            ),
            "note": "Path honesty — no fake DCF MoS without FCF.",
        }
    )

    # Stance / MoS / score
    axes.append(
        {
            "id": "stance_mos",
            "label": "Stance / MoS / score",
            "a": (
                f"stance={a.get('stance') or '?'} · MoS={a.get('mos')} · "
                f"score={a.get('score_overall')}"
            ),
            "b": (
                f"stance={b.get('stance') or '?'} · MoS={b.get('mos')} · "
                f"score={b.get('score_overall')}"
            ),
            "delta": "informational",
            "note": "MoS missing ⇒ no capital-allocation winner from this compare.",
        }
    )

    # Prefer deeper research (not buy)
    prefer_sym = None
    prefer_reasons: list[str] = []

    def _gap_count(s: dict[str, Any]) -> int:
        return len(s.get("distinctiveness_gaps") or [])

    # Prefer the name with resolved identity but thinner coverage / more gaps
    for cand, other in ((a, b), (b, a)):
        reasons: list[str] = []
        if cand.get("identity_status") in {"resolved", "weak"} and (
            (cand.get("coverage") or 0) < (other.get("coverage") or 0)
        ):
            reasons.append("lower coverage — higher marginal research value")
        if _gap_count(cand) > _gap_count(other):
            reasons.append("more distinctiveness gaps to close")
        if not cand.get("mvr_satisfied") and other.get("mvr_satisfied"):
            reasons.append("MVR incomplete")
        if reasons and (prefer_sym is None or len(reasons) > len(prefer_reasons)):
            prefer_sym = cand["symbol"]
            prefer_reasons = reasons

    held_a = _held(holdings, a["symbol"])
    held_b = _held(holdings, b["symbol"])
    portfolio_context: dict[str, Any] = {
        "a_held": held_a,
        "b_held": held_b,
        "note": None,
    }
    if held_a and not held_b:
        portfolio_context["note"] = (
            f"Already hold {a['symbol']} — compare asks why add/switch to {b['symbol']}, "
            "not a fresh pair trade."
        )
    elif held_b and not held_a:
        portfolio_context["note"] = (
            f"Already hold {b['symbol']} — compare asks why add/switch to {a['symbol']}, "
            "not a fresh pair trade."
        )
    elif held_a and held_b:
        portfolio_context["note"] = "Both held — compare is concentration / relative thesis check."

    # Verdict
    if blockers:
        verdict = VERDICT_INSUFFICIENT
        summary = (
            f"Insufficient identity/pack on one side — classify business before "
            f"comparing {a['symbol']} vs {b['symbol']}."
        )
    elif a.get("mos") is None and b.get("mos") is None and same_pack and not why_diff:
        verdict = VERDICT_SAME_LENS
        summary = (
            f"{a['symbol']} and {b['symbol']} share a thin same-lens view — "
            "close company-specific distinctiveness gaps before ranking."
        )
    elif not same_pack and (a.get("pack_id") and b.get("pack_id")):
        verdict = VERDICT_INCOMPARABLE
        summary = (
            f"{a['symbol']} ({a['pack_id']}) and {b['symbol']} ({b['pack_id']}) are "
            "different business types — do not rank on a shared DD template. "
            "Compare opportunity cost only after each has MoS on its own path."
        )
    else:
        verdict = VERDICT_RESEARCH
        summary = (
            f"Compare frames research priority between {a['symbol']} and {b['symbol']}; "
            "not a buy recommendation."
        )

    return {
        "version": VERSION,
        "as_of": utc_now_iso(),
        "a": a,
        "b": b,
        "axes": axes,
        "why_not_interchangeable": why_diff,
        "prefer_deeper_research": {
            "symbol": prefer_sym,
            "reasons": prefer_reasons,
        },
        "portfolio_context": portfolio_context,
        "verdict": verdict,
        "summary": summary,
        "honesty": (
            "SI.6 frames ‘Why A vs B?’ for research priority and lens honesty. "
            "It is not a buy ticket — MoS, evidence sufficiency, and capital rules still gate size."
        ),
        "blockers": blockers,
    }
