"""Tests for the AssistantService chat orchestrator (Sprint 10).

Hermetic: a real Planner + ConversationService (in-memory repo) drive real routing
and persistence, while knowledge/memory/agent/llm are fakes. No DB/Ollama.
"""

from __future__ import annotations

import uuid

from atlas.agents.base import AgentResult, Citation
from atlas.conversation import ConversationService
from atlas.execution import ToolExecutor
from atlas.kernel.tools import ToolRegistry
from atlas.llm.provider import LLMResponse
from atlas.models import ConversationMessage, ConversationSession, MemoryItem
from atlas.planner import Planner
from atlas.services.assistant_service import AssistantService, ChatTurn


class FakeConvRepo:
    def __init__(self):
        self.sessions = {}
        self.messages = {}

    def create_session(self, *, title=None, metadata=None):
        sid = str(uuid.uuid4())
        self.sessions[sid] = ConversationSession(id=sid, title=title, metadata=metadata or {})
        self.messages[sid] = []
        return self.sessions[sid]

    def get_session(self, session_id):
        return self.sessions.get(str(session_id))

    def list_sessions(self, *, limit=50):
        return list(self.sessions.values())[:limit]

    def touch_session(self, session_id):
        pass

    def add_message(self, session_id, role, content, *, tool_calls=None):
        sid = str(session_id)
        msg = ConversationMessage(
            id=str(uuid.uuid4()),
            session_id=sid,
            ordinal=len(self.messages[sid]),
            role=role,
            content=content,
            tool_calls=tool_calls or [],
        )
        self.messages[sid].append(msg)
        return msg

    def history(self, session_id, *, limit=None):
        msgs = self.messages.get(str(session_id), [])
        return msgs[-limit:] if limit else list(msgs)

    def count_sessions(self):
        return len(self.sessions)


class FakeMemory:
    def __init__(self):
        self.remembered = []
        self.recall_results = []

    def remember(self, content, *, kind="semantic", scope="global", **kw):
        item = MemoryItem(id="mem-1", kind=kind, content=content, scope=scope)
        self.remembered.append(item)
        return item

    def recall(self, query, *, scope=None, limit=5, kind=None):
        return self.recall_results


class FakeKnowledge:
    def __init__(self, docs=None):
        self._docs = docs or []
        self.ingested = None

    def list_documents(self, *, limit=25):
        return self._docs

    def ingest_text(self, source, content, **kw):
        self.ingested = (source, content, kw)
        return {"document_id": "doc-1", "status": "embedded", "chunks": 2, "deduped": False}


class FakeAgent:
    def __init__(self):
        self.calls = []

    def run(self, name, query, **options):
        self.calls.append((name, query))
        if name == "rag":
            return AgentResult(
                answer="It says Atlas is an AI OS [1].",
                citations=[Citation(1, "doc-1", "chunk-1", 0.9, "Atlas is an AI OS.")],
                usage={},
                run_id="run-rag",
            )
        return AgentResult(answer="96", citations=[], usage={"tools_used": []}, run_id="run-react")


class _RoleStub:
    def chat(self, messages, **options):
        return LLMResponse(text="SUMMARY", model="fake")


class FakeLLM:
    def for_role(self, role):
        return _RoleStub()


