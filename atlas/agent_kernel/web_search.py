"""Level-3 web search adapter.

Calls the existing SearchPlugin / SearchProvider. It does not open a second
search stack, and it does not turn snippets into prices or fundamentals.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

POLICY_DISABLED = "POLICY_DISABLED"
CLIENT_NOT_CONFIGURED = "CLIENT_NOT_CONFIGURED"
PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
SEARCH_ERROR = "SEARCH_ERROR"
NO_RESULTS = "NO_RESULTS"
SUCCESS = "SUCCESS"

# Snippets are not a number. These requirements stay missing until a structured
# source returns a value.
NUMERIC_REQUIREMENTS = frozenset(
    {
        "pe",
        "fcf",
        "roe",
        "pb",
        "debt",
        "mos",
        "price",
        "price_history",
        "sector_benchmark",
        "sector_history",
        "sector_ohlcv",
        "relative_strength",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WebSearchCapability:
    """Executable ``web_search`` over Atlas's existing search client."""

    name = "web_search"

    def __init__(self, client: Any) -> None:
        self._client = client

    def available(self) -> bool:
        client = self._client
        if client is None or not hasattr(client, "search_web"):
            return False
        health = getattr(client, "health_check", None)
        if not callable(health):
            return True
        try:
            status = health()
        except Exception:  # noqa: BLE001
            return False
        return bool(getattr(status, "healthy", False))

    def unavailable_reason(self) -> str:
        if self._client is None or not hasattr(self._client, "search_web"):
            return CLIENT_NOT_CONFIGURED
        if not self.available():
            return PROVIDER_UNAVAILABLE
        return ""

    def execute(self, query: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run one search. Never invents hits."""
        started = _now()
        text = " ".join(str(query or "").split())
        base = {
            "capability": self.name,
            "query": text,
            "provider": None,
            "started_at": started,
            "completed_at": None,
            "result_count": 0,
            "status": SEARCH_ERROR,
            "error": None,
            "evidence": [],
            "evidence_ids": [],
            "citations": [],
            "context": {k: context.get(k) for k in ("work_id", "symbol", "requirement") if context and context.get(k)},
        }
        if not text:
            base["error"] = "empty_query"
            base["completed_at"] = _now()
            return base
        if not self.available():
            base["status"] = self.unavailable_reason() or PROVIDER_UNAVAILABLE
            base["error"] = base["status"]
            base["completed_at"] = _now()
            return base
        try:
            raw = self._client.search_web(text, max_results=5)
        except Exception as exc:  # noqa: BLE001
            base["status"] = SEARCH_ERROR
            base["error"] = str(exc)[:300]
            base["completed_at"] = _now()
            return base
        return _from_response(base, raw)


def _from_response(base: dict[str, Any], raw: Any) -> dict[str, Any]:
    if hasattr(raw, "as_dict"):
        doc = raw.as_dict()
    elif isinstance(raw, dict):
        doc = raw
    else:
        base["status"] = SEARCH_ERROR
        base["error"] = "search client returned an unreadable response"
        base["completed_at"] = _now()
        return base
    provider = str(doc.get("provider") or "") or None
    outcome = str(doc.get("outcome") or "")
    reason = doc.get("reason")
    hits = doc.get("results") if isinstance(doc.get("results"), list) else doc.get("hits")
    if hits is None and hasattr(raw, "hits"):
        hits = [
            h.as_dict() if hasattr(h, "as_dict") else h
            for h in (raw.hits or [])
        ]
    evidence = []
    for hit in hits or []:
        if not isinstance(hit, dict):
            continue
        url = str(hit.get("url") or "").strip()
        title = str(hit.get("title") or "").strip()
        if not url or not title:
            continue
        eid = "web:" + hashlib.sha1(f"{base['query']}|{url}".encode()).hexdigest()[:16]
        evidence.append(
            {
                "evidence_id": eid,
                "type": "external_web",
                "query": base["query"],
                "title": title,
                "url": url,
                "snippet": str(hit.get("snippet") or ""),
                "published_at": hit.get("published_at") or hit.get("published") or None,
                "retrieved_at": _now(),
                "provider": provider,
                "source": "web_search",
            }
        )
    base["provider"] = provider
    base["evidence"] = evidence
    base["evidence_ids"] = [row["evidence_id"] for row in evidence]
    base["citations"] = [row["url"] for row in evidence]
    base["result_count"] = len(evidence)
    base["completed_at"] = _now()
    if outcome in {"blocked", "skipped"}:
        base["status"] = PROVIDER_UNAVAILABLE
        base["error"] = str(reason or outcome)
    elif outcome not in {"ok", ""}:
        base["status"] = SEARCH_ERROR
        base["error"] = str(reason or outcome)
    elif not evidence:
        base["status"] = NO_RESULTS
        base["error"] = str(reason or "no results")
    else:
        base["status"] = SUCCESS
        base["error"] = None
    return base
