"""Headless browser automation (Stage 2, S20e — the last Tier-2 tool).

The escalation path from plain HTTP fetch (§5c): some pages only yield their content
after JavaScript runs. This capability renders a URL in a real headless browser and
returns the *rendered* title/text/links (and can screenshot it). It is deliberately
**read-only** — navigate + extract only; there is no click/type/submit path — and, per
the build order, it ships last because it carries the heaviest dependency (Playwright +
a browser binary) and the largest safety surface.

Built on an injectable ``BrowserBackend`` seam: the default ``PlaywrightBackend``
**degrades gracefully** — a missing ``playwright`` package or un-installed browser
surfaces as an ``unavailable`` outcome, never a crash (R2/R3). It reuses the shared
net politeness (``robots.txt`` via ``FetchClient.allowed``) and confines screenshots to
a sandbox root. Tests inject a fake backend for full hermetic coverage.
"""

from __future__ import annotations

from atlas.browser.browser import (
    BROWSER_BLOCKED,
    BROWSER_EMPTY,
    BROWSER_ERROR,
    BROWSER_OK,
    BROWSER_TIMEOUT,
    BROWSER_UNAVAILABLE,
    BrowserBackend,
    BrowserClient,
    BrowserError,
    BrowserTimeout,
    BrowserUnavailable,
    PlaywrightBackend,
    RenderedPage,
)

__all__ = [
    "BrowserClient",
    "BrowserBackend",
    "PlaywrightBackend",
    "RenderedPage",
    "BrowserError",
    "BrowserTimeout",
    "BrowserUnavailable",
    "BROWSER_OK",
    "BROWSER_EMPTY",
    "BROWSER_BLOCKED",
    "BROWSER_UNAVAILABLE",
    "BROWSER_TIMEOUT",
    "BROWSER_ERROR",
]
