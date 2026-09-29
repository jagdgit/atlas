"""A0 Agent Kernel — autonomous loop acceptance tests.

These scenarios are deterministic. They do not place orders or touch live control.
"""

from __future__ import annotations

import json
from pathlib import Path

from atlas.agent_kernel.eod import format_autonomous_agent_lines
from atlas.agent_kernel.kernel import AgentKernel
from atlas.agent_kernel.models import DIAGNOSTIC_FIELDS, TERMINAL_OR_WAITING
from atlas.agent_kernel.worker import AgentKernelWorker
from atlas.investment.reports import format_evening_report
from atlas.investment.uncertainty_queue import enqueue_from_unknowns
from atlas.workers.base import TickContext


class _Journal:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def journal(self, **kwargs):
        self.entries.append(kwargs)
        return {"ok": True, "result": {"id": f"exp-{len(self.entries)}"}}


def _reviewed(packet: dict) -> dict:
    evid = " ".join(str(x) for x in (packet.get("evidence") or packet.get("known") or []))
    return {
        "review_status": "REVIEWED",
        "conclusion": f"Interpreted only cited evidence ({len(evid)} chars).",
        "uncertainty": "single snapshot",
        "falsifiers": ["cited series reverses"],
        "action": "BUY",
        "orders": [{"side": "BUY", "quantity": 1}],
    }


def _assert_explained(task: dict) -> None:
    assert task["status"] in TERMINAL_OR_WAITING
    for key in DIAGNOSTIC_FIELDS:
        assert key in task
    if task["status"] != "SUCCESS":
        assert task["reason"]
        assert task["next_action"]
        assert task["attempted_capabilities"] is not None


def _kernel(tmp_path: Path, **kwargs) -> AgentKernel:
    journal = kwargs.pop("experience_os", _Journal())
    return AgentKernel(
        tmp_path,
        experience_os=journal,
        cognitive_fn=kwargs.pop("cognitive_fn", _reviewed),
        **kwargs,
    )


def _hbl_observation() -> dict:
    return {
        "source": "position_state",
        "domain": "investment",
        "symbol": "HBLPOWER",
        "objective": (
            "Should Atlas consider HBLPOWER's current position well supported "
            "by available evidence?"
        ),
        "reason": "open position; sector-relative strength is missing and blocks allocation",
        "decision_impact": True,
        "urgency": 0.9,
        "priority_class": "P1",
        "required": [
            "price_history",
            "sector_benchmark",
            "relative_strength",
            "company_news",
        ],
        "needs_relative_strength": True,
        "impact": "blocks_next_rupee_comparison",
    }


def _withhold_sector(kernel: AgentKernel) -> None:
    bus = kernel.bus
    bus.put(
        "local_market_store",
        "price_history",
        {
            "evidence": {"last_close": 100.0, "source": "local_bar_store"},
            "citations": ["bars:HBLPOWER"],
        },
    )
    bus.put(
        "local_market_store",
        "company_news",
        {
            "evidence": [{"title": "order win", "source": "fixture"}],
            "citations": ["news:hbl"],
        },
    )
    for cap, error in (
        ("knowledge_search", "insufficient"),
        ("structured_provider", "sector_index_history_not_available"),
        ("web_search", "no_reliable_historical_series"),
        ("research_scientist", "research_unavailable"),
        ("alternative_source", "no_alternative_series"),
    ):
        bus.put(
            cap,
            "sector_benchmark",
            {"insufficient": True, "error": error, "citations": []},
        )


