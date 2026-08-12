"""Daily Investment Plan (IL.6) — Planning OS object from M0 ranked watchlist.

Hermetic sizing heuristics only. Simulation guidance — not advice, not orders (P10).
Cold-start honesty: when phase=learning / confidence=very_low, sizes are provisional.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

VERSION = "il.6c"
KIND = "daily_investment_plan"


def build_daily_plan(
    ranked: list[dict[str, Any]] | None,
    *,
    capital: float = 10_000.0,
    program_id: str = "market_intelligence",
    portfolio_key: str | None = None,
    index: str | None = None,
    max_candidates: int = 5,
    deploy_fraction: float = 0.40,
    as_of: str | None = None,
    extra: dict[str, Any] | None = None,
    research_by_symbol: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build today's plan from ranked universe rows (+ optional watchlist extra)."""
    rows = [r for r in (ranked or []) if isinstance(r, dict) and r.get("symbol")]
    extra = dict(extra or {})
    research_map = dict(research_by_symbol or {})
    phase = str(extra.get("phase") or "").strip().lower()
    confidence = str(extra.get("confidence") or "").strip().lower()
    if not phase and rows:
        phase = str(rows[0].get("phase") or "").strip().lower()
        confidence = str(rows[0].get("confidence") or confidence).strip().lower()
    learning = phase == "learning" or confidence in {"very_low", "very-low"}

    try:
        capital_f = max(0.0, float(capital))
    except (TypeError, ValueError):
        capital_f = 10_000.0
    try:
        frac = min(1.0, max(0.0, float(deploy_fraction)))
    except (TypeError, ValueError):
        frac = 0.40
    n = max(1, int(max_candidates))

    candidates_src = rows[:n]
    avoids = _collect_avoids(rows, skip={str(r.get("symbol")) for r in candidates_src})

    budget = capital_f * frac
    per = (budget / len(candidates_src)) if candidates_src else 0.0

    candidates: list[dict[str, Any]] = []
    researched_n = 0
    for i, r in enumerate(candidates_src):
        sym = str(r.get("symbol"))
        score = r.get("score")
        try:
            score_f = float(score) if score is not None else None
        except (TypeError, ValueError):
            score_f = None
        weight = _weight_for(i, len(candidates_src), score_f)
        size = round(budget * weight, 2) if candidates_src else 0.0
        # Equal-weight fallback if weights degenerate
        if size <= 0 and per > 0:
            size = round(per, 2)
        cand: dict[str, Any] = {
            "symbol": sym,
            "name": r.get("name") or "",
            "sector": r.get("sector") or "",
            "rank": r.get("rank") or (i + 1),
            "score": score_f,
            "why": (r.get("reason") or "").strip(),
            "explanations": list(r.get("explanations") or [])[:6],
            "suggested_notional": size,
            "suggested_weight": round(weight, 4),
            "phase": r.get("phase") or phase,
            "confidence": r.get("confidence") or confidence,
            "components": dict(r.get("components") or {}),
        }
        # UTS.C — E[R] × confidence when computable (null under cold-start)
        try:
            from atlas.investment.opportunity_switch import attach_opportunity_metrics

            attach_opportunity_metrics(cand, r)
        except Exception:  # noqa: BLE001
            pass
        # IRA.13 — cite dossier/thesis/coverage when available
        aw = research_map.get(sym) or research_map.get(sym.upper()) or {}
        if not aw and isinstance(r.get("research"), dict):
            aw = r.get("research") or {}
        if aw:
            thesis = aw.get("thesis") if isinstance(aw.get("thesis"), dict) else {}
            cand["research_coverage"] = aw.get("coverage")
            cand["research_confidence"] = aw.get("confidence")
            cand["mvr_satisfied"] = aw.get("mvr_satisfied")
            cand["thesis_stance"] = thesis.get("stance") or aw.get("stance")
            cand["thesis_summary"] = (thesis.get("summary") or aw.get("thesis_summary") or "")[:200]
            # IIP.6 dual confidence / score band on plan candidates
            score = aw.get("investment_score") if isinstance(aw.get("investment_score"), dict) else {}
            if score:
                from atlas.investment.scoring import attach_score_to_ranked_row

                cand = attach_score_to_ranked_row(cand, score)
            if cand["thesis_summary"]:
                researched_n += 1
                cand["explanations"] = list(cand["explanations"]) + [
                    {
                        "sign": "·",
                        "text": f"Thesis ({cand.get('thesis_stance') or '?'}): {cand['thesis_summary'][:120]}",
                        "component": "research",
                    }
                ]
                if not cand["why"]:
                    cand["why"] = cand["thesis_summary"][:160]
            if score.get("path"):
                cand["explanations"] = list(cand.get("explanations") or []) + [
                    {
                        "sign": "·",
                        "text": (
                            f"Score {score.get('overall')} ({score.get('score_band')}) · "
                            f"research={score.get('research_confidence')} · "
                            f"investment={score.get('investment_confidence')} → {score.get('path')}"
                        ),
                        "component": "score",
                    }
                ]
        candidates.append(cand)

    _finalize_weights(candidates, budget)

    notes: list[str] = [
        "Simulation-only plan (P10) — no broker orders.",
        f"Deploy up to {frac:.0%} of capital ({capital_f:,.0f}) across top {len(candidates)} candidates.",
    ]
    if learning:
        notes.append(
            "Cold start: phase=learning / confidence=very_low — treat sizes as provisional, "
            "not a proven edge."
        )
    if researched_n:
        notes.append(
            f"{researched_n}/{len(candidates)} candidate(s) cite Investing Research (coverage/thesis)."
        )
    if not rows:
        notes.append("No ranked watchlist yet — start M0 / India learner first.")
    if avoids:
        notes.append(f"{len(avoids)} symbol(s) flagged avoid / weak relative to the top set.")

    as_of_s = as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {
        "kind": KIND,
        "version": VERSION,
        "as_of": as_of_s,
        "program_id": program_id,
        "portfolio_key": portfolio_key,
        "index": index or extra.get("index"),
        "capital": capital_f,
        "deploy_fraction": frac,
        "phase": "learning" if learning else (phase or "active"),
        "confidence": confidence or ("very_low" if learning else "n/a"),
        "candidates": candidates,
        "avoids": avoids,
        "notes": notes,
        "summary": _summary(candidates, avoids, learning=learning, capital=capital_f),
        "research_cited": researched_n,
    }


