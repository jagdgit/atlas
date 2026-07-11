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
    cmd_forget,
    cmd_ingest,
    cmd_plugins,
    cmd_recall,
    cmd_remember,
    cmd_search,
    cmd_tool,
    cmd_tools,
)
from atlas.knowledge.service import SearchResult
from atlas.models import MemoryItem


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


class FakePluginManager:
    def describe(self):
        return [{"name": "filesystem", "version": "0.1.0"}, {"name": "web", "version": "0.1.0"}]


class FakeTools:
    def describe(self):
        return [{"name": "fs.read", "description": "Read a file.", "params": {}, "plugin": "filesystem"}]


class FakeApp:
    def __init__(self):
        self.tools = FakeTools()
        self.container = _Container(
            {
                "agent": FakeAgentService(),
                "knowledge": FakeKnowledge(),
                "memory": FakeMemory(),
                "plugins": FakePluginManager(),
            }
        )

    def invoke_tool(self, name, **kwargs):
        return {"tool": name, "args": kwargs}


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
