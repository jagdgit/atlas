"""Tests for the resilient net layer (FetchClient, S13 / D10).

Hermetic: transport, sleep, clock, and jitter are injected — no real I/O or waits.
"""

from __future__ import annotations

from atlas.net import (
    OUTCOME_BLOCKED,
    OUTCOME_OK,
    OUTCOME_SKIPPED,
    FetchClient,
)


class Resp:
    def __init__(self, status=200, content=b"body", content_type="text/plain",
                 url="https://example.com", retry_after=None):
        self.status_code = status
        self.content = content
        self.encoding = "utf-8"
        self.url = url
        self.headers = {"content-type": content_type}
        if retry_after is not None:
            self.headers["retry-after"] = str(retry_after)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _client(responses, *, robots=None, **kw):
    """responses: callable(url)->Resp OR list (popped in order)."""
    calls = {"n": 0}

    def http_get(url, headers):
        calls["n"] += 1
        if url.endswith("/robots.txt"):
            return robots if robots is not None else Resp(status=404, content=b"")
        if callable(responses):
            return responses(url)
        return responses.pop(0)

    sleeps: list[float] = []
    kw.setdefault("respect_robots", robots is not None)
    kw.setdefault("per_domain_delay", 0.0)
    kw.setdefault("rand", lambda: 0.0)
    client = FetchClient(
        http_get=http_get,
        sleep=lambda s: sleeps.append(s),
        **kw,
    )
    return client, calls, sleeps


def test_ok_returns_text_and_caches():
    clock = Clock()
    client, calls, _ = _client(lambda u: Resp(content=b"hello"),
                               cache_ttl=300.0, monotonic=clock)
    r1 = client.get("https://example.com")
    assert r1.outcome == OUTCOME_OK
    assert r1.text == "hello"
    assert r1.from_cache is False
    # second call served from cache (no extra transport call)
    before = calls["n"]
    r2 = client.get("https://example.com")
    assert r2.from_cache is True
    assert calls["n"] == before


def test_rejects_non_http():
    client, _, _ = _client(lambda u: Resp())
    assert client.get("ftp://x/y").outcome == "error"


def test_blocked_on_401_403():
    for status in (401, 403):
        client, _, _ = _client(lambda u, s=status: Resp(status=s, content=b""))
        r = client.get("https://example.com")
        assert r.outcome == OUTCOME_BLOCKED
        assert r.status_code == status


def test_skipped_on_404():
    client, _, _ = _client(lambda u: Resp(status=404, content=b""))
    r = client.get("https://example.com")
    assert r.outcome == OUTCOME_SKIPPED
    assert r.status_code == 404


def test_retry_on_503_then_success():
    responses = [Resp(status=503, content=b""), Resp(status=200, content=b"ok")]
    client, calls, sleeps = _client(responses, max_retries=3)
    r = client.get("https://example.com")
    assert r.outcome == OUTCOME_OK
    assert r.attempts == 2
    assert len(sleeps) == 1  # backed off once


def test_retries_exhausted_becomes_skipped():
    client, calls, sleeps = _client(lambda u: Resp(status=503, content=b""),
                                    max_retries=2)
    r = client.get("https://example.com")
    assert r.outcome == OUTCOME_SKIPPED
    assert r.attempts == 3  # initial + 2 retries
    assert "retries exhausted" in r.reason


def test_retry_after_header_used_for_backoff():
    responses = [Resp(status=429, content=b"", retry_after=7),
                 Resp(status=200, content=b"ok")]
    client, _, sleeps = _client(responses, max_retries=2, backoff_base=1.0)
    client.get("https://example.com")
    assert sleeps == [7.0]  # honoured Retry-After, not the computed backoff


def test_transport_error_retried_then_skipped():
    def boom(url):
        raise RuntimeError("connection reset")

    client, _, sleeps = _client(boom, max_retries=1)
    r = client.get("https://example.com")
    assert r.outcome == OUTCOME_SKIPPED
    assert "transport error" in r.reason
    assert len(sleeps) == 1


def test_robots_disallow_skips():
    robots = Resp(status=200, content=b"User-agent: *\nDisallow: /secret")
    client, calls, _ = _client(lambda u: Resp(content=b"secret page"), robots=robots)
    r = client.get("https://example.com/secret/page")
    assert r.outcome == OUTCOME_SKIPPED
    assert "robots" in r.reason


def test_robots_allow_fetches():
    robots = Resp(status=200, content=b"User-agent: *\nDisallow: /private")
    client, _, _ = _client(lambda u: Resp(content=b"public"), robots=robots)
    r = client.get("https://example.com/public/page")
    assert r.outcome == OUTCOME_OK


def test_per_domain_throttle_sleeps_between_requests():
    clock = Clock()
    client, _, sleeps = _client(lambda u: Resp(content=b"x"),
                                per_domain_delay=5.0, cache_ttl=0.0,
                                monotonic=clock)
    client.get("https://example.com/a")
    client.get("https://example.com/b")  # same domain, clock not advanced
    assert sleeps and sleeps[-1] == 5.0
