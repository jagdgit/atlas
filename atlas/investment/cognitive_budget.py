"""OI-COG-BUDGET0 — Cognitive Budget (deterministic scoring).

Spend LLM / research passes where importance × novelty × uncertainty is highest.
Not every ticker every night.
"""

from __future__ import annotations

from typing import Any

VERSION = "cog.budget.v1"

# Locked defaults (BRE plan §4 / A11)
DEFAULT_NIGHTLY_LLM_PASSES = 3
DEFAULT_CURIOSITY_TASKS = 3


def score_dimensions(
    *,
    importance: str = "medium",
    novelty: str = "medium",
    uncertainty: str = "medium",
) -> dict[str, Any]:
    """Map ordinal dims → llm_budget passes (0 / 1 / 3)."""
    order = {"low": 0, "medium": 1, "high": 2, "unknown": 1}
    imp = order.get(str(importance).lower(), 1)
    nov = order.get(str(novelty).lower(), 1)
    unc = order.get(str(uncertainty).lower(), 1)
    total = imp + nov + unc  # 0..6
    if total >= 5:
        budget = 3
    elif total >= 3:
        budget = 1
    else:
        budget = 0
    return {
        "version": VERSION,
        "importance": importance,
        "novelty": novelty,
        "uncertainty": uncertainty,
        "score_sum": total,
        "llm_budget": budget,
    }


def budget_for_wso(
    wso: dict[str, Any] | None,
    *,
    is_open_position: bool = True,
    has_material_delta: bool = False,
    previously_queued: bool = False,
) -> dict[str, Any]:
    """Heuristic budget from WSO shell fields (no LLM)."""
    w = wso if isinstance(wso, dict) else {}
    unknowns = list(w.get("unknowns") or [])
    unc = w.get("uncertainty") if isinstance(w.get("uncertainty"), dict) else {}
    data_u = str(unc.get("data") or "unknown").lower()
    importance = "high" if is_open_position else "low"
    novelty = "low" if previously_queued else ("high" if unknowns else "medium")
    if has_material_delta:
        novelty = "high" if novelty != "high" else novelty
    uncertainty = "high" if data_u == "high" or len(unknowns) >= 3 else (
        "medium" if unknowns or data_u == "medium" else "low"
    )
    return score_dimensions(
        importance=importance, novelty=novelty, uncertainty=uncertainty
    )


def pick_budgeted(
    items: list[dict[str, Any]],
    *,
    budget_key: str = "llm_budget",
    max_passes: int = DEFAULT_NIGHTLY_LLM_PASSES,
) -> list[dict[str, Any]]:
    """Sort by budget desc and take until pass cap exhausted (each item costs its budget)."""
    ranked = sorted(
        [i for i in items if isinstance(i, dict)],
        key=lambda x: int(x.get(budget_key) or 0),
        reverse=True,
    )
    out: list[dict[str, Any]] = []
    used = 0
    for it in ranked:
        cost = max(0, int(it.get(budget_key) or 0))
        if cost <= 0:
            continue
        if used + cost > int(max_passes):
            continue
        out.append(it)
        used += cost
    return out
