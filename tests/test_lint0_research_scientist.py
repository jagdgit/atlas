"""OI-LINT0 Phase 3 — research scientist: events only, structured JSON, UNREVIEWED."""

from __future__ import annotations

import json

from atlas.investment.belief_revision import revise_one_wso
from atlas.investment.world_state import empty_wso, evidence_delta_counts, format_mind_change_section
from atlas.llm.provider import LLMResponse
from atlas.reasoning.research_scientist import (
    DECISION_ADVICE,
    LLM_UNAVAILABLE,
    UNREVIEWED,
    build_research_packet,
    drain_scientist_queue,
    enqueue_unreviewed,
    is_scientist_event,
    normalize_scientist_output,
    run_research_scientist,
)


class _SeqLLM:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls = 0

    def chat(self, messages, **kwargs):  # noqa: ANN001
        self.calls += 1
        item = self._responses.pop(0) if self._responses else TimeoutError("gone")
        if isinstance(item, Exception):
            raise item
        return LLMResponse(text=item, model="fake")


def test_scientist_skips_clock_holds():
    assert is_scientist_event(action="hold", strategy_tag="engine_hold") is False
    assert is_scientist_event(action="hold", strategy_tag="mark_only") is False
    assert is_scientist_event(action="buy", strategy_tag="sma_cross_rsi") is True
    assert is_scientist_event(action="sell", strategy_tag="eod_flatten") is True
    assert is_scientist_event(
        action="hold",
        strategy_tag="lab_policy_hold",
        contradictions=["technical_buy_vs_fundamental_watch"],
    ) is True


def test_packet_is_bounded_and_unknown_honest():
    pkt = build_research_packet(
        symbol="CIPLA.NS",
        laboratory_id="india_equity_learner",
        action="buy",
        strategy_tag="sma_cross_rsi",
        fundamentals={"pe": 36.1, "roe": 0.12},
        challengers=[{"symbol": "BOSCHLTD.NS", "expected_return": 0.1}] * 20,
        decomposition={
            "technical_signal": "BUY",
            "fundamental_thesis": "WATCH",
            "identity": "VALID",
            "contradictions": ["technical_buy_vs_fundamental_watch"],
        },
        events={"news": [], "policy": []},
    )
    assert "question" in pkt
    assert len(pkt["challengers"]) <= 5
    assert pkt["events"]["news"] == "unknown"
    assert "fcf" in pkt["unknowns"]


def test_llm_buy_advice_cannot_override_engine():
    out = normalize_scientist_output(
        {
            "belief_changed": True,
            "new_stance": "BUY",
            "decision_advice": "BUY_NOW",
            "confidence": 0.9,
        }
    )
    assert out["decision_advice"] == DECISION_ADVICE
    assert out["new_stance"] == "BUY"


def test_retry_then_unreviewed_is_not_unchanged(tmp_path):
    llm = _SeqLLM([TimeoutError("timed out"), TimeoutError("timed out again")])
    out = run_research_scientist(
        llm=llm,
        data_dir=tmp_path,
        consume_budget=False,
        symbol="CIPLA.NS",
        laboratory_id="india_equity_learner",
        action="buy",
        strategy_tag="sma_cross_rsi",
    )
    assert llm.calls == 2
    assert out["status"] == UNREVIEWED
    assert LLM_UNAVAILABLE in out["reason"]
    assert out["belief_changed"] is False
    assert out["reschedule"] is True


def test_successful_json_is_reviewed(tmp_path):
    payload = {
        "belief_changed": False,
        "new_stance": "WATCH",
        "confidence": 0.31,
        "unknowns": ["fcf"],
        "research_tasks": ["find latest FCF"],
        "decision_advice": "ignored",
        "analyst": "thesis still watch",
        "skeptic": "MoS unknown",
        "researcher": "need FCF",
        "teacher": "do not treat SMA as confirmation",
    }
    llm = _SeqLLM([json.dumps(payload)])
    out = run_research_scientist(
        llm=llm,
        data_dir=tmp_path,
        symbol="CIPLA.NS",
        laboratory_id="india_equity_learner",
        action="buy",
        strategy_tag="sma_cross_rsi",
        decomposition={"technical_signal": "BUY", "fundamental_thesis": "WATCH"},
    )
    assert out["status"] == "reviewed"
    assert out["output"]["decision_advice"] == DECISION_ADVICE
    assert out["output"]["unknowns"] == ["fcf"]
    assert out["belief_changed"] is False


def test_engine_hold_does_not_spend_budget(tmp_path):
    llm = _SeqLLM([json.dumps({"belief_changed": True})])
    out = run_research_scientist(
        llm=llm,
        data_dir=tmp_path,
        symbol="CIPLA.NS",
        laboratory_id="india_equity_learner",
        action="hold",
        strategy_tag="engine_hold",
    )
    assert out["reason"] == "not_an_event"
    assert llm.calls == 0


def test_drain_retries_queue(tmp_path):
    enqueue_unreviewed(
        tmp_path,
        laboratory_id="india_equity_learner",
        packet={
            "symbol": "ASTRAL.NS",
            "laboratory": "equity_intraday_learner",
            "action": "sell",
            "strategy_tag": "eod_flatten",
        },
        reason="pending_event",
    )
    llm = _SeqLLM(
        [
            json.dumps(
                {
                    "belief_changed": False,
                    "new_stance": "WATCH",
                    "teacher": "flatten recorded an outcome",
                }
            )
        ]
    )
    stats = drain_scientist_queue(
        tmp_path, laboratory_id="india_equity_learner", llm=llm, max_n=3
    )
    assert stats["done"] == 1
    assert stats["pending"] == 0


def test_bre2_missing_llm_is_unreviewed_not_unchanged(tmp_path):
    w = empty_wso(symbol="CIPLA.NS", laboratory_id="lab")
    out = revise_one_wso(
        w,
        llm=None,
        evidence_delta=evidence_delta_counts(news_n=1),
        data_dir=str(tmp_path),
    )
    assert out["status"] == "unreviewed"
    assert "LLM_UNAVAILABLE" in out["revision_history"][-1]["reason"]
    lines = format_mind_change_section([out])
    assert any("UNREVIEWED" in x for x in lines)
    assert any("belief_changed=no" in x for x in lines)
