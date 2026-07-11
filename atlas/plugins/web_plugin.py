"""Web plugin (ADR-0041): fetch a URL and return readable text.

Exposes one tool (ADR-0050):
    web.fetch(url)  -> {"url", "status", "content_type", "text", "outcome", "from_cache"}

As of S13 (D10 / §5c) the fetch goes through the shared **resilient net layer**
(`atlas.net.FetchClient`): per-domain throttling, robots.txt awareness, bounded
backoff/retry, and response caching. HTML is reduced to plain text (reusing the
ingestion HTML extractor); other text types pass through. A hard block (401/403)
or unavailable source (4xx/robots/retries-exhausted) is surfaced as a structured
outcome and raised as a ``PluginError`` so the caller can report it (R2) — the
step-level *blocked/skipped* mapping (R3) lands with the HITL work in S17.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from atlas.exceptions import PluginError
from atlas.ingestion.extractors import html_to_text
from atlas.net import OUTCOME_BLOCKED, OUTCOME_OK, FetchClient
from atlas.plugins.base import BasePlugin
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.config import AtlasConfig
    from atlas.kernel.application import Application


class WebPlugin(BasePlugin):
    name = "web"
    version = "0.1.0"

    def __init__(
        self,
        client: FetchClient,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._client = client
        self._logger = logger or logging.getLogger("atlas.plugins.web")

    def register(self, kernel: "Application") -> None:
        from atlas.capabilities import CAP_WEB, FetchCapability

        kernel.capabilities.register(
            CAP_WEB, self, contract=FetchCapability, kind="plugin"
        )
        kernel.tools.register(
            "web.fetch",
            self.fetch,
            description="Fetch an http(s) URL and return its readable text.",
            params={"url": "absolute http(s) URL to fetch"},
            plugin=self.name,
        )

    # --- actions --------------------------------------------------------
    def fetch(self, url: str) -> dict[str, Any]:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise PluginError(f"only http(s) URLs are allowed: {url}", url=url)

        result = self._client.get(url)
        if result.outcome != OUTCOME_OK:
            # Honest failure (R2): name the outcome (blocked vs skipped) and reason.
            hint = "needs login" if result.outcome == OUTCOME_BLOCKED else "unavailable"
            raise PluginError(
                f"fetch {result.outcome} ({hint}) for {url}: {result.reason}",
                url=url,
            )

        if "html" in result.content_type.lower():
            text = html_to_text(result.text) or ""
        else:
            text = result.text
        return {
            "url": result.final_url or url,
            "status": result.status_code,
            "content_type": result.content_type,
            "text": text,
            "outcome": result.outcome,
            "from_cache": result.from_cache,
        }

    def health_check(self) -> HealthStatus:
        return HealthStatus.ok("web fetcher ready (resilient net layer)")


def build(config: "AtlasConfig") -> WebPlugin:
    net = config.net
    web = config.plugins.web
    client = FetchClient(
        user_agent=net.user_agent or web.user_agent,
        timeout=net.timeout or web.timeout,
        max_bytes=net.max_bytes or web.max_bytes,
        per_domain_delay=net.per_domain_delay,
        max_retries=net.max_retries,
        backoff_base=net.backoff_base,
        backoff_cap=net.backoff_cap,
        jitter=net.jitter,
        respect_robots=net.respect_robots,
        cache_ttl=net.cache_ttl,
    )
    return WebPlugin(client)