def test_a0_observation_plan_gap_and_diagnostics(tmp_path: Path):
    inbox = tmp_path / "agent_kernel" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "hbl.json").write_text(json.dumps(_hbl_observation()), encoding="utf-8")
    journal = _Journal()
    kernel = _kernel(tmp_path, experience_os=journal)
    _withhold_sector(kernel)
    report = kernel.cycle(mode="deep", max_investigations=1)
    assert report["created"], "work must be created from observed state, not a prebuilt job"
    task = kernel.task(report["ran"][0])
    assert task is not None
    assert task["source"] == "position_state"
    assert task["priority_class"] == "P1"
    assert task["planner_source"] == "deterministic_ladder"
    steps = task["plan"]["steps"]
    assert len(steps) >= 5
    caps = {s["capability"] for s in steps}
    assert {"local_market_store", "web_search", "cognitive_core", "python_calculation"} <= caps
    assert task["status"] == "CAPABILITY_GAP"
    assert task["missing_requirement"] == "durable_sector_OHLCV_provider"
    assert "historical sector series unavailable" in task["reason"]
    assert "web_search" in task["attempted_capabilities"]
    assert "local_market_store" in task["attempted_capabilities"]
    assert "knowledge_search" in task["attempted_capabilities"]
    assert kernel.bus.call_count("web_search", "sector_benchmark") >= 1
    assert "relative_strength" not in task["evidence"]
    assert task["retry_policy"] == "on_capability_change"
    assert task["next_action"].startswith("register_or_acquire:")
    _assert_explained(task)
    assert journal.entries
    assert journal.entries[-1]["metadata"]["validated_lesson"] is False
    assert "Provisional" in journal.entries[-1]["lesson"]
    assert task["lineage"]["episode_id"]
    assert task["lineage"]["work_id"] == task["id"]
    assert task["lineage"]["experience_id"]
    assert task["lineage"]["cognitive_result_id"]
    assert task["cognitive"]["action"] is None
    assert task["cognitive"]["orders"] is None
    assert task["cognitive"]["never_orders"] is True


def test_a0_sector_gap_does_not_invent_rs(tmp_path: Path):
    kernel = _kernel(tmp_path)
    kernel.bus.put(
        "local_market_store",
        "price_history",
        {"evidence": {"last_close": 50.0}, "citations": ["bars"]},
    )
    kernel.bus.put(
        "web_search",
        "sector_benchmark",
        {"insufficient": True, "error": "no_reliable_historical_series", "citations": []},
    )
    kernel.bus.put(
        "knowledge_search",
        "sector_benchmark",
        {"insufficient": True, "error": "insufficient", "citations": []},
    )
    report = kernel.cycle(
        mode="event",
        observations=[
            {
                "source": "decision_blocker",
                "domain": "investment",
                "symbol": "SECTOR",
                "objective": "Determine historical sector-relative strength.",
                "reason": "allocation needs sector RS",
                "decision_impact": True,
                "priority_class": "P1",
                "required": ["price_history", "sector_benchmark", "relative_strength"],
                "deterministic_only": True,
                "needs_relative_strength": True,
            }
        ],
    )
    task = kernel.task(report["ran"][0])
    assert task["status"] == "CAPABILITY_GAP"
    assert task["reason"] == "historical sector series unavailable"
    assert task["missing_requirement"] == "durable_sector_OHLCV_provider"
    assert "relative_strength" not in task["evidence"]
    assert task["next_action"] == "register_or_acquire:durable_sector_OHLCV_provider"
    assert task["retry_policy"] == "on_capability_change"
    blob = json.dumps(task["evidence"])
    assert "relative_strength" not in blob


