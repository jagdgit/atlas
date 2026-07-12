"""YouTube plugin (S18a): video URL/id → transcript text.

Exposes one tool:
    youtube.transcript(video)
        -> {"video_id", "url", "outcome", "title", "language", "text",
            "segments": [...], "reason", "evidence_level"}

Registered as the ``transcript`` capability. Built on the resilient net layer, so a
private/blocked video or one without captions returns an honest outcome
(`skipped`/`blocked`/`error`) rather than raising (R2/R3). Transcripts are informal
sources ⇒ **L1** evidence (§5a.2).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.net import FetchClient
from atlas.plugins.base import BasePlugin
from atlas.services.base import HealthStatus
from atlas.transcripts import YouTubeTranscriptProvider

if TYPE_CHECKING:
    from atlas.config import AtlasConfig
    from atlas.kernel.application import Application


class YouTubePlugin(BasePlugin):
    name = "youtube"
    version = "0.1.0"

    def __init__(
        self,
        provider: YouTubeTranscriptProvider,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._provider = provider
        self._logger = logger or logging.getLogger("atlas.plugins.youtube")

    def register(self, kernel: "Application") -> None:
        from atlas.capabilities import CAP_TRANSCRIPT, TranscriptCapability

        kernel.capabilities.register(
            CAP_TRANSCRIPT, self, contract=TranscriptCapability, kind="plugin"
        )
        kernel.tools.register(
            "youtube.transcript",
            self.youtube_transcript,
            description="Fetch the transcript of a YouTube video (URL or id).",
            params={"video": "YouTube URL or 11-char video id"},
            plugin=self.name,
        )

    # --- capability -----------------------------------------------------
    def get_transcript(self, video: str) -> dict[str, Any]:
        return self._provider.fetch(video).as_dict()

    def youtube_transcript(self, video: str) -> dict[str, Any]:
        return self.get_transcript(video)

    def health_check(self) -> HealthStatus:
        return HealthStatus.ok("youtube transcript provider ready")


def build(config: "AtlasConfig") -> YouTubePlugin:
    net = config.net
    yt = config.plugins.youtube
    client = FetchClient(
        user_agent=net.user_agent,
        timeout=net.timeout,
        max_bytes=net.max_bytes,
        per_domain_delay=net.per_domain_delay,
        max_retries=net.max_retries,
        backoff_base=net.backoff_base,
        backoff_cap=net.backoff_cap,
        jitter=net.jitter,
        respect_robots=net.respect_robots,
        cache_ttl=net.cache_ttl,
    )
    provider = YouTubeTranscriptProvider(client, languages=yt.languages)
    return YouTubePlugin(provider)
