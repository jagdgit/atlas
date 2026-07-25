"""Speaker diarization plugin (OI-M2).

Exposes ``speaker_diarization`` capability + tool. Default **off**.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.diarization.engine import DiarizationClient, LabelPreservingEngine
from atlas.plugins.base import BasePlugin
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.config import AtlasConfig
    from atlas.kernel.application import Application


class DiarizationPlugin(BasePlugin):
    name = "diarization"
    version = "0.1.0"

    def __init__(
        self, client: DiarizationClient, *, logger: logging.Logger | None = None
    ) -> None:
        self._client = client
        self._logger = logger or logging.getLogger("atlas.plugins.diarization")

    def register(self, kernel: "Application") -> None:
        from atlas.capabilities import (
            CAP_SPEAKER_DIARIZATION,
            SpeakerDiarizationCapability,
        )

        kernel.capabilities.register(
            CAP_SPEAKER_DIARIZATION,
            self,
            contract=SpeakerDiarizationCapability,
            kind="plugin",
        )
        kernel.tools.register(
            "speech.diarize",
            self.diarize,
            description=(
                "Assign speaker labels on transcript segments "
                "(label-preserving; ML diarization opt-in later)."
            ),
            params={
                "segments": "optional list of {start,end,text,speaker?}",
                "text": "optional full transcript text",
                "path": "optional audio path for future ML engines",
            },
            plugin=self.name,
        )

    def diarize(
        self,
        path: str | None = None,
        segments: list[dict[str, Any]] | None = None,
        text: str = "",
    ) -> dict[str, Any]:
        return self._client.diarize(path, segments=segments, text=text)

    def health_check(self) -> HealthStatus:
        enabled = self._client.enabled
        ready = self._client.available()
        if not enabled:
            detail = "speaker_diarization disabled (plugins.diarization.enabled=false)"
        elif ready:
            detail = f"speaker_diarization ready (engine={self._client.model})"
        else:
            detail = "speaker_diarization unavailable"
        return HealthStatus(
            healthy=True,
            detail=detail,
            data={"enabled": enabled, "available": ready, "model": self._client.model},
        )


def build(config: "AtlasConfig") -> DiarizationPlugin:
    dia = getattr(config.plugins, "diarization", None)
    enabled = bool(getattr(dia, "enabled", False)) if dia is not None else False
    client = DiarizationClient(LabelPreservingEngine(), enabled=enabled)
    return DiarizationPlugin(client)
