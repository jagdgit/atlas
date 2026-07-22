"""Browser → Asset caption extract (Media Browser Acquisition · BA.1).

Read-only: open page (via injectable renderer), pull metadata + DOM/HTML caption
signals, return transcript text when present. Never writes Knowledge — caller
registers Assets / Knowledge. Honours whatever policy the renderer applies
(robots, etc.) — not a bypass.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable
from urllib.parse import unquote

from atlas.ingestion.source_fetch import is_youtube_url

STRATEGY_BROWSER_DOM_CAPTIONS = "browser_dom_captions"

_CAPTION_TRACKS_RE = re.compile(r'"captionTracks":(\[.*?\])', re.DOTALL)
_TIMED_LINE_RE = re.compile(
    r"(?m)^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\.\d+)?\s+\S+"
)

BrowserRender = Callable[[str], dict[str, Any]]


def extract_caption_tracks_json(html: str) -> list[dict[str, Any]]:
    match = _CAPTION_TRACKS_RE.search(html or "")
    if not match:
        return []
    try:
        tracks = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    return [t for t in tracks if isinstance(t, dict)]


def text_looks_like_transcript(text: str) -> bool:
    body = (text or "").strip()
    if len(body) < 80:
        return False
    timed = len(_TIMED_LINE_RE.findall(body))
    if timed >= 3:
        return True
    # Dense multi-line prose from a captions panel.
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    return len(lines) >= 8 and sum(len(ln) for ln in lines) >= 200


def browser_dom_captions(
    source: str,
    *,
    render: BrowserRender,
    fetch_timedtext: Callable[[str], str] | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Run Browser v1 strategy. Returns a strategy result dict (never raises)."""
    log = logger or logging.getLogger("atlas.ingestion.browser_captions")
    out: dict[str, Any] = {
        "strategy": STRATEGY_BROWSER_DOM_CAPTIONS,
        "outcome": "skipped",
        "reason_code": "not_attempted",
        "reason": None,
        "title": None,
        "text": "",
        "metadata": {},
        "bytes_read": 0,
    }
    if not (source or "").strip():
        out["reason"] = "missing source"
        out["reason_code"] = "bad_source"
        return out

    try:
        page = render(source) or {}
    except Exception as exc:  # noqa: BLE001
        log.exception("browser render failed")
        out["outcome"] = "error"
        out["reason"] = str(exc)
        out["reason_code"] = "browser_error"
        return out

    outcome = str(page.get("outcome") or "ok")
    if outcome != "ok":
        out["outcome"] = outcome if outcome in (
            "blocked", "skipped", "unavailable", "timeout", "error", "empty"
        ) else "error"
        out["reason"] = page.get("reason") or outcome
        out["reason_code"] = str(page.get("reason_code") or outcome)
        out["metadata"] = {
            "title": page.get("title"),
            "final_url": page.get("final_url") or page.get("url"),
        }
        return out

    title = page.get("title") or ""
    text = (page.get("text") or "").strip()
    html = page.get("html") or page.get("content") or ""
    out["metadata"] = {
        "title": title,
        "final_url": page.get("final_url") or page.get("url") or source,
    }
    out["title"] = title or None

    # Prefer embedded captionTracks (YouTube player config in page HTML).
    tracks = extract_caption_tracks_json(html)
    if tracks and fetch_timedtext is not None:
        for track in tracks:
            base = track.get("baseUrl") or track.get("base_url")
            if not base:
                continue
            try:
                raw = fetch_timedtext(unquote(str(base)))
            except Exception as exc:  # noqa: BLE001
                log.debug("timedtext fetch failed: %s", exc)
                continue
            cleaned = _strip_timedtext(raw)
            if cleaned.strip():
                out["outcome"] = "ok"
                out["reason_code"] = "ok"
                out["text"] = cleaned.strip()
                out["bytes_read"] = len(cleaned.encode("utf-8"))
                out["metadata"]["caption_lang"] = track.get("languageCode")
                return out

    if text_looks_like_transcript(text):
        out["outcome"] = "ok"
        out["reason_code"] = "ok"
        out["text"] = text
        out["bytes_read"] = len(text.encode("utf-8"))
        out["reason"] = "dom transcript text"
        return out

    out["outcome"] = "skipped"
    out["reason_code"] = "no_captions"
    out["reason"] = (
        "browser rendered page but no DOM captions / captionTracks found"
        + (" (YouTube-shaped URL)" if is_youtube_url(source) else "")
    )
    out["bytes_read"] = len((html or text).encode("utf-8"))
    return out


def _strip_timedtext(raw: str) -> str:
    """Best-effort strip of YouTube timedtext XML/JSON3 to plain lines."""
    if not raw:
        return ""
    # JSON3
    if raw.lstrip().startswith("{"):
        try:
            data = json.loads(raw)
            events = data.get("events") or []
            parts = []
            for ev in events:
                segs = ev.get("segs") or []
                parts.append("".join(s.get("utf8") or "" for s in segs if isinstance(s, dict)))
            return "\n".join(p for p in parts if p.strip())
        except json.JSONDecodeError:
            pass
    # XML-ish: drop tags
    plain = re.sub(r"<[^>]+>", " ", raw)
    plain = re.sub(r"&amp;", "&", plain)
    plain = re.sub(r"&lt;", "<", plain)
    plain = re.sub(r"&gt;", ">", plain)
    plain = re.sub(r"&quot;", '"', plain)
    plain = re.sub(r"&#39;", "'", plain)
    plain = re.sub(r"\s+", " ", plain)
    return plain.strip()
