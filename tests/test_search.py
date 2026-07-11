"""Tests for web search (S13b, D5): DuckDuckGo provider + SearchPlugin.

Hermetic — no network. The provider's FetchClient uses a canned URL→response map.
"""

from __future__ import annotations

from urllib.parse import quote_plus

import pytest

from atlas.net import FetchClient
from atlas.plugins.search_plugin import SearchPlugin
from atlas.search.providers import DuckDuckGoProvider, SearchHit, SearchResponse

_HTML = """
<html><body>
  <div class="result">
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&rut=x">First result</a>
    <a class="result__snippet">Snippet one about soiling.</a>
  </div>
  <div class="result">
    <a class="result__a" href="https://direct.example.org/b">Second result</a>
    <a class="result__snippet">Snippet two.</a>
  </div>
</body></html>
"""


class _FakeResp:
    def __init__(self, content, status=200, url="https://html.duckduckgo.com/html/"):
        self.content = content
        self.headers = {"content-type": "text/html; charset=utf-8"}
        self.status_code = status
        self.url = url
        self.encoding = "utf-8"


def _client(resp_map):
    def http_get(url, headers):
        return resp_map[url]

    return FetchClient(
        http_get=http_get,
        respect_robots=False,
        per_domain_delay=0.0,
        cache_ttl=0.0,
        sleep=lambda _s: None,
    )


def _ddg(html, *, endpoint="https://html.duckduckgo.com/html/"):
    url = f"{endpoint}?q={quote_plus('solar soiling')}"
    client = _client({url: _FakeResp(html.encode("utf-8"))})
    return DuckDuckGoProvider(client, endpoint=endpoint)


# --- DuckDuckGoProvider ---------------------------------------------------
def test_ddg_parses_and_unwraps_redirect_urls():
    resp = _ddg(_HTML).search("solar soiling")
    assert resp.ok and resp.provider == "duckduckgo"
    assert len(resp.hits) == 2
    assert resp.hits[0].title == "First result"
    # uddg redirect target is unwrapped to the real URL
    assert resp.hits[0].url == "https://example.com/a"
    assert resp.hits[0].snippet == "Snippet one about soiling."
    assert resp.hits[1].url == "https://direct.example.org/b"


def test_ddg_respects_max_results():
    resp = _ddg(_HTML).search("solar soiling", max_results=1)
    assert len(resp.hits) == 1


def test_ddg_empty_query_is_ok_with_no_hits():
    resp = _ddg(_HTML).search("   ")
    assert resp.ok and resp.hits == []


def test_ddg_propagates_blocked_outcome():
    endpoint = "https://html.duckduckgo.com/html/"
    url = f"{endpoint}?q={quote_plus('x')}"
    client = _client({url: _FakeResp(b"", status=403)})
    resp = DuckDuckGoProvider(client, endpoint=endpoint).search("x")
    assert not resp.ok
    assert resp.outcome == "blocked"
    assert resp.hits == []


# --- SearchPlugin (provider fallback, D5) ---------------------------------
class _StubProvider:
    def __init__(self, name, response):
        self.name = name
        self._response = response
        self.calls = 0

    def search(self, query, *, max_results=5):
        self.calls += 1
        return self._response


def _resp(provider, outcome, hits=()):
    return SearchResponse("q", provider, outcome, hits=list(hits))


def test_plugin_returns_first_provider_with_results():
    good = _StubProvider("a", _resp("a", "ok", [SearchHit("t", "https://x")]))
    other = _StubProvider("b", _resp("b", "ok", [SearchHit("t2", "https://y")]))
    plugin = SearchPlugin([good, other])
    resp = plugin.search_web("q")
    assert resp.provider == "a"
    assert other.calls == 0  # short-circuits once results found


def test_plugin_falls_back_when_provider_blocked():
    blocked = _StubProvider("a", _resp("a", "blocked"))
    good = _StubProvider("b", _resp("b", "ok", [SearchHit("t", "https://x")]))
    plugin = SearchPlugin([blocked, good])
    resp = plugin.search_web("q")
    assert resp.provider == "b" and resp.ok
    assert blocked.calls == 1 and good.calls == 1


def test_plugin_returns_last_outcome_when_all_fail():
    a = _StubProvider("a", _resp("a", "blocked"))
    b = _StubProvider("b", _resp("b", "skipped"))
    plugin = SearchPlugin([a, b])
    resp = plugin.search_web("q")
    assert not resp.ok
    assert resp.outcome == "skipped"


def test_plugin_survives_a_raising_provider():
    class _Boom:
        name = "boom"

        def search(self, query, *, max_results=5):
            raise RuntimeError("nope")

    good = _StubProvider("b", _resp("b", "ok", [SearchHit("t", "https://x")]))
    plugin = SearchPlugin([_Boom(), good])
    resp = plugin.search_web("q")
    assert resp.ok and resp.provider == "b"


def test_plugin_no_providers_reports_error():
    plugin = SearchPlugin([])
    resp = plugin.search_web("q")
    assert resp.outcome == "error"
    assert plugin.health_check().healthy is False


def test_web_search_tool_returns_plain_dict():
    good = _StubProvider("a", _resp("a", "ok", [SearchHit("t", "https://x", "s")]))
    plugin = SearchPlugin([good])
    data = plugin.web_search("q", max_results=3)
    assert data["outcome"] == "ok"
    assert data["results"][0] == {"title": "t", "url": "https://x", "snippet": "s"}
