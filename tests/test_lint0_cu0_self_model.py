"""OI-CU0 CU.D — global self-model assemble / chat / evening."""

from __future__ import annotations

from atlas.investment.self_model import (
    VERSION,
    answer_self_model_query,
    assemble_self_model,
    detect_self_model_query,
    ensure_self_model,
    format_self_model_answer,
    format_self_model_evening_lines,
    load_self_model,
)
from atlas.planner.planner import Intent, Planner


def test_detect_kinds():
    assert detect_self_model_query("Who are you?") == "who"
    assert detect_self_model_query("what are you doing?") == "doing"
    assert detect_self_model_query("what do you know?") == "know"
    assert detect_self_model_query("what don't you know") == "know"
    assert (
        detect_self_model_query(
            "what did you learn so far in markets and about investments or trading?"
        )
        == "learned"
    )
    assert detect_self_model_query("what have you learned?") == "learned"
    assert detect_self_model_query("what is F&O?") is None


def test_assemble_and_persist(tmp_path):
    books = [
        {
            "portfolio_key": "india_equity_learner",
            "cash": 17100,
            "equity": 54450,
            "positions": [{"symbol": "CIPLA.NS", "quantity": 15}],
        },
        {
            "portfolio_key": "india_fno_learner",
            "cash": 50000,
            "equity": 50000,
            "positions": [],
        },
        {
            "portfolio_key": "equity_intraday_learner",
            "cash": 100000,
            "equity": 100000,
            "positions": [],
        },
    ]
    from atlas.investment.daily_cognitive_agenda import save_agenda

    agenda = {
        "version": "test",
        "laboratory_id": "india_equity_learner",
        "ist_date": "2026-08-20",
        "items": [{"topic": "CIPLA FCF gap", "symbol": "CIPLA.NS"}],
    }
    save_agenda(tmp_path, agenda)

    doc = ensure_self_model(
        tmp_path,
        as_of_ist="2026-08-20",
        lab_books=books,
        llm_status={"busy": False, "max_concurrency": 1},
    )
    assert doc["version"] == VERSION
    assert doc["kind"] == "SELF_MODEL"
    assert "india_equity_learner" in doc["laboratories"]
    swing = doc["laboratories"]["india_equity_learner"]
    assert "CIPLA.NS" in swing["book"]["positions"]
    assert swing["agenda"]["items"] == 1
    assert doc["cognitive_work"]["agenda_items_open"] >= 1
    assert any("FCF" in u for u in doc["knowledge"]["open_unknowns_sample"])

    loaded = load_self_model(tmp_path, as_of_ist="2026-08-20")
    assert loaded is not None
    assert loaded["as_of_ist"] == "2026-08-20"

    who = format_self_model_answer(doc, "who")
    assert "Atlas" in who

    doing = format_self_model_answer(doc, "doing")
    assert "Laboratories" in doing or "laboratories" in doing.lower()

    know = format_self_model_answer(doc, "know")
    assert "unknown" in know.lower() or "FCF" in know

    learned = format_self_model_answer(doc, "learned")
    assert "learning" in learned.lower() or "experiences" in learned.lower()
    assert "no Ollama" in learned or "deterministic" in learned.lower()

    lines = format_self_model_evening_lines(doc)
    text = "\n".join(lines)
    assert "self-model" in text.lower()
    assert "india_equity_learner" in text


def test_answer_query(tmp_path):
    out = answer_self_model_query(tmp_path, "Who are you?")
    assert out is not None
    assert out["kind"] == "who"
    assert "Atlas" in out["answer"]
    assert assemble_self_model(tmp_path)["laboratories"]


def test_planner_routes_self_model():
    plan = Planner().plan("Who are you?")
    assert plan.intent == Intent.SELF_MODEL
    assert Planner().plan("what are you doing?").intent == Intent.SELF_MODEL
    assert Planner().plan("what do you know?").intent == Intent.SELF_MODEL
    assert (
        Planner()
        .plan(
            "what did you learn so far in markets and about investments or trading?"
        )
        .intent
        == Intent.SELF_MODEL
    )
