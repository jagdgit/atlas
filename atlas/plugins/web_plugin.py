"""Web plugin (ADR-0041): fetch a URL and return readable text.

Exposes one tool (ADR-0050):
    web.fetch(url)  -> {"url", "status", "content_type", "text"}

HTML is reduced to plain text (reusing the ingestion HTML extractor); other text
types pass through. Bodies are capped (``plugins.web.max_bytes``) and only
http/https URLs are allowed. This is the primitive agents use to read the web and
feed it into the knowledge base / their context.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx

from atlas.exceptions import PluginError
from atlas.ingestion.extractors import html_to_text
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
        *,
        timeout: float = 15.0,
        max_bytes: int = 2_097_152,
        user_agent: str = "Atlas/0.1",
        logger: logging.Logger | None = None,
    ) -> None:
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._user_agent = user_agent
        self._logger = logger or logging.getLogger("atlas.plugins.web")

    def register(self, kernel: "Application") -> None:
        kernel.capabilities.register("web", self, kind="plugin")
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
        try:
            with httpx.Client(
                timeout=self._timeout,
                follow_redirects=True,
                headers={"User-Agent": self._user_agent},
            ) as client:
                resp = client.get(url)
        except httpx.HTTPError as exc:
            raise PluginError(f"fetch failed for {url}: {exc}", url=url) from exc

        body = resp.content[: self._max_bytes]
        content_type = resp.headers.get("content-type", "")
        raw = body.decode(resp.encoding or "utf-8", errors="replace")
        if "html" in content_type.lower():
            text = html_to_text(raw) or ""
        else:
            text = raw
        return {
            "url": str(resp.url),
            "status": resp.status_code,
            "content_type": content_type,
            "text": text,
        }

    def health_check(self) -> HealthStatus:
        return HealthStatus.ok(f"web fetcher ready (cap {self._max_bytes} bytes)")


def build(config: "AtlasConfig") -> WebPlugin:
    web = config.plugins.web
    return WebPlugin(
        timeout=web.timeout,
        max_bytes=web.max_bytes,
        user_agent=web.user_agent,
    )
