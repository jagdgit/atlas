"""Speech package (Media Reader Family · M.5) — optional local STT."""

from __future__ import annotations

from atlas.speech.engine import (
    CAPABILITY_GAP,
    STT_EMPTY,
    STT_ERROR,
    STT_OK,
    STT_UNAVAILABLE,
    SpeechClient,
    SpeechEngineError,
    SpeechUnavailable,
    WhisperEngine,
)

__all__ = [
    "CAPABILITY_GAP",
    "STT_EMPTY",
    "STT_ERROR",
    "STT_OK",
    "STT_UNAVAILABLE",
    "SpeechClient",
    "SpeechEngineError",
    "SpeechUnavailable",
    "WhisperEngine",
]
