"""Tests for the Python (ast) parser + CodeParser dispatch (S14)."""

from __future__ import annotations

from atlas.code.models import (
    KIND_CLASS,
    KIND_FUNCTION,
    KIND_METHOD,
    OUTCOME_ERROR,
    OUTCOME_OK,
    OUTCOME_UNSUPPORTED,
)
from atlas.code.parser import CodeParser
from atlas.code.pyast import parse_python

_SRC = '''\
"""Module doc."""
import os
from collections import OrderedDict
from .local import helper


def top_level(a, b, *args, **kwargs):
    """A top function."""
    return helper(a) + os.getpid()


class Widget:
    """A widget."""

    def method(self, x):
        return self.compute(x)

    async def acompute(self):
        return await do_async()
'''


def test_python_symbols_kinds_and_lines():
    fp = parse_python(_SRC, "m.py")
    assert fp.outcome == OUTCOME_OK
    by_name = {s.name: s for s in fp.symbols}
    assert by_name["top_level"].kind == KIND_FUNCTION
    assert by_name["Widget"].kind == KIND_CLASS
    assert by_name["method"].kind == KIND_METHOD
    assert by_name["method"].parent == "Widget"
    assert by_name["method"].qualname == "Widget.method"
    assert by_name["top_level"].signature == "def top_level(a, b, *args, **kwargs)"
    assert by_name["acompute"].signature.startswith("async def acompute(self)")
    assert by_name["top_level"].docstring == "A top function."
    assert by_name["top_level"].start_line <= by_name["top_level"].end_line


def test_python_imports_absolute_and_relative():
    fp = parse_python(_SRC, "m.py")
    modules = {i.module for i in fp.imports}
    assert "os" in modules
    assert "collections" in modules
    assert ".local" in modules
    frm = next(i for i in fp.imports if i.module == "collections")
    assert "OrderedDict" in frm.names


def test_python_calls_capture_caller_scope():
    fp = parse_python(_SRC, "m.py")
    calls = {(c.caller, c.callee) for c in fp.calls}
    assert ("top_level", "helper") in calls
    assert ("top_level", "os.getpid") in calls
    assert ("Widget.method", "self.compute") in calls


def test_python_syntax_error_is_classified_not_raised():
    fp = parse_python("def broken(:\n", "bad.py")
    assert fp.outcome == OUTCOME_ERROR
    assert "syntax error" in (fp.reason or "")


def test_parser_dispatch_python(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("def f():\n    return 1\n", encoding="utf-8")
    fp = CodeParser().parse_file(f)
    assert fp.lang == "python"
    assert fp.outcome == OUTCOME_OK
    assert fp.symbols[0].name == "f"


def test_parser_unsupported_language(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("hello world\n", encoding="utf-8")
    fp = CodeParser().parse_file(f)
    assert fp.outcome == OUTCOME_UNSUPPORTED


def test_parser_oversized_file_is_error(tmp_path):
    f = tmp_path / "big.py"
    f.write_text("x = 1\n" * 100, encoding="utf-8")
    fp = CodeParser(max_file_bytes=10).parse_file(f)
    assert fp.outcome == OUTCOME_ERROR
    assert "too large" in (fp.reason or "")
