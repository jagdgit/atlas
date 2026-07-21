"""Speech-to-text plugin (Media Reader Family · M.5).

Exposes the ``speech_to_text`` capability + tool:
    speech.transcribe(path, language=?) -> honest outcome dict

Default **off** (``plugins.speech.enabled: false``). Missing Whisper → degraded health,
never a failed boot (P15 / MD5).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.plugins.base import BasePlugin
from atlas.services.base import HealthStatus
from atlas.speech.engine import SpeechClient, WhisperEngine

if TYPE_CHECKING:
    from atlas.config import AtlasConfig
    from atlas.kernel.application import Application


class SpeechPlugin(BasePlugin):
    name = "speech"
    version = "0.1.0"

    def __init__(self, client: SpeechClient, *, logger: logging.Logger | None = None) -> None:
        self._client = client
        self._logger = logger or logging.getLogger("atlas.plugins.speech")

    def register(self, kernel: "Application") -> None:
        from atlas.capabilities import CAP_SPEECH_TO_TEXT, SpeechToTextCapability

        kernel.capabilities.register(
            CAP_SPEECH_TO_TEXT, self, contract=SpeechToTextCapability, kind="plugin"
        )
        kernel.tools.register(
            "speech.transcribe",
            self.transcribe,
            description="Transcribe speech from a local audio/video file (Whisper).",
            params={
                "path": "path to an audio or video file",
                "language": "optional language code (default: plugins.speech.language)",
            },
            plugin=self.name,
        )

    def transcribe(self, path: str, language: str | None = None) -> dict[str, Any]:
        return self._client.transcribe(path, language=language)

    def health_check(self) -> HealthStatus:
        enabled = self._client.enabled
        ready = self._client.available()
        if not enabled:
            detail = "speech_to_text disabled (plugins.speech.enabled=false)"
        elif ready:
            detail = f"speech_to_text ready (model={self._client.model})"
        else:
            detail = "speech_to_text unavailable (whisper not installed)"
        return HealthStatus(
            healthy=True,  # missing STT is degraded, not failed
            detail=detail,
            data={"enabled": enabled, "available": ready, "model": self._client.model},
        )


def build(config: "AtlasConfig") -> SpeechPlugin:
    speech = config.plugins.speech
    client = SpeechClient(
        WhisperEngine(binary=speech.binary, timeout=speech.timeout),
        enabled=speech.enabled,
        model=speech.model,
        language=speech.language or None,
    )
    return SpeechPlugin(client)
