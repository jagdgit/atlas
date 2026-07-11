"""Tests for the tree-sitter multi-language parser (S14).

Skipped cleanly if the optional grammar pack isn't installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("tree_sitter_language_pack")

from atlas.code.models import KIND_CLASS, KIND_FUNCTION, KIND_METHOD, OUTCOME_OK
from atlas.code.parser import CodeParser


def _parse(text, path, lang):
    return CodeParser().parse_text(text, path, lang)


def test_javascript_symbols_and_imports():
    src = (
        "import { a } from 'lib';\n"
        "function greet(name) { return name; }\n"
        "class Foo { bar() { return 1; } }\n"
    )
    fp = _parse(src, "app.js", "javascript")
    assert fp.outcome == OUTCOME_OK
    kinds = {s.name: s.kind for s in fp.symbols}
    assert kinds.get("greet") == KIND_FUNCTION
    assert kinds.get("Foo") == KIND_CLASS
    assert kinds.get("bar") == KIND_METHOD
    modules = {i.module for i in fp.imports}
    assert "lib" in modules


def test_typescript_class_and_method():
    src = "export class Service {\n  run(x: number): number { return x; }\n}\n"
    fp = _parse(src, "svc.ts", "typescript")
    names = {s.name for s in fp.symbols}
    assert "Service" in names
    assert "run" in names


def test_go_functions():
    src = 'package main\nimport "fmt"\nfunc main() { fmt.Println("hi") }\n'
    fp = _parse(src, "main.go", "go")
    assert any(s.name == "main" and s.kind == KIND_FUNCTION for s in fp.symbols)


def test_method_parent_scope_tracked():
    src = "class Foo { bar() { return 1; } }\n"
    fp = _parse(src, "a.js", "javascript")
    bar = next(s for s in fp.symbols if s.name == "bar")
    assert bar.parent == "Foo"
    assert bar.qualname == "Foo.bar"
