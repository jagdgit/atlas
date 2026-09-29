"""Production web_search wiring for the Agent Kernel.

Uses the existing SearchPlugin response shape. The live DuckDuckGo call is
separate from the bus fixtures used by the A0 ladder tests.
"""

from __future__ import annotations

from types import SimpleNamespace

from atlas.agent_kernel.kernel import AgentKernel
from atlas.agent_kernel.models import DIAGNOSTIC_FIELDS
from atlas.agent_kernel.web_search import (
    CLIENT_NOT_CONFIGURED,
    POLICY_DISABLED,
    PROVIDER_UNAVAILABLE,
    SUCCESS,
)
from atlas.agent_kernel.worker import AgentKernelWorker
from atlas.search.providers import SearchHit, SearchResponse
from atlas.workers.base import TickContext


class _Client:
    def __init__(self, response: SearchResponse | None = None, *, raise_error: bool = False) -> None:
        self.calls: list[str] = []
        self.response = response
        self.raise_error = raise_error

    def health_check(self):
        return SimpleNamespace(healthy=True, detail="stub")

    def search_web(self, query: str, max_results: int | None = None) -> SearchResponse:
        self.calls.append(query)
        if self.raise_error:
            raise RuntimeError("provider down")
        assert self.response is not None
        return self.response


def _hit_response() -> SearchResponse:
    return SearchResponse(
        "what is the current date",
        "duckduckgo",
        "ok",
        hits=[
            SearchHit(
                title="Date and time",
                url="https://example.com/current-date",
                snippet="A public page that states the date.",
            )
        ],
    )


def _obs() -> dict:
    return {
        "source": "inbox",
        "domain": "research",
        "symbol": "DATE",
        "objective": "Find a public web reference for the current date.",
        "reason": "local evidence is missing",
        "decision_impact": True,
        "priority_class": "P1",
        "required": ["public_reference"],
        "interpretive": False,
    }


def test_resolve_web_search_is_executable_when_configured(tmp_path):
    client = _Client(_hit_response())
    kernel = AgentKernel(tmp_path, web_search=client)
    kernel._allow_external = True
    resolved = kernel.resolve("web_search")
    assert resolved["executable"] is True
    assert resolved["status"] == SUCCESS
    assert resolved["capability"].name == "web_search"
    news = kernel.resolve("news_search")
    assert news["executable"] is False
    assert news["status"] == CLIENT_NOT_CONFIGURED


def test_web_search_execute_preserves_provenance(tmp_path):
    client = _Client(_hit_response())
    kernel = AgentKernel(tmp_path, web_search=client)
    outcome = kernel.resolve("web_search")["capability"].execute("what is the current date")
    assert client.calls == ["what is the current date"]
    assert outcome["status"] == SUCCESS
    assert outcome["provider"] == "duckduckgo"
    row = outcome["evidence"][0]
    assert row["url"] == "https://example.com/current-date"
    assert row["title"] == "Date and time"
    assert row["source"] == "web_search"
    assert row["query"] == "what is the current date"
    assert "confidence" not in row


def test_kernel_uses_web_search_when_local_evidence_is_missing(tmp_path):
    client = _Client(_hit_response())
    kernel = AgentKernel(tmp_path, web_search=client)
    report = kernel.cycle(mode="event", allow_external=True, observations=[_obs()])
    task = kernel.task(report["ran"][0])
    assert client.calls
    assert task["status"] == "SUCCESS"
    assert kernel.bus.has_slot("web_search", "public_reference")
    evidence = task["evidence"]["public_reference"]
    assert evidence[0]["url"].startswith("https://")
    attempt = task["external_searches"][-1]
    assert attempt["capability"] == "web_search"
    assert attempt["status"] == SUCCESS
    assert attempt["result_count"] == 1
    assert attempt["evidence_ids"]
    assert attempt["query"]
    assert "api_key" not in str(attempt).lower()


def test_provider_failure_is_a_recorded_gap(tmp_path):
    client = _Client(SearchResponse("q", "duckduckgo", "blocked", reason="http 403"))
    kernel = AgentKernel(tmp_path, web_search=client)
    report = kernel.cycle(mode="event", allow_external=True, observations=[_obs()])
    task = kernel.task(report["ran"][0])
    assert task["status"] == "CAPABILITY_GAP"
    assert client.calls
    for key in DIAGNOSTIC_FIELDS:
        assert key in task
    assert task["reason"]
    assert task["next_action"]
    assert "web_search" in task["attempted_capabilities"]
    assert task["external_searches"][-1]["status"] == PROVIDER_UNAVAILABLE
    assert "public_reference" not in task["evidence"]


def test_allow_external_false_makes_no_request(tmp_path):
    client = _Client(_hit_response())
    kernel = AgentKernel(tmp_path, web_search=client)
    report = kernel.cycle(mode="event", allow_external=False, observations=[_obs()])
    task = kernel.task(report["ran"][0])
    assert client.calls == []
    assert task["status"] == "CAPABILITY_GAP"
    assert any(row["status"] == POLICY_DISABLED for row in task["external_searches"])


def test_blocked_search_resumes_when_provider_returns(tmp_path):
    blocked = _Client(SearchResponse("q", "duckduckgo", "blocked", reason="http 403"))
    kernel = AgentKernel(tmp_path, web_search=blocked)
    first = kernel.cycle(mode="event", allow_external=True, observations=[_obs()])
    task_id = first["ran"][0]
    assert kernel.task(task_id)["status"] == "CAPABILITY_GAP"
    calls_before = len(blocked.calls)
    restored = _Client(_hit_response())
    kernel.bind_web_search(restored)
    second = kernel.cycle(mode="event", allow_external=True)
    assert task_id in second["ran"]
    done = kernel.task(task_id)
    assert done["status"] == "SUCCESS"
    assert len(kernel.tasks()) == 2  # original task plus the outcome follow-up
    assert restored.calls
    assert len(blocked.calls) == calls_before


def test_external_search_does_not_expose_order_capabilities(tmp_path):
    kernel = AgentKernel(tmp_path, web_search=_Client(_hit_response()))
    for name in ("broker_order", "live_orders", "strategy_control", "capital_allocation"):
        resolved = kernel.resolve(name)
        assert resolved["executable"] is False
    worker = AgentKernelWorker(data_dir=str(tmp_path), allow_external=True)
    result = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={"enabled": True, "action_scope": "live_orders", "allow_external": True},
            config_version=1,
            state={},
        )
    )
    assert "refused action_scope" in result.note


def test_live_duckduckgo_search_returns_a_url():
    """One real provider call. This is not a bus fixture."""
    from atlas.config import load_config
    from atlas.plugins.search_plugin import build

    plugin = build(load_config())
    assert plugin.health_check().healthy
    response = plugin.search_web("what is the current date", max_results=3)
    assert response.provider
    assert response.hits, response.reason
    assert response.hits[0].url.startswith("http")
    assert response.hits[0].title
