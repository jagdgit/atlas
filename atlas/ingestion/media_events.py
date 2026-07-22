"""Media Reader Family events (M.7).

Typed event names emitted by MediaIngestor / Librarian video path so jobs and the
operator console can distinguish *acquisition/read* outcomes from reasoning gaps.
"""

from __future__ import annotations

from typing import Any, Protocol


class _Emitter(Protocol):
    def emit(
        self, event_type: str, payload: dict[str, Any], *, source: str | None = None
    ) -> Any: ...


EVENT_MEDIA_METADATA_ACQUIRED = "MediaMetadataAcquired"
EVENT_TRANSCRIPT_ACQUIRED = "TranscriptAcquired"
EVENT_SPEECH_TO_TEXT_GAP = "SpeechToTextGap"
EVENT_MEDIA_READ_FAILED = "MediaReadFailed"

MEDIA_EVENT_SOURCE = "media"


def emit_media_event(
    events: _Emitter | None,
    event_type: str,
    payload: dict[str, Any],
    *,
    source: str = MEDIA_EVENT_SOURCE,
) -> None:
    """Best-effort emit — never raises into the media pipeline."""
    if events is None:
        return
    try:
        events.emit(event_type, payload, source=source)
    except Exception:  # noqa: BLE001
        return
