"""Stage 3.2d execution planning, admission, and adaptive pools."""

from __future__ import annotations

from atlas.core.execution import ExecutionPlanner, ExecutionTask, TaskCostModel
from atlas.core.resources import ResourceManager
from atlas.research.concurrency import clamp_workers


def _services(*, llm_max: int = 1):
    resources = ResourceManager(
        profile="balanced",
        max_worker_threads=4,
        llm_max_concurrency=llm_max,
        cost_budgets={"balanced": 20},
    )
    return resources, ExecutionPlanner(resources, TaskCostModel())


def test_execution_order_is_priority_cost_then_id():
    _, planner = _services()
    tasks = [
        ExecutionTask("b", "ocr_pdf"),
        ExecutionTask("a", "read_html"),
        ExecutionTask("c", "download", priority=1),
    ]
    assert [task.id for task in planner.order(tasks)] == ["c", "a", "b"]


def test_execution_dependencies_filter_not_ready_tasks():
    _, planner = _services()
    tasks = [
        ExecutionTask("read", "read_pdf", depends_on=("download",)),
        ExecutionTask("download", "download"),
    ]
    assert [task.id for task in planner.order(tasks)] == ["download"]
    assert [task.id for task in planner.order(tasks, completed={"download"})] == ["read"]


def test_llm_lane_changes_global_admission():
    resources, planner = _services()
    extract = ExecutionTask("extract", "llm_extract")
    download = ExecutionTask("download", "download")
    with resources.llm_lane(kind="chat"):
        planned = {row.task.id: row for row in planner.plan([extract, download])}
        assert planned["extract"].admitted is False
        assert "LLM lane busy" in planned["extract"].reason
        assert planned["download"].admitted is True
        assert resources.llm_capacity["in_use"] == 1
        assert resources.llm_capacity["cost_in_use"] > 0
    assert resources.llm_capacity["available"] == 1
    assert resources.llm_capacity["cost_in_use"] == 0


def test_adaptive_pool_never_exceeds_work_count():
    assert clamp_workers(
        4, global_max=4, queue_depth=2, work_count=2
    ) == 2
    assert clamp_workers(
        4, global_max=4, queue_depth=100, work_count=100
    ) == 4


def test_resource_recommendation_adapts_to_work():
    resources, _ = _services()
    rec = resources.recommend_pool_sizes(
        download_work=2,
        reader_work=2,
        extract_work=1,
    )
    assert rec.download_workers == 2
    assert rec.reader_workers == 2
    assert rec.extract_workers == 1
