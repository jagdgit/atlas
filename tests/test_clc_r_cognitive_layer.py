"""CLC.R* — decide-rationale drain, honest roster, BRE.5 narrative hygiene."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.decide_rationale import schedule_decide_rationale
from atlas.investment.decision_packets import DecisionPacketStore
from atlas.investment.decision_timeline import DecisionTimelineStore
from atlas.investment.global_mind import _llm_global_narrative
from atlas.llm.service import LLMService
from atlas.workers.base import TickContext
from atlas.workers.decision_evolution import DecisionEvolutionWorker
from tests.test_bre3_decide_rationale import _FakeLLM, _JSON
from tests.test_laboratory_lq2_timeline_density import _CriticalGuard
from tests.test_llm import FakeProvider


def test_clc_r2_honest_roster():
    svc = LLMService(
        FakeProvider(["qwen3:4b", "nomic-embed-text", "llama3:latest"]),
        model="qwen3:4b",
        embedding_model="nomic-embed-text",
        roles={
            "chat": "qwen3:4b",
            "planner": "qwen3:4b",
            "scientist": "qwen3:4b",
            "embed": "nomic-embed-text",
        },
    )
    roster = svc.honest_roster()
    assert roster["reasoner"] == "qwen3:4b"
    assert roster["embed"] == "nomic-embed-text"
    assert roster["vision"] == "not installed"
    assert roster["roles_are_lanes"] is True
    assert "llama3:latest" in roster["unused"]
    assert "one local reasoner" in roster["honesty"]
    health = svc.health_check()
    assert health.data["honest_roster"]["reasoner"] == "qwen3:4b"


def test_clc_r0_drain_when_host_guard_zero(tmp_path: Path):
    packets = DecisionPacketStore(data_dir=tmp_path)
    timeline = DecisionTimelineStore(data_dir=tmp_path)
    timeline._packets = packets
    packets.record(
        action="buy",
        symbol="IDEA.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="sma_cross_rsi",
        ts_ist="2026-09-22",
        prices={"mark": 14.1, "fill_price": 14.1, "filled_qty": 1},
        reasons_for=["sma"],
    )
    schedule_decide_rationale(
        tmp_path,
        decision_id="dec-thin",
        symbol="IDEA.NS",
        action="buy",
        laboratory_id="india_equity_learner",
        packet={
            "decision_id": "dec-thin",
            "action": "buy",
            "symbol": "IDEA.NS",
            "unknowns": ["fcf", "news", "pe"],
            "observation_ids": ["obs-1"],
        },
    )
    worker = DecisionEvolutionWorker(
        timeline=timeline,
        decision_packets=packets,
        host_guard=_CriticalGuard(),
        llm=_FakeLLM(_JSON),
    )
    result = worker.do_tick(
        TickContext(
            worker_id="evo-r0",
            mission_id="m",
            config={
                "portfolio_key": "india_equity_learner",
                "open_symbols": ["IDEA.NS"],
            },
            config_version=1,
            state={},
        )
    )
    assert "thinned to 0" in result.note
    bre3 = (result.state.get("last_evolution") or {}).get("decide_rationale") or {}
    assert bre3.get("done") == 1
    assert bre3.get("llm_bound") is True


def test_bre5_global_narrative_reads_resp_text():
    llm = _FakeLLM(
        '{"status":"unchanged","thesis_text":"patterns thin","reason":"n=1",'
        '"notes":"","mentor_bullets":["keep PLC.A"]}'
    )
    out = _llm_global_narrative(llm, patterns=[{"k": "v"}], digest={"n": 1})
    assert out is not None
    assert "patterns" in (out.get("thesis_text") or "").lower() or out.get("status")
    assert llm.calls >= 1
