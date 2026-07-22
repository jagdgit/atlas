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

# Operator recovery actions (Media Report Honesty · RH.1) — prefer these over raw capability ids.
STRATEGY_UPLOAD_TRANSCRIPT = "upload_transcript"
STRATEGY_UPLOAD_LOCAL_MEDIA = "upload_local_media"
STRATEGY_ENABLE_SPEECH_TO_TEXT = "enable_speech_to_text"
STRATEGY_OFFICIAL_CAPTIONS_API = "configure_official_captions_api"

SPEECH_STATUS_READY = "ready"
SPEECH_STATUS_DISABLED = "disabled"
SPEECH_STATUS_MISSING = "missing"

_STRATEGY_LABELS = {
    STRATEGY_UPLOAD_TRANSCRIPT: "transcript available (upload .vtt / .srt / .txt)",
    STRATEGY_UPLOAD_LOCAL_MEDIA: "local media uploaded (.mp4 / .mp3 / …)",
    STRATEGY_ENABLE_SPEECH_TO_TEXT: "speech_to_text enabled and ready (Whisper)",
    STRATEGY_OFFICIAL_CAPTIONS_API: "official captions API configured (when available)",
}


def speech_to_text_status(*, enabled: bool, available: bool) -> str:
    """Distinguish installed-but-off from not-installed (RH5 / R5)."""
    if enabled and available:
        return SPEECH_STATUS_READY
    if enabled and not available:
        return SPEECH_STATUS_MISSING
    if not enabled and available:
        return SPEECH_STATUS_DISABLED
    return SPEECH_STATUS_MISSING


def default_media_recovery_strategies(
    *,
    speech_status: str | None = None,
    include_official_api: bool = True,
) -> tuple[str, ...]:
    """Ordered operator actions after a media acquire-stop (RH4)."""
    out: list[str] = [
        STRATEGY_UPLOAD_TRANSCRIPT,
        STRATEGY_UPLOAD_LOCAL_MEDIA,
        STRATEGY_ENABLE_SPEECH_TO_TEXT,
    ]
    if include_official_api:
        out.append(STRATEGY_OFFICIAL_CAPTIONS_API)
    # If STT is already ready, still list enable as a no-op path is fine — operators
    # may need to re-run after upload. Status is reported separately.
    _ = speech_status
    return tuple(out)


def strategy_label(strategy_id: str) -> str:
    return _STRATEGY_LABELS.get(strategy_id, strategy_id)


def format_next_research_blocked(
    strategies: list[str] | tuple[str, ...] | None = None,
    *,
    speech_status: str | None = None,
) -> str:
    """Operator-facing Next Research copy for Research acquire-stop (RH.1–RH.4)."""
    return format_next_action(
        strategies,
        speech_status=speech_status,
        audience="research",
        status="blocked",
    )


def format_next_action(
    strategies: list[str] | tuple[str, ...] | None = None,
    *,
    speech_status: str | None = None,
    audience: str = "job",
    status: str = "waiting",
) -> str:
    """Operator-facing next steps for acquire termination (RH.5 / RH9–RH10).

    ``audience=job`` → "Waiting for operator" / Next Action semantics.
    ``audience=research`` → "Research blocked" (legacy Research report wording).
    """
    actions = list(strategies) if strategies else list(default_media_recovery_strategies())
    if audience == "research":
        lines = ["Research blocked.", "", "Continue after one of:"]
    elif status == "waiting":
        lines = ["Waiting for operator.", "", "Continue after one of:"]
    else:
        lines = ["Blocked.", "", "Continue after one of:"]
    for sid in actions:
        lines.append(f"• {strategy_label(sid)}")
    if speech_status:
        lines.append("")
        lines.append(f"speech_to_text status: {speech_status}")
    return "\n".join(lines)


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
    suggested_next_strategies: tuple[str, ...] = ()
    speech_to_text_status: str | None = None

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
        if self.suggested_next_strategies:
            labels = "; ".join(strategy_label(s) for s in self.suggested_next_strategies[:4])
            hint = f" Suggested next strategies: {labels}."
            if self.speech_to_text_status:
                hint += f" speech_to_text status: {self.speech_to_text_status}."
        elif self.suggested_next_capability:
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
            "suggested_next_strategies": list(self.suggested_next_strategies),
            "speech_to_text_status": self.speech_to_text_status,
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
        suggested_next_strategies: tuple[str, ...] | list[str] | None = None,
        speech_to_text_status: str | None = None,
    ) -> "AcquisitionRecord":
        """Build a record from ordered attempts: first ``ok`` wins; else last failure."""
        strategies = tuple(suggested_next_strategies or ())
        if not attempts:
            return cls(
                outcome="skipped",
                reason_code=REASON_STRATEGY_NOT_ATTEMPTED,
                reason="no acquisition strategy was attempted",
                source_url=source_url,
                source_kind=source_kind,
                suggested_next_capability=suggested_next_capability,
                suggested_next_strategies=strategies,
                speech_to_text_status=speech_to_text_status,
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
            suggested_next_strategies=(() if winner else strategies),
            speech_to_text_status=(None if winner else speech_to_text_status),
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
            suggested_next_strategies=default_media_recovery_strategies(),
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
