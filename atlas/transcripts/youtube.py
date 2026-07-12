"""YouTube transcript provider (Stage 2, S18a).

Two polite fetches through the resilient net layer, never raising (R2/R3):

1. GET the watch page, scrape the ``captionTracks`` list from the embedded player
   response, and pick a track (prefer a configured language).
2. GET the track's ``baseUrl`` (timedtext XML) and decode the ``<text>`` cues into a
   transcript (full text + timed segments).

Every failure mode is an **outcome**, not an exception: no video id ⇒ ``error``; a
blocked/rate-limited fetch ⇒ the net layer's outcome; no captions ⇒ ``skipped``.
"""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from atlas.evidence.models import LEVEL_FORUM, level_name
from atlas.net import OUTCOME_ERROR, OUTCOME_OK, OUTCOME_SKIPPED

if TYPE_CHECKING:
    from atlas.net import FetchClient

_CAPTION_TRACKS_RE = re.compile(r'"captionTracks":(\[.*?\])', re.DOTALL)
_TITLE_RE = re.compile(r'"title":"((?:[^"\\]|\\.)*)"')
_CUE_RE = re.compile(r'<text start="([\d.]+)"(?: dur="([\d.]+)")?[^>]*>(.*?)</text>', re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    duration: float
    text: str

    def as_dict(self) -> dict[str, object]:
        return {"start": self.start, "duration": self.duration, "text": self.text}


@dataclass(frozen=True)
class TranscriptResult:
    video_id: str
    url: str
    outcome: str
    title: str = ""
    language: str = ""
    text: str = ""
    segments: list[TranscriptSegment] = field(default_factory=list)
    reason: str | None = None
    evidence_level: int = LEVEL_FORUM

    @property
    def ok(self) -> bool:
        return self.outcome == OUTCOME_OK

    def as_dict(self) -> dict[str, object]:
        return {
            "video_id": self.video_id,
            "url": self.url,
            "outcome": self.outcome,
            "title": self.title,
            "language": self.language,
            "text": self.text,
            "segments": [s.as_dict() for s in self.segments],
            "reason": self.reason,
            "evidence_level": self.evidence_level,
            "level_name": level_name(self.evidence_level),
        }

    def as_source(self) -> dict[str, object]:
        return {
            "id": f"youtube:{self.video_id}",
            "title": self.title or self.video_id,
            "url": self.url,
            "evidence_level": self.evidence_level,
            "kind": "video",
        }


class YouTubeTranscriptProvider:
    name = "youtube"

    def __init__(
        self,
        client: "FetchClient",
        *,
        languages: list[str] | None = None,
        evidence_level: int = LEVEL_FORUM,
        logger: logging.Logger | None = None,
    ) -> None:
        self._client = client
        self._languages = [lang.lower() for lang in (languages or ["en"])]
        self._evidence_level = evidence_level
        self._logger = logger or logging.getLogger("atlas.transcripts.youtube")

    def fetch(self, url_or_id: str) -> TranscriptResult:
        video_id = self._video_id((url_or_id or "").strip())
        watch_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
        if not video_id:
            return TranscriptResult(
                "", url_or_id or "", OUTCOME_ERROR,
                reason="could not parse a YouTube video id",
                evidence_level=self._evidence_level,
            )
        page = self._client.get(watch_url)
        if page.outcome != OUTCOME_OK:
            return TranscriptResult(
                video_id, watch_url, page.outcome, reason=page.reason,
                evidence_level=self._evidence_level,
            )
        try:
            return self._extract(video_id, watch_url, page.text)
        except Exception as exc:  # noqa: BLE001 - fragile scrape must not crash the job
            self._logger.exception("youtube transcript extraction failed")
            return TranscriptResult(
                video_id, watch_url, OUTCOME_ERROR, reason=str(exc),
                evidence_level=self._evidence_level,
            )

    # --- internals ------------------------------------------------------
    def _extract(self, video_id: str, watch_url: str, page: str) -> TranscriptResult:
        title = self._title(page)
        tracks_match = _CAPTION_TRACKS_RE.search(page)
        if not tracks_match:
            return TranscriptResult(
                video_id, watch_url, OUTCOME_SKIPPED, title=title,
                reason="no captions available for this video",
                evidence_level=self._evidence_level,
            )
        tracks = json.loads(tracks_match.group(1))
        track = self._pick_track(tracks)
        if track is None or not track.get("baseUrl"):
            return TranscriptResult(
                video_id, watch_url, OUTCOME_SKIPPED, title=title,
                reason="no usable caption track",
                evidence_level=self._evidence_level,
            )
        base_url = track["baseUrl"].replace("\\u0026", "&")
        language = str(track.get("languageCode", ""))
        cues = self._client.get(base_url)
        if cues.outcome != OUTCOME_OK:
            return TranscriptResult(
                video_id, watch_url, cues.outcome, title=title, language=language,
                reason=cues.reason, evidence_level=self._evidence_level,
            )
        segments = self._parse_cues(cues.text)
        text = " ".join(s.text for s in segments).strip()
        outcome = OUTCOME_OK if text else OUTCOME_SKIPPED
        return TranscriptResult(
            video_id, watch_url, outcome, title=title, language=language,
            text=text, segments=segments,
            reason=None if text else "transcript was empty",
            evidence_level=self._evidence_level,
        )

    def _pick_track(self, tracks: list[dict]) -> dict | None:
        if not tracks:
            return None
        for lang in self._languages:
            for track in tracks:
                if str(track.get("languageCode", "")).lower().startswith(lang):
                    return track
        return tracks[0]

    @staticmethod
    def _parse_cues(xml_text: str) -> list[TranscriptSegment]:
        segments: list[TranscriptSegment] = []
        for start, dur, body in _CUE_RE.findall(xml_text):
            text = html.unescape(_TAG_RE.sub("", body)).replace("\n", " ").strip()
            if text:
                segments.append(
                    TranscriptSegment(
                        start=float(start),
                        duration=float(dur) if dur else 0.0,
                        text=text,
                    )
                )
        return segments

    @staticmethod
    def _title(page: str) -> str:
        m = _TITLE_RE.search(page)
        if m:
            try:
                return json.loads(f'"{m.group(1)}"')
            except Exception:  # noqa: BLE001
                return m.group(1)
        return ""

    @staticmethod
    def _video_id(value: str) -> str:
        if not value:
            return ""
        if _ID_RE.match(value):
            return value
        parsed = urlparse(value)
        host = parsed.netloc.lower()
        if "youtu.be" in host:
            candidate = parsed.path.lstrip("/").split("/")[0]
            return candidate if _ID_RE.match(candidate) else ""
        if "youtube" in host:
            qs = parse_qs(parsed.query)
            if qs.get("v") and _ID_RE.match(qs["v"][0]):
                return qs["v"][0]
            for prefix in ("/shorts/", "/embed/", "/v/"):
                if parsed.path.startswith(prefix):
                    candidate = parsed.path[len(prefix):].split("/")[0]
                    return candidate if _ID_RE.match(candidate) else ""
        return ""
