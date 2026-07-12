"""Browser plugin (S20e): read-only headless browser automation.

Exposes tools (registered as the ``browser`` capability):
    browser.open(url)              -> rendered {title, text, links, final_url, status}
    browser.screenshot(url, path)  -> saves a PNG under the sandbox root

The JS-rendering escalation from plain HTTP fetch. **Read-only** (navigate + extract
only) and **degrades gracefully**: if Playwright or a browser binary is missing, calls
return an ``unavailable`` outcome rather than raising (R2/R3). Honours ``robots.txt``
through the shared net policy and confines screenshots to a sandbox root.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.browser.browser import BrowserClient, PlaywrightBackend
from atlas.plugins.base import BasePlugin
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.config import AtlasConfig
    from atlas.kernel.application import Application


class BrowserPlugin(BasePlugin):
    name = "browser"
    version = "0.1.0"

    def __init__(self, client: BrowserClient, *, logger: logging.Logger | None = None) -> None:
        self._client = client
        self._logger = logger or logging.getLogger("atlas.plugins.browser")

    def register(self, kernel: "Application") -> None:
        from atlas.capabilities import CAP_BROWSER, BrowserCapability

        kernel.capabilities.register(
            CAP_BROWSER, self, contract=BrowserCapability, kind="plugin"
        )
        kernel.tools.register(
            "browser.open", self.open,
            description="Render a URL in a headless browser (runs JS) and extract "
            "the rendered title, text, and links.",
            params={"url": "an http(s) URL to render"},
            plugin=self.name,
        )
        kernel.tools.register(
            "browser.screenshot", self.screenshot,
            description="Render a URL and save a PNG screenshot under the sandbox root.",
            params={"url": "an http(s) URL", "path": "output PNG path under the root"},
            plugin=self.name,
        )

    # --- capability -----------------------------------------------------
    def open(self, url: str) -> dict[str, Any]:
        return self._client.open(url)

    def screenshot(self, url: str, path: str, full_page: bool = True) -> dict[str, Any]:
        return self._client.screenshot(url, path, full_page=full_page)

    def health_check(self) -> HealthStatus:
        backend = getattr(self._client, "_backend", None)
        available = bool(backend and backend.available())
        return HealthStatus(
            healthy=True,  # a missing browser engine is a degraded, not failed, state
            detail=("browser engine ready" if available
                    else "browser unavailable (playwright/browser not installed)"),
            data={"available": available},
        )


def build(config: "AtlasConfig") -> BrowserPlugin:
    br = config.plugins.browser
    root = br.screenshot_root or str(config.paths.data / "screenshots")
    backend = PlaywrightBackend(headless=br.headless, browser=br.browser)

    is_allowed = None
    if br.respect_robots:
        from atlas.net import FetchClient

        net = config.net
        fetch = FetchClient(
            user_agent=net.user_agent,
            timeout=net.timeout,
            respect_robots=True,
            cache_ttl=net.cache_ttl,
        )
        is_allowed = fetch.allowed

    client = BrowserClient(
        backend,
        root,
        is_allowed=is_allowed,
        timeout=br.timeout,
        wait_until=br.wait_until,
        max_text_chars=br.max_text_chars,
        max_links=br.max_links,
    )
    return BrowserPlugin(client)
