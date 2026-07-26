"""OX.4 — deterministic Goal / learner progress narratives.

No LLM required. Cold-start honesty: when M0 phase=learning or confidence=very_low,
the narrative says so explicitly.
"""

from __future__ import annotations

from typing import Any


def build_progress_report(
    goal: dict[str, Any],
    *,
    book: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
    watchlist: dict[str, Any] | None = None,
    mentor_advice: str | None = None,
) -> dict[str, Any]:
    """Assemble structured progress + human narrative for a Goal."""
    goal = goal or {}
    obj = goal.get("objective") if isinstance(goal.get("objective"), dict) else {}
    objective_text = str(obj.get("text") or goal.get("title") or "").strip()
    criteria = goal.get("success_criteria") if isinstance(goal.get("success_criteria"), dict) else {}
    criteria_text = str((criteria or {}).get("text") or "").strip()

    wl = watchlist or {}
    extra = wl.get("extra") if isinstance(wl.get("extra"), dict) else {}
    ranked = list(wl.get("ranked") or wl.get("watchlist") or [])
    phase = str(extra.get("phase") or "").strip().lower()
    confidence = str(extra.get("confidence") or "").strip().lower()
    if not phase and ranked:
        # Infer from first ranked row (IL.3 contract)
        phase = str((ranked[0] or {}).get("phase") or "").strip().lower()
        confidence = str((ranked[0] or {}).get("confidence") or confidence).strip().lower()

    learning = phase == "learning" or confidence in {"very_low", "very-low"}

    bullets: list[str] = []
    bullets.append(f"Status: {goal.get('status') or 'active'}")
    if criteria_text:
        bullets.append(f"Success criteria: {criteria_text}")

    prog = goal.get("program_id")
    pkey = goal.get("portfolio_key")
    if prog or pkey:
        bullets.append(
            f"Links: program={prog or '—'}, portfolio={pkey or '—'}"
        )
    else:
        bullets.append("Links: none yet (Goal stands alone — Program/Portfolio optional)")

    persona = None
    if isinstance(book, dict):
        persona = book.get("persona") if isinstance(book.get("persona"), dict) else None
        if persona:
            bullets.append(
                "Persona: "
                f"objective={persona.get('objective')}, "
                f"risk={persona.get('risk')}, "
                f"horizon={persona.get('time_horizon')}, "
                f"capital={persona.get('capital')}"
            )

    equity = cash = None
    positions_n = 0
    realized = None
    if isinstance(snapshot, dict) and snapshot:
        try:
            equity = float(snapshot.get("equity"))
        except (TypeError, ValueError):
            equity = None
        try:
            cash = float(snapshot.get("cash"))
        except (TypeError, ValueError):
            cash = None
        positions_n = len(snapshot.get("positions") or [])
        try:
            realized = float(snapshot.get("realized_pnl"))
        except (TypeError, ValueError):
            realized = None
        start = None
        if persona and persona.get("capital") is not None:
            try:
                start = float(persona["capital"])
            except (TypeError, ValueError):
                start = None
        if equity is not None:
            vs = ""
            if start and start > 0:
                pct = ((equity - start) / start) * 100.0
                vs = f" ({pct:+.1f}% vs start)"
            bullets.append(
                f"Sim book: equity={equity:,.0f}, cash={cash if cash is not None else '—'}, "
                f"open positions={positions_n}, realized_pnl={realized if realized is not None else 0}{vs}"
            )
        else:
            bullets.append("Sim book: linked but no snapshot yet")
    elif pkey:
        bullets.append("Sim book: portfolio linked — no live snapshot yet")

    if ranked:
        top = ranked[:3]
        why_bits = []
        for r in top:
            if not isinstance(r, dict):
                continue
            sym = r.get("symbol") or "?"
            reason = (r.get("reason") or "").strip()
            why_bits.append(f"{sym}" + (f" ({reason})" if reason else ""))
        bullets.append("Watchlist top: " + "; ".join(why_bits))
        if learning:
            bullets.append(
                "Cold start: Atlas is still Learning — ranking confidence is very low; "
                "do not treat scores as proven edge."
            )
        elif phase:
            bullets.append(f"Universe phase={phase}, confidence={confidence or 'n/a'}")
    else:
        bullets.append("Watchlist: none published yet (start M0 / Investment Universe)")

    daily = extra.get("daily_plan") if isinstance(extra.get("daily_plan"), dict) else None
    if daily and daily.get("summary"):
        bullets.append(f"Today's plan: {daily.get('summary')}")
        cands = daily.get("candidates") or []
        if cands:
            bits = []
            for c in cands[:3]:
                if not isinstance(c, dict):
                    continue
                bits.append(
                    f"{c.get('symbol')}≈{c.get('suggested_notional')}"
                )
            if bits:
                bullets.append("Plan sizes (sim): " + "; ".join(bits))
    elif ranked:
        bullets.append(
            "Today's plan: not cached yet — GET /v1/planning/daily-investment-plan"
        )

    if mentor_advice:
        bullets.append(f"Mentor: {mentor_advice.strip()[:240]}")
    else:
        bullets.append("Mentor: no scoped lesson yet")

    # Paragraph
    if learning:
        para = (
            f"Toward “{objective_text or goal.get('title')}”, Atlas is in an early Learning phase"
            f"{' on book ' + str(pkey) if pkey else ''}. "
            "Confidence is intentionally very low until enough market history lands — "
            "this is honesty, not a finished ranking."
        )
    elif equity is not None and pkey:
        para = (
            f"Toward “{objective_text or goal.get('title')}”, the linked simulation book "
            f"“{pkey}” shows equity {equity:,.0f} with {positions_n} open position(s). "
            "Ranking and mentor signals below summarize what Atlas is watching next."
        )
    elif pkey:
        para = (
            f"Toward “{objective_text or goal.get('title')}”, portfolio “{pkey}” is linked "
            "but the ledger snapshot is not available yet. Watchlist and mentor lines still apply."
        )
    else:
        para = (
            f"Goal “{objective_text or goal.get('title')}” is recorded as an objective"
            f"{' (' + str(goal.get('status')) + ')' if goal.get('status') else ''}. "
            "No Program/Portfolio link yet — attach one when you want Atlas to pursue it in simulation."
        )

    progress = {
        "phase": "learning" if learning else (phase or "active"),
        "confidence": confidence or ("very_low" if learning else "n/a"),
        "note": para,
        "narrative": para,
        "bullets": bullets,
        "equity": equity,
        "cash": cash,
        "open_positions": positions_n,
        "realized_pnl": realized,
        "watchlist_top": [
            {
                "symbol": r.get("symbol"),
                "rank": r.get("rank"),
                "score": r.get("score"),
                "reason": r.get("reason"),
                "phase": r.get("phase"),
                "confidence": r.get("confidence"),
            }
            for r in ranked[:5]
            if isinstance(r, dict)
        ],
        "daily_plan": daily,
        "mentor_advice": (mentor_advice or "")[:500] or None,
        "portfolio_key": pkey,
        "program_id": prog,
    }
    return {
        "goal": goal,
        "progress": progress,
        "narrative": para,
        "bullets": bullets,
        "version": "ox.4",
    }


def format_progress_answer(report: dict[str, Any]) -> str:
    """Chat-ready block: one paragraph + bullets."""
    lines = [str(report.get("narrative") or "").strip(), ""]
    for b in report.get("bullets") or []:
        lines.append(f"- {b}")
    return "\n".join(lines).strip()
