"""Tests for the plugin system (Sprint 7): manager, filesystem, web.

Hermetic — no network. The web plugin's HTTP client is monkeypatched.
"""

from __future__ import annotations

import pytest

from atlas.config import get_config
from atlas.exceptions import PluginError
from atlas.kernel.capabilities import CapabilityRegistry
from atlas.kernel.tools import ToolRegistry
from atlas.plugins.base import BasePlugin
from atlas.plugins.filesystem_plugin import FilesystemPlugin
from atlas.plugins.manager import PluginManager
from atlas.plugins.web_plugin import WebPlugin


class FakeKernel:
    def __init__(self):
        self.capabilities = CapabilityRegistry()
        self.tools = ToolRegistry()


def _config(enabled):
    cfg = get_config().model_copy(deep=True)
    cfg.plugins.enabled = list(enabled)
    return cfg


# --- PluginManager --------------------------------------------------------
def test_manager_loads_builtin_plugins():
    cfg = _config(["atlas.plugins.filesystem_plugin", "atlas.plugins.web_plugin"])
    mgr = PluginManager()
    mgr.load(cfg)
    assert mgr.names() == ["filesystem", "web"]
    assert mgr.errors == {}


def test_manager_records_bad_module_without_raising():
    cfg = _config(["atlas.plugins.does_not_exist"])
    mgr = PluginManager()
    mgr.load(cfg)  # must not raise
    assert mgr.names() == []
    assert "atlas.plugins.does_not_exist" in mgr.errors
    assert mgr.health_check().healthy is False


def test_manager_register_all_advertises_capabilities_and_tools():
    cfg = _config(["atlas.plugins.filesystem_plugin", "atlas.plugins.web_plugin"])
    mgr = PluginManager()
    mgr.load(cfg)
    kernel = FakeKernel()
    mgr.register_all(kernel)
    assert kernel.capabilities.has("filesystem")
    assert kernel.capabilities.has("web")
    assert "fs.read" in kernel.tools.names()
    assert "web.fetch" in kernel.tools.names()


def test_manager_lifecycle_captures_plugin_start_errors():
    class BoomPlugin(BasePlugin):
        name = "boom"

        def start(self):
            raise RuntimeError("nope")

    mgr = PluginManager([BoomPlugin()])
    mgr.start()  # must not raise
    assert "boom" in mgr.errors
    mgr.stop()  # must not raise


# --- FilesystemPlugin -----------------------------------------------------
def test_filesystem_list_and_read(tmp_path):
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    plugin = FilesystemPlugin(tmp_path)

    entries = plugin.list_dir(".")
    names = {e["path"] for e in entries}
    assert "a.txt" in names and "sub" in names
    assert plugin.read_file("a.txt") == "hello"


def test_filesystem_blocks_escape(tmp_path):
    plugin = FilesystemPlugin(tmp_path)
    with pytest.raises(PluginError):
        plugin.read_file("../../etc/passwd")


def test_filesystem_enforces_size_cap(tmp_path):
    (tmp_path / "big.txt").write_text("x" * 100, encoding="utf-8")
    plugin = FilesystemPlugin(tmp_path, max_bytes=10)
    with pytest.raises(PluginError):
        plugin.read_file("big.txt")


# --- WebPlugin (now over the resilient net layer, S13) --------------------
class _FakeResp:
    def __init__(self, content, headers, status=200, url="https://example.com"):
        self.content = content
        self.headers = headers
        self.status_code = status
        self.url = url
        self.encoding = "utf-8"


def _web_plugin(resp_map, *, respect_robots=False):
    """Build a WebPlugin whose FetchClient uses a canned URL→response map."""
    from atlas.net import FetchClient

    def http_get(url, headers):
        return resp_map[url]

    client = FetchClient(
        http_get=http_get,
        respect_robots=respect_robots,
        per_domain_delay=0.0,
        cache_ttl=0.0,
        sleep=lambda _s: None,
    )
    return WebPlugin(client)


def test_web_fetch_extracts_html_text():
    resp = _FakeResp(
        b"<html><body><h1>Hi</h1><script>evil()</script></body></html>",
        {"content-type": "text/html; charset=utf-8"},
    )
    plugin = _web_plugin({"https://example.com": resp})
    result = plugin.fetch("https://example.com")
    assert result["status"] == 200
    assert "Hi" in result["text"]
    assert "evil" not in result["text"]  # script stripped
    assert result["outcome"] == "ok"


def test_web_fetch_passes_through_plain_text():
    resp = _FakeResp(b"just text", {"content-type": "text/plain"})
    plugin = _web_plugin({"https://example.com": resp})
    assert plugin.fetch("https://example.com")["text"] == "just text"


def test_web_fetch_rejects_non_http():
    plugin = _web_plugin({})
    with pytest.raises(PluginError):
        plugin.fetch("ftp://example.com/file")


def test_web_fetch_blocked_raises_plugin_error():
    resp = _FakeResp(b"", {"content-type": "text/html"}, status=403)
    plugin = _web_plugin({"https://example.com": resp})
    with pytest.raises(PluginError) as exc:
        plugin.fetch("https://example.com")
    assert "blocked" in str(exc.value)
