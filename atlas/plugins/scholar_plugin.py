"""Scholar plugin (S18a): academic *search* — query → graded papers.

Exposes one tool:
    scholar.search(query, max_results=5)
        -> {"query", "provider", "outcome",
            "results": [{title, authors, year, venue, doi, citation_count, ...}],
            "sources": [{id, title, url, evidence_level, kind}]}   # Evidence Graph shape

Registered as the ``scholar`` capability. Holds an ordered list of `ScholarlyProvider`s
tried in turn (**provider fallback**, mirroring D5 web search): the first that returns
``ok`` with papers wins; a blocked/rate-limited provider (via the resilient net layer)
falls through to the next, and the final structured outcome is returned so the caller
can report the gap (R2) without crashing (R3). Papers carry an Evidence Level so results
drop straight into the Verification Engine / Evidence Graph (§5a).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.net import OUTCOME_OK, FetchClient
from atlas.plugins.base import BasePlugin
from atlas.search.scholarly import (
    ArxivProvider,
    ScholarlyProvider,
    ScholarlyResponse,
    SemanticScholarProvider,
)
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.config import AtlasConfig
    from atlas.kernel.application import Application


class ScholarPlugin(BasePlugin):
    name = "scholar"
    version = "0.1.0"

    def __init__(
        self,
        providers: list[ScholarlyProvider],
        *,
        max_results: int = 5,
        logger: logging.Logger | None = None,
    ) -> None:
        self._providers = providers
        self._max_results = max_results
        self._logger = logger or logging.getLogger("atlas.plugins.scholar")

    def register(self, kernel: "Application") -> None:
        from atlas.capabilities import CAP_SCHOLAR, ScholarCapability

        kernel.capabilities.register(
            CAP_SCHOLAR, self, contract=ScholarCapability, kind="plugin"
        )
        kernel.tools.register(
            "scholar.search",
            self.scholar_search,
            description="Search academic sources (arXiv, Semantic Scholar) for papers.",
            params={
                "query": "search query",
                "max_results": "max papers to return (default 5)",
            },
            plugin=self.name,
        )

    # --- capability -----------------------------------------------------
    def search_scholar(
        self, query: str, *, max_results: int | None = None
    ) -> ScholarlyResponse:
        """Try each provider in order; first ``ok`` with papers wins (fallback)."""
        n = max_results or self._max_results
        last: ScholarlyResponse | None = None
        for provider in self._providers:
            try:
                resp = provider.search(query, max_results=n)
            except Exception as exc:  # noqa: BLE001 - a bad provider must not crash search
                self._logger.exception("scholar provider %s failed", provider.name)
                last = ScholarlyResponse(query, provider.name, "error", reason=str(exc))
                continue
            if resp.outcome == OUTCOME_OK and resp.papers:
                return resp
            last = resp
            self._logger.info(
                "scholar provider %s => %s (%s); trying next",
                provider.name, resp.outcome, resp.reason,
            )
        if last is not None:
            return last
        return ScholarlyResponse(query, "none", "error", reason="no scholar providers")

    def scholar_search(self, query: str, max_results: int | None = None) -> dict[str, Any]:
        return self.search_scholar(query, max_results=max_results).as_dict()

    def health_check(self) -> HealthStatus:
        names = ", ".join(p.name for p in self._providers) or "none"
        return HealthStatus(
            healthy=bool(self._providers),
            detail=f"scholar providers: {names}",
            data={"providers": [p.name for p in self._providers]},
        )


def _client(config: "AtlasConfig") -> FetchClient:
    net = config.net
    return FetchClient(
        user_agent=net.user_agent,
        timeout=net.timeout,
        max_bytes=net.max_bytes,
        per_domain_delay=net.per_domain_delay,
        max_retries=net.max_retries,
        backoff_base=net.backoff_base,
        backoff_cap=net.backoff_cap,
        jitter=net.jitter,
        respect_robots=net.respect_robots,
        cache_ttl=net.cache_ttl,
    )


def _build_provider(
    name: str, client: FetchClient, config: "AtlasConfig"
) -> ScholarlyProvider | None:
    scholar = config.plugins.scholar
    if name == "arxiv":
        return ArxivProvider(client, evidence_level=scholar.arxiv_level)
    if name == "semantic_scholar":
        return SemanticScholarProvider(
            client,
            evidence_level=scholar.semantic_scholar_level,
            api_key=scholar.semantic_scholar_api_key or None,
        )
    return None


def build(config: "AtlasConfig") -> ScholarPlugin:
    scholar = config.plugins.scholar
    client = _client(config)
    providers: list[ScholarlyProvider] = []
    for name in scholar.providers:
        provider = _build_provider(name, client, config)
        if provider is not None:
            providers.append(provider)
    return ScholarPlugin(providers, max_results=scholar.max_results)