def test_a0_recovery_when_capability_appears(tmp_path: Path):
    journal = _Journal()
    kernel = _kernel(tmp_path, experience_os=journal)
    _withhold_sector(kernel)
    first = kernel.cycle(mode="event", observations=[_hbl_observation()])
    task_id = first["ran"][0]
    assert kernel.task(task_id)["status"] == "CAPABILITY_GAP"
    web_calls = kernel.bus.call_count("web_search", "sector_benchmark")

    restarted = AgentKernel(
        tmp_path,
        experience_os=journal,
        cognitive_fn=_reviewed,
        bus=kernel.bus,
    )
    assert restarted.task(task_id)["status"] == "CAPABILITY_GAP"

    restarted.bus.put(
        "structured_provider",
        "sector_benchmark",
        {
            "evidence": {"last_close": 80.0, "source": "sector_index"},
            "citations": ["sector:energy"],
        },
    )
    second = restarted.cycle(mode="event")
    assert task_id in second["ran"]
    task = restarted.task(task_id)
    assert task["status"] == "SUCCESS"
    assert task["evidence"]["relative_strength"]["provenance"] == [
        "price_history",
        "sector_benchmark",
    ]
    assert task["evidence"]["relative_strength"]["relative_strength"] == 1.25
    assert task["cognitive"]["review_status"] == "REVIEWED"
    assert task["cognitive"]["action"] is None
    assert task["lineage"]["cognitive_result_id"]
    follow = [
        t
        for t in restarted.tasks()
        if t.get("parent_work_id") == task_id and t.get("status") == "WAITING_FOR_EVENT"
    ]
    assert follow
    assert follow[0]["next_action"] == "observe_outcome_when_event_arrives"
    assert restarted.bus.call_count("web_search", "sector_benchmark") == web_calls
    assert any(e["metadata"]["validated_lesson"] is False for e in journal.entries)


def test_a0_failure_memory_skips_repeated_web_search(tmp_path: Path):
    kernel = _kernel(tmp_path)
    _withhold_sector(kernel)
    obs = {
        "source": "decision_blocker",
        "domain": "investment",
        "symbol": "SECTOR",
        "objective": "Determine historical sector-relative strength.",
        "reason": "sector series missing",
        "decision_impact": True,
        "priority_class": "P1",
        "required": ["price_history", "sector_benchmark", "relative_strength"],
        "deterministic_only": True,
        "needs_relative_strength": True,
    }
    kernel.bus.put(
        "local_market_store",
        "price_history",
        {"evidence": {"last_close": 50.0}, "citations": ["bars"]},
    )
    first = kernel.cycle(mode="deep", observations=[obs])
    calls = kernel.bus.call_count("web_search", "sector_benchmark")
    assert calls >= 1
    kernel.state["tasks"].pop(first["ran"][0])
    kernel.save()
    second = kernel.cycle(mode="deep", observations=[obs])
    task = kernel.task(second["ran"][0])
    assert kernel.bus.call_count("web_search", "sector_benchmark") == calls
    assert task["status"] == "CAPABILITY_GAP"
    assert "previously failed because" in task["reason"]
    assert "relative_strength" not in task["evidence"]


def test_a0_prioritizes_decision_blocker_over_curiosity(tmp_path: Path):
    kernel = _kernel(tmp_path)
    kernel.bus.put(
        "local_market_store",
        "price_history",
        {"evidence": {"last_close": 10.0}, "citations": ["bars"]},
    )
    report = kernel.cycle(
        mode="tick",
        max_investigations=1,
        observations=[
            {
                "source": "curiosity",
                "domain": "investment",
                "symbol": "IDLE",
                "objective": "Collect a background trivia note.",
                "reason": "curiosity",
                "priority_class": "P3",
                "required": ["price_history"],
                "urgency": 0.1,
            },
            {
                "source": "integrity",
                "domain": "investment",
                "symbol": "BLOCK",
                "objective": "Resolve the active decision blocker.",
                "reason": "blocks allocation",
                "decision_impact": True,
                "priority_class": "P1",
                "required": ["price_history"],
                "urgency": 0.95,
                "interpretive": False,
            },
        ],
    )
    ran = kernel.task(report["ran"][0])
    assert ran["symbol"] == "BLOCK"
    assert ran["status"] == "SUCCESS"
    waiting = [t for t in kernel.tasks() if t["symbol"] == "IDLE"]
    assert waiting
    assert waiting[0]["status"] == "RETRY_SCHEDULED"
    assert waiting[0]["next_action"]
    _assert_explained(waiting[0])


def test_a0_planning_failed_is_explicit(tmp_path: Path):
    kernel = _kernel(tmp_path)
    report = kernel.cycle(
        mode="event",
        observations=[
            {
                "source": "operator_sensor",
                "domain": "general",
                "symbol": "",
                "objective": "Plan this objective.",
                "reason": "planner check",
                "priority_class": "P2",
                "required": ["pe"],
                "constraints": {"refuse_plan": True},
            }
        ],
    )
    task = kernel.task(report["ran"][0])
    assert task["status"] == "PLANNING_FAILED"
    assert "no safe plan" in task["reason"]
    assert task["next_action"]
    _assert_explained(task)


