"""Planning OS — goal → gaps → compare → risk → decide (OI-PA-PLAN / PA.1).

Platform service. Deterministic first (no LLM required). Uses Mission Context to
see what is already known, names gaps honestly, compares a small alternative set,
estimates coarse risk, optionally consults Policy for soft notes, then recommends
gather / decide / simulate next steps.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any

_WORD = re.compile(r"[a-z0-9.+-]+", re.I)


@dataclass
class PlanningResult:
    goal: str
    program_id: str | None
    gaps: list[dict[str, Any]] = field(default_factory=list)
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    risks: list[dict[str, Any]] = field(default_factory=list)
    policy_notes: list[dict[str, Any]] = field(default_factory=list)
    recommended: list[dict[str, Any]] = field(default_factory=list)
    decision: dict[str, Any] = field(default_factory=dict)
    context_summary: str = ""
    context_citations: list[str] = field(default_factory=list)
    version: str = "pa.1"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class PlanningService:
    """Multi-step planning loop for any Program (Market / Engineering / Personal)."""

    name = "planning"
    VERSION = "pa.1"

    def __init__(
        self,
        *,
        mission_context: Any | None = None,
        policy: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._context = mission_context
        self._policy = policy
        self._logger = logger or logging.getLogger("atlas.planning")

    def plan(
        self,
        goal: str,
        *,
        program_id: str | None = None,
        limit: int = 12,
    ) -> dict[str, Any]:
        goal = (goal or "").strip()
        if not goal:
            return PlanningResult(
                goal="",
                program_id=program_id,
                gaps=[{"id": "goal", "detail": "empty goal — nothing to plan"}],
                decision={
                    "action": "hold",
                    "why": "no goal provided",
                    "side_effecting": False,
                },
            ).as_dict()

        program_id = (program_id or _infer_program(goal) or "").strip() or None
        ctx = self._gather_context(goal, program_id=program_id, limit=limit)
        gaps = _identify_gaps(goal, ctx, program_id)
        alternatives = _compare_alternatives(goal, ctx, program_id)
        risks = _estimate_risks(goal, ctx, program_id)
        policy_notes = self._policy_notes(goal, program_id)
        recommended = _recommend_actions(goal, gaps, alternatives, program_id)
        decision = _pick_decision(goal, alternatives, risks, policy_notes, recommended)

        return PlanningResult(
            goal=goal,
            program_id=program_id,
            gaps=gaps,
            alternatives=alternatives,
            risks=risks,
            policy_notes=policy_notes,
            recommended=recommended,
            decision=decision,
            context_summary=str(ctx.get("summary") or ""),
            context_citations=list(ctx.get("citations") or [])[:8],
        ).as_dict()

    def _gather_context(
        self, goal: str, *, program_id: str | None, limit: int
    ) -> dict[str, Any]:
        if self._context is None:
            return {"items": [], "summary": "", "citations": [], "sources": []}
        try:
            return self._context.gather(goal, program_id=program_id, limit=limit) or {}
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("mission_context gather skipped: %s", exc)
            return {"items": [], "summary": "", "citations": [], "sources": []}

    def _policy_notes(self, goal: str, program_id: str | None) -> list[dict[str, Any]]:
        if self._policy is None:
            return []
        notes: list[dict[str, Any]] = []
        goal_l = goal.lower()
        scopes: list[str] = []
        if program_id:
            # Program ids may be aliases (market → market_intelligence); accept both.
            scopes.append(f"domain:{program_id}")
            if program_id in ("market", "market_intelligence"):
                scopes.extend(["domain:markets", "domain:market"])
        try:
            influences = (
                self._policy.retrieval_influence(scopes=scopes)
                if scopes
                else self._policy.retrieval_influence()
            ) or []
            for inf in influences[:8]:
                if not isinstance(inf, dict):
                    continue
                subj = str(inf.get("subject") or "").lower()
                if subj and subj not in goal_l and not any(
                    t in goal_l for t in _WORD.findall(subj) if len(t) > 2
                ):
                    continue
                notes.append(
                    {
                        "kind": "soft",
                        "subject": inf.get("subject"),
                        "rule": inf.get("rule"),
                        "scope": inf.get("scope"),
                        "weight": inf.get("weight"),
                        "detail": "policy influence (not a hard block)",
                    }
                )
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("policy notes skipped: %s", exc)
        return notes[:8]


def _infer_program(goal: str) -> str | None:
    g = goal.lower()
    if any(k in g for k in ("stock", "market", "nse", "bse", "trade", "equity", "invest")):
        return "market"
    if any(k in g for k in ("repo", "code", "git", "architecture", "bug")):
        return "engineering"
    if any(k in g for k in ("email", "calendar", "personal", "resume", "job")):
        return "personal"
    return None


def _identify_gaps(
    goal: str, ctx: dict[str, Any], program_id: str | None
) -> list[dict[str, Any]]:
    items = list(ctx.get("items") or [])
    kinds = {str(i.get("item_kind") or i.get("kind") or "") for i in items}
    gaps: list[dict[str, Any]] = []
    g = goal.lower()

    if not items:
        gaps.append(
            {
                "id": "context_empty",
                "detail": "Mission Context returned nothing for this goal",
                "suggested": "gather",
            }
        )
    if "finding" not in kinds and "chunk" not in kinds:
        gaps.append(
            {
                "id": "knowledge",
                "detail": "No Knowledge findings/chunks matched the goal",
                "suggested": "research_or_ingest",
            }
        )
    if program_id == "market":
        if "world_fact" not in kinds and any(
            k in g for k in ("settlement", "exchange", "session", "nse", "bse")
        ):
            gaps.append(
                {
                    "id": "world_model",
                    "detail": "No World Model fact matched market structure query",
                    "suggested": "consult_world_models",
                }
            )
        if any(k in g for k in ("buy", "sell", "invest", "position")):
            if "experience_advice" not in kinds:
                gaps.append(
                    {
                        "id": "experience",
                        "detail": "No Experience advice yet — Mentor / closed trades thin",
                        "suggested": "run_decision_simulation",
                    }
                )
            if not any(k in g for k in ("risk", "drawdown", "size")):
                gaps.append(
                    {
                        "id": "risk_params",
                        "detail": "Goal lacks explicit risk limits (size / drawdown)",
                        "suggested": "set_constraints",
                    }
                )
    return gaps


def _compare_alternatives(
    goal: str, ctx: dict[str, Any], program_id: str | None
) -> list[dict[str, Any]]:
    g = goal.lower()
    alts: list[dict[str, Any]] = [
        {
            "id": "gather_more",
            "label": "Gather missing information first",
            "score": 0.7,
            "why": "Reduce blind spots before acting",
        },
        {
            "id": "hold",
            "label": "Hold / wait",
            "score": 0.5,
            "why": "Default when risk or gaps are high",
        },
    ]
    if program_id == "market" or any(k in g for k in ("buy", "sell", "trade", "invest")):
        alts.append(
            {
                "id": "simulate",
                "label": "Decision Simulation (paper)",
                "score": 0.85,
                "why": "P10 — simulate fills; never broker login",
            }
        )
        alts.append(
            {
                "id": "research_event",
                "label": "Spawn research Job",
                "score": 0.75,
                "why": "Fill Knowledge gaps via Event Research / research",
            }
        )
    if program_id == "engineering" or "bug" in g or "repo" in g:
        alts.append(
            {
                "id": "repo_learn",
                "label": "Repository learning / architecture read",
                "score": 0.8,
                "why": "Engineering Program path",
            }
        )
    if any(k in g for k in ("verify", "claim", "trust")):
        alts.append(
            {
                "id": "verify",
                "label": "Verify findings",
                "score": 0.9,
                "why": "Verification OS before trusting claims",
            }
        )
    # Boost gather if context empty
    if not (ctx.get("items") or []):
        for a in alts:
            if a["id"] == "gather_more":
                a["score"] = 0.95
                a["why"] = "No context yet — gather first"
    alts.sort(key=lambda a: float(a.get("score") or 0), reverse=True)
    return alts


def _estimate_risks(
    goal: str, ctx: dict[str, Any], program_id: str | None
) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    g = goal.lower()
    if any(k in g for k in ("buy", "sell", "trade", "invest", "live", "broker")):
        risks.append(
            {
                "id": "real_money",
                "severity": "high",
                "detail": "Real trading is forbidden here — use Decision Simulation only (P10)",
            }
        )
    if not (ctx.get("items") or []):
        risks.append(
            {
                "id": "blind_decision",
                "severity": "medium",
                "detail": "Acting without Mission Context increases error risk",
            }
        )
    if "contested" in str(ctx.get("summary") or "").lower():
        risks.append(
            {
                "id": "contested_knowledge",
                "severity": "medium",
                "detail": "Context may include contested claims — verify before relying",
            }
        )
    if program_id == "market" and "earnings" in g:
        risks.append(
            {
                "id": "pre_earnings",
                "severity": "medium",
                "detail": "Pre-earnings entries are often constrained by Policy (when configured)",
            }
        )
    return risks


def _recommend_actions(
    goal: str,
    gaps: list[dict[str, Any]],
    alternatives: list[dict[str, Any]],
    program_id: str | None,
) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    for gap in gaps[:4]:
        sug = gap.get("suggested")
        if sug == "research_or_ingest":
            recs.append(
                {
                    "action": "research",
                    "detail": gap.get("detail"),
                    "template": "event_research" if program_id == "market" else None,
                }
            )
        elif sug == "run_decision_simulation":
            recs.append(
                {
                    "action": "simulate",
                    "detail": gap.get("detail"),
                    "template": "decision_simulation",
                }
            )
        elif sug == "consult_world_models":
            recs.append(
                {
                    "action": "consult_world_models",
                    "detail": gap.get("detail"),
                    "api": "GET /v1/world-models",
                }
            )
        elif sug == "set_constraints":
            recs.append(
                {
                    "action": "set_policy_constraints",
                    "detail": gap.get("detail"),
                    "note": "Hard limits land with OI-PA-POLICY; set soft avoid/prefer today",
                }
            )
        else:
            recs.append({"action": "gather", "detail": gap.get("detail")})

    top = alternatives[0] if alternatives else None
    if top and top["id"] == "simulate":
        recs.append(
            {
                "action": "simulate",
                "detail": top.get("why"),
                "template": "decision_simulation",
            }
        )
    elif top and top["id"] == "verify":
        recs.append({"action": "verify", "detail": top.get("why"), "tool": "knowledge.verify"})
    elif top and top["id"] == "research_event":
        recs.append(
            {
                "action": "research",
                "detail": top.get("why"),
                "template": "event_research",
            }
        )

    # Dedupe by action
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in recs:
        key = str(r.get("action"))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out[:6]


def _pick_decision(
    goal: str,
    alternatives: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    policy_notes: list[dict[str, Any]],
    recommended: list[dict[str, Any]],
) -> dict[str, Any]:
    high_risk = any(r.get("severity") == "high" for r in risks)
    top = alternatives[0] if alternatives else {"id": "hold", "label": "Hold"}
    action = str(top.get("id") or "hold")
    if high_risk and action not in {"simulate", "gather_more", "hold", "verify"}:
        action = "simulate"
    # Soft policy avoid → prefer gather/hold over aggressive paths
    for note in policy_notes:
        if str(note.get("rule") or "").lower() in {"avoid", "distrust"}:
            if action in {"simulate"} and "buy" in goal.lower():
                action = "gather_more"
            break
    return {
        "action": action,
        "label": top.get("label") if action == top.get("id") else action,
        "why": top.get("why") or "top-ranked alternative",
        "side_effecting": False,
        "next": [r.get("action") for r in recommended[:3]],
        "p10": "simulation / recommend only — no real-world side effects from Planning OS",
    }