def _assistant(
    *, memory=None, knowledge=None, agent=None, with_web=True, with_search=True,
    search_result=None, with_python=True, python_result=None, capabilities=None,
    with_scholar=True, scholar_result=None, with_youtube=True, youtube_result=None,
    with_git=True, git_result=None, with_sql=True, sql_result=None,
    with_ocr=True, ocr_result=None,
):
    tools = ToolRegistry()
    if with_web:
        tools.register("web.fetch", lambda url: f"page content for {url}")
    if with_search:
        default = {
            "query": "q",
            "provider": "duckduckgo",
            "outcome": "ok",
            "results": [
                {"title": "Result A", "url": "https://a.example", "snippet": "about x"}
            ],
        }
        payload = search_result if search_result is not None else default
        tools.register("web.search", lambda query, max_results=5: payload)
    if with_scholar:
        default_sch = {
            "query": "q", "provider": "semantic_scholar", "outcome": "ok",
            "results": [
                {"title": "A Review of PV Soiling", "authors": ["A. Smith"],
                 "year": 2021, "venue": "Solar Energy", "url": "https://s2.org/1",
                 "level_name": "L4 peer-reviewed"}
            ],
            "sources": [{"id": "10.1/s2.1", "evidence_level": 4, "kind": "peer_reviewed"}],
        }
        sch_payload = scholar_result if scholar_result is not None else default_sch
        tools.register("scholar.search", lambda query, max_results=5: sch_payload)
    if with_youtube:
        default_yt = {
            "video_id": "abcdefghijk", "url": "https://youtu.be/abcdefghijk",
            "outcome": "ok", "title": "How Solar Works", "language": "en",
            "text": "Solar panels convert sunlight into electricity.", "segments": [],
        }
        yt_payload = youtube_result if youtube_result is not None else default_yt
        tools.register("youtube.transcript", lambda video: yt_payload)
    if with_python:
        default_py = {
            "outcome": "ok", "ok": True, "stdout": "4\n", "stderr": "",
            "returncode": 0, "error": None, "result": None, "artifacts": {},
            "backend": "subprocess", "duration_ms": 3,
        }
        py_payload = python_result if python_result is not None else default_py
        tools.register("python.run", lambda code, **kw: py_payload)
    if with_git:
        default_git = {
            "outcome": "ok", "repo": ".", "branch": "main", "ahead": 0, "behind": 0,
            "changes": [{"status": "M", "path": "a.py"}], "clean": False,
        }
        git_payload = git_result if git_result is not None else default_git
        tools.register("git.status", lambda repo, **kw: git_payload)
        tools.register(
            "git.log",
            lambda repo, **kw: {
                "outcome": "ok", "repo": repo,
                "commits": [{"short": "abc123", "date": "2026-07-01",
                             "author": "Ada", "subject": "init"}],
            },
        )
    if with_sql:
        default_sql = {
            "outcome": "ok", "backend": "sqlite", "columns": ["product", "amount"],
            "rows": [{"product": "a", "amount": 10.0}], "row_count": 1,
            "truncated": False,
        }
        sql_payload = sql_result if sql_result is not None else default_sql
        tools.register("sql.query", lambda sql, **kw: sql_payload)
    if with_ocr:
        default_ocr = {
            "outcome": "ok", "path": "scan.png", "lang": "eng", "engine": "tesseract",
            "text": "INVOICE 42", "chars": 10,
        }
        ocr_payload = ocr_result if ocr_result is not None else default_ocr
        tools.register("ocr.image", lambda path, **kw: ocr_payload)
    return AssistantService(
        ConversationService(FakeConvRepo(), memory),
        Planner(),
        ToolExecutor(tools, retry_base=0.0),
        knowledge=knowledge or FakeKnowledge(),
        memory=memory,
        agent=agent or FakeAgent(),
        llm=FakeLLM(),
        tools=tools,
        capabilities=capabilities,
    )


# --- per-intent behaviour -------------------------------------------------
def test_remember_stores_and_confirms():
    mem = FakeMemory()
    turn = _assistant(memory=mem).chat("Remember that I prefer PostgreSQL over Milvus.")
    assert isinstance(turn, ChatTurn)
    assert turn.intent == "remember"
    assert mem.remembered[0].content == "I prefer PostgreSQL over Milvus."
    assert "remember" in turn.answer.lower()
    assert turn.tool_calls[0]["action"] == "remember"


def test_recall_lists_memories():
    mem = FakeMemory()
    mem.recall_results = [MemoryItem(id="m", kind="semantic", content="prefers PostgreSQL")]
    turn = _assistant(memory=mem).chat("What do you remember about my preferences?")
    assert turn.intent == "recall"
    assert "prefers PostgreSQL" in turn.answer


def test_recall_when_empty_is_honest():
    turn = _assistant(memory=FakeMemory()).chat("what do you remember about me?")
    assert turn.intent == "recall"
    assert "don't have anything" in turn.answer.lower()


def test_list_documents_lists_titles():
    docs = [_doc("Solar Report", "embedded"), _doc("Notes", "chunked")]
    turn = _assistant(knowledge=FakeKnowledge(docs)).chat("What documents do you know about?")
    assert turn.intent == "list_documents"
    assert "Solar Report" in turn.answer and "Notes" in turn.answer


