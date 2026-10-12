"""Deterministic investigation plans.

JobPlanner is consulted only for open objectives that have no evidence ladder.
Invalid or unsafe steps are dropped. An empty plan is PLANNING_FAILED, not silence.
Live toolbox steps (sql/logs/git/code) are only kept when present in the unified catalog (J1).
"""

from __future__ import annotations

import re
from typing import Any

from atlas.agent_kernel.bus import (
    DERIVED_REQUIREMENTS,
    LADDER,
    LIVE_TOOLBOX,
    NEWS_REQUIREMENTS,
)
from atlas.agent_kernel.safety import capability_allowed

_ACQUIRE_FOR = {
    "company_news": ("local_market_store", "knowledge_search", "news_search", "web_search", "research_scientist"),
    "news": ("local_market_store", "knowledge_search", "news_search", "web_search"),
}

_SQL_FENCE_RE = re.compile(r"```sql\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_DB_OBJECTIVE_RE = re.compile(
    r"\b(sql|database|postgres|scheduler\.|task_runs|schedules|"
    r"query\s+the\s+(?:database|db)|how many\b.*\b(fail|schedule|task))",
    re.IGNORECASE,
)
# Blind North-Star / ops self-diagnosis phrasing (no tool hints from the operator).
_OPS_OBJECTIVE_RE = re.compile(
    r"\b("
    r"scheduled[- ]?task\s+fail|task\s+fail|root\s+cause|"
    r"self[- ]?diagnos|why\s+atlas\s+.*fail|large\s+number\s+of\s+.*fail|"
    r"retention_prune|no\s+handler\s+registered"
    r")\b",
    re.IGNORECASE,
)


def _memory_key(requirement: str, capability: str) -> str:
    return f"{requirement}|{capability}"


def known_failure(memory: dict[str, Any], requirement: str, capability: str, generation: int) -> dict[str, Any] | None:
    row = memory.get(_memory_key(requirement, capability))
    if not isinstance(row, dict):
        return None
    if int(generation) > int(row.get("generation") or 0):
        return None
    return row


