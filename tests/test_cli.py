"""Tests for the `atlas` CLI (Sprint 5).

The argument parser is tested directly; command handlers are tested with a fake
Application injected, so no kernel/DB/Ollama is started.
"""

from __future__ import annotations

import pytest

from atlas.agents.base import AgentResult, Citation
from atlas.cli.main import (
    build_parser,
    cmd_agents,
    cmd_ask,
    cmd_backup,
    cmd_capabilities,
    cmd_chat,
    cmd_code,
    cmd_download,
    cmd_forget,
    cmd_formats,
    cmd_git,
    cmd_ingest,
    cmd_intel,
    cmd_job,
    cmd_jobs,
    cmd_learn,
    cmd_plugins,
    cmd_python,
    cmd_recall,
    cmd_remember,
    cmd_report,
    cmd_scholar,
    cmd_search,
    cmd_tool,
    cmd_tools,
    cmd_verify,
    cmd_websearch,
    cmd_youtube,
)
from atlas.services.assistant_service import ChatTurn
from atlas.knowledge.service import SearchResult
from atlas.models import MemoryItem
from atlas.reports.service import ReportService
from atlas.verification.service import VerificationService


class FakeAgentService:
    def list(self):
        return ["rag", "summarizer"]

    def run(self, name, query, **options):
        return AgentResult(
            answer=f"answer to {query!r} via {name}",
            citations=[
                Citation(1, "doc-1", "chunk-1", 0.9, "snippet"),
            ],
            usage={},
            run_id="run-1",
        )


class FakeKnowledge:
    def search(self, query, *, limit=5):
        return [SearchResult("chunk-1", "doc-1", 0, "the cat sat", 0.1, 0.9)]

    def ingest_text(self, source, content, **kwargs):
        return {"document_id": "doc-9", "status": "embedded", "chunks": 1, "deduped": False}


class FakeMemory:
    def __init__(self):
        self.forgot = None

    def remember(self, content, **kwargs):
        return MemoryItem(
            id="mem-1", kind=kwargs.get("kind", "semantic"), content=content,
            scope=kwargs.get("scope", "global"),
        )

    def recall(self, query, *, limit=5, kind=None, scope=None):
        return [MemoryItem(id="mem-1", kind="semantic", content="the cat sat", similarity=0.9)]

    def forget(self, memory_id):
        self.forgot = memory_id
        return memory_id == "mem-1"


class FakeDocuments:
    def supported(self):
        return [".csv", ".docx", ".pdf", ".txt"]


class FakeCode:
    def parse(self, path):
        return {"path": path, "lang": "python", "loc": 3, "outcome": "ok",
                "symbols": [{"name": "foo", "kind": "function", "parent": None,
                             "signature": "def foo()", "start_line": 1, "end_line": 2}]}

    def repo_map(self, root):
        return {"root": root, "file_count": 2, "total_loc": 10,
                "languages": {"python": 2}, "frameworks": ["FastAPI"],
                "entry_points": ["run.py"], "dependencies": {"python": ["pytest"]}}

    def graph(self, root):
        return {"import_edges": [["a.py", "b.py"]], "call_edges": [],
                "import_edge_count": 1, "call_edge_count": 0,
                "unresolved_calls": 0, "external_imports": 1}

    def patterns(self, root):
        return [{"name": "Repository pattern", "description": "repo",
                 "confidence": 0.9, "evidence": ["2 classes"]}]

    def search_symbols(self, query, *, root, kind=None, lang=None, limit=50):
        return [{"kind": "function", "qualname": "foo", "file": "a.py", "start_line": 1}]

    def explain(self, path, question=None):
        return {"path": path, "outcome": "ok", "outline": "file: a.py", "explanation": "x"}


class FakePluginManager:
    def describe(self):
        return [{"name": "filesystem", "version": "0.1.0"}, {"name": "web", "version": "0.1.0"}]


class FakeTools:
    def describe(self):
        return [{"name": "fs.read", "description": "Read a file.", "params": {}, "plugin": "filesystem"}]


class FakeBackup:
    def backup(self):
        return "/data/atlas_data/backups/atlas_atlas_20260101_000000.dump"


