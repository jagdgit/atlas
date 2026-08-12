"""PLC.F — Career / Market status chat routes without LLM."""

from __future__ import annotations

import json

from atlas.planner.planner import Intent, Planner


def test_career_intelligence_question_routes_to_career_status():
    plan = Planner().plan("what did you learn so far in career intelligence?")
    assert plan.intent == Intent.CAREER_STATUS


def test_career_status_phrase():
    plan = Planner().plan("career intelligence status")
    assert plan.intent == Intent.CAREER_STATUS


def test_market_intelligence_question_routes():
    plan = Planner().plan("what did you learn on market intelligence so far?")
    assert plan.intent == Intent.MARKET_STATUS


def test_learner_status_routes_market():
    plan = Planner().plan("learner status")
    assert plan.intent == Intent.MARKET_STATUS


def test_unrelated_still_answer_or_other():
    plan = Planner().plan("what is the capital of France?")
    assert plan.intent == Intent.ANSWER


def test_market_status_builder_hermetic(tmp_path):
    from atlas.investment.market_status_chat import build_market_intelligence_status

    (tmp_path / "market").mkdir(parents=True)
    (tmp_path / "investment" / "fundamentals").mkdir(parents=True)
    (tmp_path / "investment" / "research" / "market_intelligence").mkdir(parents=True)
    (tmp_path / "market" / "virtual_portfolios.json").write_text(
        json.dumps(
            {
                "portfolios": [
                    {
                        "portfolio_key": "india_equity_learner",
                        "asset_class": "cash_equity",
                        "mission_id": "m1",
                        "persona": {"capital": 50000},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "investment" / "fundamentals" / "market_intelligence.json").write_text(
        json.dumps({"symbols": {"INFY.NS": {"pe": 20.0}}, "count": 1}),
        encoding="utf-8",
    )
    (tmp_path / "investment" / "research" / "market_intelligence" / "INFY.NS.json").write_text(
        "{}", encoding="utf-8"
    )
    doc = build_market_intelligence_status(data_dir=tmp_path, goals=None)
    assert doc["ok"] is True
    assert "Market Intelligence" in doc["answer"]
    assert doc["labs"] >= 1
    assert doc["research_n"] >= 1


def test_f5_what_do_we_know_routes_ask_knowledge():
    plan = Planner().plan("what do we know about INFY in the knowledge base?")
    assert plan.intent == Intent.ASK_KNOWLEDGE


def test_f6_lane_busy_preflight():
    from atlas.llm.service import LLMService

    class _FakeProv:
        name = "fake"

        def health(self):
            return True

        def chat(self, *a, **k):
            raise AssertionError("should not call chat when busy")

    svc = LLMService(_FakeProv(), model="m", embedding_model="e", max_concurrency=1)
    assert svc.lane_busy() is False
    assert svc._lane.acquire(blocking=False) is True  # noqa: SLF001
    assert svc.lane_busy() is True
    svc._lane.release()  # noqa: SLF001
    assert svc.lane_busy() is False
