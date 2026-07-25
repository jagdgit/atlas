"""Decision Knowledge helpers (OI-F1).

Turn ``Decision → outcome`` into Experience-OS lessons that can soft-bias future
scoring via the existing OI-MP5 ``LearningService.enable_bias`` /
``DecisionEngine`` exp-bias path. No parallel Knowledge DB.
"""

from __future__ import annotations

from typing import Any


def outcome_label(pnl: float) -> str:
    if pnl > 0:
        return "profit"
    if pnl < 0:
        return "loss"
    return "flat"


def should_enable_decision_bias(outcome: str) -> bool:
    """Flat outcomes are inconclusive — do not soft-bias from a single no-signal close."""
    return str(outcome or "").lower() in {"profit", "loss"}


def decision_knowledge_tags(
    symbol: str,
    outcome: str,
    *,
    decision_id: str | None = None,
    action_kind: str = "sell",
) -> list[str]:
    sym = str(symbol or "").strip().lower()
    tags = [
        sym,
        "paper_trading",
        "decision_simulation",
        "decision_knowledge",
        str(outcome).lower(),
        "experience_journal",
        f"{action_kind}:{sym}" if sym else action_kind,
    ]
    if decision_id:
        tags.append(f"decision:{decision_id}")
    return [t for t in tags if t]


def bias_recommendations(
    symbol: str, outcome: str, pnl: float
) -> list[dict[str, str]]:
    """Terms that can overlap ScoredOption tags/keys for soft prefer influence."""
    sym = str(symbol or "").strip().lower()
    if outcome == "profit":
        return [
            {"title": sym or "markets", "why": f"profitable close {pnl:+.2f}"},
            {"title": "buy", "why": f"winning setup on {sym or 'symbol'}"},
            {"title": "momentum", "why": "common strategy tag reinforcement"},
        ]
    if outcome == "loss":
        return [
            {"title": sym or "markets", "why": f"losing close {pnl:+.2f}"},
            {"title": "hold", "why": f"caution after loss on {sym or 'symbol'}"},
            {"title": "risk", "why": "review entry timing and risk limits"},
        ]
    return []


def experience_id_from_result(result: Any) -> str | None:
    """Pull the applied experience id from ``remember_experience`` / ``journal`` result."""
    if not isinstance(result, dict):
        return None
    # ExperienceOS.journal wraps LearningService result under "result"
    inner = result.get("result") if isinstance(result.get("result"), dict) else result
    if not isinstance(inner, dict):
        return None
    event = inner.get("event") if isinstance(inner.get("event"), dict) else {}
    ref = event.get("ref_id") or inner.get("ref_id")
    if ref:
        return str(ref)
    exp = inner.get("experience")
    if isinstance(exp, dict) and exp.get("id"):
        return str(exp["id"])
    return None


def link_metadata(
    *,
    decision_id: str | None,
    symbol: str,
    outcome: str,
    pnl: float,
    mission_type: str = "decision_simulation",
) -> dict[str, Any]:
    return {
        "decision_knowledge": True,
        "decision_id": str(decision_id) if decision_id else None,
        "symbol": str(symbol),
        "outcome": outcome,
        "pnl": float(pnl),
        "mission_type": mission_type,
        "action_key": f"sell:{str(symbol).lower()}",
    }
