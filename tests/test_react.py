"""Tests for the ReAct agent (Sprint 8).

Fully hermetic: a scripted fake LLM drives the loop and a real ToolRegistry holds
simple in-process tools. No Ollama, no DB (run_repo omitted).
"""

from __future__ import annotations

import pytest

from atlas.agents.react_agent import ReActAgent
from atlas.kernel.tools import ToolRegistry


class _Resp:
    def __init__(self, text: str, model: str = "fake"):
        self.text = text
        self.model = model


class FakeLLM:
    def __init__(self, scripted: list[str]):
        self._scripted = list(scripted)
        self.calls: list[list] = []

    def chat(self, messages, **options):
        self.calls.append(messages)
        return _Resp(self._scripted.pop(0))


def _tools() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register("echo", lambda text: f"echoed:{text}", description="echo text")

    def boom():
        raise ValueError("kaboom")

    reg.register("boom", boom, description="always fails")
    return reg


def _agent(scripted, tools=None, **kw):
    kw.setdefault("reflection", False)
    return ReActAgent(FakeLLM(scripted), tools or _tools(), None, **kw)


def test_direct_final_answer():
    agent = _agent(['{"final": "hello"}'])
    result = agent.run("hi")
    assert result.answer == "hello"
    assert result.usage["tools_used"] == []


def test_tool_then_final_feeds_observation():
    llm = FakeLLM(['{"tool": "echo", "args": {"text": "hi"}}', '{"final": "done"}'])
    agent = ReActAgent(llm, _tools(), None, reflection=False)
    result = agent.run("q")
    assert result.answer == "done"
    assert result.usage["tools_used"] == ["echo"]
    # The second LLM call must have seen the observation from the echo tool.
    second_call = llm.calls[1]
    assert any("Observation: echoed:hi" in m.content for m in second_call)


def test_tool_error_becomes_observation():
    llm = FakeLLM(['{"tool": "boom", "args": {}}', '{"final": "recovered"}'])
    agent = ReActAgent(llm, _tools(), None, reflection=False)
    result = agent.run("q")
    assert result.answer == "recovered"
    assert any("Error: ValueError: kaboom" in m.content for m in llm.calls[1])


def test_parse_error_then_recovers():
    agent = _agent(["not json at all", '{"final": "ok"}'])
    assert agent.run("q").answer == "ok"


def test_max_iterations_forces_final():
    scripted = [
        '{"tool": "echo", "args": {"text": "a"}}',
        '{"tool": "echo", "args": {"text": "b"}}',
        '{"final": "forced answer"}',
    ]
    agent = _agent(scripted, max_iterations=2)
    assert agent.run("q").answer == "forced answer"


def test_reflection_revises_answer():
    llm = FakeLLM(['{"final": "draft"}', "improved answer"])
    agent = ReActAgent(llm, _tools(), None, reflection=True)
    assert agent.run("q").answer == "improved answer"


def test_reflection_keeps_answer_when_empty():
    llm = FakeLLM(['{"final": "draft"}', ""])
    agent = ReActAgent(llm, _tools(), None, reflection=True)
    assert agent.run("q").answer == "draft"


def test_agents_as_tools_delegation():
    tools = ToolRegistry()
    tools.register("agent.rag", lambda query: f"rag says: {query}", description="ask rag")
    llm = FakeLLM(
        ['{"tool": "agent.rag", "args": {"query": "what is atlas?"}}', '{"final": "ok"}']
    )
    agent = ReActAgent(llm, tools, None, reflection=False)
    result = agent.run("q")
    assert result.usage["tools_used"] == ["agent.rag"]
    assert any("rag says: what is atlas?" in m.content for m in llm.calls[1])


# --- action parsing -------------------------------------------------------
def test_parse_plain_json():
    assert ReActAgent._parse_action('{"final": "x"}') == {"final": "x"}


def test_parse_fenced_json():
    text = 'Sure:\n```json\n{"tool": "echo", "args": {"text": "hi"}}\n```'
    action = ReActAgent._parse_action(text)
    assert action["tool"] == "echo"


def test_parse_embedded_json():
    text = 'thinking... {"final": "answer"} done'
    assert ReActAgent._parse_action(text) == {"final": "answer"}


def test_parse_returns_none_for_garbage():
    assert ReActAgent._parse_action("no json here") is None


def test_config_snapshot_lists_tools():
    agent = _agent(['{"final": "x"}'])
    snap = agent.config_snapshot()
    assert "echo" in snap["tools"] and snap["max_iterations"] == 6
