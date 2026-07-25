"""Live / streaming caption ingest (OI-M3).

Append caption chunks into a session buffer, then materialize a transcript
(text + segments / WebVTT). Default **off** (``plugins.live_captions.enabled``).
No livestream client — operators/tests push chunks; missing/disabled → P15 gap.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any


LIVE_OK = "ok"
LIVE_UNAVAILABLE = "unavailable"
LIVE_EMPTY = "empty"
CAPABILITY_GAP = "live_caption_ingest"


@dataclass
class _Session:
    session_id: str
    source_uri: str | None = None
    title: str | None = None
    chunks: list[dict[str, Any]] = field(default_factory=list)
    closed: bool = False


def _fmt_vtt_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def chunks_to_transcript(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Build text + segments + WebVTT from ordered caption chunks."""
    segments: list[dict[str, Any]] = []
    lines: list[str] = []
    t = 0.0
    for i, raw in enumerate(chunks):
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        start = raw.get("start")
        end = raw.get("end")
        if start is None:
            start = raw.get("t", t)
        start_f = float(start or 0.0)
        if end is None:
            end_f = start_f + max(1.0, len(text.split()) * 0.4)
        else:
            end_f = float(end)
        t = end_f
        seg: dict[str, Any] = {"start": start_f, "end": end_f, "text": text, "ordinal": i}
        if raw.get("speaker"):
            seg["speaker"] = str(raw["speaker"])
        segments.append(seg)
        lines.append(text)
    body = "\n".join(lines)
    vtt_lines = ["WEBVTT", ""]
    for i, seg in enumerate(segments, start=1):
        vtt_lines.append(str(i))
        vtt_lines.append(
            f"{_fmt_vtt_ts(float(seg['start']))} --> {_fmt_vtt_ts(float(seg['end']))}"
        )
        speaker = seg.get("speaker")
        cue = f"<v {speaker}>{seg['text']}" if speaker else str(seg["text"])
        vtt_lines.append(cue)
        vtt_lines.append("")
    return {
        "text": body,
        "segments": segments,
        "vtt": "\n".join(vtt_lines).strip() + "\n",
        "chunk_count": len(segments),
    }


class LiveCaptionClient:
    """In-memory live caption sessions with honest capability-gap when disabled."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        assets: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self._assets = assets
        self._sessions: dict[str, _Session] = {}
        self._logger = logger or logging.getLogger("atlas.live_captions")

    def open(
        self,
        session_id: str | None = None,
        *,
        source_uri: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {
                "outcome": LIVE_UNAVAILABLE,
                "capability_gap": CAPABILITY_GAP,
                "reason": "live_caption_ingest disabled (set plugins.live_captions.enabled)",
            }
        sid = str(session_id or uuid.uuid4())
        self._sessions[sid] = _Session(
            session_id=sid, source_uri=source_uri, title=title
        )
        return {"outcome": LIVE_OK, "session_id": sid, "capability_gap": None}

    def append(self, session_id: str, chunk: dict[str, Any] | str) -> dict[str, Any]:
        if not self.enabled:
            return {
                "outcome": LIVE_UNAVAILABLE,
                "capability_gap": CAPABILITY_GAP,
                "reason": "live_caption_ingest disabled",
            }
        sess = self._sessions.get(str(session_id))
        if sess is None or sess.closed:
            return {
                "outcome": LIVE_EMPTY,
                "capability_gap": CAPABILITY_GAP,
                "reason": f"unknown or closed session {session_id!r}",
            }
        payload = {"text": chunk} if isinstance(chunk, str) else dict(chunk or {})
        if not str(payload.get("text") or "").strip():
            return {
                "outcome": LIVE_EMPTY,
                "session_id": sess.session_id,
                "reason": "empty chunk",
                "n_chunks": len(sess.chunks),
            }
        sess.chunks.append(payload)
        return {
            "outcome": LIVE_OK,
            "session_id": sess.session_id,
            "n_chunks": len(sess.chunks),
            "chars": sum(len(str(c.get("text") or "")) for c in sess.chunks),
        }

    def snapshot(self, session_id: str) -> dict[str, Any]:
        return self._materialize(session_id, close=False)

    def finalize(self, session_id: str) -> dict[str, Any]:
        return self._materialize(session_id, close=True)

    def _materialize(self, session_id: str, *, close: bool) -> dict[str, Any]:
        if not self.enabled:
            return {
                "outcome": LIVE_UNAVAILABLE,
                "capability_gap": CAPABILITY_GAP,
                "reason": "live_caption_ingest disabled",
            }
        sess = self._sessions.get(str(session_id))
        if sess is None:
            return {
                "outcome": LIVE_EMPTY,
                "capability_gap": CAPABILITY_GAP,
                "reason": f"unknown session {session_id!r}",
            }
        built = chunks_to_transcript(sess.chunks)
        if not built["text"].strip():
            out = {
                "outcome": LIVE_EMPTY,
                "session_id": sess.session_id,
                "capability_gap": CAPABILITY_GAP,
                "reason": "no caption chunks",
                **built,
            }
        else:
            out = {
                "outcome": LIVE_OK,
                "session_id": sess.session_id,
                "source_uri": sess.source_uri,
                "title": sess.title,
                "strategy": "live_caption_chunks",
                "capability_gap": None,
                **built,
            }
            asset = self._maybe_register(sess, built)
            if asset:
                out.update(asset)
        if close:
            sess.closed = True
        return out

    def _maybe_register(self, sess: _Session, built: dict[str, Any]) -> dict[str, Any]:
        if self._assets is None or not hasattr(self._assets, "register"):
            return {}
        try:
            name = (sess.title or f"live-captions-{sess.session_id}")[:120]
            row = self._assets.register(
                kind="transcript",
                name=name,
                data=built["vtt"].encode("utf-8"),
                content_type="text/vtt",
                metadata={
                    "filename": f"{name}.vtt",
                    "strategy": "live_caption_chunks",
                    "session_id": sess.session_id,
                    "source_uri": sess.source_uri,
                },
            )
            if isinstance(row, dict):
                return {
                    "asset_id": str(row.get("id") or row.get("asset_id") or ""),
                    "asset_version": int(row.get("version") or 1),
                }
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("live caption asset register skipped: %s", exc)
        return {}