def test_list_documents_empty_is_honest():
    turn = _assistant(knowledge=FakeKnowledge([])).chat("what documents do you have?")
    assert "empty" in turn.answer.lower()


def test_ask_knowledge_uses_rag_and_returns_citations():
    agent = FakeAgent()
    turn = _assistant(agent=agent).chat("What does it say?")
    assert turn.intent == "ask_knowledge"
    assert ("rag", "What does it say?") in agent.calls
    assert turn.citations[0]["document_id"] == "doc-1"
    assert turn.run_id == "run-rag"


def test_general_question_uses_react():
    agent = FakeAgent()
    turn = _assistant(agent=agent).chat("What is 12 times 8?")
    assert turn.intent == "react"
    assert agent.calls[0][0] == "assistant"


def test_smalltalk_uses_llm_composition():
    turn = _assistant().chat("hello there")
    assert turn.intent == "smalltalk"
    assert turn.answer == "SUMMARY"


def test_web_fetch_summarizes():
    turn = _assistant().chat("fetch https://example.com")
    assert turn.intent == "web_fetch"
    assert turn.answer == "SUMMARY"
    assert turn.tool_calls[0]["ok"] is True


def test_web_search_lists_results():
    turn = _assistant().chat("search the web for solar soiling losses")
    assert turn.intent == "web_search"
    assert "Result A" in turn.answer
    assert "https://a.example" in turn.answer
    assert turn.tool_calls[0]["action"] == "web.search"
    assert turn.tool_calls[0]["ok"] is True


def test_web_search_reports_blocked_outcome_honestly():
    blocked = {"query": "q", "provider": "duckduckgo", "outcome": "blocked",
               "results": [], "reason": "HTTP 403"}
    turn = _assistant(search_result=blocked).chat("search the web for anything")
    assert turn.intent == "web_search"
    assert "unavailable" in turn.answer.lower()


def test_web_search_no_results_is_honest():
    empty = {"query": "q", "provider": "duckduckgo", "outcome": "ok", "results": []}
    turn = _assistant(search_result=empty).chat("search the web for zzzz")
    assert "no web results" in turn.answer.lower()


def test_search_gap_when_no_search_tool():
    turn = _assistant(with_search=False).chat("search the web for solar soiling")
    assert turn.capability_gaps
    assert turn.capability_gaps[0]["missing_capability"] == "search"


# --- scholar + youtube (S18a) ---------------------------------------------
def test_scholar_search_lists_papers():
    turn = _assistant().chat("find recent papers on PV soiling")
    assert turn.intent == "scholar_search"
    assert "A Review of PV Soiling" in turn.answer
    assert turn.tool_calls[0]["action"] == "scholar.search"
    assert turn.tool_calls[0]["ok"] is True


def test_scholar_reports_blocked_honestly():
    blocked = {"query": "q", "provider": "arxiv", "outcome": "blocked",
               "results": [], "sources": [], "reason": "HTTP 429"}
    turn = _assistant(scholar_result=blocked).chat("papers on graph neural networks")
    assert turn.intent == "scholar_search"
    assert "unavailable" in turn.answer.lower()


def test_scholar_gap_when_no_tool():
    turn = _assistant(with_scholar=False).chat("find papers on lithium batteries")
    assert turn.capability_gaps
    assert turn.capability_gaps[0]["missing_capability"] == "scholar"


def test_youtube_transcript_summarizes():
    turn = _assistant().chat("transcript of https://youtu.be/abcdefghijk")
    assert turn.intent == "youtube_transcript"
    assert turn.answer == "SUMMARY"
    assert turn.tool_calls[0]["action"] == "youtube.transcript"
    assert turn.tool_calls[0]["outcome"] == "ok"


def test_youtube_no_transcript_is_honest():
    none = {"video_id": "abcdefghijk", "url": "u", "outcome": "skipped",
            "title": "", "language": "", "text": "", "segments": [],
            "reason": "no captions available"}
    turn = _assistant(youtube_result=none).chat("transcript of https://youtu.be/abcdefghijk")
    assert "no transcript" in turn.answer.lower()


def test_youtube_gap_when_no_tool():
    turn = _assistant(with_youtube=False).chat("get the transcript of https://youtu.be/abcdefghijk")
    assert turn.capability_gaps
    assert turn.capability_gaps[0]["missing_capability"] == "transcript"


