"""Resilient, polite HTTP fetch client (D10 / §5c).

`FetchClient.get(url)` returns a `FetchResult` and *never* raises for network or
HTTP conditions — it classifies them:

- ``ok``       — 2xx; body returned (capped), response cached.
- ``blocked``  — 401/403; needs credentials/login (maps to a **blocked** step, R3).
- ``skipped``  — 404/other 4xx, robots-disallowed, or retries exhausted; the source
                 is unavailable, so skip it and keep the job going (R3), record the
                 gap (R2).
- ``error``    — bad scheme / unexpected local failure.

Politeness: per-domain minimum interval (honours `robots.txt` `crawl-delay`),
`robots.txt` allow/deny for the User-Agent, bounded exponential backoff with jitter
on 429/503/5xx (honours `Retry-After`), and an in-memory response cache with TTL.

Testable by construction: the transport (`http_get`), `sleep`, `monotonic`, and
`rand` are injectable, so tests exercise throttle/backoff/robots without real I/O
or wall-clock waits.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

OUTCOME_OK = "ok"
OUTCOME_BLOCKED = "blocked"
OUTCOME_SKIPPED = "skipped"
OUTCOME_ERROR = "error"

# Minimal duck type for an injected transport response.
HttpGet = Callable[[str, dict[str, str]], Any]


@dataclass(frozen=True)
class FetchResult:
    url: str
    outcome: str
    final_url: str = ""
    status_code: int | None = None
    text: str = ""
    content: bytes = b""
    content_type: str = ""
    from_cache: bool = False
    attempts: int = 0
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == OUTCOME_OK

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "outcome": self.outcome,
            "final_url": self.final_url,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "from_cache": self.from_cache,
            "attempts": self.attempts,
            "reason": self.reason,
            "chars": len(self.text),
        }


@dataclass
class _CacheEntry:
    result: FetchResult
    at: float


class FetchClient:
    def __init__(
        self,
        *,
        http_get: HttpGet | None = None,
        user_agent: str = "Atlas/0.1 (+https://localhost)",
        timeout: float = 15.0,
        max_bytes: int = 2_097_152,
        per_domain_delay: float = 1.0,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        backoff_cap: float = 30.0,
        jitter: float = 0.25,
        respect_robots: bool = True,
        cache_ttl: float = 300.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        rand: Callable[[], float] = random.random,
        logger: logging.Logger | None = None,
    ) -> None:
        self._http_get = http_get or self._default_http_get
        self._ua = user_agent
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._per_domain_delay = per_domain_delay
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._jitter = jitter
        self._respect_robots = respect_robots
        self._cache_ttl = cache_ttl
        self._sleep = sleep
        self._monotonic = monotonic
        self._rand = rand
        self._logger = logger or logging.getLogger("atlas.net")

        self._lock = threading.Lock()
        self._last_request: dict[str, float] = {}      # domain -> monotonic ts
        self._cache: dict[str, _CacheEntry] = {}
        self._robots: dict[str, tuple[RobotFileParser | None, float | None]] = {}

    # --- default transport (httpx) -------------------------------------
    def _default_http_get(self, url: str, headers: dict[str, str]) -> Any:
        import httpx

        with httpx.Client(
            timeout=self._timeout, follow_redirects=True, headers=headers
        ) as client:
            return client.get(url)

    # --- public --------------------------------------------------------
    def allowed(self, url: str) -> bool:
        """Whether ``robots.txt`` permits fetching ``url`` for our User-Agent.

        Permissive when robots respect is disabled or robots is unavailable (the same
        convention as :meth:`get`). Lets non-HTTP clients (e.g. the browser) reuse the
        one robots policy without duplicating it.
        """
        if not self._respect_robots:
            return True
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False
        allowed, _ = self._robots_allows(parsed)
        return allowed

    def get(self, url: str, *, use_cache: bool = True) -> FetchResult:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return FetchResult(url, OUTCOME_ERROR, reason="only http(s) URLs allowed")

        domain = parsed.netloc

        if use_cache:
            cached = self._cache_get(url)
            if cached is not None:
                return cached

        if self._respect_robots:
            allowed, crawl_delay = self._robots_allows(parsed)
            if not allowed:
                self._logger.info("robots.txt disallows %s", url)
                return FetchResult(
                    url, OUTCOME_SKIPPED, reason="robots.txt disallows this URL"
                )
        else:
            crawl_delay = None

        self._throttle(domain, crawl_delay)
        result = self._request_with_retries(url)
        if result.ok and use_cache:
            self._cache_put(url, result)
        return result

    # --- request + retry ------------------------------------------------
    def _request_with_retries(self, url: str) -> FetchResult:
        headers = {"User-Agent": self._ua}
        last_reason = "unknown error"
        for attempt in range(self._max_retries + 1):
            domain = urlparse(url).netloc
            try:
                resp = self._http_get(url, headers)
            except Exception as exc:  # noqa: BLE001 - transport failures are retryable
                last_reason = f"transport error: {type(exc).__name__}: {exc}"
                self._mark_request(domain)
                if attempt < self._max_retries:
                    self._sleep(self._backoff(attempt))
                    continue
                return FetchResult(url, OUTCOME_SKIPPED, attempts=attempt + 1,
                                   reason=last_reason)
            self._mark_request(domain)

            status = int(getattr(resp, "status_code", 0))
            if status in (401, 403):
                return FetchResult(
                    url, OUTCOME_BLOCKED, status_code=status, attempts=attempt + 1,
                    reason=f"HTTP {status}: authentication/login required",
                )
            if status == 429 or status >= 500:
                last_reason = f"HTTP {status}"
                if attempt < self._max_retries:
                    self._sleep(self._retry_after(resp) or self._backoff(attempt))
                    continue
                return FetchResult(url, OUTCOME_SKIPPED, status_code=status,
                                   attempts=attempt + 1,
                                   reason=f"{last_reason}: retries exhausted")
            if 400 <= status < 500:
                return FetchResult(url, OUTCOME_SKIPPED, status_code=status,
                                   attempts=attempt + 1, reason=f"HTTP {status}")
            # success (2xx / redirected 3xx already followed by transport)
            return self._build_ok(url, resp, attempt + 1)
        return FetchResult(url, OUTCOME_SKIPPED, reason=last_reason)

    def _build_ok(self, url: str, resp: Any, attempts: int) -> FetchResult:
        content = bytes(getattr(resp, "content", b"") or b"")[: self._max_bytes]
        content_type = ""
        headers = getattr(resp, "headers", {}) or {}
        try:
            content_type = headers.get("content-type", "")
        except AttributeError:
            content_type = ""
        encoding = getattr(resp, "encoding", None) or "utf-8"
        text = content.decode(encoding, errors="replace")
        final_url = str(getattr(resp, "url", url))
        return FetchResult(
            url, OUTCOME_OK, final_url=final_url,
            status_code=int(getattr(resp, "status_code", 200)),
            text=text, content=content, content_type=content_type, attempts=attempts,
        )

    # --- politeness helpers --------------------------------------------
    def _backoff(self, attempt: int) -> float:
        delay = min(self._backoff_base * (2**attempt), self._backoff_cap)
        return delay + self._rand() * self._jitter

    @staticmethod
    def _retry_after(resp: Any) -> float | None:
        headers = getattr(resp, "headers", {}) or {}
        try:
            value = headers.get("retry-after")
        except AttributeError:
            return None
        if value is None:
            return None
        try:
            return float(int(value))
        except (ValueError, TypeError):
            return None

    def _throttle(self, domain: str, crawl_delay: float | None) -> None:
        min_interval = max(self._per_domain_delay, crawl_delay or 0.0)
        if min_interval <= 0:
            return
        with self._lock:
            last = self._last_request.get(domain)
            now = self._monotonic()
            wait = 0.0 if last is None else (last + min_interval) - now
        if wait > 0:
            self._sleep(wait)

    def _mark_request(self, domain: str) -> None:
        with self._lock:
            self._last_request[domain] = self._monotonic()

    # --- robots ---------------------------------------------------------
    def _robots_allows(self, parsed: Any) -> tuple[bool, float | None]:
        base = f"{parsed.scheme}://{parsed.netloc}"
        rp = self._robots_for(base)
        if rp is None:
            return True, None  # unavailable robots => permissive (common practice)
        url = parsed.geturl()
        allowed = rp.can_fetch(self._ua, url)
        try:
            delay = rp.crawl_delay(self._ua)
        except Exception:  # noqa: BLE001 - crawl_delay can raise on odd robots
            delay = None
        return allowed, (float(delay) if delay else None)

    def _robots_for(self, base: str) -> RobotFileParser | None:
        with self._lock:
            entry = self._robots.get(base)
            now = self._monotonic()
            if entry is not None and (entry[1] is None or now < entry[1]):
                return entry[0]
        rp = self._fetch_robots(base)
        with self._lock:
            self._robots[base] = (rp, self._monotonic() + max(self._cache_ttl, 60.0))
        return rp

    def _fetch_robots(self, base: str) -> RobotFileParser | None:
        try:
            resp = self._http_get(f"{base}/robots.txt", {"User-Agent": self._ua})
        except Exception:  # noqa: BLE001 - no robots => permissive
            return None
        status = int(getattr(resp, "status_code", 0))
        if status != 200:
            return None
        body = bytes(getattr(resp, "content", b"") or b"")
        rp = RobotFileParser()
        rp.parse(body.decode("utf-8", errors="replace").splitlines())
        return rp

    # --- cache ----------------------------------------------------------
    def _cache_get(self, url: str) -> FetchResult | None:
        if self._cache_ttl <= 0:
            return None
        with self._lock:
            entry = self._cache.get(url)
            if entry is None:
                return None
            if self._monotonic() - entry.at > self._cache_ttl:
                self._cache.pop(url, None)
                return None
            r = entry.result
        return FetchResult(
            r.url, r.outcome, final_url=r.final_url, status_code=r.status_code,
            text=r.text, content=r.content, content_type=r.content_type,
            from_cache=True, attempts=r.attempts, reason=r.reason,
        )

    def _cache_put(self, url: str, result: FetchResult) -> None:
        if self._cache_ttl <= 0:
            return
        with self._lock:
            self._cache[url] = _CacheEntry(result=result, at=self._monotonic())