def plan_investigation(
    task: dict[str, Any],
    *,
    catalog_names: list[str],
    availability: dict[str, bool],
    generations: dict[str, int],
    failure_memory: dict[str, Any],
    job_planner: Any = None,
) -> dict[str, Any]:
    objective = str(task.get("objective") or "").strip()
    if not objective or task.get("constraints", {}).get("refuse_plan"):
        return {
            "ok": False,
            "status": "PLANNING_FAILED",
            "reason": "no safe plan: objective empty or planning refused",
            "steps": [],
            "source": "deterministic_ladder",
        }

    required = [str(r) for r in (task.get("required") or []) if r]
    interpretive = bool(task.get("interpretive"))

    # C4/C5 — a hypothesis test is one deterministic step that hands the work to the
    # existing FEL queue. The kernel orchestrates; it does not evaluate models.
    if required == ["hypothesis_test"] and task.get("hypothesis_id"):
        return {
            "ok": True,
            "status": "PLANNED",
            "reason": "hypothesis test delegated to the FEL experiment queue",
            "source": "cognitive_loop",
            "steps": [
                {
                    "id": "s0",
                    "kind": "hypothesis_test",
                    "capability": "python_calculation",
                    "requirement": "hypothesis_test",
                    "description": (
                        f"Enqueue FEL experiment for hypothesis {task['hypothesis_id']}"
                    ),
                    "depends_on": None,
                }
            ],
            "skipped": [],
        }
    if not required and job_planner is not None:
        return _from_job_planner(job_planner, objective, catalog_names=catalog_names)

    if not required and job_planner is None:
        return {
            "ok": False,
            "status": "PLANNING_FAILED",
            "reason": "no evidence requirements and no job planner available",
            "steps": [],
            "source": "deterministic_ladder",
        }

    steps: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    index = 0
    for requirement in required:
        if requirement in DERIVED_REQUIREMENTS:
            continue
        caps = _ACQUIRE_FOR.get(requirement) or tuple(
            name for name, _level in LADDER if name != "cognitive_core"
        )
        if requirement in NEWS_REQUIREMENTS:
            caps = _ACQUIRE_FOR.get(requirement, caps)
        for capability in caps:
            if capability not in catalog_names:
                continue
            if not capability_allowed(capability):
                continue
            if requirement not in NEWS_REQUIREMENTS and capability == "news_search":
                continue
            prior = known_failure(
                failure_memory,
                requirement,
                capability,
                int(generations.get(capability) or 0),
            )
            if prior:
                skipped.append(
                    {
                        "requirement": requirement,
                        "capability": capability,
                        "reason": (
                            "previously failed because "
                            f"{prior.get('error') or 'the same approach failed'}"
                        ),
                    }
                )
                continue
            if not availability.get(capability, False):
                skipped.append(
                    {
                        "requirement": requirement,
                        "capability": capability,
                        "reason": f"{capability}_unavailable",
                    }
                )
                continue
            steps.append(
                {
                    "id": f"s{index}",
                    "kind": "acquire",
                    "capability": capability,
                    "requirement": requirement,
                    "description": f"Try {capability} for {requirement}",
                    "depends_on": None,
                }
            )
            index += 1

    derived = [r for r in required if r in DERIVED_REQUIREMENTS]
    if derived or "relative_strength" in required or task.get("needs_relative_strength"):
        steps.append(
            {
                "id": f"s{index}",
                "kind": "calculate",
                "capability": "python_calculation",
                "requirement": "relative_strength",
                "description": "Calculate relative strength from retrieved price and sector series",
                "depends_on": None,
            }
        )
        index += 1

    steps.append(
        {
            "id": f"s{index}",
            "kind": "lookup_experience",
            "capability": "experience_lookup",
            "requirement": None,
            "description": "Retrieve prior failures for this objective",
            "depends_on": None,
        }
    )
    index += 1
    if interpretive or required:
        steps.append(
            {
                "id": f"s{index}",
                "kind": "interpret",
                "capability": "cognitive_core",
                "requirement": None,
                "description": "Interpret collected evidence or name what is still missing",
                "depends_on": None,
            }
        )
        index += 1
    steps.append(
        {
            "id": f"s{index}",
            "kind": "verify",
            "capability": "verifier",
            "requirement": None,
            "description": "Verify evidence, provenance, and that nothing was invented",
            "depends_on": None,
        }
    )

    criteria = _criteria(task)
    return {
        "ok": True,
        "status": "PLANNED",
        "source": "deterministic_ladder",
        "steps": steps,
        "skipped_known_failures": skipped,
        "success_criteria": criteria["success"],
        "failure_criteria": criteria["failure"],
        "verification_criteria": criteria["verification"],
    }


def _criteria(task: dict[str, Any]) -> dict[str, str]:
    if task.get("deterministic_only"):
        return {
            "success": "deterministic calculation + input provenance + sanity checks",
            "failure": "inputs missing or value invented",
            "verification": "calculation",
        }
    if task.get("interpretive"):
        return {
            "success": "answer + evidence + uncertainty + falsifiers",
            "failure": "missing critical evidence or unverified interpretation",
            "verification": "research",
        }
    return {
        "success": "required evidence present + citations + not invented",
        "failure": "requirement still missing after the escalation ladder",
        "verification": "investigation",
    }