# --- run_python (S16) -----------------------------------------------------
def test_run_python_reports_output():
    turn = _assistant().chat("run this:\n```python\nprint(2 + 2)\n```")
    assert turn.intent == "run_python"
    assert "4" in turn.answer
    assert turn.tool_calls[0]["action"] == "python.run"
    assert turn.tool_calls[0]["outcome"] == "ok"


def test_run_python_reports_error_honestly():
    err = {"outcome": "error", "ok": False, "stdout": "", "returncode": 1,
           "stderr": "ValueError: boom", "error": "ValueError: boom",
           "result": None, "artifacts": {}, "backend": "subprocess", "duration_ms": 2}
    turn = _assistant(python_result=err).chat("execute python: raise ValueError('boom')")
    assert turn.intent == "run_python"
    assert "error" in turn.answer.lower()
    assert "boom" in turn.answer


def test_run_python_timeout_is_honest():
    to = {"outcome": "timeout", "ok": False, "stdout": "", "returncode": None,
          "stderr": "", "error": "timed out after 30s", "result": None,
          "artifacts": {}, "backend": "subprocess", "duration_ms": 30000}
    turn = _assistant(python_result=to).chat("run python: while True: pass")
    assert "timed out" in turn.answer.lower()


def test_run_python_blocked_when_sandbox_unavailable():
    blocked = {"outcome": "blocked", "ok": False, "stdout": "", "returncode": None,
               "stderr": "", "error": "docker sandbox backend is not implemented yet",
               "result": None, "artifacts": {}, "backend": "docker", "duration_ms": 0}
    turn = _assistant(python_result=blocked).chat("run python: print(1)")
    assert "unavailable" in turn.answer.lower()


def test_python_gap_when_no_python_tool():
    turn = _assistant(with_python=False).chat("run this:\n```python\nprint(1)\n```")
    assert turn.capability_gaps
    assert turn.capability_gaps[0]["missing_capability"] == "python"


# --- git (S20a) -----------------------------------------------------------
def test_git_status_reports_branch_and_changes():
    turn = _assistant().chat("what's the git status of /data/atlas?")
    assert turn.intent == "git_status"
    assert "main" in turn.answer
    assert turn.tool_calls[0]["action"] == "git.status"
    assert turn.tool_calls[0]["outcome"] == "ok"


def test_git_log_lists_commits():
    turn = _assistant().chat("show recent commits in /data/atlas")
    assert turn.intent == "git_status"
    assert "abc123" in turn.answer and "init" in turn.answer


def test_git_not_a_repo_is_honest():
    bad = {"outcome": "not_a_repo", "repo": "/tmp/x", "reason": "not a repo"}
    turn = _assistant(git_result=bad).chat("git status /tmp/x")
    assert "isn't a git repository" in turn.answer


def test_git_gap_when_no_tool():
    turn = _assistant(with_git=False).chat("git status /data/atlas")
    assert turn.capability_gaps
    assert turn.capability_gaps[0]["missing_capability"] == "git"


# --- sql (S20b) -----------------------------------------------------------
def test_sql_query_renders_rows():
    turn = _assistant().chat("run this:\n```sql\nSELECT product, amount FROM sales\n```")
    assert turn.intent == "sql_query"
    assert "product | amount" in turn.answer
    assert turn.tool_calls[0]["action"] == "sql.query"
    assert turn.tool_calls[0]["outcome"] == "ok"


def test_sql_blocked_is_honest():
    blocked = {"outcome": "blocked", "reason": "only read-only statements allowed",
               "backend": "sqlite"}
    turn = _assistant(sql_result=blocked).chat("```sql\nDELETE FROM sales\n```")
    assert "read-only" in turn.answer.lower()


def test_sql_unavailable_blocks_step():
    un = {"outcome": "unavailable", "reason": "database not found: x.db", "backend": "sqlite"}
    turn = _assistant(sql_result=un).chat("SELECT 1 FROM sales")
    assert "couldn't reach" in turn.answer.lower()


def test_sql_gap_when_no_tool():
    turn = _assistant(with_sql=False).chat("SELECT * FROM sales")
    assert turn.capability_gaps
    assert turn.capability_gaps[0]["missing_capability"] == "sql"