class FakePython:
    def run(self, code, *, timeout=None):
        return {"outcome": "ok", "stdout": "4\n", "stderr": "", "returncode": 0,
                "duration_ms": 3, "error": None, "result": None, "backend": "subprocess"}

    def run_file(self, path, *, timeout=None):
        return {"outcome": "ok", "stdout": "from file\n", "stderr": "",
                "returncode": 0, "duration_ms": 3, "error": None, "result": None,
                "backend": "subprocess"}


class FakeChat:
    def chat(self, message, *, session_id=None, **options):
        return ChatTurn(
            session_id=session_id or "sess-1",
            answer=f"answer to {message!r}",
            intent="react",
        )


class FakeJobs:
    def __init__(self):
        from atlas.models.job import Job, JobStep

        self._job = Job(id="job-1", objective="do research", status="running")
        self._steps = [
            JobStep(id="s0", job_id="job-1", ordinal=0, intent="react",
                    capability="agent", status="done"),
            JobStep(id="s1", job_id="job-1", ordinal=1, intent="web_fetch",
                    capability="web", status="blocked",
                    blocked_reason="needs capability: web"),
        ]
        self.resumed = None
        self.cancelled = None

    def _detail(self):
        return {
            "job": self._job,
            "steps": self._steps,
            "progress": {"total": 2, "done": 1, "blocked": 1, "failed": 0},
            "blocked": [],
        }

    def create_job(self, objective, *, session_id=None):
        return self._detail()

    def list_jobs(self, *, status=None, limit=50):
        return [self._job]

    def list_blocked(self, *, limit=50):
        return [{"job_id": "job-1", "ordinal": 1, "capability": "web",
                 "needs": "needs capability: web", "objective": "do research"}]

    def job_detail(self, job_id):
        if job_id != "job-1":
            raise KeyError(job_id)
        return self._detail()

    def resume_job(self, job_id):
        self.resumed = job_id
        return self._detail()

    def cancel_job(self, job_id):
        self.cancelled = job_id
        return self._detail()


def _fake_capabilities():
    from atlas.capabilities import MemoryCapability
    from atlas.kernel.capabilities import CapabilityRegistry

    reg = CapabilityRegistry()
    reg.register("memory", FakeMemory(), contract=MemoryCapability, kind="service")
    return reg


class FakeApp:
    def __init__(self):
        self.tools = FakeTools()
        self.capabilities = _fake_capabilities()
        self.container = _Container(
            {
                "agent": FakeAgentService(),
                "knowledge": FakeKnowledge(),
                "memory": FakeMemory(),
                "chat": FakeChat(),
                "plugins": FakePluginManager(),
                "backup": FakeBackup(),
                "jobs": FakeJobs(),
                "documents": FakeDocuments(),
                "code": FakeCode(),
                "python": FakePython(),
                "verification": VerificationService(),
                "reports": ReportService(VerificationService()),
                "learning": _fake_learning(),
                "intelligence": _fake_intelligence(),
            }
        )

    def invoke_tool(self, name, **kwargs):
        if name == "web.search":
            return {
                "query": kwargs.get("query"),
                "provider": "duckduckgo",
                "outcome": "ok",
                "results": [
                    {"title": "R1", "url": "https://a.example", "snippet": "s"}
                ],
            }
        if name == "web.download":
            return {
                "url": kwargs.get("url"),
                "path": "/tmp/downloads/file.pdf",
                "bytes": 42,
                "outcome": "ok",
            }
        if name == "scholar.search":
            return {
                "query": kwargs.get("query"),
                "provider": "semantic_scholar",
                "outcome": "ok",
                "results": [
                    {"title": "Paper A", "authors": ["A. Smith"], "year": 2021,
                     "venue": "Solar Energy", "url": "https://s2.org/1",
                     "level_name": "L4 peer-reviewed"}
                ],
            }
        if name == "youtube.transcript":
            return {
                "video_id": "abcdefghijk", "url": kwargs.get("video"), "outcome": "ok",
                "title": "How Solar Works", "language": "en",
                "text": "Solar panels convert sunlight into electricity.", "segments": [],
            }
        if name == "git.status":
            return {
                "outcome": "ok", "repo": kwargs.get("repo"), "branch": "main",
                "ahead": 1, "behind": 0,
                "changes": [{"status": "M", "path": "a.py"}], "clean": False,
            }
        if name == "git.log":
            return {
                "outcome": "ok", "repo": kwargs.get("repo"),
                "commits": [{"short": "abc123", "date": "2026-07-01",
                             "author": "Ada", "subject": "init"}],
            }
        return {"tool": name, "args": kwargs}


