"""Code Understanding (`CodeCapability`, Stage 2 S14, D9 — Tier B).

Atlas reads code as **structure**, not text: a deterministic parse (Python via the
stdlib `ast`; other languages via tree-sitter) yields symbols, imports, and calls;
those feed a **repo map**, a **symbol index**, an **import + cross-file call graph**
(Python-first), **pattern mining**, and code-aware chunking for RAG. The `code`-role
LLM (D7) explains/reviews grounded on those facts (curbing hallucination).

Layers (§5b.1): parse → repo map → code-aware RAG → symbol index + graph →
`code`-role LLM → pattern mining → plain-text fallback for unsupported languages (R2).
"""

from __future__ import annotations

from atlas.code.models import (
    CallRef,
    CodeGraph,
    FileParse,
    ImportRef,
    Pattern,
    RepoMap,
    Symbol,
)
from atlas.code.parser import CodeParser
from atlas.code.service import CodeService

__all__ = [
    "Symbol",
    "ImportRef",
    "CallRef",
    "FileParse",
    "RepoMap",
    "CodeGraph",
    "Pattern",
    "CodeParser",
    "CodeService",
]