# --- ocr (S20c) -----------------------------------------------------------
def test_ocr_returns_text():
    turn = _assistant().chat("run ocr on scan.png")
    assert turn.intent == "ocr_image"
    assert "INVOICE 42" in turn.answer
    assert turn.tool_calls[0]["action"] == "ocr.image"
    assert turn.tool_calls[0]["outcome"] == "ok"


def test_ocr_unavailable_blocks_step():
    un = {"outcome": "unavailable", "reason": "tesseract not installed",
          "path": "scan.png", "engine": "tesseract"}
    turn = _assistant(ocr_result=un).chat("ocr scan.png")
    assert "isn't available" in turn.answer.lower()


def test_ocr_empty_is_honest():
    empty = {"outcome": "empty", "path": "scan.png", "text": "", "chars": 0,
             "engine": "tesseract", "lang": "eng"}
    turn = _assistant(ocr_result=empty).chat("extract text from scan.png")
    assert "no readable text" in turn.answer.lower()


def test_ocr_gap_when_no_tool():
    turn = _assistant(with_ocr=False).chat("run ocr on scan.png")
    assert turn.capability_gaps
    assert turn.capability_gaps[0]["missing_capability"] == "ocr"


def test_ingest_without_path_asks_for_one():
    turn = _assistant().chat("Read this PDF.")
    assert turn.intent == "ingest_path"
    assert "path" in turn.answer.lower()


def test_ingest_reads_and_ingests(tmp_path):
    doc = tmp_path / "note.md"
    doc.write_text("# Title\n\nAtlas is great.", encoding="utf-8")
    knowledge = FakeKnowledge()
    turn = _assistant(knowledge=knowledge).chat(f"ingest {doc}")
    assert turn.intent == "ingest_path"
    assert knowledge.ingested is not None
    assert "note.md" in turn.answer


# --- capability honesty (R2) ---------------------------------------------
def test_capability_gap_when_memory_missing():
    # No memory service => the 'remember' capability is unavailable.
    turn = _assistant(memory=None).chat("Remember that I like tea.")
    assert turn.capability_gaps
    assert turn.capability_gaps[0]["missing_capability"] == "memory"
    assert "missing" in turn.answer.lower()


def test_web_gap_when_no_web_tool():
    turn = _assistant(with_web=False).chat("fetch https://example.com")
    assert turn.capability_gaps
    assert turn.capability_gaps[0]["missing_capability"] == "web"


def test_gap_preflight_uses_capability_registry_when_wired():
    # With a registry, it is the source of truth: 'web' isn't registered here, so a
    # fetch is a gap even though the web.fetch tool exists.
    from atlas.capabilities import MemoryCapability
    from atlas.kernel.capabilities import CapabilityRegistry

    reg = CapabilityRegistry()
    reg.register("memory", FakeMemory(), contract=MemoryCapability, kind="service")
    turn = _assistant(with_web=True, capabilities=reg).chat("fetch https://example.com")
    assert turn.capability_gaps
    gap = turn.capability_gaps[0]
    assert gap["missing_capability"] == "web"
    assert gap["unlocks"]  # enriched from the capability catalog
    assert gap["since"] == "S7"


def test_no_gap_when_registry_provides_capability():
    from atlas.capabilities import MemoryCapability
    from atlas.kernel.capabilities import CapabilityRegistry

    reg = CapabilityRegistry()
    mem = FakeMemory()
    reg.register("memory", mem, contract=MemoryCapability, kind="service")
    turn = _assistant(memory=mem, capabilities=reg).chat("Remember that I like tea.")
    assert turn.capability_gaps == []
    assert turn.intent == "remember"


# --- session persistence --------------------------------------------------
def test_turns_persist_to_same_session():
    assistant = _assistant(memory=FakeMemory())
    first = assistant.chat("hello there")
    second = assistant.chat("hello again", session_id=first.session_id)
    assert second.session_id == first.session_id
    history = assistant._conversation.history(first.session_id)
    assert len(history) == 4  # 2 user + 2 assistant turns
    assert history[-1].tool_calls  # assistant turn records what it did


def _doc(title, status):
    from atlas.models import Document

    return Document(
        id=str(uuid.uuid4()), source="chat", checksum="x", title=title, status=status
    )
