"""Phase 7 — blind North-Star self-diagnosis (plan + execute sql/logs)."""

from __future__ import annotations

from pathlib import Path

from atlas.agent_kernel.bus import build_unified_catalog
from atlas.agent_kernel.kernel import AgentKernel
from atlas.agent_kernel.planner import plan_investigation
from atlas.jobs.planner import JobPlanner
from atlas.kernel.capabilities import CapabilityRegistry
from atlas.kernel.tools import ToolRegistry
from atlas.planner.planner import Planner

NORTH_STAR = (
    "Investigate why Atlas experienced a large number of scheduled-task failures today. "
    "Determine the root cause, verify using available evidence, and report what should be done."
)


def _toolbox():
    caps = CapabilityRegistry()
    tools = ToolRegistry()

    def sql_query(*, sql, source=None, limit=None, params=None):
        return {
            "outcome": "ok",
            "rows": [
                {"err": "no handler registered for task_type 'retention_prune'", "n": 1200},
                {"err": "other", "n": 3},
            ],
            "columns": ["err", "n"],
        }

    def logs_search(*, pattern, file=None, max_matches=None):
        return {
            "outcome": "ok",
            "matches": [{"file": "atlas.log", "line": 1, "text": "retention_prune"}],
        }

    caps.register("sql", object(), kind="plugin")
    caps.register("logs", object(), kind="plugin")
    tools.register("sql.query", sql_query, description="q", params={"sql": "str"}, plugin="sql")
    tools.register(
        "logs.search", logs_search, description="s", params={"pattern": "str"}, plugin="logs"
    )
    return caps, tools


def test_north_star_objective_plans_sql_and_logs():
    caps, tools = _toolbox()
    catalog = build_unified_catalog(caps, tools)
    planned = plan_investigation(
        {"objective": NORTH_STAR, "required": []},
        catalog_names=list(catalog),
        availability={n: True for n in catalog},
        generations={n: 0 for n in catalog},
        failure_memory={},
        job_planner=JobPlanner(Planner(), llm=None, research_first=False),
    )
    assert planned["ok"], planned
    caps_used = {s["capability"] for s in planned["steps"]}
    assert "sql" in caps_used
    assert "logs" in caps_used
    sql = next(s for s in planned["steps"] if s["capability"] == "sql")
    assert sql["args"].get("sql")


def test_north_star_cycle_executes_tools_and_emits_candidate(tmp_path: Path):
    caps, tools = _toolbox()
    kernel = AgentKernel(tmp_path, job_planner=JobPlanner(Planner(), llm=None, research_first=False))
    kernel.bind_live_toolbox(caps, tools)
    report = kernel.cycle(
        mode="event",
        observations=[
            {
                "source": "operator",
                "domain": "ops",
                "symbol": "",
                "objective": NORTH_STAR,
                "reason": "blind North-Star self-diagnosis",
                "decision_impact": True,
                "priority_class": "P0",
                "required": [],
                "interpretive": False,
            }
        ],
        allow_external=False,
        max_investigations=1,
    )
    assert report.get("ran"), report
    tasks = [t for t in kernel.state["tasks"].values() if NORTH_STAR[:40] in str(t.get("objective"))]
    assert tasks
    task = tasks[0]
    attempted = set(task.get("attempted_capabilities") or [])
    assert "sql" in attempted and "logs" in attempted
    assert set(task.get("succeeded") or []) >= {"sql", "logs"}
    assert task.get("status") == "SUCCESS"
    assert task.get("next_question")
    assert task.get("learning_candidate_path")
    assert Path(task["learning_candidate_path"]).is_file()
    # Experience persisted for later ticks.
    assert kernel.state.get("experiences")
    assert any(q.get("not_operator_supplied") for q in kernel.state.get("open_questions") or [])