def _from_job_planner(
    job_planner: Any,
    objective: str,
    *,
    catalog_names: list[str] | None = None,
) -> dict[str, Any]:
    catalog = set(catalog_names or [])
    try:
        proposed = job_planner.decompose(objective) or []
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "PLANNING_FAILED",
            "reason": f"job planner failed: {exc}",
            "steps": [],
            "source": "job_planner",
        }
    steps = []
    for i, step in enumerate(proposed):
        intent = str(getattr(step, "intent", "") or "")
        capability = str(getattr(step, "capability", "") or "")
        if not capability_allowed(capability) or not capability_allowed(intent):
            continue
        # J1: live toolbox steps require a registered catalog entry.
        if capability in LIVE_TOOLBOX and catalog and capability not in catalog:
            continue
        steps.append(
            {
                "id": f"j{i}",
                "kind": "job_step",
                "capability": capability,
                "requirement": None,
                "description": str(getattr(step, "description", "") or intent),
                "args": dict(getattr(step, "args", {}) or {}),
                "depends_on": getattr(step, "depends_on", None),
            }
        )
    steps = _ensure_ops_investigation_steps(steps, objective, catalog)
    if _OPS_OBJECTIVE_RE.search(objective or ""):
        # Ops self-diagnosis must run executable toolbox steps, not open-ended
        # research/agent fillers that the kernel cannot invoke.
        steps = [
            s
            for s in steps
            if str(s.get("capability") or "") in LIVE_TOOLBOX
        ]
    if not steps:
        return {
            "ok": False,
            "status": "PLANNING_FAILED",
            "reason": "job planner returned no safe steps",
            "steps": [],
            "source": "job_planner",
        }
    return {
        "ok": True,
        "status": "PLANNED",
        "source": "job_planner",
        "steps": steps,
        "skipped_known_failures": [],
        "success_criteria": "planned steps finished without a forbidden side effect",
        "failure_criteria": "planner produced nothing safe",
        "verification_criteria": "investigation",
    }


def _ensure_ops_investigation_steps(
    steps: list[dict[str, Any]],
    objective: str,
    catalog: set[str],
) -> list[dict[str, Any]]:
    """Ground open objectives on the live toolbox (sql ± logs) when the ask is ops/DB."""
    ops = bool(_OPS_OBJECTIVE_RE.search(objective or ""))
    db = bool(_DB_OBJECTIVE_RE.search(objective or ""))
    if not ops and not db:
        return steps
    out = _repair_sql_args(list(steps), objective)
    have = {str(s.get("capability") or "") for s in out}
    prepend: list[dict[str, Any]] = []
    if "sql" in catalog and "sql" not in have:
        prepend.append(
            {
                "id": "j_sql",
                "kind": "job_step",
                "capability": "sql",
                "requirement": None,
                "description": "Query Atlas database for failure evidence",
                "args": _sql_args_from_objective(objective, ops=ops),
                "depends_on": None,
            }
        )
    if ops and "logs" in catalog and "logs" not in have:
        prepend.append(
            {
                "id": "j_logs",
                "kind": "job_step",
                "capability": "logs",
                "requirement": None,
                "description": "Search Atlas logs for matching failure signatures",
                "args": {
                    "pattern": r"retention_prune|no handler registered|TaskCompleted",
                    "file": "all",
                    "max_matches": 40,
                },
                "depends_on": None,
            }
        )
    return prepend + out


def _repair_sql_args(
    steps: list[dict[str, Any]], objective: str
) -> list[dict[str, Any]]:
    out = []
    for s in steps:
        if str(s.get("capability") or "") != "sql":
            out.append(s)
            continue
        args = dict(s.get("args") or {})
        if not str(args.get("sql") or "").strip():
            args = _sql_args_from_objective(objective)
        elif not str(args.get("source") or "").strip():
            args["source"] = "atlas"
        out.append({**s, "args": args})
    return out


def _sql_args_from_objective(objective: str, *, ops: bool = False) -> dict[str, Any]:
    fence = _SQL_FENCE_RE.search(objective or "")
    if fence:
        return {"sql": fence.group(1).strip(), "source": "atlas"}
    if ops:
        return {
            "sql": (
                "SELECT left(coalesce(error,''), 160) AS err, count(*)::int AS n "
                "FROM scheduler.task_runs "
                "WHERE status = 'failed' AND started_at >= current_date - interval '2 days' "
                "GROUP BY 1 ORDER BY n DESC LIMIT 25"
            ),
            "source": "atlas",
        }
    return {
        "sql": (
            "SELECT task_type, count(*)::int AS n "
            "FROM scheduler.task_runs "
            "WHERE status = 'failed' AND started_at >= current_date "
            "GROUP BY 1 ORDER BY n DESC LIMIT 20"
        ),
        "source": "atlas",
    }
