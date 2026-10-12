"""J1 — Agent Kernel plans against the live capability/tool registry.

Acceptance (Phase 6): a DB question yields a real ``sql`` step with args;
sql/logs/git/code are not a parallel orphan catalog.
"""

from __future__ import annotations

from pathlib import Path

from atlas.agent_kernel.bus import (
    LIVE_TOOLBOX,
    build_unified_catalog,
    default_catalog,
)
from atlas.agent_kernel.kernel import AgentKernel
from atlas.agent_kernel.planner import plan_investigation
from atlas.jobs.planner import JobPlanner
from atlas.kernel.capabilities import CapabilityRegistry
from atlas.kernel.tools import ToolRegistry
from atlas.planner.planner import Planner


def _live_sql_registries():
    caps = CapabilityRegistry()
    tools = ToolRegistry()
    caps.register("sql", object(), kind="plugin")
    tools.register(
        "sql.query",
        lambda **kwargs: {"outcome": "ok"},
        description="query",
        params={"sql": "str", "source": "str"},
        plugin="sql",
    )
    for name in ("logs", "git", "code"):
        caps.register(name, object(), kind="plugin")
        tools.register(f"{name}.ping", lambda **kwargs: {}, description=name, plugin=name)
    return caps, tools


def test_unified_catalog_adds_toolbox_only_when_live():
    bare = default_catalog()
    assert "sql" not in bare
    assert "logs" not in bare

    caps, tools = _live_sql_registries()
    unified = build_unified_catalog(caps, tools)
    for name in LIVE_TOOLBOX:
        if name == "python":
            # python may already exist as python_calculation adapter; live "python" is separate
            continue
        assert name in unified, name
    assert "sql" in unified
    assert unified["sql"].input_schema.get("sql") == "str"
    # Without registries, toolbox stays out.
    assert "sql" not in build_unified_catalog(None, None)


def test_db_question_plans_sql_step_with_args():
    caps, tools = _live_sql_registries()
    catalog = build_unified_catalog(caps, tools)
    planned = plan_investigation(
        {
            "objective": (
                "How many failed task_runs are in the atlas database today?\n"
                "```sql\nSELECT count(*)::int AS n FROM scheduler.task_runs "
                "WHERE status = 'failed' AND started_at >= current_date\n```"
            ),
            "required": [],
        },
        catalog_names=list(catalog),
        availability={n: True for n in catalog},
        generations={n: 0 for n in catalog},
        failure_memory={},
        job_planner=JobPlanner(Planner(), llm=None, research_first=False),
    )
    assert planned["ok"], planned
    sql_steps = [s for s in planned["steps"] if s.get("capability") == "sql"]
    assert sql_steps, planned["steps"]
    assert str(sql_steps[0].get("args", {}).get("sql") or "").strip()
    assert sql_steps[0]["args"].get("source") == "atlas"


def test_kernel_bind_live_toolbox_surfaces_sql(tmp_path: Path):
    caps, tools = _live_sql_registries()
    kernel = AgentKernel(tmp_path)
    names_before = {row["name"] for row in kernel.catalog()}
    assert "sql" not in names_before
    kernel.bind_live_toolbox(caps, tools)
    names = {row["name"] for row in kernel.catalog()}
    assert "sql" in names
    assert "logs" in names
    assert "git" in names
    assert "code" in names
    assert "cognitive_core" in names  # ladder preserved
    assert "broker_order" not in names


def test_sql_not_planned_when_not_in_live_catalog():
    planned = plan_investigation(
        {
            "objective": "```sql\nSELECT 1\n```",
            "required": [],
        },
        catalog_names=list(default_catalog()),  # no sql
        availability={n: True for n in default_catalog()},
        generations={n: 0 for n in default_catalog()},
        failure_memory={},
        job_planner=JobPlanner(Planner(), llm=None, research_first=False),
    )
    # May still plan other steps, but must not claim a live sql capability.
    assert not any(s.get("capability") == "sql" for s in planned.get("steps") or [])
