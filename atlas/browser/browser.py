"""Browser client + Playwright backend (S20e).

``BrowserClient`` renders a URL and returns the JS-rendered title/text/links, or a
screenshot, through an injectable ``BrowserBackend`` (default ``PlaywrightBackend``).
The seam keeps the client hermetic (tests inject a fake) while the real backend
**degrades gracefully** — missing Playwright / browser binary ⇒ ``unavailable``.

**Read-only by design:** the backend only navigates and extracts (no click/type/submit).
Only ``http(s)`` URLs are allowed, ``robots.txt`` is honoured through the shared net
policy, navigations are time-bounded, and screenshots are confined to a sandbox root.

Outcomes are honest and never raise (R2/R3):
  ``ok`` | ``empty`` (rendered but no text) | ``blocked`` (robots-disallowed) |
  ``timeout`` | ``unavailable`` (engine/browser missing) | ``error``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

BROWSER_OK = "ok"
BROWSER_EMPTY = "empty"
BROWSER_BLOCKED = "blocked"
BROWSER_TIMEOUT = "timeout"
BROWSER_UNAVAILABLE = "unavailable"
BROWSER_ERROR = "error"


class BrowserUnavailable(Exception):
    """Playwright / a browser binary is not installed → unavailable."""


class BrowserTimeout(Exception):
    """The navigation exceeded its time budget → timeout."""


class BrowserError(Exception):
    """The backend failed to render a valid URL → error."""


@dataclass(frozen=True)
class RenderedPage:
    final_url: str
    status: int | None = None
    title: str = ""
    text: str = ""
    links: list[str] = field(default_factory=list)
    html: str = ""


class BrowserBackend(Protocol):
    name: str

    def available(self) -> bool:
        """True iff a browser can be launched (package + binary present)."""
        ...

    def open(self, url: str, *, timeout: float, wait_until: str) -> RenderedPage:
        """Render `url`. Raise BrowserUnavailable/BrowserTimeout/BrowserError."""
        ...

    def screenshot(
        self, url: str, out_path: str, *, timeout: float, full_page: bool
    ) -> None:
        """Render `url` and write a PNG to `out_path`. Raise as above."""
        ...


class PlaywrightBackend:
    """Default backend: Chromium via Playwright. All imports are lazy."""

    name = "playwright"

    def __init__(self, *, headless: bool = True, browser: str = "chromium") -> None:
        self._headless = headless
        self._browser = browser

    def available(self) -> bool:
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except Exception:  # noqa: BLE001 - package missing
            return False
        return True

    def _launch(self):
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # noqa: BLE001 - package missing
            raise BrowserUnavailable(f"playwright not installed: {exc}") from exc
        try:
            pw = sync_playwright().start()
            launcher = getattr(pw, self._browser)
            browser = launcher.launch(headless=self._headless)
        except Exception as exc:  # noqa: BLE001 - no browser binary / launch failure
            raise BrowserUnavailable(
                f"cannot launch {self._browser} (is a browser installed?): {exc}"
            ) from exc
        return pw, browser

    def _goto(self, page, url: str, timeout: float, wait_until: str):
        from playwright.sync_api import TimeoutError as PWTimeout

        try:
            return page.goto(url, timeout=timeout * 1000, wait_until=wait_until)
        except PWTimeout as exc:
            raise BrowserTimeout(f"navigation timed out after {timeout}s") from exc

    def open(self, url: str, *, timeout: float, wait_until: str) -> RenderedPage:
        pw, browser = self._launch()
        try:
            page = browser.new_page()
            resp = self._goto(page, url, timeout, wait_until)
            title = page.title() or ""
            try:
                text = page.inner_text("body")
            except Exception:  # noqa: BLE001 - body may be absent
                text = ""
            try:
                html = page.content() or ""
            except Exception:  # noqa: BLE001
                html = ""
            links = page.eval_on_selector_all(
                "a[href]", "els => els.map(e => e.href)"
            )
            return RenderedPage(
                final_url=page.url,
                status=int(resp.status) if resp is not None else None,
                title=title,
                text=text or "",
                links=[h for h in (links or []) if isinstance(h, str)],
                html=html,
            )
        except (BrowserTimeout, BrowserUnavailable):
            raise
        except Exception as exc:  # noqa: BLE001 - render failure
            raise BrowserError(str(exc)) from exc
        finally:
            self._close(pw, browser)

    def screenshot(
        self, url: str, out_path: str, *, timeout: float, full_page: bool
    ) -> None:
        pw, browser = self._launch()
        try:
            page = browser.new_page()
            self._goto(page, url, timeout, "load")
            page.screenshot(path=out_path, full_page=full_page)
        except (BrowserTimeout, BrowserUnavailable):
            raise
        except Exception as exc:  # noqa: BLE001 - render failure
            raise BrowserError(str(exc)) from exc
        finally:
            self._close(pw, browser)

    @staticmethod
    def _close(pw, browser) -> None:
        try:
            browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            pw.stop()
        except Exception:  # noqa: BLE001
            pass


class BrowserClient:
    def __init__(
        self,
        backend: BrowserBackend,
        root: Path | str,
        *,
        is_allowed: Callable[[str], bool] | None = None,
        timeout: float = 30.0,
        wait_until: str = "load",
        max_text_chars: int = 20_000,
        max_links: int = 100,
        logger: logging.Logger | None = None,
    ) -> None:
        self._backend = backend
        self._root = Path(root).resolve()
        self._is_allowed = is_allowed
        self._timeout = timeout
        self._wait_until = wait_until
        self._max_text_chars = max_text_chars
        self._max_links = max_links
        self._logger = logger or logging.getLogger("atlas.browser")

    def open(self, url: str, *, timeout: float | None = None) -> dict[str, Any]:
        base = {"url": url, "backend": self._backend.name}
        precheck = self._precheck(url, base)
        if precheck is not None:
            return precheck
        try:
            page = self._backend.open(
                url, timeout=timeout or self._timeout, wait_until=self._wait_until
            )
        except BrowserUnavailable as exc:
            return {**base, "outcome": BROWSER_UNAVAILABLE, "reason": str(exc)}
        except BrowserTimeout as exc:
            return {**base, "outcome": BROWSER_TIMEOUT, "reason": str(exc)}
        except BrowserError as exc:
            return {**base, "outcome": BROWSER_ERROR, "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001 - a bad backend must not crash the caller
            self._logger.exception("browser backend crashed")
            return {**base, "outcome": BROWSER_ERROR, "reason": str(exc)}
        text = (page.text or "").strip()[: self._max_text_chars]
        # Cap HTML retained for captionTracks extraction (BA.1); keep modest.
        html = (page.html or "")[: max(self._max_text_chars * 20, 200_000)]
        return {
            **base,
            "outcome": BROWSER_OK if (text or html) else BROWSER_EMPTY,
            "final_url": page.final_url,
            "status": page.status,
            "title": page.title,
            "text": text,
            "html": html,
            "chars": len(text),
            "links": page.links[: self._max_links],
        }

    def screenshot(
        self, url: str, path: str, *, timeout: float | None = None, full_page: bool = True
    ) -> dict[str, Any]:
        base = {"url": url, "backend": self._backend.name}
        precheck = self._precheck(url, base)
        if precheck is not None:
            return precheck
        try:
            target = self._resolve(path)
        except ValueError as exc:
            return {**base, "outcome": BROWSER_ERROR, "reason": str(exc)}
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            self._backend.screenshot(
                url, str(target), timeout=timeout or self._timeout, full_page=full_page
            )
        except BrowserUnavailable as exc:
            return {**base, "outcome": BROWSER_UNAVAILABLE, "reason": str(exc)}
        except BrowserTimeout as exc:
            return {**base, "outcome": BROWSER_TIMEOUT, "reason": str(exc)}
        except BrowserError as exc:
            return {**base, "outcome": BROWSER_ERROR, "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001
            self._logger.exception("browser screenshot crashed")
            return {**base, "outcome": BROWSER_ERROR, "reason": str(exc)}
        return {**base, "outcome": BROWSER_OK, "path": str(target)}

    def _precheck(self, url: str, base: dict[str, Any]) -> dict[str, Any] | None:
        parsed = urlparse(url or "")
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return {**base, "outcome": BROWSER_ERROR, "reason": "only http(s) URLs allowed"}
        if self._is_allowed is not None and not self._is_allowed(url):
            return {**base, "outcome": BROWSER_BLOCKED,
                    "reason": "robots.txt disallows this URL"}
        return None

    def _resolve(self, path: str) -> Path:
        candidate = (self._root / path).resolve()
        if candidate != self._root and not candidate.is_relative_to(self._root):
            raise ValueError(f"path escapes browser sandbox root: {path}")
        return candidate
