"""Scholarly search providers (Stage 2, S18a) — academic retrieval over the net layer.

Where `SearchProvider` (D5) returns general web links, a `ScholarlyProvider` returns
**papers** — title, authors, year, venue, abstract, DOI, citation count — each already
tagged with an **Evidence Level** (§5a.2) so results drop straight into the Evidence
Graph / Verification Engine as graded sources (peer-reviewed = L4, preprint = L3).

Providers never raise for network/HTTP conditions: they translate the resilient net
layer's outcome (`ok`/`blocked`/`skipped`/`error`) so the `ScholarPlugin` can fall back
to the next provider and the job keeps going (R2/R3).

- **`ArxivProvider`** — the arXiv Atom API (keyless); preprints ⇒ **L3** by default.
- **`SemanticScholarProvider`** — the Semantic Scholar Graph API (keyless, rate-limited;
  optional API key); indexed published venues + citation counts ⇒ **L4** by default.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from urllib.parse import quote_plus

from atlas.evidence.models import (
    LEVEL_GOVERNMENT,
    LEVEL_PEER_REVIEWED,
    level_name,
)
from atlas.net import OUTCOME_ERROR, OUTCOME_OK

if TYPE_CHECKING:
    from atlas.net import FetchClient


@dataclass(frozen=True)
class Paper:
    title: str
    url: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    abstract: str = ""
    doi: str = ""
    citation_count: int | None = None
    provider: str = ""
    evidence_level: int = LEVEL_PEER_REVIEWED

    @property
    def source_id(self) -> str:
        return self.doi or self.url or self.title[:60]

    def as_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "url": self.url,
            "authors": list(self.authors),
            "year": self.year,
            "venue": self.venue,
            "abstract": self.abstract,
            "doi": self.doi,
            "citation_count": self.citation_count,
            "provider": self.provider,
            "evidence_level": self.evidence_level,
            "level_name": level_name(self.evidence_level),
        }

    def as_source(self) -> dict[str, object]:
        """The Evidence Graph `Source` shape (§5a.1) — a graded, citable source."""
        kind = "peer_reviewed" if self.evidence_level >= LEVEL_PEER_REVIEWED else "preprint"
        citation = _format_citation(
            authors=self.authors,
            year=self.year,
            title=self.title,
            venue=self.venue,
            doi=self.doi,
        )
        return {
            "id": self.source_id,
            "title": self.title,
            "url": self.url,
            "evidence_level": self.evidence_level,
            "kind": kind,
            "doi": self.doi,
            "citation": citation,
            "authors": list(self.authors),
            "year": self.year,
            "venue": self.venue,
        }


def _format_citation(
    *,
    authors: list[str] | tuple[str, ...],
    year: int | None,
    title: str,
    venue: str,
    doi: str,
) -> str:
    """Cheap human cite-string when metadata is present (Stage 3.2 / D32.7)."""
    parts: list[str] = []
    names = [a.strip() for a in (authors or []) if str(a).strip()]
    if names:
        if len(names) == 1:
            who = names[0]
        elif len(names) == 2:
            who = f"{names[0]} & {names[1]}"
        else:
            who = f"{names[0]} et al."
        parts.append(who)
    if year is not None:
        parts.append(f"({year})")
    if title:
        parts.append(f"{title.rstrip('.')}." )
    if venue:
        parts.append(f"{venue}.")
    if doi:
        parts.append(f"DOI: {doi}")
    return " ".join(parts).strip()


@dataclass(frozen=True)
class ScholarlyResponse:
    query: str
    provider: str
    outcome: str
    papers: list[Paper] = field(default_factory=list)
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == OUTCOME_OK

    def as_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "provider": self.provider,
            "outcome": self.outcome,
            "results": [p.as_dict() for p in self.papers],
            "sources": [p.as_source() for p in self.papers],
            "reason": self.reason,
        }


@runtime_checkable
class ScholarlyProvider(Protocol):
    name: str

    def search(self, query: str, *, max_results: int = 5) -> ScholarlyResponse: ...


_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"


class ArxivProvider:
    """arXiv Atom API (keyless). Preprints ⇒ L3 by default (not peer-reviewed)."""

    name = "arxiv"

    def __init__(
        self,
        client: "FetchClient",
        *,
        endpoint: str = "http://export.arxiv.org/api/query",
        evidence_level: int = LEVEL_GOVERNMENT,
        logger: logging.Logger | None = None,
    ) -> None:
        self._client = client
        self._endpoint = endpoint
        self._evidence_level = evidence_level
        self._logger = logger or logging.getLogger("atlas.search.arxiv")

    def search(self, query: str, *, max_results: int = 5) -> ScholarlyResponse:
        query = (query or "").strip()
        if not query:
            return ScholarlyResponse(query, self.name, OUTCOME_OK, papers=[])
        url = (
            f"{self._endpoint}?search_query=all:{quote_plus(query)}"
            f"&start=0&max_results={max_results}"
        )
        result = self._client.get(url)
        if result.outcome != OUTCOME_OK:
            return ScholarlyResponse(query, self.name, result.outcome, reason=result.reason)
        try:
            papers = self._parse(result.text, max_results)
        except Exception as exc:  # noqa: BLE001 - malformed feed must not crash search
            self._logger.exception("arxiv parse failed")
            return ScholarlyResponse(query, self.name, OUTCOME_ERROR, reason=str(exc))
        return ScholarlyResponse(query, self.name, OUTCOME_OK, papers=papers)

    def _parse(self, xml_text: str, max_results: int) -> list[Paper]:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml_text)
        papers: list[Paper] = []
        for entry in root.findall(f"{_ATOM}entry")[:max_results]:
            title = _text(entry.find(f"{_ATOM}title"))
            summary = _text(entry.find(f"{_ATOM}summary"))
            link = _text(entry.find(f"{_ATOM}id"))
            published = _text(entry.find(f"{_ATOM}published"))
            year = _year(published)
            authors = [
                _text(a.find(f"{_ATOM}name"))
                for a in entry.findall(f"{_ATOM}author")
            ]
            doi = _text(entry.find(f"{_ARXIV}doi"))
            papers.append(
                Paper(
                    title=" ".join(title.split()),
                    url=link,
                    authors=[a for a in authors if a],
                    year=year,
                    venue="arXiv",
                    abstract=" ".join(summary.split()),
                    doi=doi,
                    provider=self.name,
                    evidence_level=self._evidence_level,
                )
            )
        return papers


class SemanticScholarProvider:
    """Semantic Scholar Graph API (keyless, rate-limited). Published venues ⇒ L4."""

    name = "semantic_scholar"
    _FIELDS = "title,abstract,year,venue,authors,externalIds,citationCount,url"

    def __init__(
        self,
        client: "FetchClient",
        *,
        endpoint: str = "https://api.semanticscholar.org/graph/v1/paper/search",
        evidence_level: int = LEVEL_PEER_REVIEWED,
        api_key: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._client = client
        self._endpoint = endpoint
        self._evidence_level = evidence_level
        self._api_key = api_key
        self._logger = logger or logging.getLogger("atlas.search.s2")

    def search(self, query: str, *, max_results: int = 5) -> ScholarlyResponse:
        query = (query or "").strip()
        if not query:
            return ScholarlyResponse(query, self.name, OUTCOME_OK, papers=[])
        url = (
            f"{self._endpoint}?query={quote_plus(query)}"
            f"&limit={max_results}&fields={self._FIELDS}"
        )
        result = self._client.get(url)
        if result.outcome != OUTCOME_OK:
            return ScholarlyResponse(query, self.name, result.outcome, reason=result.reason)
        try:
            papers = self._parse(result.text, max_results)
        except Exception as exc:  # noqa: BLE001 - malformed payload must not crash search
            self._logger.exception("semantic scholar parse failed")
            return ScholarlyResponse(query, self.name, OUTCOME_ERROR, reason=str(exc))
        return ScholarlyResponse(query, self.name, OUTCOME_OK, papers=papers)

    def _parse(self, body: str, max_results: int) -> list[Paper]:
        data = json.loads(body or "{}")
        papers: list[Paper] = []
        for item in (data.get("data") or [])[:max_results]:
            ext = item.get("externalIds") or {}
            authors = [a.get("name", "") for a in (item.get("authors") or [])]
            papers.append(
                Paper(
                    title=item.get("title") or "",
                    url=item.get("url") or "",
                    authors=[a for a in authors if a],
                    year=item.get("year"),
                    venue=item.get("venue") or "",
                    abstract=item.get("abstract") or "",
                    doi=str(ext.get("DOI") or ""),
                    citation_count=item.get("citationCount"),
                    provider=self.name,
                    evidence_level=self._evidence_level,
                )
            )
        return papers


def _text(node) -> str:
    return (node.text or "").strip() if node is not None else ""


def _year(published: str) -> int | None:
    if len(published) >= 4 and published[:4].isdigit():
        return int(published[:4])
    return None