def test_a0_unverified_is_not_success(tmp_path: Path):
    def unreviewed(_packet: dict) -> dict:
        return {"review_status": "UNREVIEWED", "reason": "no_llm"}

    kernel = _kernel(tmp_path, cognitive_fn=unreviewed)
    kernel.bus.put(
        "local_market_store",
        "price_history",
        {"evidence": {"last_close": 10.0}, "citations": ["bars"]},
    )
    report = kernel.cycle(
        mode="event",
        observations=[
            {
                "source": "position_state",
                "domain": "investment",
                "symbol": "PARTIAL",
                "objective": "Should this position be treated as supported?",
                "reason": "interpretation required",
                "decision_impact": True,
                "priority_class": "P1",
                "required": ["price_history"],
                "interpretive": True,
            }
        ],
    )
    task = kernel.task(report["ran"][0])
    assert task["status"] == "UNVERIFIED"
    assert task["status"] != "SUCCESS"


def test_a0_refuses_orders_and_live_scope(tmp_path: Path):
    kernel = _kernel(tmp_path)
    task = {
        "attempt_count": 0,
        "attempted_capabilities": [],
        "failed": [],
        "evidence": {},
        "last_error": None,
    }
    refused = kernel._run_step(
        task,
        {"capability": "broker_order", "kind": "acquire", "requirement": "pe"},
    )
    assert refused["refused"] is True
    assert kernel.bus.call_count("broker_order") == 0

    worker = AgentKernelWorker(data_dir=str(tmp_path), enabled=True)
    result = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={"enabled": True, "action_scope": "live_orders"},
            config_version=1,
            state={},
        )
    )
    assert "refused action_scope" in result.note
    names = {row["name"] for row in kernel.catalog()}
    assert "cognitive_core" in names
    assert "broker_order" not in names
    assert all(row["side_effect_level"] != "place_order" for row in kernel.catalog())


def test_a0_manufactured_evidence_is_rejected(tmp_path: Path):
    kernel = _kernel(tmp_path)
    kernel.bus.put(
        "structured_provider",
        "pe",
        {"invented": True, "evidence": {"value": 99}},
    )
    report = kernel.cycle(
        mode="event",
        observations=[
            {
                "source": "decision_blocker",
                "domain": "investment",
                "symbol": "FAKE",
                "objective": "Resolve PE.",
                "reason": "valuation",
                "decision_impact": True,
                "priority_class": "P1",
                "required": ["pe"],
                "interpretive": False,
            }
        ],
    )
    task = kernel.task(report["ran"][0])
    assert task["status"] == "FAILED"
    assert "pe" not in task["evidence"]
    assert task["next_action"] == "do_not_invent_missing_evidence"


