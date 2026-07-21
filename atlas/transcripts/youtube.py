"""YouTube transcript provider (Stage 2, S18a + Media Reader Family · M.1/M.2).

Two polite fetches through the resilient net layer, never raising (R2/R3):

1. GET the watch page, scrape the ``captionTracks`` list from the embedded player
   response (strategy ``youtube_watch_page``).
2. For each configured language, then ``:any``, try that caption track's timedtext
   via ``ReaderStrategyChain`` (first ``ok`` wins) — M.2 / MD3.

Every failure mode is an **outcome**, not an exception. Every result carries an
``AcquisitionRecord`` with ``strategies_tried[]`` so reports can say *acquisition
failed before read* instead of looking like a reasoning failure (P15).
"""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

from atlas.evidence.models import LEVEL_FORUM, level_name
from atlas.net import OUTCOME_ERROR, OUTCOME_OK, OUTCOME_SKIPPED
from atlas.readers.strategy_chain import ReaderStrategyChain, StrategyResult
from atlas.transcripts.acquisition import (
    REASON_NO_CAPTIONS,
    STRATEGY_YOUTUBE_CAPTION_ANY,
    STRATEGY_YOUTUBE_CAPTION_TRACKS,
    STRATEGY_YOUTUBE_WATCH_PAGE,
    AcquisitionAttempt,
    AcquisitionRecord,
    normalize_reason_code,
)

if TYPE_CHECKING:
    from atlas.net import FetchClient

_CAPTION_TRACKS_RE = re.compile(r'"captionTracks":(\[.*?\])', re.DOTALL)
_TITLE_RE = re.compile(r'"title":"((?:[^"\\]|\\.)*)"')
_CUE_RE = re.compile(r'<text start="([\d.]+)"(?: dur="([\d.]+)")?[^>]*>(.*?)</text>', re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Soft handoff toward M.5 — captions failed; speech_to_text may help later.
_SUGGEST_SPEECH = "speech_to_text"


def _attempt_from_strategy(result: StrategyResult) -> AcquisitionAttempt:
    code = result.reason_code
    if not code or code == "unknown":
        code = normalize_reason_code(result.outcome, result.reason)
    return AcquisitionAttempt(
        strategy=result.name,
        outcome=result.outcome,
        reason=result.reason,
        reason_code=code,
        bytes_read=max(0, int(result.bytes_read or 0)),
    )


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
    acquisition: AcquisitionRecord | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == OUTCOME_OK

    def as_dict(self) -> dict[str, object]:
        acq = self.acquisition or self._default_acquisition()
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
            "bytes_read": acq.bytes_read,
            "strategies_tried": [a.as_dict() for a in acq.strategies_tried],
            "reason_code": acq.reason_code,
            "acquisition": acq.as_dict(),
            "operator_summary": acq.operator_summary,
            "suggested_next_capability": acq.suggested_next_capability,
        }

    def as_source(self) -> dict[str, object]:
        return {
            "id": f"youtube:{self.video_id}",
            "title": self.title or self.video_id,
            "url": self.url,
            "evidence_level": self.evidence_level,
            "kind": "video",
        }

    def _default_acquisition(self) -> AcquisitionRecord:
        code = normalize_reason_code(self.outcome, self.reason)
        attempt = AcquisitionAttempt(
            strategy=STRATEGY_YOUTUBE_CAPTION_TRACKS,
            outcome=self.outcome,
            reason=self.reason,
            reason_code=code,
            bytes_read=len((self.text or "").encode("utf-8")),
        )
        return AcquisitionRecord.from_attempts([attempt], source_url=self.url)


