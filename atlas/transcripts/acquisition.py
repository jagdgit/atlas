"""Structured media/transcript acquisition records (Media Reader Family · M.1).

An **acquisition failure is not a reasoning failure**. When Atlas cannot obtain bytes or a
transcript, the Reader never starts — Knowledge must not be fabricated (P15). This module
defines a small, stable taxonomy + ``AcquisitionRecord`` so job reports, the assistant, and
(later) ``ReaderStrategyChain`` (M.2) all speak the same language:

    stage=acquire → strategies_tried[] → outcome + reason_code + bytes_read
    → operator_summary ("acquisition failed before read: …")

M.1 instruments acquisition honesty; M.2 runs strategies through ``ReaderStrategyChain``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --- reason codes (stable; reports + tests key on these) -----------------

REASON_OK = "ok"
REASON_ROBOTS_DISALLOWED = "robots_disallowed"
REASON_NO_CAPTIONS = "no_captions"
REASON_EMPTY_TRANSCRIPT = "empty_transcript"
REASON_BAD_VIDEO_ID = "bad_video_id"
REASON_RATE_LIMITED = "rate_limited"
REASON_PRIVATE_OR_UNAVAILABLE = "private_or_unavailable"
REASON_FETCH_FAILED = "fetch_failed"
REASON_PARSE_ERROR = "parse_error"
REASON_STRATEGY_NOT_ATTEMPTED = "strategy_not_attempted"
REASON_UNKNOWN = "unknown"

STAGE_ACQUIRE = "acquire"

# Strategy names (M.1 single caption scrape; M.2 adds watch-page + per-language variants).
STRATEGY_YOUTUBE_CAPTION_TRACKS = "youtube_caption_tracks"
STRATEGY_YOUTUBE_WATCH_PAGE = "youtube_watch_page"
STRATEGY_YOUTUBE_CAPTION_ANY = "youtube_caption_tracks:any"


@dataclass(frozen=True)
class AcquisitionAttempt:
    """One strategy invocation inside an acquisition pass."""

    strategy: str
    outcome: str
    reason: str | None = None
    reason_code: str = REASON_UNKNOWN
    bytes_read: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "outcome": self.outcome,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "bytes_read": int(self.bytes_read or 0),
        }


@dataclass(frozen=True)
class AcquisitionRecord:
    """Explainable acquisition result — suitable for pipeline traces and tool payloads."""

    stage: str = STAGE_ACQUIRE
    outcome: str = "error"
    reason_code: str = REASON_UNKNOWN
    reason: str | None = None
    bytes_read: int = 0
    strategies_tried: tuple[AcquisitionAttempt, ...] = ()
    source_url: str = ""
    source_kind: str = "video"
    suggested_next_capability: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == "ok"

    @property
    def operator_summary(self) -> str:
        """Human-facing one-liner: distinguishes acquire-stop from reasoning failure."""
        if self.ok:
            n = len(self.strategies_tried)
            return (
                f"Acquisition succeeded ({self.bytes_read} B read"
                + (f", {n} strateg{'y' if n == 1 else 'ies'}" if n else "")
                + ")."
            )
        detail = self.reason or self.reason_code or self.outcome
        tried = ", ".join(a.strategy for a in self.strategies_tried) or "none"
        hint = ""
        if self.suggested_next_capability:
            hint = f" Suggested next capability: {self.suggested_next_capability}."
        return (
            f"Acquisition failed before read ({self.outcome}/{self.reason_code}): {detail}. "
            f"Strategies tried: {tried}. "
            f"No document was fabricated.{hint}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "outcome": self.outcome,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "bytes_read": int(self.bytes_read or 0),
            "strategies_tried": [a.as_dict() for a in self.strategies_tried],
            "source_url": self.source_url,
            "source_kind": self.source_kind,
            "suggested_next_capability": self.suggested_next_capability,
            "operator_summary": self.operator_summary,
            "read_started": False if not self.ok else True,
        }

    @classmethod
    def from_attempts(
        cls,
        attempts: list[AcquisitionAttempt],
        *,
        source_url: str = "",
        source_kind: str = "video",
        suggested_next_capability: str | None = None,
    ) -> "AcquisitionRecord":
        """Build a record from ordered attempts: first ``ok`` wins; else last failure."""
        if not attempts:
            return cls(
                outcome="skipped",
                reason_code=REASON_STRATEGY_NOT_ATTEMPTED,
                reason="no acquisition strategy was attempted",
                source_url=source_url,
                source_kind=source_kind,
                suggested_next_capability=suggested_next_capability,
            )
        winner = next((a for a in attempts if a.outcome == "ok"), None)
        chosen = winner or attempts[-1]
        return cls(
            outcome=chosen.outcome,
            reason_code=chosen.reason_code,
            reason=chosen.reason,
            bytes_read=sum(a.bytes_read for a in attempts),
            strategies_tried=tuple(attempts),
            source_url=source_url,
            source_kind=source_kind,
            suggested_next_capability=(
                None if winner else suggested_next_capability
            ),
        )

    @classmethod
    def not_attempted(
        cls,
        *,
        source_url: str = "",
        reason: str = "transcript acquisition not wired for this source",
    ) -> "AcquisitionRecord":
        return cls(
            outcome="skipped",
            reason_code=REASON_STRATEGY_NOT_ATTEMPTED,
            reason=reason,
            source_url=source_url,
            source_kind="video",
        )


def normalize_reason_code(outcome: str, reason: str | None) -> str:
    """Map net/provider outcome + free-text reason onto the stable taxonomy."""
    text = (reason or "").lower()
    if outcome == "ok":
        return REASON_OK
    if "robots.txt" in text or "disallows" in text:
        return REASON_ROBOTS_DISALLOWED
    if "429" in text or "rate" in text:
        return REASON_RATE_LIMITED
    if "video id" in text or "could not parse" in text:
        return REASON_BAD_VIDEO_ID
    if "no caption" in text or "no usable caption" in text:
        return REASON_NO_CAPTIONS
    if "empty" in text and "transcript" in text:
        return REASON_EMPTY_TRANSCRIPT
    if "private" in text or "unavailable" in text:
        return REASON_PRIVATE_OR_UNAVAILABLE
    if outcome == "blocked":
        return REASON_RATE_LIMITED if "429" in text else REASON_PRIVATE_OR_UNAVAILABLE
    if outcome == "skipped":
        if "caption" in text:
            return REASON_NO_CAPTIONS
        if "robots" in text:
            return REASON_ROBOTS_DISALLOWED
        return REASON_FETCH_FAILED
    if outcome == "error":
        if "video id" in text:
            return REASON_BAD_VIDEO_ID
        return REASON_PARSE_ERROR if "parse" in text or "extract" in text else REASON_FETCH_FAILED
    return REASON_UNKNOWN
