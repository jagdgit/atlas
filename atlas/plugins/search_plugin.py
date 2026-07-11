"""Search plugin (D5): web *search* — query → ranked result links.

Exposes one tool:
    web.search(query, max_results=5)
        -> {"query", "provider", "outcome", "results": [{title, url, snippet}]}

Registered as the ``search`` capability (`SearchCapability`). Holds an ordered list
of `SearchProvider`s and tries them in turn (**provider fallback**, D5): the first
that returns ``ok`` wins; if a provider is ``blocked``/``skipped`` (via the resilient
net layer), the next is tried, and the final structured outcome is returned so the
caller can report the gap (R2) without crashing (R3). Never raises for network.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.net import OUTCOME_OK, FetchClient
from atlas.plugins.base import BasePlugin
from atlas.search.providers import DuckDuckGoProvider, SearchProvider, SearchResponse
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.config import AtlasConfig
    from atlas.kernel.application import Application


class SearchPlugin(BasePlugin):
    name = "search"
    version = "0.1.0"

    def __init__(
        self,
        providers: list[SearchProvider],
        *,
        max_results: int = 5,
        logger: logging.Logger | None = None,
    ) -> None:
        self._providers = providers
        self._max_results = max_results
        self._logger = logger or logging.getLogger("atlas.plugins.search")

    def register(self, kernel: "Application") -> None:
        from atlas.capabilities import CAP_SEARCH, SearchCapability

        kernel.capabilities.register(
            CAP_SEARCH, self, contract=SearchCapability, kind="plugin"
        )
        kernel.tools.register(
            "web.search",
            self.web_search,
            description="Search the web and return ranked result links.",
            params={
                "query": "search query",
                "max_results": "max results to return (default 5)",
            },
            plugin=self.name,
        )

    # --- capability -----------------------------------------------------
    def search_web(self, query: str, *, max_results: int | None = None) -> SearchResponse:
        """Try each provider in order; first ``ok`` wins (provider fallback, D5)."""
        n = max_results or self._max_results
        last: SearchResponse | None = None
        for provider in self._providers:
            try:
                resp = provider.search(query, max_results=n)
            except Exception as exc:  # noqa: BLE001 - a bad provider must not crash search
                self._logger.exception("search provider %s failed", provider.name)
                last = SearchResponse(query, provider.name, "error", reason=str(exc))
                continue
            if resp.outcome == OUTCOME_OK and resp.hits:
                return resp
            last = resp
            self._logger.info(
                "provider %s => %s (%s); trying next",
                provider.name, resp.outcome, resp.reason,
            )
        if last is not None:
            return last
        return SearchResponse(query, "none", "error", reason="no search providers")

    def web_search(self, query: str, max_results: int | None = None) -> dict[str, Any]:
        """Tool entry point: returns the plain-dict form of a `SearchResponse`."""
        return self.search_web(query, max_results=max_results).as_dict()

    def health_check(self) -> HealthStatus:
        names = ", ".join(p.name for p in self._providers) or "none"
        healthy = bool(self._providers)
        return HealthStatus(
            healthy=healthy,
            detail=f"search providers: {names}",
            data={"providers": [p.name for p in self._providers]},
        )


def _build_provider(name: str, client: FetchClient, config: "AtlasConfig") -> SearchProvider | None:
    search = config.plugins.search
    if name == "duckduckgo":
        return DuckDuckGoProvider(client, endpoint=search.endpoint)
    return None


def build(config: "AtlasConfig") -> SearchPlugin:
    net = config.net
    search = config.plugins.search
    client = FetchClient(
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
    providers: list[SearchProvider] = []
    for name in search.providers:
        provider = _build_provider(name, client, config)
        if provider is not None:
            providers.append(provider)
    return SearchPlugin(providers, max_results=search.max_results)