class YouTubeTranscriptProvider:
    name = "youtube"

    def __init__(
        self,
        client: "FetchClient",
        *,
        languages: list[str] | None = None,
        evidence_level: int = LEVEL_FORUM,
        logger: logging.Logger | None = None,
        strategy_chain: ReaderStrategyChain | None = None,
    ) -> None:
        self._client = client
        self._languages = [lang.lower() for lang in (languages or ["en"])]
        self._evidence_level = evidence_level
        self._logger = logger or logging.getLogger("atlas.transcripts.youtube")
        self._chain = strategy_chain or ReaderStrategyChain(logger_=self._logger)

    def fetch(self, url_or_id: str) -> TranscriptResult:
        video_id = self._video_id((url_or_id or "").strip())
        watch_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
        if not video_id:
            reason = "could not parse a YouTube video id"
            attempt = AcquisitionAttempt(
                strategy=STRATEGY_YOUTUBE_WATCH_PAGE,
                outcome=OUTCOME_ERROR,
                reason=reason,
                reason_code=normalize_reason_code(OUTCOME_ERROR, reason),
            )
            return self._from_attempts(
                "", url_or_id or "", OUTCOME_ERROR, reason=reason, attempts=[attempt],
            )

        # --- strategy: watch page (must succeed before caption strategies) -------
        page = self._client.get(watch_url)
        page_bytes = self._bytes_of(page)
        if page.outcome != OUTCOME_OK:
            watch_attempt = AcquisitionAttempt(
                strategy=STRATEGY_YOUTUBE_WATCH_PAGE,
                outcome=page.outcome,
                reason=page.reason,
                reason_code=normalize_reason_code(page.outcome, page.reason),
                bytes_read=page_bytes,
            )
            return self._from_attempts(
                video_id, watch_url, page.outcome, reason=page.reason,
                attempts=[watch_attempt],
            )

        title = self._title(page.text)
        tracks_match = _CAPTION_TRACKS_RE.search(page.text)
        if not tracks_match:
            reason = "no captions available for this video"
            no_cap = AcquisitionAttempt(
                strategy=STRATEGY_YOUTUBE_CAPTION_TRACKS,
                outcome=OUTCOME_SKIPPED,
                reason=reason,
                reason_code=REASON_NO_CAPTIONS,
                bytes_read=page_bytes,
            )
            return self._from_attempts(
                video_id, watch_url, OUTCOME_SKIPPED, title=title, reason=reason,
                attempts=[no_cap],
                suggested_next=_SUGGEST_SPEECH,
            )

        try:
            tracks = json.loads(tracks_match.group(1))
        except Exception as exc:  # noqa: BLE001
            self._logger.exception("youtube captionTracks parse failed")
            bad = AcquisitionAttempt(
                strategy=STRATEGY_YOUTUBE_CAPTION_TRACKS,
                outcome=OUTCOME_ERROR,
                reason=str(exc),
                reason_code=normalize_reason_code(OUTCOME_ERROR, str(exc)),
                bytes_read=page_bytes,
            )
            return self._from_attempts(
                video_id, watch_url, OUTCOME_ERROR, title=title, reason=str(exc),
                attempts=[bad],
            )

        if not tracks:
            reason = "no usable caption track"
            no_cap = AcquisitionAttempt(
                strategy=STRATEGY_YOUTUBE_CAPTION_TRACKS,
                outcome=OUTCOME_SKIPPED,
                reason=reason,
                reason_code=REASON_NO_CAPTIONS,
                bytes_read=page_bytes,
            )
            return self._from_attempts(
                video_id, watch_url, OUTCOME_SKIPPED, title=title, reason=reason,
                attempts=[no_cap],
                suggested_next=_SUGGEST_SPEECH,
            )

        # --- ReaderStrategyChain: per-language caption strategies, then :any -----
        tried_langs: set[str] = set()
        strategies: list[tuple[str, Any]] = []
        for lang in self._languages:
            name = f"{STRATEGY_YOUTUBE_CAPTION_TRACKS}:{lang}"
            strategies.append(
                (name, self._caption_strategy(tracks, lang, page_bytes, tried_langs))
            )
        strategies.append(
            (
                STRATEGY_YOUTUBE_CAPTION_ANY,
                self._caption_strategy(tracks, None, page_bytes, tried_langs),
            )
        )

        chain = self._chain.execute(
            strategies,
            source_url=watch_url,
            source_kind="video",
            suggested_next_capability=_SUGGEST_SPEECH,
        )
        # Watch-page success is setup, not a winning "ok" attempt (would mask caption failure).
        attempts = [_attempt_from_strategy(r) for r in chain.tried]
        if chain.ok and chain.winner is not None:
            payload = chain.winner.value or {}
            return self._from_attempts(
                video_id, watch_url, OUTCOME_OK, title=title,
                language=str(payload.get("language") or ""),
                text=str(payload.get("text") or ""),
                segments=list(payload.get("segments") or []),
                attempts=attempts,
            )

        # All caption strategies failed — merge into one acquisition record.
        acq = AcquisitionRecord.from_attempts(
            attempts,
            source_url=watch_url,
            source_kind="video",
            suggested_next_capability=_SUGGEST_SPEECH,
        )
        return TranscriptResult(
            video_id, watch_url, acq.outcome, title=title,
            reason=acq.reason, evidence_level=self._evidence_level, acquisition=acq,
        )

    # --- caption strategy factory ---------------------------------------
    def _caption_strategy(
        self,
        tracks: list[dict],
        lang: str | None,
        page_bytes: int,
        tried_langs: set[str],
    ):
        def run() -> StrategyResult:
            track = self._find_track(tracks, lang, tried_langs)
            if track is None:
                reason = (
                    f"no caption track for language {lang!r}"
                    if lang
                    else "no remaining caption track"
                )
                return StrategyResult(
                    name="",
                    outcome=OUTCOME_SKIPPED,
                    reason=reason,
                    reason_code=REASON_NO_CAPTIONS,
                    bytes_read=page_bytes,
                )
            code = str(track.get("languageCode", "")).lower()
            if code:
                tried_langs.add(code)
            base_url = str(track.get("baseUrl") or "").replace("\\u0026", "&")
            if not base_url:
                return StrategyResult(
                    name="",
                    outcome=OUTCOME_SKIPPED,
                    reason="caption track missing baseUrl",
                    reason_code=REASON_NO_CAPTIONS,
                    bytes_read=page_bytes,
                )
            cues = self._client.get(base_url)
            cue_bytes = self._bytes_of(cues)
            total = page_bytes + cue_bytes
            language = str(track.get("languageCode", ""))
            if cues.outcome != OUTCOME_OK:
                return StrategyResult(
                    name="",
                    outcome=cues.outcome,
                    reason=cues.reason,
                    reason_code=normalize_reason_code(cues.outcome, cues.reason),
                    bytes_read=total,
                )
            segments = self._parse_cues(cues.text)
            text = " ".join(s.text for s in segments).strip()
            if not text:
                return StrategyResult(
                    name="",
                    outcome=OUTCOME_SKIPPED,
                    reason="transcript was empty",
                    reason_code=normalize_reason_code(OUTCOME_SKIPPED, "transcript was empty"),
                    bytes_read=total,
                )
            return StrategyResult(
                name="",
                outcome=OUTCOME_OK,
                reason_code="ok",
                bytes_read=total,
                value={"text": text, "segments": segments, "language": language},
            )

        return run

    def _find_track(
        self,
        tracks: list[dict],
        lang: str | None,
        tried_langs: set[str],
    ) -> dict | None:
        if lang:
            for track in tracks:
                code = str(track.get("languageCode", "")).lower()
                if code.startswith(lang):
                    return track
            return None
        for track in tracks:
            code = str(track.get("languageCode", "")).lower()
            if code and code in tried_langs:
                continue
            if track.get("baseUrl"):
                return track
        # Last resort: first track with a baseUrl even if already tried.
        for track in tracks:
            if track.get("baseUrl"):
                return track
        return None

    def _from_attempts(
        self,
        video_id: str,
        url: str,
        outcome: str,
        *,
        title: str = "",
        language: str = "",
        text: str = "",
        segments: list[TranscriptSegment] | None = None,
        reason: str | None = None,
        attempts: list[AcquisitionAttempt],
        suggested_next: str | None = None,
    ) -> TranscriptResult:
        acq = AcquisitionRecord.from_attempts(
            attempts,
            source_url=url,
            source_kind="video",
            suggested_next_capability=suggested_next if outcome != OUTCOME_OK else None,
        )
        return TranscriptResult(
            video_id, url, outcome, title=title, language=language, text=text,
            segments=list(segments or []), reason=reason,
            evidence_level=self._evidence_level, acquisition=acq,
        )

    @staticmethod
    def _bytes_of(fetch_result: object) -> int:
        content = getattr(fetch_result, "content", None)
        if isinstance(content, (bytes, bytearray)) and content:
            return len(content)
        text = getattr(fetch_result, "text", None) or ""
        return len(str(text).encode("utf-8"))

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