def test_a0_production_slice_coalindia(tmp_path: Path):
    symbol = "COALINDIA.NS"
    bars = tmp_path / "market" / "bars"
    bars.mkdir(parents=True)
    (bars / f"{symbol}.json").write_text(
        json.dumps(
            {
                "symbol": symbol,
                "provider": "yahoo",
                "bar_count": 2,
                "bars": [
                    {"date": "2026-09-28", "close": 420.0},
                    {"date": "2026-09-29", "close": 424.1},
                ],
            }
        ),
        encoding="utf-8",
    )
    research = tmp_path / "investment" / "research" / "market_intelligence"
    research.mkdir(parents=True)
    (research / f"{symbol}.json").write_text(
        json.dumps({"symbol": symbol, "sector": "Oil Gas & Fuels", "pe": None}),
        encoding="utf-8",
    )
    comp = tmp_path / "investment" / "evidence_completeness" / "india_equity_learner"
    comp.mkdir(parents=True)
    (comp / f"{symbol}_latest.json").write_text(
        json.dumps(
            {
                "symbol": symbol,
                "items": [
                    {"key": "price_history", "status": "AVAILABLE", "required": True, "value": 424.1},
                    {"key": "pe", "status": "MISSING", "required": True, "value": None},
                ],
            }
        ),
        encoding="utf-8",
    )
    enq = enqueue_from_unknowns(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol=symbol,
        unknowns=["pe_missing"],
    )
    assert enq["created_ids"]
    inbox = tmp_path / "agent_kernel" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "coal.json").write_text(
        json.dumps(
            {
                "source": "evidence_completeness",
                "domain": "investment",
                "symbol": symbol,
                "objective": (
                    "Determine whether COALINDIA's open decision is supported "
                    "by available evidence."
                ),
                "reason": "PE missing blocks valuation; local price history exists",
                "decision_impact": True,
                "urgency": 1.0,
                "priority_class": "P1",
                "required": ["price_history", "sector", "company_news", "pe"],
                "interpretive": True,
                "uncertainty_refs": enq["created_ids"],
                "decision_id": "dec-coalindia",
            }
        ),
        encoding="utf-8",
    )
    journal = _Journal()
    kernel = _kernel(tmp_path, experience_os=journal, laboratory_id="india_equity_learner")
    kernel.bus.put(
        "news_search",
        "company_news",
        {
            "evidence": [{"title": "production update", "source": "fixture"}],
            "citations": ["news:coalindia"],
        },
    )
    kernel.bus.put(
        "web_search",
        "pe",
        {"insufficient": True, "error": "no_reliable_fundamental", "citations": []},
    )
    first = kernel.cycle(mode="deep", allow_external=True, max_investigations=1)
    task = kernel.task(first["ran"][0])
    assert task["source"] == "evidence_completeness"
    assert task["status"] == "CAPABILITY_GAP"
    assert task["evidence"]["price_history"]["last_close"] == 424.1
    assert task["evidence"]["price_history"]["source"] == "local_bar_store"
    assert task["evidence"]["sector"]["sector"] == "Oil Gas & Fuels"
    assert "company_news" in task["evidence"]
    assert "pe" not in task["evidence"]
    assert kernel.bus.call_count("web_search", "pe") >= 1
    assert len(task["plan"]["steps"]) >= 4
    assert task["lineage"]["decision_id"] == "dec-coalindia"
    assert task["lineage"]["experience_id"]
    _assert_explained(task)
    assert any(t["source"] == "uncertainty_queue" for t in kernel.tasks())

    restarted = AgentKernel(
        tmp_path,
        experience_os=journal,
        cognitive_fn=_reviewed,
        bus=kernel.bus,
        laboratory_id="india_equity_learner",
    )
    assert restarted.task(task["id"])["status"] == "CAPABILITY_GAP"
    restarted.bus.put(
        "structured_provider",
        "pe",
        {
            "evidence": {"value": 6.5, "source": "cited_filing"},
            "citations": ["filing:coalindia-pe"],
        },
    )
    second = restarted.cycle(mode="event", allow_external=True)
    done = restarted.task(task["id"])
    assert done["status"] == "SUCCESS"
    assert done["evidence"]["pe"]["value"] == 6.5
    assert done["evidence"]["pe"]["source"] == "cited_filing"
    assert done["cognitive"]["action"] is None
    assert done["cognitive"]["never_orders"] is True
    assert any(t.get("status") == "WAITING_FOR_EVENT" for t in restarted.tasks())
    lines = format_autonomous_agent_lines(tmp_path)
    assert any(line.startswith("━━━━━━━━ AUTONOMOUS AGENT") for line in lines)
    assert any(line.startswith("Capability gaps:") for line in lines)
    assert any(line.startswith("Experiences created:") for line in lines)
    _subj, body = format_evening_report(
        plan={"as_of": "2026-09-29", "phase": "post_close", "confidence": "low"},
        portfolio={"data_dir": str(tmp_path), "portfolio_key": "india_equity_learner"},
    )
    assert "AUTONOMOUS AGENT" in body
    assert "Capability gaps:" in body