def _fake_learning():
    from atlas.services.learning_service import LearningService
    from tests.test_learning import FakeLearningRepo

    return LearningService(FakeLearningRepo())


def _fake_intelligence():
    from atlas.intelligence.service import CodeStoreSink, IntelligenceService
    from atlas.services.learning_service import LearningService
    from tests.test_intelligence import FakeCodeService, FakeIntelRepo, _repo_fixture
    from tests.test_learning import FakeLearningRepo

    code = FakeCodeService({
        "/repos/a": _repo_fixture("a", ["FastAPI"], {"python": 10}, ["Repository pattern"]),
        "/repos/b": _repo_fixture("b", ["FastAPI"], {"python": 8}, ["Repository pattern"]),
    })
    intel_repo = FakeIntelRepo()
    learning = LearningService(FakeLearningRepo())
    learning.register_sink("code", CodeStoreSink(intel_repo))
    return IntelligenceService(code, intel_repo, learning)


class _Container:
    def __init__(self, mapping):
        self._mapping = mapping

    def resolve(self, key):
        return self._mapping[key]


# --- parser ---------------------------------------------------------------
def test_parser_requires_a_command():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_parser_ask_defaults():
    args = build_parser().parse_args(["ask", "what is atlas?"])
    assert args.command == "ask"
    assert args.query == "what is atlas?"
    assert args.agent == "rag"
    assert args.k is None


def test_parser_serve_options():
    args = build_parser().parse_args(["serve", "--host", "0.0.0.0", "--port", "9000"])
    assert args.host == "0.0.0.0"
    assert args.port == 9000


# --- handlers -------------------------------------------------------------
def test_cmd_agents_lists(capsys):
    args = build_parser().parse_args(["agents"])
    rc = cmd_agents(args, app=FakeApp())
    assert rc == 0
    out = capsys.readouterr().out
    assert "rag" in out and "summarizer" in out


def test_cmd_ask_prints_answer(capsys):
    args = build_parser().parse_args(["ask", "hello", "--agent", "rag"])
    rc = cmd_ask(args, app=FakeApp())
    assert rc == 0
    assert "answer to 'hello' via rag" in capsys.readouterr().out


def test_cmd_search_prints_results(capsys):
    args = build_parser().parse_args(["search", "cat", "--limit", "1"])
    rc = cmd_search(args, app=FakeApp())
    assert rc == 0
    out = capsys.readouterr().out
    assert "doc-1" in out and "the cat sat" in out


def test_cmd_ingest_missing_file(tmp_path):
    args = build_parser().parse_args(["ingest", str(tmp_path / "nope.md")])
    rc = cmd_ingest(args, app=FakeApp())
    assert rc == 1


def test_cmd_ingest_reads_and_ingests(tmp_path, capsys):
    doc = tmp_path / "note.md"
    doc.write_text("# Title\n\nAtlas is great.", encoding="utf-8")
    args = build_parser().parse_args(["ingest", str(doc)])
    rc = cmd_ingest(args, app=FakeApp())
    assert rc == 0
    assert "doc-9" in capsys.readouterr().out


# --- memory ---------------------------------------------------------------
def test_parser_remember_defaults():
    args = build_parser().parse_args(["remember", "a fact"])
    assert args.kind == "semantic"
    assert args.scope == "global"
    assert args.ttl is None


def test_parser_remember_rejects_bad_kind():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["remember", "x", "--kind", "bogus"])


def test_cmd_remember_prints_id(capsys):
    args = build_parser().parse_args(["remember", "Atlas rocks", "--kind", "episodic"])
    rc = cmd_remember(args, app=FakeApp())
    assert rc == 0
    assert "mem-1" in capsys.readouterr().out


def test_cmd_recall_prints_results(capsys):
    args = build_parser().parse_args(["recall", "cat", "--limit", "1"])
    rc = cmd_recall(args, app=FakeApp())
    assert rc == 0
    out = capsys.readouterr().out
    assert "mem-1" in out and "the cat sat" in out


def test_cmd_forget_found(capsys):
    args = build_parser().parse_args(["forget", "mem-1"])
    rc = cmd_forget(args, app=FakeApp())
    assert rc == 0
    assert "forgotten" in capsys.readouterr().out


def test_cmd_forget_not_found(capsys):
    args = build_parser().parse_args(["forget", "ghost"])
    rc = cmd_forget(args, app=FakeApp())
    assert rc == 1
    assert "not found" in capsys.readouterr().out


