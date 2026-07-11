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
from atlas.models import MemoryItem
from atlas.services.base import HealthStatus

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
        self.container = FakeContainer(
            {
                "agent": FakeAgentService(),
                "knowledge": FakeKnowledge(),
                "memory": FakeMemory(),
                "plugins": FakePluginManager(),
            }
        )

    def invoke_tool(self, name, **kwargs):
        if name != "web.fetch":
            raise ToolNotFoundError(f"no tool named '{name}'", tool=name)
        return {"url": kwargs.get("url"), "status": 200, "text": "hello"}

    def health(self):
        return {"database": HealthStatus.ok("reachable")}


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


def test_openapi_docs_served():
    resp = _client().get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["info"]["title"] == "Atlas API"
