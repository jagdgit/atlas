"""Tests for the code graph (S14): import + cross-file call graph (Python-first)."""

from __future__ import annotations

from atlas.code.graph import build_graph
from atlas.code.parser import CodeParser

_PKG_UTIL = '''\
def helper(x):
    return x + 1
'''

_PKG_MAIN = '''\
from pkg.util import helper


def run(n):
    return helper(n)


class Service:
    def do(self):
        return self.step()

    def step(self):
        return run(1)
'''


def _parse_repo():
    parser = CodeParser()
    return [
        parser.parse_text(_PKG_UTIL, "pkg/util.py"),
        parser.parse_text(_PKG_MAIN, "pkg/main.py"),
    ]


def test_import_graph_resolves_in_repo_module():
    g = build_graph(_parse_repo())
    assert ("pkg/main.py", "pkg/util.py") in g.import_edges


def test_cross_file_call_resolved():
    g = build_graph(_parse_repo())
    # run() calls helper() defined in the other file
    assert ("pkg/main.py::run", "pkg/util.py::helper") in g.call_edges


def test_self_method_call_resolved_within_class():
    g = build_graph(_parse_repo())
    assert ("pkg/main.py::Service.do", "pkg/main.py::Service.step") in g.call_edges


def test_relative_import_resolution():
    parser = CodeParser()
    parses = [
        parser.parse_text("def f():\n    return 1\n", "pkg/util.py"),
        parser.parse_text("from .util import f\n", "pkg/main.py"),
    ]
    g = build_graph(parses)
    assert ("pkg/main.py", "pkg/util.py") in g.import_edges


def test_external_imports_counted_not_resolved():
    parser = CodeParser()
    parses = [parser.parse_text("import os\nimport requests\n", "a.py")]
    g = build_graph(parses)
    assert g.external_imports == 2
    assert g.import_edges == []


def test_builtins_are_not_counted_as_unresolved():
    parser = CodeParser()
    parses = [parser.parse_text("def f():\n    print(len([1]))\n", "a.py")]
    g = build_graph(parses)
    # print/len are not repo symbols -> ignored, not counted
    assert g.unresolved_calls == 0
    assert g.call_edges == []