# --- plugins / tools ------------------------------------------------------
def test_cmd_plugins_lists(capsys):
    args = build_parser().parse_args(["plugins"])
    rc = cmd_plugins(args, app=FakeApp())
    assert rc == 0
    out = capsys.readouterr().out
    assert "filesystem" in out and "web" in out


def test_cmd_tools_lists(capsys):
    args = build_parser().parse_args(["tools"])
    rc = cmd_tools(args, app=FakeApp())
    assert rc == 0
    assert "fs.read" in capsys.readouterr().out


def test_cmd_tool_invokes_with_args(capsys):
    args = build_parser().parse_args(
        ["tool", "web.fetch", "--arg", "url=https://example.com"]
    )
    rc = cmd_tool(args, app=FakeApp())
    assert rc == 0
    out = capsys.readouterr().out
    assert "web.fetch" in out and "https://example.com" in out


def test_cmd_tool_rejects_bad_arg():
    args = build_parser().parse_args(["tool", "fs.read", "--arg", "noequals"])
    rc = cmd_tool(args, app=FakeApp())
    assert rc == 1


def test_cmd_capabilities_lists_provided_and_missing(capsys):
    args = build_parser().parse_args(["capabilities"])
    rc = cmd_capabilities(args, app=FakeApp())
    assert rc == 0
    out = capsys.readouterr().out
    # provided one is marked ok; a catalogued-but-unregistered one shows unlocks
    assert "[ok " in out and "memory" in out
    assert "search" in out and "unlocks:" in out


# --- chat -----------------------------------------------------------------
def test_parser_chat_oneshot():
    args = build_parser().parse_args(["chat", "hello"])
    assert args.command == "chat"
    assert args.message == "hello"
    assert args.session is None


def test_parser_chat_repl_has_no_message():
    args = build_parser().parse_args(["chat"])
    assert args.message is None


def test_cmd_chat_oneshot_prints_answer(capsys):
    args = build_parser().parse_args(["chat", "what is atlas?"])
    rc = cmd_chat(args, app=FakeApp())
    assert rc == 0
    assert "answer to 'what is atlas?'" in capsys.readouterr().out


# --- jobs -----------------------------------------------------------------
def test_parser_job_start():
    args = build_parser().parse_args(["job", "start", "research soiling loss"])
    assert args.command == "job"
    assert args.action == "start"
    assert args.target == "research soiling loss"


def test_cmd_jobs_lists(capsys):
    args = build_parser().parse_args(["jobs"])
    rc = cmd_jobs(args, app=FakeApp())
    assert rc == 0
    assert "job-1" in capsys.readouterr().out


def test_cmd_job_start_prints_id(capsys):
    args = build_parser().parse_args(["job", "start", "do research"])
    rc = cmd_job(args, app=FakeApp())
    assert rc == 0
    out = capsys.readouterr().out
    assert "started job job-1" in out
    assert "needs: needs capability: web" in out


def test_cmd_job_show(capsys):
    args = build_parser().parse_args(["job", "show", "job-1"])
    rc = cmd_job(args, app=FakeApp())
    assert rc == 0
    assert "job job-1" in capsys.readouterr().out


def test_cmd_job_resume(capsys):
    app = FakeApp()
    args = build_parser().parse_args(["job", "resume", "job-1"])
    rc = cmd_job(args, app=app)
    assert rc == 0
    assert app.container.resolve("jobs").resumed == "job-1"


def test_cmd_job_show_unknown(capsys):
    args = build_parser().parse_args(["job", "show", "ghost"])
    rc = cmd_job(args, app=FakeApp())
    assert rc == 1
    assert "no job ghost" in capsys.readouterr().err


# --- documents ------------------------------------------------------------
def test_cmd_formats_lists(capsys):
    args = build_parser().parse_args(["formats"])
    rc = cmd_formats(args, app=FakeApp())
    assert rc == 0
    out = capsys.readouterr().out
    assert ".pdf" in out and ".docx" in out


# --- web search / download ------------------------------------------------
def test_cmd_websearch_lists(capsys):
    args = build_parser().parse_args(["websearch", "solar soiling"])
    rc = cmd_websearch(args, app=FakeApp())
    assert rc == 0
    out = capsys.readouterr().out
    assert "R1" in out and "https://a.example" in out


