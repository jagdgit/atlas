"""Live caption ingest plugin (OI-M3)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.live_captions.buffer import LiveCaptionClient
from atlas.plugins.base import BasePlugin
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.config import AtlasConfig
    from atlas.kernel.application import Application


class LiveCaptionsPlugin(BasePlugin):
    name = "live_captions"
    version = "0.1.0"

    def __init__(
        self, client: LiveCaptionClient, *, logger: logging.Logger | None = None
    ) -> None:
        self._client = client
        self._logger = logger or logging.getLogger("atlas.plugins.live_captions")

    def register(self, kernel: "Application") -> None:
        from atlas.capabilities import (
            CAP_LIVE_CAPTION_INGEST,
            LiveCaptionIngestCapability,
        )

        kernel.capabilities.register(
            CAP_LIVE_CAPTION_INGEST,
            self,
            contract=LiveCaptionIngestCapability,
            kind="plugin",
        )
        kernel.tools.register(
            "media.live_caption_open",
            self.open,
            description="Open a live caption session (chunk ingest; no livestream client).",
            params={"session_id": "optional id", "source_uri": "optional", "title": "optional"},
            plugin=self.name,
        )
        kernel.tools.register(
            "media.live_caption_append",
            self.append,
            description="Append a caption chunk to a live session.",
            params={"session_id": "session id", "text": "caption text", "start": "optional", "end": "optional"},
            plugin=self.name,
        )
        kernel.tools.register(
            "media.live_caption_finalize",
            self.finalize,
            description="Finalize a live caption session into transcript text/VTT.",
            params={"session_id": "session id"},
            plugin=self.name,
        )

    def open(
        self,
        session_id: str | None = None,
        source_uri: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        return self._client.open(session_id, source_uri=source_uri, title=title)

    def append(
        self,
        session_id: str,
        text: str = "",
        start: float | None = None,
        end: float | None = None,
        speaker: str | None = None,
    ) -> dict[str, Any]:
        chunk: dict[str, Any] = {"text": text}
        if start is not None:
            chunk["start"] = start
        if end is not None:
            chunk["end"] = end
        if speaker:
            chunk["speaker"] = speaker
        return self._client.append(session_id, chunk)

    def finalize(self, session_id: str) -> dict[str, Any]:
        return self._client.finalize(session_id)

    def health_check(self) -> HealthStatus:
        enabled = self._client.enabled
        detail = (
            "live_caption_ingest ready (chunk buffer)"
            if enabled
            else "live_caption_ingest disabled (plugins.live_captions.enabled=false)"
        )
        return HealthStatus(
            healthy=True,
            detail=detail,
            data={"enabled": enabled},
        )


def build(config: "AtlasConfig") -> LiveCaptionsPlugin:
    cfg = getattr(config.plugins, "live_captions", None)
    enabled = bool(getattr(cfg, "enabled", False)) if cfg is not None else False
    return LiveCaptionsPlugin(LiveCaptionClient(enabled=enabled))
