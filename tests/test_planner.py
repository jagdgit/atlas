"""Tests for the deterministic Planner (Sprint 10, D2a).

Pure/hermetic: the planner has no dependencies, so routing and argument
extraction are tested directly.
"""

from __future__ import annotations

import pytest

from atlas.planner import Intent, Plan, Planner


@pytest.fixture
def planner() -> Planner:
    return Planner()


# --- the five acceptance intents route correctly --------------------------
@pytest.mark.parametrize(
    "message, expected",
    [
        ("What documents do you know about?", Intent.LIST_DOCUMENTS),
        ("Read this PDF.", Intent.INGEST_PATH),
        ("What does it say?", Intent.ASK_KNOWLEDGE),
        ("Remember that I prefer PostgreSQL over Milvus.", Intent.REMEMBER),
        ("What do you remember about my preferences?", Intent.RECALL),
    ],
)
def test_acceptance_intents(planner, message, expected):
    assert planner.plan(message).intent == expected


# --- routing edges --------------------------------------------------------
def test_general_question_falls_back_to_react(planner):
    assert planner.plan("What is 12 times 8?").intent == Intent.REACT


def test_greeting_is_smalltalk(planner):
    assert planner.plan("hello there").intent == Intent.SMALLTALK


def test_recall_not_shadowed_by_list_documents(planner):
    # 'know' appears in both; a personal-memory question must be RECALL.
    assert planner.plan("what do you remember about me?").intent == Intent.RECALL


def test_remember_not_shadowed_by_recall(planner):
    plan = planner.plan("Remember that my name is Sam.")
    assert plan.intent == Intent.REMEMBER


# --- argument extraction --------------------------------------------------
def test_remember_strips_prefix(planner):
    args = planner.plan("Remember that I prefer PostgreSQL over Milvus.").steps[0].args
    assert args["content"] == "I prefer PostgreSQL over Milvus."
    assert args["kind"] == "semantic"


def test_web_fetch_extracts_url(planner):
    plan = planner.plan("please fetch https://example.com/page.")
    assert plan.intent == Intent.WEB_FETCH
    assert plan.steps[0].args["url"] == "https://example.com/page"


def test_web_search_routes_and_extracts_query(planner):
    plan = planner.plan("search the web for PV soiling losses in India")
    assert plan.intent == Intent.WEB_SEARCH
    assert plan.steps[0].capability == "search"
    assert plan.steps[0].args["query"] == "PV soiling losses in India"


def test_web_search_look_up_prefix_stripped(planner):
    plan = planner.plan("look up NREL soiling report")
    assert plan.intent == Intent.WEB_SEARCH
    assert plan.steps[0].args["query"] == "NREL soiling report"


def test_web_fetch_wins_over_search_when_url_present(planner):
    # A URL should still be fetched, not routed to search.
    plan = planner.plan("search https://example.com/page")
    assert plan.intent == Intent.WEB_FETCH


def test_ingest_extracts_path(planner):
    plan = planner.plan("ingest /data/atlas_data/documents/report.pdf")
    assert plan.intent == Intent.INGEST_PATH
    assert plan.steps[0].args["path"] == "/data/atlas_data/documents/report.pdf"


def test_ingest_without_path_is_none(planner):
    assert planner.plan("Read this PDF.").steps[0].args["path"] is None


def test_bare_filename_routes_to_ingest(planner):
    plan = planner.plan("notes.md")
    assert plan.intent == Intent.INGEST_PATH
    assert plan.steps[0].args["path"] == "notes.md"


# --- plan shape -----------------------------------------------------------
def test_plan_capabilities_required(planner):
    plan = planner.plan("Remember that I like tea.")
    assert plan.capabilities_required == ["memory"]


def test_empty_message_is_smalltalk(planner):
    plan = planner.plan("")
    assert isinstance(plan, Plan)
    assert plan.intent == Intent.SMALLTALK


def test_fallback_capability_is_agent(planner):
    assert planner.plan("ponder the meaning of life").steps[0].capability == "agent"