def plan_from_watchlist(
    snap: dict[str, Any] | None,
    *,
    capital: float = 10_000.0,
    portfolio_key: str | None = None,
    max_candidates: int = 5,
    deploy_fraction: float = 0.40,
) -> dict[str, Any]:
    """Convenience: build from ``watchlists.latest`` snapshot."""
    snap = snap or {}
    extra = snap.get("extra") if isinstance(snap.get("extra"), dict) else {}
    ranked = list(snap.get("ranked") or [])
    return build_daily_plan(
        ranked,
        capital=capital,
        program_id=str(snap.get("program_id") or "market_intelligence"),
        portfolio_key=portfolio_key,
        index=str(snap.get("index") or "") or None,
        max_candidates=max_candidates,
        deploy_fraction=deploy_fraction,
        extra=extra,
    )


def _weight_for(index: int, n: int, score: float | None) -> float:
    """Prefer score-proportional weights; fall back to equal weight."""
    if n <= 0:
        return 0.0
    if score is None or score <= 0:
        return 1.0 / n
    # Soft: caller normalizes across the set
    return max(0.01, float(score))


def _collect_avoids(
    rows: list[dict[str, Any]],
    *,
    skip: set[str],
) -> list[dict[str, Any]]:
    avoids: list[dict[str, Any]] = []
    for r in rows:
        sym = str(r.get("symbol") or "")
        if not sym or sym in skip:
            continue
        reason = (r.get("reason") or "").lower()
        exps = r.get("explanations") or []
        weak = "weak quality" in reason or "avoid" in reason or "−" in (r.get("reason") or "")
        for e in exps:
            if not isinstance(e, dict):
                continue
            text = str(e.get("text") or "").lower()
            sign = str(e.get("sign") or "")
            if sign == "-" or "weak" in text or "avoid" in text or "policy" in text and "block" in text:
                weak = True
        # Also flag lower half of ranked list beyond candidates as soft avoids
        rank = r.get("rank")
        try:
            rank_i = int(rank) if rank is not None else 999
        except (TypeError, ValueError):
            rank_i = 999
        if weak or rank_i > 10:
            avoids.append(
                {
                    "symbol": sym,
                    "name": r.get("name") or "",
                    "why": (r.get("reason") or "lower-ranked / weaker relative signals").strip(),
                    "rank": rank,
                }
            )
        if len(avoids) >= 8:
            break
    return avoids


def _summary(
    candidates: list[dict[str, Any]],
    avoids: list[dict[str, Any]],
    *,
    learning: bool,
    capital: float,
) -> str:
    if not candidates:
        return "No candidates — publish an Investment Universe watchlist first."
    top = ", ".join(c["symbol"] for c in candidates[:3])
    cold = " (cold-start provisional)" if learning else ""
    return (
        f"Today: {len(candidates)} candidate(s) [{top}]"
        f" from ₹{capital:,.0f} book{cold}; "
        f"{len(avoids)} avoid(s)."
    )


# Re-normalize weights after soft scoring
def _finalize_weights(candidates: list[dict[str, Any]], budget: float) -> None:
    raw = [float(c.get("suggested_weight") or 0.0) for c in candidates]
    total = sum(raw)
    if total <= 0:
        eq = 1.0 / len(candidates) if candidates else 0.0
        for c in candidates:
            c["suggested_weight"] = round(eq, 4)
            c["suggested_notional"] = round(budget * eq, 2)
        return
    for c, w in zip(candidates, raw):
        nw = w / total
        c["suggested_weight"] = round(nw, 4)
        c["suggested_notional"] = round(budget * nw, 2)
