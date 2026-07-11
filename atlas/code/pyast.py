"""Python structural parser (stdlib ``ast``) — the full-fidelity path (§5b.1).

Python is the primary language (D9: "Python-first" cross-file resolution), so it is
parsed with the standard library ``ast`` rather than tree-sitter: exact line ranges,
signatures, docstrings, imports, and — crucially — **call sites** with their enclosing
symbol, which is what the cross-file call graph (Tier B) is built from.
"""

from __future__ import annotations

import ast

from atlas.code.languages import PYTHON
from atlas.code.models import (
    KIND_CLASS,
    KIND_FUNCTION,
    KIND_METHOD,
    OUTCOME_ERROR,
    OUTCOME_OK,
    CallRef,
    FileParse,
    ImportRef,
    Symbol,
)


def parse_python(text: str, path: str) -> FileParse:
    loc = text.count("\n") + 1 if text else 0
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return FileParse(
            path=path, lang=PYTHON, outcome=OUTCOME_ERROR, loc=loc,
            reason=f"syntax error: {exc.msg} (line {exc.lineno})",
        )
    visitor = _Visitor(path)
    visitor.visit(tree)
    return FileParse(
        path=path,
        lang=PYTHON,
        outcome=OUTCOME_OK,
        symbols=visitor.symbols,
        imports=visitor.imports,
        calls=visitor.calls,
        loc=loc,
    )


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.symbols: list[Symbol] = []
        self.imports: list[ImportRef] = []
        self.calls: list[CallRef] = []
        self._scope: list[str] = []       # qualified-name stack (symbols)
        self._in_class: list[bool] = []    # parallel: is the scope a class?

    # --- imports --------------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(
                ImportRef(module=alias.name, file=self.path, line=node.lineno)
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = ("." * (node.level or 0)) + (node.module or "")
        names = tuple(a.name for a in node.names)
        self.imports.append(
            ImportRef(module=module, file=self.path, line=node.lineno, names=names)
        )

    # --- definitions ----------------------------------------------------
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._add_symbol(node, KIND_CLASS, signature=f"class {node.name}")
        self._descend(node, is_class=True)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_func(node, is_async=True)

    def _visit_func(self, node: ast.AST, *, is_async: bool = False) -> None:
        kind = KIND_METHOD if (self._in_class and self._in_class[-1]) else KIND_FUNCTION
        prefix = "async def" if is_async else "def"
        sig = f"{prefix} {node.name}({self._format_args(node.args)})"
        self._add_symbol(node, kind, signature=sig)
        self._descend(node, is_class=False)

    def _descend(self, node: ast.AST, *, is_class: bool) -> None:
        self._scope.append(node.name)
        self._in_class.append(is_class)
        self.generic_visit(node)
        self._in_class.pop()
        self._scope.pop()

    # --- calls ----------------------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        callee = self._dotted(node.func)
        if callee:
            caller = ".".join(self._scope)
            self.calls.append(
                CallRef(caller=caller, callee=callee, file=self.path, line=node.lineno)
            )
        self.generic_visit(node)

    # --- helpers --------------------------------------------------------
    def _add_symbol(self, node: ast.AST, kind: str, *, signature: str) -> None:
        parent = ".".join(self._scope) or None
        self.symbols.append(
            Symbol(
                name=node.name,
                kind=kind,
                file=self.path,
                start_line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno) or node.lineno,
                lang=PYTHON,
                signature=signature,
                docstring=(ast.get_docstring(node) or "")[:500],
                parent=parent,
            )
        )

    @staticmethod
    def _format_args(args: ast.arguments) -> str:
        parts: list[str] = []
        posonly = getattr(args, "posonlyargs", [])
        for a in list(posonly) + list(args.args):
            parts.append(a.arg)
        if args.vararg:
            parts.append("*" + args.vararg.arg)
        for a in args.kwonlyargs:
            parts.append(a.arg)
        if args.kwarg:
            parts.append("**" + args.kwarg.arg)
        return ", ".join(parts)

    @classmethod
    def _dotted(cls, node: ast.AST) -> str:
        """Reconstruct a dotted callee name (best-effort)."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = cls._dotted(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        return ""
