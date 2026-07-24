"""Investment Mentor + Experience synthesis (MI.7)."""

from __future__ import annotations

from atlas.trading.mentor import synthesize_mentor_lesson
from atlas.trading.strategy import StrategyDecisionRule
from atlas.decision.contracts import DecisionRequest
from atlas.decision.context import IntelligenceContext
from atlas.workers.base import TickContext
from atlas.workers.investment_mentor import InvestmentMentorWorker


def test_synthesize_idle_without_experiences():
    assert synthesize_mentor_lesson([]) is None


def test_synthesize_seed_force_topic():
    lesson = synthesize_mentor_lesson([], force_topic="RELIANCE")
    assert lesson is not None
    assert "RELIANCE" in lesson.title
    assert lesson.recommendations


def test_synthesize_from_losses():
    experiences = [
        {
            "id": "e1",
            "title": "Paper trade closed on DEMO: loss -12.00",
            "tags": ["demo", "paper_trading", "loss", "markets"],
            "lessons": "Lesson: re-check catalysts",
            "domain": "markets",
        },
        {
            "id": "e2",
            "title": "Paper trade closed on DEMO: loss -5.00",
            "tags": ["demo", "paper_trading", "loss"],
            "lessons": "Lesson: size down",
        },
    ]
    lesson = synthesize_mentor_lesson(experiences)
    assert lesson is not None
    assert "loss" in lesson.outcome_summary
    assert any("hold" in r.lower() or "trade_fraction" in r.lower() for r in lesson.recommendations)
    payload = lesson.experience_payload()
    assert "Observation:" in payload["problem"]
    assert "Lesson:" in payload["lessons"]


def test_mentor_worker_writes_once():
    remembered: list[dict] = []

    class _Learning:
        def list_experiences(self, *, limit=40):
            return [
                {
                    "id": "e1",
                    "title": "Paper trade closed on X: profit +1",
                    "tags": ["x", "paper_trading", "profit", "markets"],
                    "lessons": "Lesson: reinforce",
                }
            ]

        def remember_experience(self, **fields):
            remembered.append(fields)
            return {"ok": True}

    worker = InvestmentMentorWorker(learning=_Learning())
    r1 = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={"focus": "markets"},
            config_version=1,
            state={},
        )
    )
    assert "wrote=True" in r1.note
    assert remembered
    r2 = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={"focus": "markets"},
            config_version=1,
            state=r1.state,
        )
    )
    assert "unchanged" in r2.note
    assert len(remembered) == 1


def test_strategy_mentor_caution_lowers_buy():
    rule = StrategyDecisionRule()
    ctx = IntelligenceContext()
    base = {
        "symbol": "DEMO",
        "price": 100.0,
        "position_qty": 0,
        "equity": 10_000,
        "cash": 10_000,
        "trade_fraction": 0.1,
        "indicators": {
            "sma_fast": 110.0,
            "sma_slow": 100.0,
            "rsi": 40.0,
            "params": {"sma_fast": 10, "sma_slow": 30},
            "bars": 40,
        },
    }
    opts_plain = rule.score(
        DecisionRequest(mission_id="m", mission_type="paper_trading", context=dict(base)),
        ctx,
    )
    buy_plain = next(o for o in opts_plain if o.key.startswith("buy:"))
    opts_caution = rule.score(
        DecisionRequest(
            mission_id="m",
            mission_type="paper_trading",
            context={**base, "mentor_advice": "Recent losses — prefer hold; re-check risk"},
        ),
        ctx,
    )
    buy_caution = next(o for o in opts_caution if o.key.startswith("buy:"))
    assert buy_caution.score < buy_plain.score
    assert "mentor caution" in buy_caution.rationale
