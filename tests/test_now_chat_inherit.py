"""NOW #10 — chat inherits Next-₹1 + worldview."""

from __future__ import annotations

from atlas.investment.market_status_chat import (
    answer_market_allocation_question,
    answer_next_rupee_chat,
    detect_next_rupee_query,
)
from atlas.investment.next_rupee import build_and_persist_next_rupee
from atlas.investment.capital_allocation import build_challenger_table
from atlas.investment.self_worldview import attach_self_worldview
from atlas.planner.planner import Intent, Planner


def test_detect_next_rupee_queries():
    assert detect_next_rupee_query("Where does the next rupee go?")
    assert detect_next_rupee_query("What is the best use of capital now?")
    assert detect_next_rupee_query("capital allocation for today")
    assert detect_next_rupee_query("Why do we still hold EICHERMOT?")
    assert not detect_next_rupee_query("What is PE?")
    assert not detect_next_rupee_query("")


def test_chat_answer_inherits_next_rupee(tmp_path):
    tbl = build_challenger_table(
        holds=[
            {
                "symbol": "EICHERMOT.NS",
                "qty": 5,
                "score": 0.5,
                "confidence": "medium",
                "components": {"momentum": 0.5},
            }
        ],
        challengers=[
            {
                "symbol": "DEVYANI.NS",
                "score": 0.9,
                "confidence": "high",
                "phase": "active",
                "components": {"momentum": 0.9},
                "rs_vs_benchmark_pct": 5.0,
                "pe": 20.0,
                "industry_pe_median": 30.0,
            }
        ],
        cash=50_000,
        laboratory_id="india_equity_learner",
    )
    wv = attach_self_worldview(
        beliefs=[
            {
                "statement": "Beliefs advise before they hard-influence capital decisions.",
                "status": "active",
            }
        ],
        experiences=[],
    )
    build_and_persist_next_rupee(
        tmp_path,
        tbl,
        laboratory_id="india_equity_learner",
        acp_summaries=[
            {"symbol": "EICHERMOT.NS", "decision": "EXIT_REVIEW"},
        ],
        worldview=wv,
    )
    out = answer_next_rupee_chat(
        "Where does the next rupee go?",
        data_dir=tmp_path,
        laboratory_id="india_equity_learner",
    )
    assert out is not None
    assert out["kind"] == "next_rupee"
    assert out["never_orders"] is True
    assert "Next ₹1" in out["answer"]
    assert "Beliefs advise" in out["answer"]
    assert "no orders" in out["answer"].lower()

    via_router = answer_market_allocation_question(
        "Where does the next rupee go?",
        data_dir=tmp_path,
        laboratory_id="india_equity_learner",
    )
    assert via_router and via_router["kind"] == "next_rupee"

    hold_q = answer_next_rupee_chat(
        "Why do we still hold EICHERMOT?",
        data_dir=tmp_path,
        laboratory_id="india_equity_learner",
    )
    assert hold_q and "EICHERMOT" in hold_q["answer"]


def test_planner_routes_next_rupee_to_market_status():
    assert Planner().plan("Where does the next rupee go?").intent == Intent.MARKET_STATUS
    assert Planner().plan("capital allocation today").intent == Intent.MARKET_STATUS
