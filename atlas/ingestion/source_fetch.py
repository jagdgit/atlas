"""Provider-agnostic source fetch → Asset (Media Reader Family · M.6 / MD8).

Only job: turn a URL or local path into a media Asset. Provider-specific logic lives
**here** (and nowhere past the Asset boundary). Uses ``ReaderStrategyChain``:

    local_file → http_direct → youtube_media → …
        ↓ first ok
    Asset (+ strategies_tried[])

Robots/ToS are law (MD6): a disallowed scrape returns ``blocked`` + operator hint
(*upload a local file or a transcript asset*) — never a silent bypass. YouTube media
bytes are optional via an injected ``youtube_fetch`` callable; without it (or when
robots denies), the chain stops honestly.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from atlas.readers.media_kinds import (
    ASSET_KIND_AUDIO,
    ASSET_KIND_TRANSCRIPT,
    ASSET_KIND_VIDEO,
    content_type_for,
    infer_media_kind,
)
from atlas.readers.strategy_chain import ReaderStrategyChain, StrategyResult

if TYPE_CHECKING:
    from atlas.ingestion.acquire import AssetAcquirer
    from atlas.net.client import FetchClient

OPERATOR_HINT = "upload a local file or a transcript asset"

# Injectable: (url) -> {outcome, content?, content_type?, filename?, reason?, kind?}
YoutubeFetchFn = Callable[[str], dict[str, Any]]

_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_CONTENT_TYPE_KIND = (
    ("video/", ASSET_KIND_VIDEO),
    ("audio/", ASSET_KIND_AUDIO),
    ("text/vtt", ASSET_KIND_TRANSCRIPT),
    ("application/x-subrip", ASSET_KIND_TRANSCRIPT),
    ("text/plain", ASSET_KIND_TRANSCRIPT),
)


@dataclass(frozen=True)
class SourceFetchResult:
    """Outcome of fetching a source into an Asset (or explaining why not)."""

    outcome: str
    source_url: str
    strategies_tried: tuple[dict[str, Any], ...] = ()
    asset_id: str | None = None
    asset_version: int | None = None
    kind: str | None = None
    filename: str | None = None
    source_id: str | None = None
    reason: str | None = None
    reason_code: str = "unknown"
    operator_hint: str | None = None
    bytes_read: int = 0
    reused: bool = False

    @property
    def ok(self) -> bool:
        return self.outcome == "ok" and bool(self.asset_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "ok": self.ok,
            "source_url": self.source_url,
            "source_id": self.source_id,
            "asset_id": self.asset_id,
            "asset_version": self.asset_version,
            "kind": self.kind,
            "filename": self.filename,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "operator_hint": self.operator_hint,
            "bytes_read": self.bytes_read,
            "reused": self.reused,
            "strategies_tried": list(self.strategies_tried),
        }


class SourceFetcher:
    """Ordered source-fetch strategies → content-addressed media Asset."""

    def __init__(
        self,
        acquirer: "AssetAcquirer",
        fetch_client: "FetchClient | None" = None,
        *,
        youtube_fetch: YoutubeFetchFn | None = None,
        max_bytes: int = 52_428_800,  # 50 MiB direct HTTP media cap
        logger: logging.Logger | None = None,
    ) -> None:
        self._acq = acquirer
        self._fetch = fetch_client
        self._youtube_fetch = youtube_fetch
        self._max_bytes = max_bytes
        self._logger = logger or logging.getLogger("atlas.ingestion.source_fetch")
        self._chain = ReaderStrategyChain(logger_=self._logger)

    def fetch(self, source: str) -> SourceFetchResult:
        """Fetch ``source`` (local path or http(s) URL) into a media Asset."""
        raw = (source or "").strip()
        if not raw:
            return SourceFetchResult(
                outcome="error",
                source_url=raw,
                reason="empty source",
                reason_code="invalid_source",
                operator_hint=OPERATOR_HINT,
            )

        source_id = stable_source_id(raw)
        strategies = [
            ("local_file", lambda: self._local_file(raw)),
            ("http_direct", lambda: self._http_direct(raw)),
            ("youtube_media", lambda: self._youtube_media(raw)),
        ]
        chain = self._chain.execute(
            strategies,
            source_url=raw,
            source_kind="media_source",
            suggested_next_capability=None,
        )
        tried = tuple(r.as_dict() for r in chain.tried)

        if chain.ok and chain.winner and isinstance(chain.winner.value, dict):
            val = chain.winner.value
            return SourceFetchResult(
                outcome="ok",
                source_url=raw,
                strategies_tried=tried,
                asset_id=val.get("asset_id"),
                asset_version=val.get("asset_version"),
                kind=val.get("kind"),
                filename=val.get("filename"),
                source_id=source_id,
                bytes_read=int(chain.winner.bytes_read or val.get("bytes_read") or 0),
                reused=bool(val.get("reused")),
                reason_code="ok",
            )

        # Prefer the most informative terminal attempt (blocked > others).
        terminal = _pick_terminal(chain.tried)
        outcome = terminal.outcome if terminal else "error"
        reason = (terminal.reason if terminal else None) or "no source-fetch strategy succeeded"
        reason_code = (terminal.reason_code if terminal else "unknown") or "unknown"
        hint = OPERATOR_HINT if outcome in ("blocked", "unsupported", "skipped", "error") else None
        # Robots / policy blocks always carry the operator escape hatch.
        if reason_code in ("robots_disallowed", "policy_requires_operator_asset"):
            outcome = "blocked"
            hint = OPERATOR_HINT
        return SourceFetchResult(
            outcome=outcome,
            source_url=raw,
            strategies_tried=tried,
            source_id=source_id,
            reason=reason,
            reason_code=reason_code,
            operator_hint=hint,
            bytes_read=int(terminal.bytes_read) if terminal else 0,
        )

    # --- strategies ------------------------------------------------------
    def _local_file(self, source: str) -> StrategyResult:
        parsed = urlparse(source)
        if parsed.scheme in ("http", "https"):
            return StrategyResult(
                name="local_file",
                outcome="skipped",
                reason="not a local path",
                reason_code="not_applicable",
            )
        path_str = source
        if parsed.scheme == "file":
            path_str = unquote(parsed.path)
        p = Path(path_str).expanduser()
        try:
            p = p.resolve()
        except OSError:
            pass
        if not p.is_file():
            return StrategyResult(
                name="local_file",
                outcome="skipped",
                reason=f"not a file: {p}",
                reason_code="not_applicable",
            )
        kind = infer_media_kind(p.name)
        if kind is None:
            return StrategyResult(
                name="local_file",
                outcome="unsupported",
                reason=f"not a media file: {p.name}",
                reason_code="unsupported_media",
            )
        acquired = self._acq.acquire_file(
            p,
            kind=kind,
            content_type=content_type_for(p.name),
            metadata={
                "filename": p.name,
                "source_url": str(p),
                "source_id": stable_source_id(str(p)),
            },
        )
        return StrategyResult(
            name="local_file",
            outcome="ok",
            bytes_read=acquired.size_bytes,
            value={
                "asset_id": acquired.asset_id,
                "asset_version": acquired.asset_version,
                "kind": kind,
                "filename": p.name,
                "reused": acquired.reused,
                "bytes_read": acquired.size_bytes,
            },
        )

    def _http_direct(self, source: str) -> StrategyResult:
        parsed = urlparse(source)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return StrategyResult(
                name="http_direct",
                outcome="skipped",
                reason="not an http(s) URL",
                reason_code="not_applicable",
            )
        if is_youtube_url(source):
            return StrategyResult(
                name="http_direct",
                outcome="skipped",
                reason="youtube URLs use the youtube_media strategy",
                reason_code="not_applicable",
            )
        if self._fetch is None:
            return StrategyResult(
                name="http_direct",
                outcome="unsupported",
                reason="no FetchClient configured",
                reason_code="fetch_unavailable",
            )

        # MD6: never bypass robots.
        if not self._fetch.allowed(source):
            return StrategyResult(
                name="http_direct",
                outcome="blocked",
                reason="robots.txt disallows this URL",
                reason_code="robots_disallowed",
            )

        filename = _filename_from_url(parsed)
        kind = infer_media_kind(filename)
        result = self._fetch.get(source)
        if result.outcome != "ok":
            # Map fetch-layer robots skip → blocked for source-fetch callers.
            outcome = "blocked" if "robots" in (result.reason or "").lower() else result.outcome
            reason_code = (
                "robots_disallowed"
                if outcome == "blocked"
                else ("http_blocked" if result.outcome == "blocked" else "fetch_failed")
            )
            return StrategyResult(
                name="http_direct",
                outcome=outcome if outcome in ("blocked", "skipped", "error") else "error",
                reason=result.reason or f"fetch {result.outcome}",
                reason_code=reason_code,
            )

        content = result.content or result.text.encode("utf-8", errors="replace")
        if len(content) > self._max_bytes:
            return StrategyResult(
                name="http_direct",
                outcome="error",
                reason=f"body exceeds max_bytes ({self._max_bytes})",
                reason_code="too_large",
                bytes_read=len(content),
            )
        if not content:
            return StrategyResult(
                name="http_direct",
                outcome="empty",
                reason="empty response body",
                reason_code="empty",
            )

        ct = (result.content_type or "").split(";")[0].strip().lower()
        if kind is None:
            kind = infer_kind_from_content_type(ct)
        if kind is None:
            return StrategyResult(
                name="http_direct",
                outcome="unsupported",
                reason=f"response is not media (content-type={ct or 'unknown'})",
                reason_code="unsupported_media",
                bytes_read=len(content),
            )
        if not filename or infer_media_kind(filename) is None:
            filename = _default_filename(kind, ct)

        acquired = self._acq.acquire_bytes(
            content,
            kind=kind,
            filename=filename,
            source_uri=source,
            content_type=ct or content_type_for(filename),
            metadata={
                "filename": filename,
                "source_url": source,
                "source_id": stable_source_id(source),
                "content_type": ct,
            },
        )
        return StrategyResult(
            name="http_direct",
            outcome="ok",
            bytes_read=len(content),
            value={
                "asset_id": acquired.asset_id,
                "asset_version": acquired.asset_version,
                "kind": kind,
                "filename": filename,
                "reused": acquired.reused,
                "bytes_read": len(content),
            },
        )

    def _youtube_media(self, source: str) -> StrategyResult:
        if not is_youtube_url(source):
            return StrategyResult(
                name="youtube_media",
                outcome="skipped",
                reason="not a YouTube URL",
                reason_code="not_applicable",
            )
        video_id = youtube_video_id(source)
        watch_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else source

        if self._fetch is not None and not self._fetch.allowed(watch_url):
            return StrategyResult(
                name="youtube_media",
                outcome="blocked",
                reason="robots.txt disallows this URL",
                reason_code="robots_disallowed",
            )

        if self._youtube_fetch is None:
            return StrategyResult(
                name="youtube_media",
                outcome="blocked",
                reason=(
                    "youtube media fetch not configured; "
                    f"{OPERATOR_HINT}"
                ),
                reason_code="policy_requires_operator_asset",
            )

        try:
            payload = self._youtube_fetch(watch_url)
        except Exception as exc:  # noqa: BLE001
            return StrategyResult(
                name="youtube_media",
                outcome="error",
                reason=str(exc),
                reason_code="youtube_fetch_error",
            )

        outcome = str(payload.get("outcome") or "error")
        if outcome != "ok":
            mapped = outcome if outcome in ("blocked", "skipped", "unsupported", "error") else "error"
            reason_code = str(payload.get("reason_code") or "youtube_fetch_failed")
            if "robots" in (payload.get("reason") or "").lower():
                mapped, reason_code = "blocked", "robots_disallowed"
            return StrategyResult(
                name="youtube_media",
                outcome=mapped,
                reason=payload.get("reason") or "youtube fetch failed",
                reason_code=reason_code,
            )

        content = payload.get("content") or b""
        if isinstance(content, str):
            content = content.encode("utf-8", errors="replace")
        if not content:
            return StrategyResult(
                name="youtube_media",
                outcome="empty",
                reason="youtube fetch returned no bytes",
                reason_code="empty",
            )
        if len(content) > self._max_bytes:
            return StrategyResult(
                name="youtube_media",
                outcome="error",
                reason=f"body exceeds max_bytes ({self._max_bytes})",
                reason_code="too_large",
                bytes_read=len(content),
            )

        filename = str(payload.get("filename") or f"{video_id or 'youtube'}.mp4")
        kind = str(payload.get("kind") or infer_media_kind(filename) or ASSET_KIND_VIDEO)
        ct = payload.get("content_type") or content_type_for(filename)
        acquired = self._acq.acquire_bytes(
            content,
            kind=kind,
            filename=filename,
            source_uri=watch_url,
            content_type=ct,
            metadata={
                "filename": filename,
                "source_url": watch_url,
                "source_id": stable_source_id(watch_url),
                "youtube_video_id": video_id,
            },
        )
        return StrategyResult(
            name="youtube_media",
            outcome="ok",
            bytes_read=len(content),
            value={
                "asset_id": acquired.asset_id,
                "asset_version": acquired.asset_version,
                "kind": kind,
                "filename": filename,
                "reused": acquired.reused,
                "bytes_read": len(content),
            },
        )


# --- helpers -------------------------------------------------------------
def stable_source_id(source: str) -> str:
    """Stable id for dedupe (M.7): ``youtube:<id>`` or ``url:<sha12>`` / ``file:<sha12>``."""
    vid = youtube_video_id(source)
    if vid:
        return f"youtube:{vid}"
    parsed = urlparse(source)
    if parsed.scheme in ("http", "https"):
        digest = hashlib.sha256(source.strip().encode("utf-8")).hexdigest()[:12]
        return f"url:{digest}"
    digest = hashlib.sha256(str(Path(source).expanduser()).encode("utf-8")).hexdigest()[:12]
    return f"file:{digest}"


def is_youtube_url(value: str) -> bool:
    host = urlparse(value).netloc.lower()
    return "youtube.com" in host or "youtu.be" in host or "youtube-nocookie.com" in host


def youtube_video_id(value: str) -> str:
    if not value:
        return ""
    if _YT_ID_RE.match(value):
        return value
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    if "youtu.be" in host:
        candidate = parsed.path.lstrip("/").split("/")[0]
        return candidate if _YT_ID_RE.match(candidate) else ""
    if "youtube" in host:
        qs = parse_qs(parsed.query)
        if qs.get("v") and _YT_ID_RE.match(qs["v"][0]):
            return qs["v"][0]
        for prefix in ("/shorts/", "/embed/", "/v/"):
            if parsed.path.startswith(prefix):
                candidate = parsed.path[len(prefix) :].split("/")[0]
                return candidate if _YT_ID_RE.match(candidate) else ""
    return ""


def infer_kind_from_content_type(content_type: str | None) -> str | None:
    ct = (content_type or "").lower()
    if not ct:
        return None
    for prefix, kind in _CONTENT_TYPE_KIND:
        if ct.startswith(prefix) or ct == prefix:
            return kind
    return None


def _filename_from_url(parsed: Any) -> str:
    name = unquote(Path(parsed.path).name)
    return name if name and name != "/" else ""


def _default_filename(kind: str, content_type: str) -> str:
    if kind == ASSET_KIND_AUDIO:
        return "audio.mp3" if "mpeg" in content_type else "audio.wav"
    if kind == ASSET_KIND_TRANSCRIPT:
        return "captions.vtt" if "vtt" in content_type else "transcript.txt"
    return "video.mp4"


def _pick_terminal(tried: tuple[StrategyResult, ...]) -> StrategyResult | None:
    if not tried:
        return None
    for pref in ("blocked", "unsupported", "error", "empty", "skipped"):
        for r in reversed(tried):
            if r.outcome == pref and r.reason_code != "not_applicable":
                return r
    return tried[-1]
