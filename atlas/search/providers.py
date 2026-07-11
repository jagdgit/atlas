"""Search providers (D5) — query → ranked results over the resilient net layer.

A `SearchProvider` turns a query into a `SearchResponse` (outcome + hits). Providers
never raise for network/HTTP conditions: they translate the net layer's outcome
(`ok`/`blocked`/`skipped`/`error`) so the `SearchPlugin` can fall back to the next
provider and the job keeps going (R2/R3).

`DuckDuckGoProvider` uses the keyless HTML endpoint (the D5 recommended default);
new backends (SearXNG, Brave/Serper) implement the same protocol and swap in via
config without touching the planner.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from urllib.parse import parse_qs, quote_plus, urlparse

from atlas.net import OUTCOME_OK

if TYPE_CHECKING:
    from atlas.net import FetchClient


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


@dataclass(frozen=True)
class SearchResponse:
    query: str
    provider: str
    outcome: str
    hits: list[SearchHit] = field(default_factory=list)
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == OUTCOME_OK

    def as_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "provider": self.provider,
            "outcome": self.outcome,
            "results": [h.as_dict() for h in self.hits],
            "reason": self.reason,
        }


@runtime_checkable
class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, max_results: int = 5) -> SearchResponse: ...


class DuckDuckGoProvider:
    """Keyless DuckDuckGo HTML backend (D5 default)."""

    name = "duckduckgo"

    def __init__(
        self,
        client: "FetchClient",
        *,
        endpoint: str = "https://html.duckduckgo.com/html/",
        logger: logging.Logger | None = None,
    ) -> None:
        self._client = client
        self._endpoint = endpoint
        self._logger = logger or logging.getLogger("atlas.search.ddg")

    def search(self, query: str, *, max_results: int = 5) -> SearchResponse:
        query = (query or "").strip()
        if not query:
            return SearchResponse(query, self.name, OUTCOME_OK, hits=[])
        url = f"{self._endpoint}?q={quote_plus(query)}"
        result = self._client.get(url)
        if result.outcome != OUTCOME_OK:
            return SearchResponse(
                query, self.name, result.outcome, reason=result.reason
            )
        hits = self._parse(result.text, max_results)
        return SearchResponse(query, self.name, OUTCOME_OK, hits=hits)

    # --- parsing --------------------------------------------------------
    def _parse(self, html: str, max_results: int) -> list[SearchHit]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        hits: list[SearchHit] = []
        results = soup.select("div.result") or soup.select("div.web-result")
        if results:
            for res in results:
                a = res.select_one("a.result__a")
                if a is None:
                    continue
                sn = res.select_one(".result__snippet")
                hit = self._hit(a, sn)
                if hit is not None:
                    hits.append(hit)
                if len(hits) >= max_results:
                    break
            return hits
        # Fallback: pair links and snippets positionally.
        links = soup.select("a.result__a")
        snippets = soup.select(".result__snippet")
        for i, a in enumerate(links[:max_results]):
            sn = snippets[i] if i < len(snippets) else None
            hit = self._hit(a, sn)
            if hit is not None:
                hits.append(hit)
        return hits

    def _hit(self, a, snippet) -> SearchHit | None:
        title = a.get_text(" ", strip=True)
        href = self._clean_url(a.get("href", ""))
        if not href:
            return None
        text = snippet.get_text(" ", strip=True) if snippet is not None else ""
        return SearchHit(title=title, url=href, snippet=text)

    @staticmethod
    def _clean_url(href: str) -> str:
        """DDG wraps results as //duckduckgo.com/l/?uddg=<encoded target>."""
        if not href:
            return ""
        if href.startswith("//"):
            href = "https:" + href
        parsed = urlparse(href)
        if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
            uddg = parse_qs(parsed.query).get("uddg")
            if uddg:
                return uddg[0]
        return href
