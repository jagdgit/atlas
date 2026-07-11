"""Multi-language structural parser (tree-sitter) — the breadth path (§5b.1).

Extracts symbols (functions/classes/methods) and imports for the v1 grammar set via
prebuilt grammars (``tree-sitter-language-pack``). Cross-file **call** resolution is
Python-first (see ``pyast``); other languages degrade to symbol + import level here,
which is exactly the Tier-B contract (D9). If a grammar is unavailable the file is
returned as ``shallow`` (honest, R2) rather than raising.

The grammar library is imported lazily so the rest of Atlas runs without it.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.code.models import (
    KIND_CLASS,
    KIND_FUNCTION,
    KIND_METHOD,
    OUTCOME_OK,
    OUTCOME_SHALLOW,
    FileParse,
    ImportRef,
    Symbol,
)

_logger = logging.getLogger("atlas.code.treesitter")

# Per-language node-type maps: symbol node type -> kind, and import node types.
# Kept intentionally small and robust; unknown nodes are ignored.
_SYMBOLS: dict[str, dict[str, str]] = {
    "javascript": {
        "function_declaration": KIND_FUNCTION,
        "generator_function_declaration": KIND_FUNCTION,
        "class_declaration": KIND_CLASS,
        "method_definition": KIND_METHOD,
    },
    "typescript": {
        "function_declaration": KIND_FUNCTION,
        "class_declaration": KIND_CLASS,
        "method_definition": KIND_METHOD,
        "interface_declaration": KIND_CLASS,
        "abstract_class_declaration": KIND_CLASS,
    },
    "tsx": {
        "function_declaration": KIND_FUNCTION,
        "class_declaration": KIND_CLASS,
        "method_definition": KIND_METHOD,
        "interface_declaration": KIND_CLASS,
    },
    "go": {
        "function_declaration": KIND_FUNCTION,
        "method_declaration": KIND_METHOD,
        "type_declaration": KIND_CLASS,
    },
    "rust": {
        "function_item": KIND_FUNCTION,
        "struct_item": KIND_CLASS,
        "enum_item": KIND_CLASS,
        "trait_item": KIND_CLASS,
        "mod_item": KIND_CLASS,
    },
    "c": {
        "function_definition": KIND_FUNCTION,
        "struct_specifier": KIND_CLASS,
    },
    "cpp": {
        "function_definition": KIND_FUNCTION,
        "class_specifier": KIND_CLASS,
        "struct_specifier": KIND_CLASS,
        "namespace_definition": KIND_CLASS,
    },
    "java": {
        "class_declaration": KIND_CLASS,
        "interface_declaration": KIND_CLASS,
        "method_declaration": KIND_METHOD,
        "constructor_declaration": KIND_METHOD,
    },
    "bash": {
        "function_definition": KIND_FUNCTION,
    },
    "sql": {},
}

_IMPORTS: dict[str, set[str]] = {
    "javascript": {"import_statement"},
    "typescript": {"import_statement"},
    "tsx": {"import_statement"},
    "go": {"import_spec"},
    "rust": {"use_declaration"},
    "c": {"preproc_include"},
    "cpp": {"preproc_include"},
    "java": {"import_declaration"},
    "bash": set(),
    "sql": set(),
}

_NAME_NODE_TYPES = {
    "identifier",
    "type_identifier",
    "field_identifier",
    "name",
    "word",
    "property_identifier",
}


def parse_treesitter(text: str, path: str, lang: str) -> FileParse:
    loc = text.count("\n") + 1 if text else 0
    parser = _get_parser(lang)
    if parser is None:
        return FileParse(
            path=path, lang=lang, outcome=OUTCOME_SHALLOW, loc=loc,
            reason="tree-sitter grammar unavailable",
        )
    data = text.encode("utf-8", errors="replace")
    tree = parser.parse(data)
    collector = _Collector(path, lang, data)
    collector.walk(tree.root_node, scope=[])
    return FileParse(
        path=path,
        lang=lang,
        outcome=OUTCOME_OK,
        symbols=collector.symbols,
        imports=collector.imports,
        loc=loc,
    )


def _get_parser(lang: str) -> Any | None:
    try:
        from tree_sitter_language_pack import get_parser
    except Exception:  # noqa: BLE001 - optional dependency
        _logger.debug("tree-sitter-language-pack not installed")
        return None
    try:
        return get_parser(lang)
    except Exception:  # noqa: BLE001 - grammar for this lang not packaged
        _logger.debug("no tree-sitter grammar for %s", lang)
        return None


class _Collector:
    def __init__(self, path: str, lang: str, data: bytes) -> None:
        self.path = path
        self.lang = lang
        self.data = data
        self.symbols: list[Symbol] = []
        self.imports: list[ImportRef] = []
        self._sym_types = _SYMBOLS.get(lang, {})
        self._imp_types = _IMPORTS.get(lang, set())

    def walk(self, node: Any, scope: list[str]) -> None:
        for child in node.children:
            ntype = child.type
            if ntype in self._imp_types:
                self._add_import(child)
            if ntype in self._sym_types:
                name = self._name_of(child)
                if name:
                    sym = self._make_symbol(child, name, self._sym_types[ntype], scope)
                    self.symbols.append(sym)
                    self.walk(child, scope + [name])
                    continue
            self.walk(child, scope)

    def _make_symbol(self, node: Any, name: str, kind: str, scope: list[str]) -> Symbol:
        parent = ".".join(scope) or None
        return Symbol(
            name=name,
            kind=kind,
            file=self.path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            lang=self.lang,
            signature=self._first_line(node),
            parent=parent,
        )

    def _add_import(self, node: Any) -> None:
        module = self._import_target(node)
        if module:
            self.imports.append(
                ImportRef(module=module, file=self.path, line=node.start_point[0] + 1)
            )

    # --- text helpers ---------------------------------------------------
    def _text(self, node: Any) -> str:
        return self.data[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

    def _first_line(self, node: Any) -> str:
        return self._text(node).splitlines()[0].strip()[:200] if node.end_byte else ""

    def _name_of(self, node: Any) -> str:
        field = node.child_by_field_name("name")
        if field is not None:
            return self._text(field)
        for child in node.children:
            if child.type in _NAME_NODE_TYPES:
                return self._text(child)
        return ""

    def _import_target(self, node: Any) -> str:
        for field in ("source", "name", "path"):
            f = node.child_by_field_name(field)
            if f is not None:
                return self._text(f).strip("\"'<>`")
        return self._text(node).strip().strip("\"'<>`")[:120]
