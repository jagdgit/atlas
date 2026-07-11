"""Tests for the ToolExecutor (Sprint 10).

Hermetic: uses a real ToolRegistry with plain Python callables. No kernel/DB.
"""

from __future__ import annotations

from atlas.execution import ToolExecutor, ToolResult
from atlas.kernel.tools import ToolRegistry


def _registry(**funcs) -> ToolRegistry:
    reg = ToolRegistry()
    for name, func in funcs.items():
        reg.register(name, func)
    return reg


def _executor(reg: ToolRegistry, **kw) -> ToolExecutor:
    kw.setdefault("retry_base", 0.0)  # no sleeps in tests
    return ToolExecutor(reg, **kw)


def test_success_returns_data():
    reg = _registry(echo=lambda value: {"value": value})
    result = _executor(reg).execute("echo", {"value": 42})
    assert isinstance(result, ToolResult)
    assert result.ok
    assert result.data == {"value": 42}
    assert result.attempts == 1


def test_unknown_tool_is_a_gap_not_a_crash():
    result = _executor(_registry()).execute("ghost", {})
    assert not result.ok
    assert result.error_kind == "ToolNotFoundError"


def test_rejects_unexpected_argument():
    reg = _registry(fetch=lambda url: url)
    result = _executor(reg).execute("fetch", {"url": "x", "bogus": 1})
    assert not result.ok
    assert result.error_kind == "ArgumentError"
    assert "bogus" in result.error


def test_rejects_missing_required_argument():
    reg = _registry(fetch=lambda url: url)
    result = _executor(reg).execute("fetch", {})
    assert not result.ok
    assert result.error_kind == "ArgumentError"
    assert "url" in result.error


def test_var_keywords_accepts_anything():
    reg = _registry(flexible=lambda **kw: kw)
    result = _executor(reg).execute("flexible", {"a": 1, "b": 2})
    assert result.ok
    assert result.data == {"a": 1, "b": 2}


def test_retries_transient_failure_then_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("temporary")
        return "ok"

    reg = _registry(flaky=flaky)
    result = _executor(reg, max_retries=2).execute("flaky", {})
    assert result.ok
    assert result.data == "ok"
    assert result.attempts == 2


def test_persistent_failure_reports_error():
    def boom():
        raise ValueError("nope")

    reg = _registry(boom=boom)
    result = _executor(reg, max_retries=1).execute("boom", {})
    assert not result.ok
    assert result.attempts == 2  # 1 retry => 2 attempts
    assert result.error_kind == "ValueError"
    assert "nope" in result.error


def test_result_as_dict_is_serializable():
    reg = _registry(echo=lambda value: value)
    result = _executor(reg).execute("echo", {"value": "hi"})
    d = result.as_dict()
    assert d["ok"] is True
    assert d["tool"] == "echo"
    assert "elapsed_ms" in d
