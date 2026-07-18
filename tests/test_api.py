"""Tests for the REST API (Sprint 5).

Hermetic: a fake Application is injected into the app state and the TestClient is
NOT used as a context manager, so the kernel lifespan (which would start real
services) never runs. Only the HTTP layer + auth + service wiring is exercised.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from atlas.agents.base import AgentResult, Citation
from atlas.api.app import create_app
from atlas.config import get_config
from atlas.exceptions import AgentNotFoundError, ToolNotFoundError
from atlas.knowledge.service import SearchResult
from atlas.models import ConversationMessage, ConversationSession, MemoryItem
from atlas.services.assistant_service import ChatTurn
from atlas.reports.service import ReportService
from atlas.services.base import HealthStatus
from atlas.verification.service import VerificationService

API_KEY = "test-secret-key"
AUTH = {"Authorization": f"Bearer {API_KEY}"}


class FakeAgentService:
    def list(self):
        return ["rag"]

    def run(self, name, query, **options):
        if name != "rag":
            raise AgentNotFoundError(f"no agent named '{name}'", agent=name)
        return AgentResult(
            answer="Atlas is an AI OS [1]",
            citations=[
                Citation(
                    index=1,
                    document_id="doc-1",
                    chunk_id="chunk-1",
                    similarity=0.82,
                    snippet="Atlas is an AI operating system.",
                )
            ],
            usage={"model": "qwen3:4b", "used": 1},
            run_id="run-1",
        )


class FakeKnowledge:
    def search(self, query, *, limit=5):
        return [
            SearchResult(
                chunk_id="chunk-1",
                document_id="doc-1",
                ordinal=0,
                content="Atlas is an AI operating system.",
                distance=0.2,
                similarity=0.8,
            )
        ]

    def retrieve(self, query, *, k=5, role="chat", **kwargs):
        from atlas.knowledge.access import RankedContext, RankedHit

        hits = [
            RankedHit(
                chunk_id="chunk-1",
                document_id="doc-1",
                ordinal=0,
                content="Atlas is an AI operating system.",
                dense_score=0.8,
                lexical_score=0.5,
                rrf_score=0.03,
                score=0.03,
                distance=0.2,
                similarity=0.8,
            )
        ]
        return RankedContext(
            query=query,
            hits=tuple(hits[:k]),
            context="[1] Atlas is an AI operating system.",
            citations=(
                {
                    "index": 1,
                    "document_id": "doc-1",
                    "chunk_id": "chunk-1",
                    "similarity": 0.8,
                    "snippet": "Atlas is an AI operating system.",
                },
            ),
            role=role,
            mode=str(kwargs.get("mode") or "hybrid"),
        )

    def list_documents(self, *, limit=50):
        return []

    def ingest_text(self, source, content, **kwargs):
        return {
            "document_id": "doc-1",
            "status": "embedded",
            "chunks": 3,
            "deduped": False,
        }


class FakeMemory:
    def __init__(self):
        self.forgot = None

    def remember(self, content, **kwargs):
        return MemoryItem(
            id="mem-1",
            kind=kwargs.get("kind", "semantic"),
            content=content,
            scope=kwargs.get("scope", "global"),
            importance=kwargs.get("importance", 0.0),
            metadata=kwargs.get("metadata") or {},
        )

    def recall(self, query, *, limit=5, kind=None, scope=None):
        return [
            MemoryItem(id="mem-1", kind="semantic", content="recalled", similarity=0.77)
        ]

    def recent(self, *, kind=None, scope=None, limit=20):
        return [MemoryItem(id="mem-1", kind="episodic", content="recent")]

    def forget(self, memory_id):
        self.forgot = memory_id
        return True


class FakeChat:
    def chat(self, message, *, session_id=None, **options):
        return ChatTurn(
            session_id=session_id or "sess-1",
            answer=f"reply to {message!r}",
            intent="ask_knowledge",
            citations=[
                {
                    "index": 1,
                    "document_id": "doc-1",
                    "chunk_id": "chunk-1",
                    "similarity": 0.9,
                    "snippet": "snip",
                }
            ],
            tool_calls=[{"intent": "ask_knowledge", "action": "rag"}],
            run_id="run-1",
        )


class FakeConversation:
    def list_sessions(self, *, limit=50):
        return [ConversationSession(id="sess-1", title="First")]

    def get_session(self, session_id):
        return ConversationSession(id=session_id) if session_id == "sess-1" else None

    def history(self, session_id, *, limit=None):
        return [
            ConversationMessage(id="m0", session_id=session_id, ordinal=0, role="user", content="hi"),
            ConversationMessage(id="m1", session_id=session_id, ordinal=1, role="assistant", content="hello"),
        ]


class FakeJobs:
    def __init__(self):
        from atlas.models.job import Job, JobStep

        self._job = Job(id="job-1", objective="research x", status="completed_with_blocks")
        self._steps = [
            JobStep(id="s0", job_id="job-1", ordinal=0, intent="react",
                    capability="agent", status="done", description="reason"),
            JobStep(id="s1", job_id="job-1", ordinal=1, intent="web_fetch",
                    capability="web", status="blocked", description="fetch",
                    blocked_reason="needs capability: web"),
        ]
        self.resumed = None
        self.cancelled = None

    def _detail(self):
        return {
            "job": self._job,
            "steps": self._steps,
            "progress": {"total": 2, "done": 1, "blocked": 1},
            "blocked": [{"ordinal": 1, "needs": "needs capability: web"}],
            "phase": "ready",
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
        if job_id != "job-1":
            raise KeyError(job_id)
        self.resumed = job_id
        return self._detail()

    def cancel_job(self, job_id):
        if job_id != "job-1":
            raise KeyError(job_id)
        self.cancelled = job_id
        return self._detail()

    def add_job_input(self, job_id, text):
        if job_id != "job-1":
            raise KeyError(job_id)
        if not (text or "").strip():
            raise ValueError("empty input")
        self.last_input = text
        return self._detail()


class FakeDocuments:
    def supported(self):
        return [".csv", ".docx", ".pdf", ".txt"]


class FakeCode:
    def parse(self, path):
        return {"path": path, "lang": "python", "outcome": "ok",
                "symbols": [{"name": "foo", "kind": "function"}]}

    def repo_map(self, root):
        return {"root": root, "file_count": 3, "frameworks": ["FastAPI"]}

    def graph(self, root):
        return {"import_edges": [["a.py", "b.py"]], "call_edges": [],
                "import_edge_count": 1, "call_edge_count": 0,
                "unresolved_calls": 0, "external_imports": 2}

    def patterns(self, root):
        return [{"name": "Repository pattern", "confidence": 0.9, "evidence": []}]

    def search_symbols(self, query, *, root, kind=None, lang=None, limit=50):
        return [{"name": "foo", "qualname": "foo", "kind": "function",
                 "file": "a.py", "start_line": 1}]

    def explain(self, path, question=None):
        return {"path": path, "outcome": "ok", "outline": "file: a.py",
                "explanation": "does things", "grounded": True}


class FakePython:
    def run(self, code, *, timeout=None, files=None, stdin=None):
        return {
            "outcome": "ok", "ok": True, "stdout": "hi\n", "stderr": "",
            "returncode": 0, "duration_ms": 4, "timed_out": False,
            "truncated": False, "error": None, "result": None,
            "artifacts": {}, "backend": "subprocess", "workdir": "/tmp/sandbox/x",
        }


class FakePluginManager:
    def describe(self):
        return [{"name": "filesystem", "version": "0.1.0"}]


class FakeTools:
    def describe(self):
        return [
            {
                "name": "web.fetch",
                "description": "Fetch a URL.",
                "params": {"url": "the URL"},
                "plugin": "web",
            }
        ]


def _fake_capabilities():
    from atlas.capabilities import KnowledgeCapability, MemoryCapability
    from atlas.kernel.capabilities import CapabilityRegistry

    reg = CapabilityRegistry()
    reg.register("memory", FakeMemory(), contract=MemoryCapability, kind="service")
    reg.register("knowledge", FakeKnowledge(), contract=KnowledgeCapability, kind="service")
    return reg


def _fake_learning():
    from atlas.services.learning_service import LearningService
    from tests.test_learning import FakeLearningRepo

    return LearningService(FakeLearningRepo())


def _fake_intelligence():
    from atlas.intelligence.service import CodeStoreSink, IntelligenceService
    from atlas.services.learning_service import LearningService
    from tests.test_intelligence import FakeCodeService, FakeIntelRepo, _repo_fixture
    from tests.test_learning import FakeLearningRepo

    code = FakeCodeService({"/repos/api": _repo_fixture(
        "api", ["FastAPI"], {"python": 10}, ["Repository pattern"]
    )})
    intel_repo = FakeIntelRepo()
    learning = LearningService(FakeLearningRepo())
    learning.register_sink("code", CodeStoreSink(intel_repo))
    return IntelligenceService(code, intel_repo, learning)


class FakeEventRepo:
    def recent(self, *, limit=100, event_type=None):
        from datetime import datetime, timezone

        rows = [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "event_type": "job.completed",
                "payload": {"job": "abc"},
                "source": "jobs",
                "status": "pending",
                "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            }
        ]
        if event_type is not None:
            rows = [r for r in rows if r["event_type"] == event_type]
        return rows[:limit]


class FakeNotifier:
    def __init__(self):
        from atlas.notify import EventBroker

        self.broker = EventBroker()

    def subscribe(self):
        return self.broker.subscribe()


class FakeOpsDashboard:
    def snapshot(self):
        return {
            "atlas": {"version": "0.1.0", "healthy": True, "degraded": False,
                      "uptime_seconds": 12.0, "severity_counts": {"ok": 3, "degraded": 0, "failed": 0}},
            "counts": {"jobs_total": 2, "jobs_active": 1, "jobs_queued": 1,
                       "workers": 0, "missions": 0},
            "host": {"cpu": {"percent": 5.0, "count": 8}, "memory": {"percent": 40.0},
                     "disk": {"percent": 71.0}, "internet": {"reachable": True},
                     "temperature": {"present": False}, "ups": {"present": False}},
            "backup": {"last": "atlas_2026.dump", "count": 3},
            "storage": {"detail": "storage ready"},
            "capabilities": [{"name": "clock", "kind": "kernel", "version": "0.1.0"}],
            "sse_subscribers": 0,
            "last_checkpoint": None,
            "generated_at": "2026-01-01T00:00:00+00:00",
        }


class FakeContainer:
    def __init__(self, mapping):
        self._mapping = mapping

    def resolve(self, key):
        return self._mapping[key]


class FakeApplication:
    def __init__(self, keys):
        cfg = get_config().model_copy(deep=True)
        cfg.api.keys = list(keys)
        self.config = cfg
        self.tools = FakeTools()
        self.capabilities = _fake_capabilities()
        self.container = FakeContainer(
            {
                "agent": FakeAgentService(),
                "knowledge": FakeKnowledge(),
                "memory": FakeMemory(),
                "chat": FakeChat(),
                "conversation": FakeConversation(),
                "jobs": FakeJobs(),
                "documents": FakeDocuments(),
                "code": FakeCode(),
                "python": FakePython(),
                "verification": VerificationService(),
                "reports": ReportService(VerificationService()),
                "learning": _fake_learning(),
                "intelligence": _fake_intelligence(),
                "plugins": FakePluginManager(),
                "event_repo": FakeEventRepo(),
                "notifier": FakeNotifier(),
                "ops_dashboard": FakeOpsDashboard(),
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
                "reason": None,
            }
        if name == "scholar.search":
            return {
                "query": kwargs.get("query"),
                "provider": "semantic_scholar",
                "outcome": "ok",
                "results": [{"title": "Paper A", "year": 2021, "level_name": "L4 peer-reviewed"}],
                "sources": [{"id": "10.1/x", "evidence_level": 4, "kind": "peer_reviewed"}],
                "reason": None,
            }
        if name == "youtube.transcript":
            return {
                "video_id": "abcdefghijk", "url": kwargs.get("video"), "outcome": "ok",
                "title": "How Solar Works", "language": "en",
                "text": "Solar panels convert sunlight.", "segments": [], "reason": None,
            }
        if name == "git.status":
            return {
                "outcome": "ok", "repo": kwargs.get("repo"), "branch": "main",
                "ahead": 0, "behind": 0, "changes": [], "clean": True,
            }
        if name == "git.log":
            return {
                "outcome": "ok", "repo": kwargs.get("repo"),
                "commits": [{"short": "abc123", "date": "2026-07-01",
                             "author": "Ada", "subject": "init"}],
            }
        if name == "sql.query":
            return {
                "outcome": "ok", "backend": "sqlite", "source": kwargs.get("source"),
                "sql": kwargs.get("sql"), "columns": ["product", "amount"],
                "rows": [{"product": "a", "amount": 10.0}], "row_count": 1,
                "truncated": False,
            }
        if name == "sql.tables":
            return {"outcome": "ok", "backend": "sqlite", "tables": ["sales", "totals"]}
        if name == "ocr.image":
            return {
                "outcome": "ok", "path": kwargs.get("path"), "lang": kwargs.get("lang") or "eng",
                "engine": "tesseract", "text": "INVOICE 42", "chars": 10,
            }
        if name == "mail.search":
            return {
                "outcome": "ok", "backend": "imap", "folder": kwargs.get("folder") or "INBOX",
                "query": kwargs.get("query"), "count": 1,
                "messages": [{"uid": "7", "subject": "Invoice", "from": "a@x.com",
                              "to": "me@x.com", "date": "Mon"}],
            }
        if name == "mail.folders":
            return {"outcome": "ok", "backend": "imap", "folders": ["INBOX", "Sent"]}
        if name == "browser.open":
            return {
                "outcome": "ok", "backend": "playwright", "url": kwargs.get("url"),
                "final_url": kwargs.get("url"), "status": 200, "title": "Example",
                "text": "hello rendered", "chars": 14, "links": ["https://ex.com/a"],
            }
        if name == "research.run":
            return {
                "outcome": "ok", "objective": kwargs.get("objective"), "iterations": 2,
                "stopped": {"decision": "stop", "convergence": 0.92,
                            "reasons": ["all budget criteria met"]},
                "claim": {"confidence": "HIGH", "confidence_score": 0.86,
                          "convergence": 0.92},
                "graph": {"sources": [{"id": "10.1/x", "title": "Paper A",
                                       "url": "https://s2.org/1", "evidence_level": 4}],
                          "claims": []},
                "verification": {}, "report": {"markdown": "# R", "sections": {}},
                "log": [],
            }
        if name == "boom":
            raise ValueError("kaboom")  # untyped error -> generic 500 handler
        if name == "dberr":
            from atlas.exceptions import DatabaseError

            raise DatabaseError("datastore down")  # -> 503
        if name != "web.fetch":
            raise ToolNotFoundError(f"no tool named '{name}'", tool=name)
        return {"url": kwargs.get("url"), "status": 200, "text": "hello"}

    def health(self):
        return {
            "database": HealthStatus.ok("reachable"),
            "llm": HealthStatus.degraded_status("chat up; embed not pulled"),
        }

    def status(self):
        report = self.health()
        counts = {"ok": 0, "degraded": 0, "failed": 0}
        for s in report.values():
            counts[s.level] += 1
        return {
            "version": self.config.system.version,
            "uptime_seconds": 1.5,
            "healthy": all(s.healthy for s in report.values()),
            "degraded": counts["degraded"] > 0,
            "services_total": len(report),
            "severity_counts": counts,
        }


def _client(keys=(API_KEY,)) -> TestClient:
    return TestClient(create_app(FakeApplication(keys)))


def test_public_health_needs_no_auth():
    resp = _client().get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_v1_requires_auth():
    resp = _client().get("/v1/agents")
    assert resp.status_code == 401


def test_v1_rejects_wrong_key():
    resp = _client().get("/v1/agents", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


def test_fails_closed_when_no_keys_configured():
    resp = _client(keys=()).get("/v1/agents", headers=AUTH)
    assert resp.status_code == 401


def test_list_agents():
    resp = _client().get("/v1/agents", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"agents": ["rag"]}


def test_recent_events_requires_auth():
    assert _client().get("/v1/events").status_code == 401


def test_recent_events_returns_durable_log():
    resp = _client().get("/v1/events", headers=AUTH)
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert events[0]["type"] == "job.completed"
    assert events[0]["payload"] == {"job": "abc"}
    assert events[0]["created_at"].startswith("2026-01-01")


def test_recent_events_filter_by_type():
    resp = _client().get("/v1/events", params={"event_type": "nope"}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["events"] == []


def test_ops_dashboard_requires_auth():
    assert _client().get("/v1/ops").status_code == 401


def test_ops_dashboard_snapshot():
    resp = _client().get("/v1/ops", headers=AUTH)
    assert resp.status_code == 200
    snap = resp.json()
    assert snap["atlas"]["version"] == "0.1.0"
    assert snap["counts"]["jobs_active"] == 1
    assert snap["host"]["disk"]["percent"] == 71.0
    assert snap["backup"]["last"] == "atlas_2026.dump"
    assert snap["last_checkpoint"] is None


def test_run_agent_returns_answer_and_citations():
    resp = _client().post(
        "/v1/agents/rag/run", headers=AUTH, json={"query": "what is atlas?"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"].startswith("Atlas is an AI OS")
    assert body["citations"][0]["document_id"] == "doc-1"
    assert body["run_id"] == "run-1"


def test_run_unknown_agent_maps_to_404():
    resp = _client().post(
        "/v1/agents/ghost/run", headers=AUTH, json={"query": "hi"}
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "AgentNotFoundError"


def test_run_agent_validates_empty_query():
    resp = _client().post("/v1/agents/rag/run", headers=AUTH, json={"query": ""})
    assert resp.status_code == 422  # pydantic min_length


def test_chat_returns_answer_and_session():
    resp = _client().post(
        "/v1/chat", headers=AUTH, json={"message": "What does it say?"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "sess-1"
    assert body["intent"] == "ask_knowledge"
    assert body["citations"][0]["document_id"] == "doc-1"
    assert body["tool_calls"][0]["action"] == "rag"


def test_chat_requires_auth():
    resp = _client().post("/v1/chat", json={"message": "hi"})
    assert resp.status_code == 401


def test_chat_validates_empty_message():
    resp = _client().post("/v1/chat", headers=AUTH, json={"message": ""})
    assert resp.status_code == 422


def test_list_sessions():
    resp = _client().get("/v1/chat/sessions", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["sessions"][0]["id"] == "sess-1"


def test_session_history_ok():
    resp = _client().get("/v1/chat/sessions/sess-1", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "sess-1"
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]


def test_session_history_unknown_404():
    resp = _client().get("/v1/chat/sessions/ghost", headers=AUTH)
    assert resp.status_code == 404


def test_search():
    resp = _client().post(
        "/v1/knowledge/search", headers=AUTH, json={"query": "atlas", "limit": 3}
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results[0]["chunk_id"] == "chunk-1"
    assert results[0]["similarity"] == 0.8


def test_ingest():
    resp = _client().post(
        "/v1/knowledge/ingest",
        headers=AUTH,
        json={"content": "hello world", "source": "api"},
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "document_id": "doc-1",
        "status": "embedded",
        "chunks": 3,
        "deduped": False,
    }


def test_memory_remember():
    resp = _client().post(
        "/v1/memory/remember",
        headers=AUTH,
        json={"content": "Atlas ships Sprint 6", "kind": "semantic"},
    )
    assert resp.status_code == 200
    item = resp.json()["item"]
    assert item["id"] == "mem-1"
    assert item["kind"] == "semantic"


def test_memory_remember_rejects_bad_kind():
    resp = _client().post(
        "/v1/memory/remember",
        headers=AUTH,
        json={"content": "x", "kind": "bogus"},
    )
    assert resp.status_code == 422


def test_memory_recall():
    resp = _client().post(
        "/v1/memory/recall", headers=AUTH, json={"query": "atlas", "limit": 3}
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results[0]["similarity"] == 0.77


def test_memory_recent():
    resp = _client().get("/v1/memory/recent", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["items"][0]["kind"] == "episodic"


def test_memory_forget():
    resp = _client().delete("/v1/memory/mem-1", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"forgotten": True}


def test_memory_requires_auth():
    resp = _client().post("/v1/memory/recall", json={"query": "x"})
    assert resp.status_code == 401


def test_list_plugins():
    resp = _client().get("/v1/plugins", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["plugins"][0]["name"] == "filesystem"


def test_list_tools():
    resp = _client().get("/v1/tools", headers=AUTH)
    assert resp.status_code == 200
    tools = resp.json()["tools"]
    assert tools[0]["name"] == "web.fetch"
    assert tools[0]["plugin"] == "web"


def test_list_capabilities():
    resp = _client().get("/v1/capabilities", headers=AUTH)
    assert resp.status_code == 200
    caps = {c["id"]: c for c in resp.json()["capabilities"]}
    # registered capability is reported as provided, with its contract name
    assert caps["memory"]["provided"] is True
    assert caps["memory"]["contract"] == "MemoryCapability"
    # a catalogued-but-unregistered capability is honestly reported as missing
    assert caps["search"]["provided"] is False
    assert caps["search"]["unlocks"]


def test_capabilities_require_auth():
    resp = _client().get("/v1/capabilities")
    assert resp.status_code == 401


def test_create_job():
    resp = _client().post("/v1/jobs", headers=AUTH, json={"objective": "research x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["job"]["id"] == "job-1"
    assert body["job"]["phase"] == "ready"
    assert body["progress"]["blocked"] == 1
    assert body["steps"][1]["blocked_reason"] == "needs capability: web"


def test_create_job_validates_empty_objective():
    resp = _client().post("/v1/jobs", headers=AUTH, json={"objective": ""})
    assert resp.status_code == 422


def test_list_jobs():
    resp = _client().get("/v1/jobs", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["jobs"][0]["id"] == "job-1"


def test_get_job_ok_and_unknown():
    ok = _client().get("/v1/jobs/job-1", headers=AUTH)
    assert ok.status_code == 200
    assert ok.json()["job"]["status"] == "completed_with_blocks"
    missing = _client().get("/v1/jobs/ghost", headers=AUTH)
    assert missing.status_code == 404


def test_resume_job():
    resp = _client().post("/v1/jobs/job-1/resume", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["job"]["id"] == "job-1"


def test_add_job_input():
    resp = _client().post(
        "/v1/jobs/job-1/input",
        headers=AUTH,
        json={"text": "prefer IEEE soiling papers"},
    )
    assert resp.status_code == 200
    assert resp.json()["job"]["id"] == "job-1"


def test_add_job_input_unknown_404():
    resp = _client().post(
        "/v1/jobs/ghost/input",
        headers=AUTH,
        json={"text": "hello"},
    )
    assert resp.status_code == 404


def test_cancel_job_unknown_404():
    resp = _client().post("/v1/jobs/ghost/cancel", headers=AUTH)
    assert resp.status_code == 404


def test_jobs_require_auth():
    resp = _client().get("/v1/jobs")
    assert resp.status_code == 401


def test_document_formats():
    resp = _client().get("/v1/documents/formats", headers=AUTH)
    assert resp.status_code == 200
    assert ".pdf" in resp.json()["formats"]


def test_document_formats_require_auth():
    resp = _client().get("/v1/documents/formats")
    assert resp.status_code == 401


def test_web_search_endpoint_returns_results():
    resp = _client().post(
        "/v1/search", headers=AUTH, json={"query": "solar soiling", "max_results": 3}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["outcome"] == "ok"
    assert body["provider"] == "duckduckgo"
    assert body["results"][0]["url"] == "https://a.example"


def test_web_search_requires_auth():
    resp = _client().post("/v1/search", json={"query": "x"})
    assert resp.status_code == 401


def test_scholar_endpoint_returns_papers():
    resp = _client().post(
        "/v1/scholar", headers=AUTH, json={"query": "pv soiling", "max_results": 3}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["outcome"] == "ok"
    assert data["results"][0]["title"] == "Paper A"
    assert data["sources"][0]["evidence_level"] == 4


def test_scholar_endpoint_requires_auth():
    assert _client().post("/v1/scholar", json={"query": "x"}).status_code == 401


def test_youtube_transcript_endpoint():
    resp = _client().post(
        "/v1/youtube/transcript", headers=AUTH,
        json={"video": "https://youtu.be/abcdefghijk"},
    )
    assert resp.status_code == 200
    assert resp.json()["outcome"] == "ok"
    assert "Solar panels" in resp.json()["text"]


def test_youtube_transcript_requires_video():
    resp = _client().post("/v1/youtube/transcript", headers=AUTH, json={})
    assert resp.status_code == 422


def test_git_status_endpoint():
    resp = _client().post(
        "/v1/git", headers=AUTH, json={"action": "status", "repo": "/data/atlas"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["outcome"] == "ok"
    assert data["branch"] == "main" and data["clean"] is True


def test_git_log_endpoint():
    resp = _client().post(
        "/v1/git", headers=AUTH, json={"action": "log", "repo": "/r", "max_count": 5}
    )
    assert resp.status_code == 200
    assert resp.json()["commits"][0]["short"] == "abc123"


def test_git_endpoint_requires_auth():
    assert _client().post("/v1/git", json={"repo": "/r"}).status_code == 401


def test_db_query_endpoint():
    resp = _client().post(
        "/v1/db/query", headers=AUTH,
        json={"sql": "SELECT product, amount FROM sales", "source": "shop.db"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["outcome"] == "ok"
    assert data["rows"][0]["product"] == "a"


def test_db_tables_endpoint():
    resp = _client().get("/v1/db/tables", headers=AUTH, params={"source": "shop.db"})
    assert resp.status_code == 200
    assert "sales" in resp.json()["tables"]


def test_db_query_requires_auth():
    assert _client().post("/v1/db/query", json={"sql": "SELECT 1"}).status_code == 401


def test_ocr_endpoint():
    resp = _client().post("/v1/ocr", headers=AUTH, json={"path": "scan.png"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["outcome"] == "ok"
    assert data["text"] == "INVOICE 42"


def test_ocr_endpoint_requires_path():
    resp = _client().post("/v1/ocr", headers=AUTH, json={})
    assert resp.status_code == 422


def test_ocr_endpoint_requires_auth():
    assert _client().post("/v1/ocr", json={"path": "x.png"}).status_code == 401


def test_mail_search_endpoint():
    resp = _client().post("/v1/mail/search", headers=AUTH, json={"query": "invoice"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["outcome"] == "ok"
    assert data["messages"][0]["subject"] == "Invoice"


def test_mail_folders_endpoint():
    resp = _client().get("/v1/mail/folders", headers=AUTH)
    assert resp.status_code == 200
    assert "INBOX" in resp.json()["folders"]


def test_mail_search_requires_auth():
    assert _client().post("/v1/mail/search", json={"query": "x"}).status_code == 401


def test_browser_open_endpoint():
    resp = _client().post("/v1/browser/open", headers=AUTH,
                          json={"url": "https://ex.com/page"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["outcome"] == "ok"
    assert data["title"] == "Example"


def test_browser_open_requires_url():
    resp = _client().post("/v1/browser/open", headers=AUTH, json={})
    assert resp.status_code == 422


def test_browser_open_requires_auth():
    assert _client().post("/v1/browser/open", json={"url": "https://x"}).status_code == 401


def test_research_endpoint():
    resp = _client().post("/v1/research", headers=AUTH,
                          json={"objective": "solar soiling losses"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["outcome"] == "ok"
    assert data["claim"]["confidence"] == "HIGH"
    assert data["iterations"] == 2


def test_research_requires_objective():
    resp = _client().post("/v1/research", headers=AUTH, json={})
    assert resp.status_code == 422


def test_research_requires_auth():
    assert _client().post("/v1/research", json={"objective": "x"}).status_code == 401


def test_code_repo_map_endpoint():
    resp = _client().post("/v1/code/repo-map", headers=AUTH, json={"root": "/x"})
    assert resp.status_code == 200
    assert resp.json()["frameworks"] == ["FastAPI"]


def test_code_parse_endpoint():
    resp = _client().post("/v1/code/parse", headers=AUTH, json={"path": "a.py"})
    assert resp.status_code == 200
    assert resp.json()["symbols"][0]["name"] == "foo"


def test_code_graph_endpoint():
    resp = _client().post("/v1/code/graph", headers=AUTH, json={"root": "/x"})
    assert resp.status_code == 200
    assert resp.json()["import_edge_count"] == 1


def test_code_symbols_endpoint():
    resp = _client().post(
        "/v1/code/symbols", headers=AUTH, json={"root": "/x", "query": "foo"}
    )
    assert resp.status_code == 200
    assert resp.json()["symbols"][0]["qualname"] == "foo"


def test_code_patterns_endpoint():
    resp = _client().post("/v1/code/patterns", headers=AUTH, json={"root": "/x"})
    assert resp.status_code == 200
    assert resp.json()["patterns"][0]["name"] == "Repository pattern"


def test_code_endpoints_require_auth():
    assert _client().post("/v1/code/repo-map", json={"root": "/x"}).status_code == 401


def test_verify_endpoint_calculates_confidence():
    body = {
        "claims": [
            {
                "id": "c1",
                "statement": "Soiling loss ≈ 4%.",
                "evidence": [
                    {"source_id": "s1", "evidence_level": 4, "extracted_value": 3.9},
                    {"source_id": "s2", "evidence_level": 3, "extracted_value": 4.0},
                    {"source_id": "s3", "evidence_level": 4, "extracted_value": 3.8},
                ],
            }
        ]
    }
    resp = _client().post("/v1/verify", headers=AUTH, json=body)
    assert resp.status_code == 200
    claim = resp.json()["claims"][0]
    assert claim["confidence"] == "HIGH"
    assert claim["convergence"] == 1.0
    assert claim["budget_decision"]["decision"] in {"stop", "continue"}


def test_verify_endpoint_budget_override():
    body = {
        "claims": [
            {
                "id": "c1",
                "statement": "x",
                "evidence": [
                    {"source_id": "s1", "evidence_level": 4, "extracted_value": 3.9},
                    {"source_id": "s2", "evidence_level": 4, "extracted_value": 4.0},
                ],
            }
        ],
        "budget": {"min_sources": 2, "min_peer_reviewed": 2, "min_government": 0},
    }
    resp = _client().post("/v1/verify", headers=AUTH, json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["budget"]["min_sources"] == 2
    assert data["claims"][0]["budget_decision"]["decision"] == "stop"


def test_python_run_endpoint():
    resp = _client().post("/v1/python/run", headers=AUTH, json={"code": "print('hi')"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["outcome"] == "ok"
    assert "hi" in body["stdout"]


def test_python_run_requires_auth():
    assert _client().post("/v1/python/run", json={"code": "print(1)"}).status_code == 401


def test_python_run_rejects_empty_code():
    resp = _client().post("/v1/python/run", headers=AUTH, json={"code": ""})
    assert resp.status_code == 422


def test_verify_endpoint_requires_auth():
    assert _client().post("/v1/verify", json={"claims": [{"statement": "x"}]}).status_code == 401


def test_verify_endpoint_rejects_empty_claims():
    resp = _client().post("/v1/verify", headers=AUTH, json={"claims": []})
    assert resp.status_code == 422


def test_report_endpoint_generates_report():
    body = {
        "objective": "Estimate soiling loss",
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
        ],
    }
    resp = _client().post("/v1/report", headers=AUTH, json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["report"]["overall_confidence"] == "HIGH"
    assert "# Research Report:" in data["report"]["markdown"]


def test_report_endpoint_requires_objective():
    resp = _client().post("/v1/report", headers=AUTH, json={"claims": []})
    assert resp.status_code == 422


def test_report_endpoint_requires_auth():
    assert _client().post("/v1/report", json={"objective": "x"}).status_code == 401


def test_learning_remember_apply_and_recall():
    c = _client()
    resp = c.post(
        "/v1/learning/experiences",
        headers=AUTH,
        json={"problem": "deadlock on migrate", "solution": "lock_timeout",
              "lessons": "run migrations serially"},
    )
    assert resp.status_code == 200
    assert resp.json()["applied"] is True
    # recall via query
    recall = c.get("/v1/learning/experiences?q=deadlock", headers=AUTH)
    assert recall.status_code == 200
    hits = recall.json()["experiences"]
    assert len(hits) == 1
    assert "deadlock" in hits[0]["problem"]


def test_learning_event_lifecycle_endpoints():
    c = _client()
    c.post("/v1/learning/experiences", headers=AUTH, json={"problem": "p1"})
    events = c.get("/v1/learning/events", headers=AUTH).json()["events"]
    assert events
    eid = events[0]["id"]
    # explain
    detail = c.get(f"/v1/learning/events/{eid}", headers=AUTH)
    assert detail.status_code == 200
    assert "explanation" in detail.json()
    # revert
    rev = c.post(f"/v1/learning/events/{eid}/revert", headers=AUTH)
    assert rev.status_code == 200
    assert rev.json()["reverted"] is True


def test_learning_apply_unknown_event_404():
    resp = _client().post("/v1/learning/events/nope/apply", headers=AUTH, json={})
    assert resp.status_code == 404


def test_learning_requires_auth():
    assert _client().get("/v1/learning/events").status_code == 401


def test_learning_sources_endpoint_is_advice_only():
    resp = _client().get("/v1/learning/sources", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["mutating"] is False
    assert "prefer" in body and "avoid" in body


def test_intelligence_learn_and_recommend_flow():
    c = _client()
    learn = c.post(
        "/v1/intelligence/repositories", headers=AUTH, json={"root": "/repos/api"}
    )
    assert learn.status_code == 200
    assert learn.json()["outcome"] == "ok"
    assert learn.json()["repository"]["name"] == "api"
    repos = c.get("/v1/intelligence/repositories", headers=AUTH).json()["repositories"]
    assert len(repos) == 1
    gen = c.post("/v1/intelligence/generalize", headers=AUTH)
    assert gen.status_code == 200
    prof = c.get("/v1/intelligence/profile", headers=AUTH)
    assert prof.status_code == 200
    assert prof.json()["repositories"] == 1


def test_intelligence_learn_bad_path():
    resp = _client().post(
        "/v1/intelligence/repositories", headers=AUTH, json={"root": "/nope"}
    )
    assert resp.status_code == 200
    assert resp.json()["outcome"] == "error"


def test_intelligence_requires_auth():
    assert _client().get("/v1/intelligence/repositories").status_code == 401


def test_blocked_jobs_endpoint():
    resp = _client().get("/v1/jobs/blocked", headers=AUTH)
    assert resp.status_code == 200
    blocked = resp.json()["blocked"]
    assert blocked[0]["capability"] == "web"
    assert blocked[0]["job_id"] == "job-1"


def test_invoke_tool():
    resp = _client().post(
        "/v1/tools/web.fetch/invoke",
        headers=AUTH,
        json={"args": {"url": "https://example.com"}},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["status"] == 200
    assert result["url"] == "https://example.com"


def test_invoke_unknown_tool_maps_to_404():
    resp = _client().post("/v1/tools/ghost/invoke", headers=AUTH, json={"args": {}})
    assert resp.status_code == 404
    assert resp.json()["error"] == "ToolNotFoundError"


def test_tools_require_auth():
    resp = _client().get("/v1/tools")
    assert resp.status_code == 401


def test_detailed_health_authed():
    resp = _client().get("/v1/health", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["healthy"] is True
    assert body["services"]["database"]["healthy"] is True


def test_detailed_health_reports_degraded_tier():
    resp = _client().get("/v1/health", headers=AUTH)
    body = resp.json()
    # A degraded service keeps the system healthy but flags the degraded roll-up (S22).
    assert body["healthy"] is True
    assert body["degraded"] is True
    assert body["services"]["llm"]["severity"] == "degraded"
    assert body["services"]["database"]["severity"] == "ok"


def test_status_endpoint_summary():
    resp = _client().get("/v1/status", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"]
    assert body["degraded"] is True
    assert body["severity_counts"] == {"ok": 1, "degraded": 1, "failed": 0}


def test_status_requires_auth():
    assert _client().get("/v1/status").status_code == 401


def test_request_id_header_present():
    resp = _client().get("/health")
    assert resp.headers.get("X-Request-ID")


def test_request_id_is_echoed_from_client():
    resp = _client().get("/health", headers={"X-Request-ID": "trace-123"})
    assert resp.headers["X-Request-ID"] == "trace-123"


def test_untyped_error_returns_structured_500():
    # raise_server_exceptions=False so the TestClient returns the handler's response
    # instead of re-raising (uvicorn returns it to the client either way).
    client = TestClient(
        create_app(FakeApplication((API_KEY,))), raise_server_exceptions=False
    )
    resp = client.post("/v1/tools/boom/invoke", headers=AUTH, json={"args": {}})
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"] == "ValueError"
    assert body["detail"] == "kaboom"
    assert body["request_id"]  # correlation id surfaced to the client


def test_database_error_maps_to_503():
    resp = _client().post("/v1/tools/dberr/invoke", headers=AUTH, json={"args": {}})
    assert resp.status_code == 503
    assert resp.json()["error"] == "DatabaseError"


def test_http_metrics_recorded():
    from atlas.telemetry import get_metrics

    client = _client()
    client.get("/health")
    snap = get_metrics().snapshot()
    assert any(k.startswith("http.requests") for k in snap["counters"])
    assert any("http.request.duration_ms" in k for k in snap["histograms"])


def test_openapi_docs_served():
    resp = _client().get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["info"]["title"] == "Atlas API"


def test_metrics_prometheus_public():
    from atlas.telemetry import get_metrics

    get_metrics().incr("api.test.requests", 3)
    resp = _client().get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "atlas_api_test_requests" in resp.text


def test_metrics_json_requires_auth():
    resp = _client().get("/v1/metrics")
    assert resp.status_code == 401


def test_metrics_json_authed():
    resp = _client().get("/v1/metrics", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert "counters" in body and "histograms" in body


def test_metrics_disabled_returns_404():
    app = FakeApplication((API_KEY,))
    app.config.api.metrics_enabled = False
    client = TestClient(create_app(app))
    assert client.get("/metrics").status_code == 404
    assert client.get("/v1/metrics", headers=AUTH).status_code == 404
