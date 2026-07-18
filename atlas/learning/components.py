"""Stable component keys for experience observations (A3B.17 / D3B.24)."""

from __future__ import annotations

from typing import Any

# Canonical prefixes for component experience rows.
READER_PREFIX = "reader:"
RETRIEVAL_HYBRID = "retrieval:hybrid"
SYNTHESIZER_V1 = "synthesizer:v1"
REASONER_V1 = "reasoner:v1"

_READER_ALIASES = {
    "html": "html",
    "pdf_text": "pdf_text",
    "pdf_ocr": "ocr",
    "ocr": "ocr",
    "text": "text",
    "none": "none",
}


def reader_component_key(reader_id: str | None) -> str | None:
    """Map a Document.reader_id to ``reader:{name}`` (A3B.17)."""
    if not reader_id:
        return None
    name = _READER_ALIASES.get(str(reader_id).strip().lower(), str(reader_id).strip().lower())
    if not name or name == "none":
        return None
    return f"{READER_PREFIX}{name}"


def component_observation(
    component_key: str,
    *,
    component_version: str = "1",
    metrics: dict[str, Any] | None = None,
    corpus: str | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """One component+version observation record (propose/apply payload shape)."""
    return {
        "component_key": component_key,
        "component_version": str(component_version or "1"),
        "corpus": corpus,
        "profile": profile,
        "metrics": dict(metrics or {}),
    }