def test_cmd_scholar_lists_papers(capsys):
    args = build_parser().parse_args(["scholar", "pv soiling"])
    rc = cmd_scholar(args, app=FakeApp())
    assert rc == 0
    out = capsys.readouterr().out
    assert "Paper A" in out
    assert "L4 peer-reviewed" in out


def test_cmd_youtube_prints_transcript(capsys):
    args = build_parser().parse_args(["youtube", "https://youtu.be/abcdefghijk"])
    rc = cmd_youtube(args, app=FakeApp())
    assert rc == 0
    out = capsys.readouterr().out
    assert "How Solar Works" in out
    assert "Solar panels convert sunlight" in out


def test_cmd_git_status(capsys):
    args = build_parser().parse_args(["git", "status", "/data/atlas"])
    rc = cmd_git(args, app=FakeApp())
    assert rc == 0
    out = capsys.readouterr().out
    assert "branch main" in out
    assert "M a.py" in out


def test_cmd_git_log(capsys):
    args = build_parser().parse_args(["git", "log", "/repo", "--max", "5"])
    rc = cmd_git(args, app=FakeApp())
    assert rc == 0
    out = capsys.readouterr().out
    assert "abc123" in out and "init" in out


def test_cmd_download_prints_path(capsys):
    args = build_parser().parse_args(["download", "https://example.com/x.pdf"])
    rc = cmd_download(args, app=FakeApp())
    assert rc == 0
    assert "/tmp/downloads/file.pdf" in capsys.readouterr().out


# --- code -----------------------------------------------------------------
def test_cmd_code_map(capsys):
    args = build_parser().parse_args(["code", "map", "/repo"])
    rc = cmd_code(args, app=FakeApp())
    assert rc == 0
    out = capsys.readouterr().out
    assert "FastAPI" in out and "run.py" in out


def test_cmd_code_parse(capsys):
    args = build_parser().parse_args(["code", "parse", "a.py"])
    rc = cmd_code(args, app=FakeApp())
    assert rc == 0
    assert "def foo()" in capsys.readouterr().out


def test_cmd_code_symbols(capsys):
    args = build_parser().parse_args(["code", "symbols", "/repo", "-q", "foo"])
    rc = cmd_code(args, app=FakeApp())
    assert rc == 0
    assert "foo" in capsys.readouterr().out


def test_cmd_code_graph(capsys):
    args = build_parser().parse_args(["code", "graph", "/repo"])
    rc = cmd_code(args, app=FakeApp())
    assert rc == 0
    assert "import edges: 1" in capsys.readouterr().out


def test_cmd_code_patterns(capsys):
    args = build_parser().parse_args(["code", "patterns", "/repo"])
    rc = cmd_code(args, app=FakeApp())
    assert rc == 0
    assert "Repository pattern" in capsys.readouterr().out


# --- python (S16) ---------------------------------------------------------
def test_cmd_python_inline(capsys):
    args = build_parser().parse_args(["python", "print(2+2)"])
    rc = cmd_python(args, app=FakeApp())
    assert rc == 0
    out = capsys.readouterr().out
    assert "outcome: ok" in out
    assert "4" in out


def test_cmd_python_file(capsys):
    args = build_parser().parse_args(["python", "-f", "prog.py"])
    rc = cmd_python(args, app=FakeApp())
    assert rc == 0
    assert "from file" in capsys.readouterr().out


def test_cmd_python_no_input_returns_2(capsys):
    args = build_parser().parse_args(["python"])
    rc = cmd_python(args, app=FakeApp())
    assert rc == 2


# --- report + blocked queue (S17) -----------------------------------------
def test_cmd_report_prints_markdown(capsys, tmp_path):
    import json

    graph = {
        "objective": "Estimate soiling",
        "claims": [
            {
                "id": "c1",
                "statement": "Soiling ~ 4%",
                "evidence": [
                    {"source_id": "s1", "evidence_level": 4, "extracted_value": 3.9},
                    {"source_id": "s2", "evidence_level": 3, "extracted_value": 4.0},
                    {"source_id": "s3", "evidence_level": 4, "extracted_value": 3.8},
                ],
            }
        ],
    }
    path = tmp_path / "g.json"
    path.write_text(json.dumps(graph), encoding="utf-8")
    args = build_parser().parse_args(["report", str(path)])
    rc = cmd_report(args, app=FakeApp())
    assert rc == 0
    out = capsys.readouterr().out
    assert "# Research Report:" in out
    assert "Soiling" in out


