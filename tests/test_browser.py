"""Tests for the read-only browser capability (S20e).

The client + outcome mapping + sandbox + robots gate are hermetic via an injectable
fake backend. The default `PlaywrightBackend` is exercised only for its offline
behaviour — it must report `unavailable` (never raise) when Playwright/a browser binary
is absent.
"""

from __future__ import annotations

from atlas.browser.browser import (
    BROWSER_BLOCKED,
    BROWSER_EMPTY,
    BROWSER_ERROR,
    BROWSER_OK,
    BROWSER_TIMEOUT,
    BROWSER_UNAVAILABLE,
    BrowserClient,
    BrowserError,
    BrowserTimeout,
    BrowserUnavailable,
    PlaywrightBackend,
    RenderedPage,
)
from atlas.plugins.browser_plugin import BrowserPlugin


class FakeBackend:
    name = "fake"

    def __init__(self, *, page=None, exc=None, available=True):
        self._page = page or RenderedPage(
            final_url="https://ex.com/", status=200, title="Example",
            text="Hello rendered world", links=["https://ex.com/a", "https://ex.com/b"],
        )
        self._exc = exc
        self._available = available
        self.screenshot_calls: list[tuple[str, str]] = []

    def available(self):
        return self._available

    def open(self, url, *, timeout, wait_until):
        if self._exc:
            raise self._exc
        return self._page

    def screenshot(self, url, out_path, *, timeout, full_page):
        if self._exc:
            raise self._exc
        self.screenshot_calls.append((url, out_path))


URL = "https://ex.com/page"


# --- open outcome mapping ------------------------------------------------
def test_open_ok(tmp_path):
    res = BrowserClient(FakeBackend(), tmp_path).open(URL)
    assert res["outcome"] == BROWSER_OK
    assert res["title"] == "Example"
    assert "rendered" in res["text"]
    assert res["links"] == ["https://ex.com/a", "https://ex.com/b"]
    assert res["backend"] == "fake"


def test_open_empty_when_no_text(tmp_path):
    page = RenderedPage(final_url=URL, status=200, title="T", text="   ", links=[])
    res = BrowserClient(FakeBackend(page=page), tmp_path).open(URL)
    assert res["outcome"] == BROWSER_EMPTY


def test_open_rejects_non_http(tmp_path):
    res = BrowserClient(FakeBackend(), tmp_path).open("file:///etc/passwd")
    assert res["outcome"] == BROWSER_ERROR
    assert "http" in res["reason"]


def test_open_robots_blocked(tmp_path):
    client = BrowserClient(FakeBackend(), tmp_path, is_allowed=lambda u: False)
    res = client.open(URL)
    assert res["outcome"] == BROWSER_BLOCKED


def test_open_robots_allowed(tmp_path):
    client = BrowserClient(FakeBackend(), tmp_path, is_allowed=lambda u: True)
    assert client.open(URL)["outcome"] == BROWSER_OK


def test_open_unavailable(tmp_path):
    res = BrowserClient(FakeBackend(exc=BrowserUnavailable("no playwright")), tmp_path).open(URL)
    assert res["outcome"] == BROWSER_UNAVAILABLE


def test_open_timeout(tmp_path):
    res = BrowserClient(FakeBackend(exc=BrowserTimeout("slow")), tmp_path).open(URL)
    assert res["outcome"] == BROWSER_TIMEOUT


def test_open_error(tmp_path):
    res = BrowserClient(FakeBackend(exc=BrowserError("boom")), tmp_path).open(URL)
    assert res["outcome"] == BROWSER_ERROR


def test_open_never_raises_on_unexpected(tmp_path):
    res = BrowserClient(FakeBackend(exc=RuntimeError("kaboom")), tmp_path).open(URL)
    assert res["outcome"] == BROWSER_ERROR
    assert "kaboom" in res["reason"]


def test_open_truncates_text_and_links(tmp_path):
    page = RenderedPage(
        final_url=URL, status=200, title="T",
        text="x" * 5000, links=[f"https://ex.com/{i}" for i in range(50)],
    )
    res = BrowserClient(
        FakeBackend(page=page), tmp_path, max_text_chars=100, max_links=5
    ).open(URL)
    assert res["chars"] == 100
    assert len(res["links"]) == 5


# --- screenshot ----------------------------------------------------------
def test_screenshot_ok(tmp_path):
    backend = FakeBackend()
    res = BrowserClient(backend, tmp_path).screenshot(URL, "shots/page.png")
    assert res["outcome"] == BROWSER_OK
    assert res["path"].endswith("shots/page.png")
    assert backend.screenshot_calls and backend.screenshot_calls[0][0] == URL


def test_screenshot_escape_is_error(tmp_path):
    res = BrowserClient(FakeBackend(), tmp_path).screenshot(URL, "../evil.png")
    assert res["outcome"] == BROWSER_ERROR
    assert "escapes" in res["reason"]


def test_screenshot_unavailable(tmp_path):
    res = BrowserClient(FakeBackend(exc=BrowserUnavailable("no pw")), tmp_path).screenshot(
        URL, "s.png"
    )
    assert res["outcome"] == BROWSER_UNAVAILABLE


# --- default backend: honest offline behaviour ---------------------------
def test_playwright_backend_offline_is_unavailable(tmp_path):
    backend = PlaywrightBackend()
    if backend.available():
        return  # playwright present in this env; nothing to assert offline
    # Missing package/binary → client must return `unavailable`, not raise.
    assert BrowserClient(backend, tmp_path).open(URL)["outcome"] == BROWSER_UNAVAILABLE


# --- plugin wiring -------------------------------------------------------
def test_plugin_delegates_and_health(tmp_path):
    plugin = BrowserPlugin(BrowserClient(FakeBackend(available=False), tmp_path))
    assert plugin.open(URL)["outcome"] == BROWSER_OK
    health = plugin.health_check()
    assert health.healthy is True  # missing engine = degraded, not failed
    assert health.data["available"] is False


class _Kernel:
    def __init__(self) -> None:
        caps: dict = {}
        tools: dict = {}
        self.caps = caps
        self.tool_map = tools

        class _Caps:
            def register(self, name, provider, *, contract=None, kind=None):
                caps[name] = provider

        class _Tools:
            def register(self, name, fn, *, description="", params=None, plugin=None):
                tools[name] = fn

        self.capabilities = _Caps()
        self.tools = _Tools()


def test_plugin_registers_capability_and_tools(tmp_path):
    plugin = BrowserPlugin(BrowserClient(FakeBackend(), tmp_path))
    kernel = _Kernel()
    plugin.register(kernel)
    assert "browser" in kernel.caps
    assert {"browser.open", "browser.screenshot"} <= set(kernel.tool_map)
