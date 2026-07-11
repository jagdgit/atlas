"""CodeParser — dispatch a file to the right structural parser (§5b.1 layers 1 & 7).

Python → stdlib ``ast`` (full, incl. calls); tree-sitter languages → symbols +
imports; anything else → an honest ``unsupported`` outcome (plain-text fallback lives
in the caller). Never raises for a bad/oversized/binary file — it classifies (R2).
"""

from __future__ import annotations

import logging
from pathlib import Path

from atlas.code.languages import PYTHON, TREE_SITTER_LANGS, language_for
from atlas.code.models import OUTCOME_ERROR, OUTCOME_UNSUPPORTED, FileParse
from atlas.code.pyast import parse_python
from atlas.code.treesitter import parse_treesitter


class CodeParser:
    def __init__(
        self,
        *,
        max_file_bytes: int = 1_048_576,
        logger: logging.Logger | None = None,
    ) -> None:
        self._max_bytes = max_file_bytes
        self._logger = logger or logging.getLogger("atlas.code.parser")

    def parse_text(self, text: str, path: str, lang: str | None = None) -> FileParse:
        lang = lang or language_for(path)
        if lang == PYTHON:
            return parse_python(text, path)
        if lang in TREE_SITTER_LANGS:
            return parse_treesitter(text, path, lang)
        return FileParse(
            path=path,
            lang=lang or "unknown",
            outcome=OUTCOME_UNSUPPORTED,
            loc=(text.count("\n") + 1 if text else 0),
            reason="no structural parser for this language (plain-text only)",
        )

    def parse_file(self, path: str | Path) -> FileParse:
        p = Path(path)
        rel = str(path)
        try:
            size = p.stat().st_size
            if size > self._max_bytes:
                return FileParse(
                    path=rel, lang=(language_for(rel) or "unknown"),
                    outcome=OUTCOME_ERROR,
                    reason=f"file too large ({size} > {self._max_bytes} bytes)",
                )
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return FileParse(
                path=rel, lang=(language_for(rel) or "unknown"),
                outcome=OUTCOME_ERROR, reason=f"read error: {exc}",
            )
        return self.parse_text(text, rel, language_for(rel))