def test_cmd_jobs_blocked(capsys):
    args = build_parser().parse_args(["jobs", "--blocked"])
    rc = cmd_jobs(args, app=FakeApp())
    assert rc == 0
    out = capsys.readouterr().out
    assert "needs capability: web" in out


# --- learn (S18b) ---------------------------------------------------------
def test_cmd_learn_remember_and_recall(capsys):
    app = FakeApp()
    learning = app.container.resolve("learning")
    learning.remember_experience(
        problem="deadlock on migrate", solution="lock_timeout",
        lessons="run migrations serially",
    )
    args = build_parser().parse_args(["learn", "recall", "deadlock"])
    rc = cmd_learn(args, app=app)
    assert rc == 0
    out = capsys.readouterr().out
    assert "deadlock" in out
    assert "run migrations serially" in out


def test_cmd_learn_events_and_revert(capsys):
    app = FakeApp()
    learning = app.container.resolve("learning")
    learning.remember_experience(problem="p1", solution="s1")
    events = learning.list_events()
    eid = events[0]["id"]

    args = build_parser().parse_args(["learn", "events"])
    assert cmd_learn(args, app=app) == 0
    assert eid in capsys.readouterr().out

    args = build_parser().parse_args(["learn", "revert", eid])
    assert cmd_learn(args, app=app) == 0
    assert "reverted" in capsys.readouterr().out
    assert learning.list_experiences() == []


def test_cmd_learn_show_unknown_returns_1(capsys):
    args = build_parser().parse_args(["learn", "show", "ghost"])
    rc = cmd_learn(args, app=FakeApp())
    assert rc == 1
    assert "not found" in capsys.readouterr().out


# --- intel (S19) ----------------------------------------------------------
def test_cmd_intel_learn_and_repos(capsys):
    app = FakeApp()
    args = build_parser().parse_args(["intel", "learn", "/repos/a"])
    rc = cmd_intel(args, app=app)
    assert rc == 0
    assert "learned a" in capsys.readouterr().out
    args = build_parser().parse_args(["intel", "repos"])
    rc = cmd_intel(args, app=app)
    assert rc == 0
    assert "FastAPI" in capsys.readouterr().out


def test_cmd_intel_generalize_and_recommend(capsys):
    app = FakeApp()
    for path in ("/repos/a", "/repos/b"):
        cmd_intel(build_parser().parse_args(["intel", "learn", path]), app=app)
    capsys.readouterr()
    rc = cmd_intel(build_parser().parse_args(["intel", "generalize"]), app=app)
    assert rc == 0
    assert "Repository pattern" in capsys.readouterr().out
    rc = cmd_intel(build_parser().parse_args(["intel", "recommend"]), app=app)
    assert rc == 0
    assert "consider it here" in capsys.readouterr().out


def test_cmd_intel_learn_bad_path(capsys):
    args = build_parser().parse_args(["intel", "learn", "/nope"])
    rc = cmd_intel(args, app=FakeApp())
    assert rc == 1
    assert "error" in capsys.readouterr().out


# --- verify (S15) ---------------------------------------------------------
def test_cmd_verify_prints_confidence(capsys, tmp_path):
    import json

    graph = {
        "claims": [
            {
                "id": "c1",
                "statement": "Soiling loss ~ 4%",
                "evidence": [
                    {"source_id": "s1", "evidence_level": 4, "extracted_value": 3.9},
                    {"source_id": "s2", "evidence_level": 3, "extracted_value": 4.0},
                    {"source_id": "s3", "evidence_level": 4, "extracted_value": 3.8},
                ],
            }
        ]
    }
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(graph), encoding="utf-8")
    args = build_parser().parse_args(["verify", str(path)])
    rc = cmd_verify(args, app=FakeApp())
    assert rc == 0
    out = capsys.readouterr().out
    assert "[HIGH]" in out
    assert "convergence=100%" in out


# --- backup ---------------------------------------------------------------
def test_parser_backup():
    args = build_parser().parse_args(["backup"])
    assert args.command == "backup"


def test_cmd_backup_prints_path(capsys):
    args = build_parser().parse_args(["backup"])
    rc = cmd_backup(args, app=FakeApp())
    assert rc == 0
    assert "atlas_atlas_20260101_000000.dump" in capsys.readouterr().out
