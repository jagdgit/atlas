"""OI-WEB-EVID0 Phase A — open-book web search → durable news observations.

Uses Atlas ``web.search`` (DuckDuckGo by default). Stores titles/URLs/snippets
only — no full-page HTML scrape of arbitrary publishers. Scientist reads via
``attach_world_evidence`` / observations. Never invents PE/FCF; never places orders.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

VERSION = "web_evid0.open_book_search.v1"
_log = logging.getLogger("atlas.investment.open_book_web_evidence")

SearchFn = Callable[..., Any]


def _bare(sym: str) -> str:
    s = str(sym or "").strip().upper()
    if s.endswith(".NS") or s.endswith(".BO"):
        return s[:-3]
    return s


def densify_open_book_web_evidence(
    data_dir: str | None,
    symbols: list[str],
    *,
    search_fn: SearchFn | None = None,
    max_symbols: int = 3,
    max_hits: int = 5,
    laboratory_id: str = "india_equity_learner",
) -> dict[str, Any]:
    """Search the web for open/plan symbols; persist evidence_candidate news rows.

    ``search_fn(query, max_results=N)`` should return an object with ``.hits``
    (each hit: title/url/snippet) or a list of dicts. Injectable for hermetic tests.
    """
    want = []
    seen: set[str] = set()
    for s in symbols or []:
        sym = str(s or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        want.append(sym)
        if len(want) >= max(1, min(int(max_symbols or 3), 8)):
            break

    out: dict[str, Any] = {
        "version": VERSION,
        "ok": True,
        "symbols_requested": list(want),
        "queried": 0,
        "hits_stored": 0,
        "per_symbol": [],
        "skipped": None,
        "honesty": (
            "DuckDuckGo/search snippets only — evidence_candidate. "
            "Not filings; not Screener scrape; does not unlock MoS BUY."
        ),
    }
    if not want:
        out["skipped"] = "no_symbols"
        return out
    if not data_dir:
        out["ok"] = False
        out["skipped"] = "no_data_dir"
        return out

    search = search_fn
    if search is None:
        try:
            from atlas.plugins.registry import get_plugin

            plug = get_plugin("search")
            if plug is not None and hasattr(plug, "search_web"):
                search = plug.search_web
        except Exception:  # noqa: BLE001
            search = None
    if search is None:
        out["ok"] = False
        out["skipped"] = "search_unavailable"
        return out

    try:
        from atlas.investment.observations import DecisionObservationStore

        store = DecisionObservationStore(data_dir=str(data_dir))
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["skipped"] = f"observations:{type(exc).__name__}"
        return out

    hits_stored = 0
    for sym in want:
        bare = _bare(sym)
        query = f"{bare} NSE stock news India"
        row: dict[str, Any] = {
            "symbol": sym,
            "query": query,
            "hits": 0,
            "stored": 0,
            "error": None,
        }
        try:
            resp = search(query, max_results=max(1, min(int(max_hits or 5), 8)))
            out["queried"] += 1
        except TypeError:
            try:
                resp = search(query)  # type: ignore[misc]
                out["queried"] += 1
            except Exception as exc:  # noqa: BLE001
                row["error"] = type(exc).__name__
                out["per_symbol"].append(row)
                continue
        except Exception as exc:  # noqa: BLE001
            row["error"] = type(exc).__name__
            out["per_symbol"].append(row)
            continue

        raw_hits: list[Any] = []
        if resp is None:
            raw_hits = []
        elif hasattr(resp, "hits"):
            raw_hits = list(getattr(resp, "hits") or [])
        elif isinstance(resp, dict):
            raw_hits = list(resp.get("hits") or resp.get("results") or [])
        elif isinstance(resp, list):
            raw_hits = resp

        row["hits"] = len(raw_hits)
        for hit in raw_hits[: max(1, min(int(max_hits or 5), 8))]:
            if isinstance(hit, dict):
                title = str(hit.get("title") or "").strip()
                url = str(hit.get("url") or hit.get("link") or "").strip()
                snippet = str(hit.get("snippet") or hit.get("body") or "").strip()
            else:
                title = str(getattr(hit, "title", "") or "").strip()
                url = str(getattr(hit, "url", "") or "").strip()
                snippet = str(getattr(hit, "snippet", "") or "").strip()
            if not title and not snippet:
                continue
            text = title
            if snippet:
                text = f"{title}: {snippet}" if title else snippet
            try:
                store.record_news_event(
                    text=text[:500],
                    symbol=sym,
                    source="duckduckgo_search",
                    link=url or None,
                    open_book=True,
                    topic_tags=["web_search", "open_book"],
                    extra={
                        "cu": "web_evid0.a",
                        "source_tier": 3,
                        "evidence_class": "evidence_candidate",
                        "event_class": "news",
                        "laboratory_id": laboratory_id,
                        "query": query,
                        "title": title[:200],
                        "snippet": snippet[:300],
                    },
                )
                row["stored"] += 1
                hits_stored += 1
            except Exception as exc:  # noqa: BLE001
                _log.debug("web evidence store failed %s: %s", sym, exc)
        out["per_symbol"].append(row)

    out["hits_stored"] = hits_stored
    if hits_stored == 0 and out["queried"] > 0:
        out["skipped"] = "zero_hits"
    return out
