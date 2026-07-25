"""Cloud STT engine stub (OI-M5).

Pluggable behind ``SpeechEngine``. Default path stays local Whisper. This stub
never opens a network socket: without an API key env var it reports unavailable;
with a key it still refuses live calls until a real provider is wired.
"""

from __future__ import annotations

import os
from typing import Any

from atlas.speech.engine import SpeechUnavailable


class CloudSttEngine:
    """Credential-gated cloud STT placeholder (no live HTTP)."""

    name = "cloud_stt"

    def __init__(
        self,
        *,
        provider: str = "",
        api_key_env: str = "ATLAS_SPEECH_API_KEY",
    ) -> None:
        self.provider = str(provider or "").strip() or "unspecified"
        self.api_key_env = str(api_key_env or "ATLAS_SPEECH_API_KEY")

    def available(self) -> bool:
        return bool(os.environ.get(self.api_key_env, "").strip())

    def transcribe(
        self, path: str, *, model: str, language: str | None
    ) -> dict[str, Any]:
        if not self.available():
            raise SpeechUnavailable(
                f"cloud STT unavailable (set {self.api_key_env}; "
                f"provider={self.provider})"
            )
        # Seam only — live providers are intentionally not implemented here.
        raise SpeechUnavailable(
            f"cloud STT provider {self.provider!r} not implemented "
            "(OI-M5 stub — no live API calls)"
        )


def build_speech_engine(speech_cfg: Any) -> Any:
    """Select Whisper vs cloud stub from ``plugins.speech`` config."""
    from atlas.speech.engine import WhisperEngine

    engine_name = str(getattr(speech_cfg, "engine", "whisper") or "whisper").lower()
    if engine_name in {"cloud", "cloud_stt", "api"}:
        return CloudSttEngine(
            provider=str(getattr(speech_cfg, "provider", "") or ""),
            api_key_env=str(
                getattr(speech_cfg, "api_key_env", "ATLAS_SPEECH_API_KEY")
                or "ATLAS_SPEECH_API_KEY"
            ),
        )
    return WhisperEngine(
        binary=str(getattr(speech_cfg, "binary", "whisper") or "whisper"),
        timeout=float(getattr(speech_cfg, "timeout", 0.0) or 0.0),
    )
