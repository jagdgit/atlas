"""Transcript extraction (Stage 2, S18a) — spoken-word sources for research.

Turns a video (YouTube today) into text Atlas can read, summarise, or ingest. Built on
the resilient net layer so a missing/blocked transcript degrades to an outcome instead
of crashing the job (R2/R3). Transcripts are informal sources ⇒ **L1** evidence (§5a.2).
"""

from __future__ import annotations

from atlas.transcripts.youtube import (
    TranscriptResult,
    TranscriptSegment,
    YouTubeTranscriptProvider,
)

__all__ = ["YouTubeTranscriptProvider", "TranscriptResult", "TranscriptSegment"]
