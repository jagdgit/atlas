"""Speaker diarization client + engines (OI-M2).

Assigns ``speaker`` labels on transcript segments. Default **off**
(``plugins.diarization.enabled``). Without a real ML engine, the label-preserving
path keeps explicit caption/STT speaker tags; missing/disabled → P15
``capability_gap: speaker_diarization`` (never invents speakers).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

DIA_OK = "ok"
DIA_EMPTY = "empty"
DIA_UNAVAILABLE = "unavailable"
DIA_ERROR = "error"

CAPABILITY_GAP = "speaker_diarization"

_SPEAKER_PREFIX = re.compile(
    r"^\s*(?:\[(?P<brack>[^\]]+)\]|(?P<plain>SPEAKER[_\-\s]?\d+|Speaker\s+\d+|[A-Z][a-z]+))\s*[:\-]\s*",
    re.IGNORECASE,
)


class DiarizationEngine(Protocol):
    name: str

    def available(self) -> bool: ...

    def diarize(
        self, path: str | None, *, segments: list[dict[str, Any]], text: str = ""
    ) -> dict[str, Any]:
        """Return ``{segments, speakers, model}``. Raise on hard failure."""
        ...


class LabelPreservingEngine:
    """Hermetic engine: keep existing ``speaker`` fields or parse ``Name: text`` prefixes."""

    name = "label_preserving"

    def available(self) -> bool:
        return True

    def diarize(
        self, path: str | None, *, segments: list[dict[str, Any]], text: str = ""
    ) -> dict[str, Any]:
        out_segs: list[dict[str, Any]] = []
        speakers: list[str] = []
        seen: set[str] = set()
        for seg in segments or []:
            row = dict(seg) if isinstance(seg, dict) else {"text": str(seg)}
            speaker = str(row.get("speaker") or "").strip()
            body = str(row.get("text") or "")
            if not speaker and body:
                m = _SPEAKER_PREFIX.match(body)
                if m:
                    speaker = (m.group("brack") or m.group("plain") or "").strip()
                    row["text"] = body[m.end() :].lstrip()
            if speaker:
                row["speaker"] = speaker
                if speaker not in seen:
                    seen.add(speaker)
                    speakers.append(speaker)
            out_segs.append(row)
        if not speakers and text:
            m = _SPEAKER_PREFIX.match(text)
            if m:
                speakers = [(m.group("brack") or m.group("plain") or "").strip()]
        return {
            "segments": out_segs,
            "speakers": speakers,
            "model": self.name,
            "text": text,
        }


class DiarizationClient:
    """Facade: enabled gate + engine; honest gap when off or no speakers/labels."""

    def __init__(
        self,
        engine: DiarizationEngine | None = None,
        *,
        enabled: bool = False,
        logger: logging.Logger | None = None,
    ) -> None:
        self._engine = engine or LabelPreservingEngine()
        self.enabled = bool(enabled)
        self._logger = logger or logging.getLogger("atlas.diarization")

    @property
    def model(self) -> str:
        return getattr(self._engine, "name", "unknown")

    def available(self) -> bool:
        if not self.enabled:
            return False
        try:
            return bool(self._engine.available())
        except Exception:  # noqa: BLE001
            return False

    def diarize(
        self,
        path: str | None = None,
        *,
        segments: list[dict[str, Any]] | None = None,
        text: str = "",
    ) -> dict[str, Any]:
        base = {
            "outcome": DIA_UNAVAILABLE,
            "text": text or "",
            "segments": list(segments or []),
            "speakers": [],
            "model": None,
            "capability_gap": CAPABILITY_GAP,
            "reason": "",
        }
        if not self.enabled:
            base["reason"] = "speaker_diarization disabled (set plugins.diarization.enabled)"
            return base
        if not self.available():
            base["reason"] = "speaker_diarization unavailable (no engine)"
            return base
        try:
            result = self._engine.diarize(
                path, segments=list(segments or []), text=text or ""
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("diarize failed: %s", exc)
            base["outcome"] = DIA_ERROR
            base["reason"] = str(exc)
            return base

        segs = list(result.get("segments") or [])
        speakers = [str(s) for s in (result.get("speakers") or []) if s]
        if not speakers:
            return {
                "outcome": DIA_EMPTY,
                "text": result.get("text") or text or "",
                "segments": segs,
                "speakers": [],
                "model": result.get("model") or self.model,
                "capability_gap": CAPABILITY_GAP,
                "reason": "no speaker labels found (ML diarization not installed)",
            }
        return {
            "outcome": DIA_OK,
            "text": result.get("text") or text or "",
            "segments": segs,
            "speakers": speakers,
            "model": result.get("model") or self.model,
            "capability_gap": None,
            "reason": None,
        }
