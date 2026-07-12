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


def test_scholar_search_routes_on_papers_phrasing(planner):
    plan = planner.plan("find recent papers on perovskite solar cells")
    assert plan.intent == Intent.SCHOLAR_SEARCH
    assert plan.steps[0].capability == "scholar"
    assert plan.steps[0].args["query"] == "perovskite solar cells"


def test_scholar_search_routes_on_arxiv_mention(planner):
    plan = planner.plan("search arxiv for graph neural networks")
    assert plan.intent == Intent.SCHOLAR_SEARCH
    assert plan.steps[0].args["query"] == "graph neural networks"


def test_scholar_beats_generic_web_search(planner):
    # "papers on X" should go to scholar, not generic web search.
    plan = planner.plan("papers on lithium battery degradation")
    assert plan.intent == Intent.SCHOLAR_SEARCH


def test_youtube_url_routes_to_transcript(planner):
    plan = planner.plan("get the transcript of https://youtu.be/abcdefghijk")
    assert plan.intent == Intent.YOUTUBE_TRANSCRIPT
    assert plan.steps[0].capability == "transcript"
    assert plan.steps[0].args["video"] == "https://youtu.be/abcdefghijk"


def test_youtube_url_beats_web_fetch(planner):
    plan = planner.plan("https://www.youtube.com/watch?v=abcdefghijk")
    assert plan.intent == Intent.YOUTUBE_TRANSCRIPT


def test_run_python_fenced_block(planner):
    plan = planner.plan("run this:\n```python\nprint(2 + 2)\n```")
    assert plan.intent == Intent.RUN_PYTHON
    assert plan.steps[0].capability == "python"
    assert plan.steps[0].args["code"] == "print(2 + 2)"


def test_run_python_prefix(planner):
    plan = planner.plan("execute python: print('hi')")
    assert plan.intent == Intent.RUN_PYTHON
    assert plan.steps[0].args["code"] == "print('hi')"


def test_run_python_fence_wins_over_url_inside_code(planner):
    plan = planner.plan("```python\nimport urllib\nx = 'https://example.com'\n```")
    assert plan.intent == Intent.RUN_PYTHON


def test_git_status_routes(planner):
    plan = planner.plan("what's the git status of /data/atlas?")
    assert plan.intent == Intent.GIT_STATUS
    assert plan.steps[0].capability == "git"
    assert plan.steps[0].args["action"] == "status"
    assert plan.steps[0].args["repo"] == "/data/atlas"


def test_git_log_routes_and_defaults_repo(planner):
    plan = planner.plan("show recent commits")
    assert plan.intent == Intent.GIT_STATUS
    assert plan.steps[0].args["action"] == "log"
    assert plan.steps[0].args["repo"] == "."


def test_git_branches_and_diff(planner):
    assert planner.plan("git branches in /repo").steps[0].args["action"] == "branches"
    assert planner.plan("git diff for /repo").steps[0].args["action"] == "diff"


def test_sql_query_fenced_block(planner):
    plan = planner.plan("run this:\n```sql\nSELECT * FROM sales\n```")
    assert plan.intent == Intent.SQL_QUERY
    assert plan.steps[0].capability == "sql"
    assert plan.steps[0].args["sql"] == "SELECT * FROM sales"


def test_sql_query_bare_select(planner):
    plan = planner.plan("SELECT product, amount FROM sales ORDER BY id")
    assert plan.intent == Intent.SQL_QUERY
    assert "SELECT product" in plan.steps[0].args["sql"]


def test_sql_query_extracts_source(planner):
    plan = planner.plan("query the database shop.db: SELECT 1")
    assert plan.intent == Intent.SQL_QUERY
    assert plan.steps[0].args["source"] == "shop.db"


def test_ocr_routes_on_keyword(planner):
    plan = planner.plan("run ocr on receipt.png")
    assert plan.intent == Intent.OCR_IMAGE
    assert plan.steps[0].capability == "ocr"
    assert plan.steps[0].args["path"] == "receipt.png"


def test_ocr_routes_on_extract_text_phrasing(planner):
    plan = planner.plan("extract the text from this screenshot shot.jpg please")
    assert plan.intent == Intent.OCR_IMAGE
    assert plan.steps[0].args["path"] == "shot.jpg"


def test_ocr_beats_ingest_for_image_path(planner):
    # An image path is OCR's, not the (doc) ingest path (which handles pdf/txt/…).
    plan = planner.plan("photos/diagram.png")
    assert plan.intent == Intent.OCR_IMAGE


def test_mail_routes_on_inbox(planner):
    plan = planner.plan("check my inbox")
    assert plan.intent == Intent.MAIL_SEARCH
    assert plan.steps[0].capability == "mail"
    assert plan.steps[0].args["query"] == ""


def test_mail_extracts_query_and_folder(planner):
    plan = planner.plan('search my email for "quarterly report" in Archive')
    assert plan.intent == Intent.MAIL_SEARCH
    assert plan.steps[0].args["query"] == "quarterly report"
    assert plan.steps[0].args["folder"] == "Archive"


def test_mail_routes_on_from_phrasing(planner):
    plan = planner.plan("find emails from alice")
    assert plan.intent == Intent.MAIL_SEARCH
    assert plan.steps[0].args["query"] == "alice"


def test_browse_routes_on_render_keyword(planner):
    plan = planner.plan("render https://example.com/app in a headless browser")
    assert plan.intent == Intent.BROWSE_URL
    assert plan.steps[0].capability == "browser"
    assert plan.steps[0].args["url"] == "https://example.com/app"
    assert plan.steps[0].args["action"] == "open"


def test_browse_screenshot_action(planner):
    plan = planner.plan("take a screenshot of https://example.com")
    assert plan.intent == Intent.BROWSE_URL
    assert plan.steps[0].args["action"] == "screenshot"


def test_plain_url_still_routes_to_web_fetch(planner):
    # Without a browser keyword, a bare URL stays plain web_fetch (browser is opt-in).
    plan = planner.plan("fetch https://example.com")
    assert plan.intent == Intent.WEB_FETCH


def test_research_routes_on_research_verb(planner):
    plan = planner.plan("research solar panel soiling losses")
    assert plan.intent == Intent.RESEARCH
    assert plan.steps[0].capability == "research"
    assert plan.steps[0].args["objective"] == "solar panel soiling losses"


def test_research_routes_on_investigate_and_deep_dive(planner):
    for msg, obj in [
        ("investigate whether heat pumps beat gas boilers",
         "heat pumps beat gas boilers"),
        ("do a deep dive on grid-scale battery economics",
         "grid-scale battery economics"),
        ("what does the evidence say about intermittent fasting",
         "intermittent fasting"),
    ]:
        plan = planner.plan(msg)
        assert plan.intent == Intent.RESEARCH, msg
        assert plan.steps[0].args["objective"] == obj, msg


def test_bare_search_does_not_route_to_research(planner):
    # A plain web search must not be captured by the research loop.
    plan = planner.plan("search the web for solar panels")
    assert plan.intent == Intent.WEB_SEARCH


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
