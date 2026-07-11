"""Web search (Stage 2, S13b, D5).

A provider-agnostic `SearchCapability`: the planner asks to *search the web*; the
`SearchPlugin` resolves a query to ranked results via one or more swappable
`SearchProvider`s (default: DuckDuckGo, no API key). Every provider fetches through
the resilient net layer (`atlas.net`), so a blocked/unavailable backend degrades to
a structured outcome (R2/R3) instead of crashing — and the plugin falls back to the
next provider (D5).
"""

from __future__ import annotations

from atlas.search.providers import (
    DuckDuckGoProvider,
    SearchHit,
    SearchProvider,
    SearchResponse,
)

__all__ = [
    "SearchHit",
    "SearchResponse",
    "SearchProvider",
    "DuckDuckGoProvider",
]
