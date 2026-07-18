"""Stable component keys for experience observations (A3B.17 / D3B.24)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

# Canonical prefixes for component experience rows.
READER_PREFIX = "reader:"
RETRIEVAL_HYBRID = "retrieval:hybrid"
SYNTHESIZER_V1 = "synthesizer:v1"
REASONER_V1 = "reasoner:v1"
# Operational source-reliability experience (§3B loop): per-publisher/domain
# acquisition outcomes accumulate here so Atlas can *recommend* preferring reliably
# readable sources (e.g. arxiv.org) and deprioritizing routinely blocked ones
# (e.g. ieeexplore.ieee.org) — advice-only, never an automatic behavior change.
SOURCE_PREFIX = "source:"


def domain_from_url(url: str | None) -> str:
    """Normalized registrable-ish host for a URL (or bare domain), or ``""``.

    ``https://www.ieeexplore.ieee.org/x`` → ``ieeexplore.ieee.org``. Bare domains
    (``arxiv.org``) are accepted too, so callers can pass either.
    """
    if not url:
        return ""
    raw = str(url).strip()
    if "//" not in raw:
        raw = "//" + raw  # let urlparse treat a bare host as netloc
    netloc = (urlparse(raw).netloc or "").lower()
    if not netloc:
        return ""
    netloc = netloc.split("@")[-1].split(":")[0]  # strip credentials / port
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def source_component_key(url: str | None) -> str | None:
    """Map a source URL/domain to ``source:{domain}`` (operational experience)."""
    domain = domain_from_url(url)
    return f"{SOURCE_PREFIX}{domain}" if domain else None

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
