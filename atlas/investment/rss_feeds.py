"""IIP.9 — RSS allow-list client (official / operator feeds only).

No HTML scraping. Only URLs explicitly listed in config or DEFAULT_ALLOWLIST
(with enabled=true) are fetched. Injectable opener for hermetic tests.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

VERSION = "iip.9.rss"
STORE_REL = Path("investment") / "rss"
LAST_FETCH_NAME = "last_fetch.json"

# Official / public RSS endpoints — disabled by default until operator enables.
# Not scraped HTML; feed XML only.
DEFAULT_ALLOWLIST: list[dict[str, Any]] = [
    {
        "id": "pib_press",
        "url": "https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=1",
        "kind": "policy",
        "label": "PIB Press Releases",
        # Stay False in defaults; E1 missions enable via rss_enable=["pib_press"].
        # Verified text/xml RSS 2026-08-10 (A1).
        "enabled": False,
        "max_items": 15,
        "note": "Verified RSS/Atom XML 2026-08-10 — enable via mission rss_enable.",
    },
    {
        "id": "rbi_press",
        "url": "https://www.rbi.org.in/Scripts/Bs_viewcontent.aspx?Id=3852",
        "kind": "policy",
        "label": "RBI (placeholder — enable only if URL serves RSS/Atom)",
        "enabled": False,
        "max_items": 10,
        "note": "Replace with a verified RBI RSS URL before enabling.",
    },
    {
        "id": "sebi_press",
        "url": "https://www.sebi.gov.in/sebirss.xml",
        "kind": "policy",
        "label": "SEBI RSS (if published)",
        "enabled": False,
        "max_items": 10,
        "note": "Verify feed URL before enabling; disable if HTML.",
    },
]

_TAG_RE = re.compile(r"<[^>]+>")
Opener = Callable[[str], str | bytes]


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def store_dir(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL


def last_fetch_path(data_dir: str | Path) -> Path:
    return store_dir(data_dir) / LAST_FETCH_NAME


def default_allowlist() -> list[dict[str, Any]]:
    return [dict(x) for x in DEFAULT_ALLOWLIST]


def merge_allowlist(
    overrides: list[dict[str, Any]] | None = None,
    *,
    include_defaults: bool = True,
) -> list[dict[str, Any]]:
    """Merge operator feeds onto defaults (by id); operator can add new ids."""
    by_id: dict[str, dict[str, Any]] = {}
    if include_defaults:
        for row in DEFAULT_ALLOWLIST:
            by_id[str(row["id"])] = dict(row)
    for raw in overrides or []:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or "").strip()
        fid = str(raw.get("id") or "").strip() or _slug_from_url(url)
        if not url and fid not in by_id:
            continue
        base = dict(by_id.get(fid) or {})
        base.update({k: v for k, v in raw.items() if v is not None})
        base["id"] = fid
        if url:
            base["url"] = url
        by_id[fid] = base
    return list(by_id.values())


def _slug_from_url(url: str) -> str:
    try:
        host = urlparse(url).netloc.replace(".", "_")[:24]
    except Exception:  # noqa: BLE001
        host = "feed"
    return f"feed_{host}_{hashlib.sha256(url.encode()).hexdigest()[:8]}"


def allowlist_view(feeds: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = feeds if feeds is not None else default_allowlist()
    return {
        "version": VERSION,
        "feeds": [
            {
                "id": r.get("id"),
                "label": r.get("label") or r.get("id"),
                "url": r.get("url"),
                "kind": r.get("kind") or "news",
                "enabled": bool(r.get("enabled")),
                "note": r.get("note"),
                "max_items": int(r.get("max_items") or 15),
            }
            for r in rows
        ],
        "enabled_count": sum(1 for r in rows if r.get("enabled")),
        "note": (
            "Only enabled allow-listed RSS/Atom URLs are fetched. "
            "No HTML scraping. Operator must verify each feed serves XML."
        ),
    }


def strip_html(text: str) -> str:
    return _TAG_RE.sub(" ", text or "").replace("&nbsp;", " ").strip()


def parse_feed_xml(body: str | bytes, *, feed_id: str = "", kind: str = "news") -> list[dict[str, Any]]:
    """Parse RSS 2.0 or Atom XML into normalized items."""
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    text = (body or "").strip()
    if not text:
        return []
    # Reject obvious HTML pages (honesty: not a scraper)
    low = text[:400].lower()
    if "<html" in low and "<rss" not in low and "<feed" not in low:
        raise ValueError("response looks like HTML, not RSS/Atom — refuse scrape")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"invalid XML feed: {exc}") from exc

    # Strip namespaces for simpler findall
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]

    items: list[dict[str, Any]] = []
    entries = root.findall(".//item") or root.findall(".//entry")
    for entry in entries:
        title = _child_text(entry, "title")
        summary = (
            _child_text(entry, "description")
            or _child_text(entry, "summary")
            or _child_text(entry, "content")
        )
        link = _child_text(entry, "link") or _attr_link(entry)
        published = (
            _child_text(entry, "pubDate")
            or _child_text(entry, "published")
            or _child_text(entry, "updated")
        )
        title_c = strip_html(title)
        summary_c = strip_html(summary)
        if not title_c and not summary_c:
            continue
        body_text = title_c
        if summary_c and summary_c != title_c:
            body_text = f"{title_c}. {summary_c}" if title_c else summary_c
        digest = hashlib.sha256(body_text.encode("utf-8")).hexdigest()[:16]
        items.append(
            {
                "id": f"{feed_id}:{digest}" if feed_id else digest,
                "text": body_text[:1200],
                "title": title_c[:300],
                "summary": summary_c[:800],
                "link": link,
                "published": published,
                "source": f"rss:{feed_id}" if feed_id else "rss",
                "kind": kind,
                "feed_id": feed_id or None,
                "symbol": "",  # optional operator tagging later
            }
        )
    return items


def _child_text(el: ET.Element, tag: str) -> str:
    child = el.find(tag)
    if child is None:
        return ""
    return (child.text or "").strip()


def _attr_link(el: ET.Element) -> str:
    link = el.find("link")
    if link is not None and link.get("href"):
        return str(link.get("href"))
    return ""


def _default_fetch(url: str, *, timeout: float = 20.0) -> str:
    import httpx

    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "AtlasRSSAllowlist/1.0 (Investment Intelligence)"},
    ) as client:
        resp = client.get(url)
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}")
        return resp.text


def fetch_allowlist(
    feeds: list[dict[str, Any]] | None = None,
    *,
    opener: Opener | None = None,
    kinds: list[str] | None = None,
    max_per_feed: int | None = None,
    timeout: float = 20.0,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Fetch enabled allow-listed feeds; return items + per-feed status."""
    log = logger or logging.getLogger("atlas.investment.rss_feeds")
    rows = feeds if feeds is not None else default_allowlist()
    kind_filter = {k.lower() for k in kinds} if kinds else None
    fetch_fn = opener or (lambda u: _default_fetch(u, timeout=timeout))

    all_items: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for row in rows:
        if not row.get("enabled"):
            statuses.append(
                {
                    "id": row.get("id"),
                    "status": "disabled",
                    "url": row.get("url"),
                }
            )
            continue
        kind = str(row.get("kind") or "news").lower()
        if kind_filter and kind not in kind_filter:
            statuses.append(
                {
                    "id": row.get("id"),
                    "status": "skipped_kind",
                    "kind": kind,
                }
            )
            continue
        url = str(row.get("url") or "").strip()
        fid = str(row.get("id") or "feed")
        if not url:
            statuses.append({"id": fid, "status": "missing_url"})
            continue
        cap = int(max_per_feed or row.get("max_items") or 15)
        try:
            body = fetch_fn(url)
            parsed = parse_feed_xml(body, feed_id=fid, kind=kind)[: max(1, cap)]
            all_items.extend(parsed)
            statuses.append(
                {
                    "id": fid,
                    "status": "ok",
                    "items": len(parsed),
                    "url": url,
                    "kind": kind,
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("rss fetch failed %s: %s", fid, exc)
            statuses.append(
                {
                    "id": fid,
                    "status": "error",
                    "error": str(exc)[:240],
                    "url": url,
                    "kind": kind,
                }
            )

    return {
        "version": VERSION,
        "fetched_at": _utc(),
        "items": all_items,
        "item_count": len(all_items),
        "feeds": statuses,
        "ok_feeds": sum(1 for s in statuses if s.get("status") == "ok"),
    }


def save_last_fetch(data_dir: str | Path | None, result: dict[str, Any]) -> Path | None:
    if not data_dir:
        return None
    path = last_fetch_path(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        slim = {
            "version": VERSION,
            "fetched_at": result.get("fetched_at"),
            "item_count": result.get("item_count"),
            "ok_feeds": result.get("ok_feeds"),
            "feeds": result.get("feeds"),
            "titles": [
                {"title": i.get("title"), "source": i.get("source"), "kind": i.get("kind")}
                for i in (result.get("items") or [])[:40]
            ],
        }
        path.write_text(json.dumps(slim, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path
    except Exception:  # noqa: BLE001
        return None


def load_last_fetch(data_dir: str | Path | None) -> dict[str, Any]:
    if not data_dir:
        return {"item_count": 0, "feeds": [], "titles": []}
    path = last_fetch_path(data_dir)
    if not path.is_file():
        return {"item_count": 0, "feeds": [], "titles": [], "note": "no fetch yet"}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {"item_count": 0}
    except Exception:  # noqa: BLE001
        return {"item_count": 0, "note": "corrupt last_fetch"}


def items_as_news(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Shape for NewsIntelligenceWorker."""
    out: list[dict[str, Any]] = []
    for it in result.get("items") or []:
        text = str(it.get("text") or it.get("title") or "").strip()
        if len(text) < 12:
            continue
        out.append(
            {
                "text": text,
                "symbol": str(it.get("symbol") or ""),
                "source": str(it.get("source") or "rss"),
                "title": it.get("title"),
                "link": it.get("link"),
                "kind": it.get("kind"),
            }
        )
    return out


def items_as_policy(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Shape for government_policy.refresh_catalog operator_items."""
    out: list[dict[str, Any]] = []
    for it in result.get("items") or []:
        title = str(it.get("title") or "").strip()
        summary = str(it.get("summary") or it.get("text") or "").strip()
        if not title and not summary:
            continue
        out.append(
            {
                "id": str(it.get("id") or "")[:80],
                "title": title or summary[:80],
                "summary": summary[:600],
                "delta": 0.04,  # soft nudge until operator tunes
                "source": str(it.get("source") or "rss_policy"),
                "kind": "policy",
                "link": it.get("link"),
            }
        )
    return out
