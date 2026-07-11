"""Language detection + the v1 grammar set (§5b.2).

Maps file extensions/names to a canonical language id. Python is parsed natively
(stdlib ``ast``, full call resolution); the rest are parsed via tree-sitter at the
symbol/import level. Everything else falls back to plain-text (honest, R2).
"""

from __future__ import annotations

from pathlib import Path

# Canonical language ids.
PYTHON = "python"

# extension -> language id (§5b.2 v1 grammars + config formats)
_EXT: dict[str, str] = {
    ".py": PYTHON,
    ".pyi": PYTHON,
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".sql": "sql",
    ".sh": "bash",
    ".bash": "bash",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
}

# exact filenames -> language id
_NAMES: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "dockerfile": "dockerfile",
}

# Languages we parse via tree-sitter (symbols + imports). Python uses `ast`.
TREE_SITTER_LANGS = frozenset(
    {
        "javascript",
        "typescript",
        "tsx",
        "c",
        "cpp",
        "rust",
        "go",
        "java",
        "sql",
        "bash",
    }
)

# Languages we can parse structurally at all (Python + tree-sitter set).
SUPPORTED_LANGS = frozenset({PYTHON}) | TREE_SITTER_LANGS


def language_for(path: str) -> str | None:
    """Return the canonical language id for a path, or ``None`` if unknown."""
    p = Path(path)
    if p.name in _NAMES:
        return _NAMES[p.name]
    return _EXT.get(p.suffix.lower())


def is_supported(lang: str | None) -> bool:
    return lang in SUPPORTED_LANGS


def supported_languages() -> list[str]:
    return sorted(SUPPORTED_LANGS)
