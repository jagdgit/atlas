"""OI-CU0 first slice — operator knowledge, lanes, report honesty."""

from __future__ import annotations

from atlas.investment.llm_lanes import cu_lane_for_role, record_llm_lane_failure
from atlas.investment.operator_knowledge import (
    format_operator_knowledge_answer,
    lookup_glossary,
    match_operator_knowledge,
)
from atlas.investment.reports import format_learned_today_section
from atlas.planner import Intent, Planner


def test_glossary_fno_and_challenger():
    hit = match_operator_knowledge("What is F&O?")
    assert hit is not None
    assert hit["term"] == "f&o"
    assert "Futures" in hit["definition"] or "future" in hit["definition"].lower()
    text = format_operator_knowledge_answer(hit)
    assert "deterministic" in text.lower()
    assert "Ollama" in text or "no chat LLM" in text

    ch = lookup_glossary("challenger")
    assert ch and "Next" in ch["definition"] or "challenger" in ch["definition"].lower()


def test_planner_routes_fno_to_operator_knowledge():
    p = Planner()
    assert p.plan("What is F&O?").intent == Intent.OPERATOR_KNOWLEDGE
    assert p.plan("what is a challenger?").intent == Intent.OPERATOR_KNOWLEDGE
    assert p.plan("what is india_fno_learner?").intent == Intent.OPERATOR_KNOWLEDGE
    # Conversational wrapper must not fall through to ANSWER/Ollama
    assert (
        p.plan("can you explain me what is f & o in the stock market?").intent
        == Intent.OPERATOR_KNOWLEDGE
    )
    assert p.plan("Could you explain what is F&O?").intent == Intent.OPERATOR_KNOWLEDGE
    # Unrelated general Q still ANSWER
    assert p.plan("What is the stock market?").intent == Intent.ANSWER


def test_cu_lane_mapping():
    assert cu_lane_for_role("chat") == "chat"
    assert cu_lane_for_role("researcher") == "research"
    assert cu_lane_for_role("market") == "market"


def test_record_chat_llm_failure(tmp_path):
    out = record_llm_lane_failure(
        tmp_path,
        lane="chat",
        reason="busy",
        detail="test busy",
        laboratory_id="india_equity_learner",
    )
    assert out.get("ok") is True
    from atlas.investment.learning_objects import load_learning_events, summarize_learning_day

    evs = load_learning_events(tmp_path, "india_equity_learner")
    assert any(e.get("event_kind") == "llm_failure" for e in evs)
    assert any(e.get("llm_lane") == "chat" for e in evs)
    summary = summarize_learning_day(evs)
    assert int((summary.get("by_kind") or {}).get("llm_failure") or 0) >= 1


def test_report_packet_unknown_breakdown_not_pe_label():
    lines = format_learned_today_section(
        plan={"as_of": "2026-08-20", "phase": "active"},
        portfolio={
            "portfolio_key": "india_equity_learner",
            "decisions": [
                {
                    "action": "hold",
                    "symbol": "CIPLA.NS",
                    "unknowns": ["fcf_missing", "pb_conflict"],
                },
                {
                    "action": "hold",
                    "symbol": "EICHERMOT.NS",
                    "unknowns": ["fcf_missing"],
                },
            ],
            "fundamentals_coverage": {
                "symbols": 18,
                "with_pe": 18,
                "with_fcf": 2,
                "learner_gaps": {
                    "symbols_checked": 2,
                    "missing_pe": 0,
                    "missing_fcf": 2,
                    "gaps": [
                        {"symbol": "CIPLA.NS", "missing": ["fcf"]},
                        {"symbol": "EICHERMOT.NS", "missing": ["fcf"]},
                    ],
                },
            },
            "evolution": {},
            "process_proxies": {},
            "meta_learning": {},
        },
    )
    text = "\n".join(lines)
    assert "Packets still missing PE/FCF/MoS" not in text
    assert "Decision packets with unresolved fields: 2/2" in text
    assert "FCF missing: 2" in text
    assert "PE missing: 0" in text
    assert "data conflicts: 1" in text or "conflicts: 1" in text
    assert "Fundamentals store" in text
    assert "PE coverage: 18/18" in text
    assert "FCF coverage: 2/18" in text
    assert "Open books" in text
