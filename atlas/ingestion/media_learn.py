"""``media.learn`` orchestrator — one semantic step, multi-strategy journal (MO*).

Job/Assistant (and later Research) call this instead of a lone ``youtube.transcript``
tool. Automatic strategies run until spoken content is acquired or exhausted;
interactive recovery (upload / local path) is suggested only — never invented.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from atlas.ingestion.browser_captions import (
    STRATEGY_BROWSER_DOM_CAPTIONS,
    browser_dom_captions,
)
from atlas.ingestion.source_fetch import is_youtube_url
from atlas.transcripts.acquisition import (
    REASON_OK,
    REASON_STRATEGY_NOT_ATTEMPTED,
    REASON_UNKNOWN,
    STRATEGY_OFFICIAL_CAPTIONS_API,
    AcquisitionAttempt,
    AcquisitionRecord,
    default_media_recovery_strategies,
)

CaptionFetch = Callable[[str], Any]
SpeechStatusFn = Callable[[], str]
BrowserRender = Callable[[str], dict[str, Any]]


def _payload(result: Any) -> dict[str, Any]:
    if result is None:
        return {}
    if isinstance(result, dict):
        return result
    as_dict = getattr(result, "as_dict", None)
    if callable(as_dict):
        data = as_dict()
        return data if isinstance(data, dict) else {}
    return {}


def _attempts_from_caption(payload: dict[str, Any]) -> list[AcquisitionAttempt]:
    acq = payload.get("acquisition") or {}
    tried = acq.get("strategies_tried") or []
    out: list[AcquisitionAttempt] = []
    for row in tried:
        if not isinstance(row, dict):
            continue
        out.append(
            AcquisitionAttempt(
                strategy=str(row.get("strategy") or "youtube_caption"),
                outcome=str(row.get("outcome") or "error"),
                reason=row.get("reason"),
                reason_code=str(row.get("reason_code") or REASON_UNKNOWN),
                bytes_read=int(row.get("bytes_read") or 0),
            )
        )
    if out:
        return out
    return [
        AcquisitionAttempt(
            strategy="youtube_caption_tracks",
            outcome=str(payload.get("outcome") or "error"),
            reason=payload.get("reason"),
            reason_code=str(payload.get("reason_code") or REASON_UNKNOWN),
            bytes_read=int(payload.get("bytes_read") or 0),
        )
    ]


def _attempts_from_fetch(fetch: dict[str, Any] | None) -> list[AcquisitionAttempt]:
    if not fetch:
        return []
    out: list[AcquisitionAttempt] = []
    for row in fetch.get("strategies_tried") or []:
        if not isinstance(row, dict):
            continue
        out.append(
            AcquisitionAttempt(
                strategy=str(row.get("name") or row.get("strategy") or "source_fetch"),
                outcome=str(row.get("outcome") or "error"),
                reason=row.get("reason"),
                reason_code=str(row.get("reason_code") or REASON_UNKNOWN),
                bytes_read=int(row.get("bytes_read") or 0),
            )
        )
    if out:
        return out
    return [
        AcquisitionAttempt(
            strategy="source_fetch",
            outcome=str(fetch.get("outcome") or "error"),
            reason=fetch.get("reason"),
            reason_code=str(fetch.get("reason_code") or REASON_UNKNOWN),
            bytes_read=int(fetch.get("bytes_read") or 0),
        )
    ]


class MediaLearnOrchestrator:
    """Acquire spoken content → optional Knowledge; journal every automatic strategy."""

    def __init__(
        self,
        *,
        caption_fetch: CaptionFetch | None = None,
        media_ingestor: Any | None = None,
        knowledge: Any | None = None,
        speech_status: SpeechStatusFn | None = None,
        official_captions_api: Callable[[str], Any] | None = None,
        browser_render: BrowserRender | None = None,
        timedtext_fetch: Callable[[str], str] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._caption_fetch = caption_fetch
        self._media = media_ingestor
        self._knowledge = knowledge
        self._speech_status = speech_status
        self._official_api = official_captions_api
        self._browser_render = browser_render
        self._timedtext_fetch = timedtext_fetch
        self._logger = logger or logging.getLogger("atlas.ingestion.media_learn")
        self.calls: list[dict[str, Any]] = []  # hermetic / MO.0–MO.4 instrumentation

    def learn(
        self,
        source: str,
        *,
        to_knowledge: bool = True,
        title: str | None = None,
        domain: str = "external",
        embed: bool = False,
    ) -> dict[str, Any]:
        """Run automatic strategies; return a structured media.learn result."""
        src = (source or "").strip()
        self.calls.append({"source": src, "to_knowledge": to_knowledge})
        attempts: list[AcquisitionAttempt] = []
        speech_status = self._speech_status() if self._speech_status else None
        media_detail: dict[str, Any] | None = None
        caption_detail: dict[str, Any] | None = None

        if not src:
            record = AcquisitionRecord.from_attempts(
                [],
                source_url="",
                suggested_next_strategies=default_media_recovery_strategies(
                    speech_status=speech_status
                ),
                speech_to_text_status=speech_status,
            )
            return self._fail_result(record, interactive=True, reason="missing_source")

        path = Path(src).expanduser()
        is_local = path.is_file()

        # --- captions (YouTube URLs only; local files skip) ---------------
        if not is_local and is_youtube_url(src) and self._caption_fetch is not None:
            try:
                caption_detail = _payload(self._caption_fetch(src))
            except Exception as exc:  # noqa: BLE001
                self._logger.exception("caption strategy failed")
                attempts.append(
                    AcquisitionAttempt(
                        strategy="youtube_caption_tracks",
                        outcome="error",
                        reason=str(exc),
                        reason_code="caption_fetch_error",
                    )
                )
                caption_detail = None
            if caption_detail is not None:
                attempts.extend(_attempts_from_caption(caption_detail))
                text = (caption_detail.get("text") or "").strip()
                if caption_detail.get("outcome") == "ok" and text:
                    ingest = None
                    if to_knowledge and self._knowledge is not None:
                        try:
                            ingest = self._knowledge.ingest_text(
                                src,
                                text,
                                domain=domain,
                                title=title or caption_detail.get("title"),
                                embed=embed,
                            )
                        except Exception as exc:  # noqa: BLE001
                            self._logger.exception("knowledge ingest after captions failed")
                            ingest = {"outcome": "error", "reason": str(exc)}
                    record = AcquisitionRecord.from_attempts(
                        attempts,
                        source_url=src,
                        speech_to_text_status=None,
                    )
                    return {
                        "outcome": "ok",
                        "source": src,
                        "text": text,
                        "title": caption_detail.get("title"),
                        "strategies": [a.as_dict() for a in attempts],
                        "acquisition": record.as_dict(),
                        "interactive_recovery": False,
                        "suggested_next_strategies": [],
                        "speech_to_text_status": None,
                        "ingest": ingest,
                        "caption": caption_detail,
                        "media": None,
                        "operator_summary": record.operator_summary,
                        "orchestrator": "media.learn",
                    }

        # --- official captions API (journal skip when not configured) ----
        if not is_local and is_youtube_url(src):
            if self._official_api is not None:
                try:
                    api_payload = _payload(self._official_api(src))
                    attempts.append(
                        AcquisitionAttempt(
                            strategy=STRATEGY_OFFICIAL_CAPTIONS_API,
                            outcome=str(api_payload.get("outcome") or "error"),
                            reason=api_payload.get("reason"),
                            reason_code=str(
                                api_payload.get("reason_code") or REASON_UNKNOWN
                            ),
                            bytes_read=int(api_payload.get("bytes_read") or 0),
                        )
                    )
                    api_text = (api_payload.get("text") or "").strip()
                    if api_payload.get("outcome") == "ok" and api_text:
                        ingest = None
                        if to_knowledge and self._knowledge is not None:
                            ingest = self._knowledge.ingest_text(
                                src, api_text, domain=domain, title=title, embed=embed
                            )
                        record = AcquisitionRecord.from_attempts(
                            attempts, source_url=src
                        )
                        return {
                            "outcome": "ok",
                            "source": src,
                            "text": api_text,
                            "strategies": [a.as_dict() for a in attempts],
                            "acquisition": record.as_dict(),
                            "interactive_recovery": False,
                            "suggested_next_strategies": [],
                            "speech_to_text_status": None,
                            "ingest": ingest,
                            "caption": caption_detail,
                            "media": None,
                            "operator_summary": record.operator_summary,
                            "orchestrator": "media.learn",
                        }
                except Exception as exc:  # noqa: BLE001
                    attempts.append(
                        AcquisitionAttempt(
                            strategy=STRATEGY_OFFICIAL_CAPTIONS_API,
                            outcome="error",
                            reason=str(exc),
                            reason_code="official_api_error",
                        )
                    )
            else:
                attempts.append(
                    AcquisitionAttempt(
                        strategy=STRATEGY_OFFICIAL_CAPTIONS_API,
                        outcome="skipped",
                        reason="official captions API not configured",
                        reason_code=REASON_STRATEGY_NOT_ATTEMPTED,
                    )
                )

        # --- Browser v1: metadata + DOM captions → text (BA.1) ------------
        if not is_local and self._browser_render is not None:
            browser_out = browser_dom_captions(
                src,
                render=self._browser_render,
                fetch_timedtext=self._timedtext_fetch,
                logger=self._logger,
            )
            attempts.append(
                AcquisitionAttempt(
                    strategy=STRATEGY_BROWSER_DOM_CAPTIONS,
                    outcome=str(browser_out.get("outcome") or "skipped"),
                    reason=browser_out.get("reason"),
                    reason_code=str(browser_out.get("reason_code") or REASON_UNKNOWN),
                    bytes_read=int(browser_out.get("bytes_read") or 0),
                )
            )
            browser_text = (browser_out.get("text") or "").strip()
            if browser_out.get("outcome") == "ok" and browser_text:
                ingest = None
                if to_knowledge and self._knowledge is not None:
                    try:
                        ingest = self._knowledge.ingest_text(
                            src,
                            browser_text,
                            domain=domain,
                            title=title or browser_out.get("title"),
                            embed=embed,
                        )
                    except Exception as exc:  # noqa: BLE001
                        ingest = {"outcome": "error", "reason": str(exc)}
                record = AcquisitionRecord.from_attempts(attempts, source_url=src)
                return {
                    "outcome": "ok",
                    "source": src,
                    "text": browser_text,
                    "title": browser_out.get("title"),
                    "strategies": [a.as_dict() for a in attempts],
                    "acquisition": record.as_dict(),
                    "interactive_recovery": False,
                    "suggested_next_strategies": [],
                    "speech_to_text_status": None,
                    "ingest": ingest,
                    "caption": caption_detail,
                    "browser": browser_out,
                    "media": None,
                    "operator_summary": record.operator_summary,
                    "orchestrator": "media.learn",
                }
        elif not is_local:
            attempts.append(
                AcquisitionAttempt(
                    strategy=STRATEGY_BROWSER_DOM_CAPTIONS,
                    outcome="skipped",
                    reason="browser render not configured",
                    reason_code=REASON_STRATEGY_NOT_ATTEMPTED,
                )
            )

        # --- Asset-first media path (SourceFetch → Readers → optional STT) -
        if self._media is not None:
            try:
                if is_local:
                    media_detail = self._media.ingest_file(
                        path,
                        domain=domain,
                        title=title,
                        embed=embed,
                        to_knowledge=to_knowledge,
                    )
                else:
                    media_detail = self._media.ingest_url(
                        src,
                        domain=domain,
                        title=title,
                        embed=embed,
                        to_knowledge=to_knowledge,
                    )
            except Exception as exc:  # noqa: BLE001
                self._logger.exception("media ingest failed")
                attempts.append(
                    AcquisitionAttempt(
                        strategy="media_ingest",
                        outcome="error",
                        reason=str(exc),
                        reason_code="media_ingest_error",
                    )
                )
                media_detail = None

            if media_detail is not None:
                attempts.extend(_attempts_from_fetch(media_detail.get("fetch")))
                has_asset = bool(media_detail.get("asset_id"))
                speech = media_detail.get("speech") or {}
                # MO.5: only journal speech when an Asset existed (real attempt).
                if has_asset and isinstance(speech, dict) and speech.get("outcome"):
                    attempts.append(
                        AcquisitionAttempt(
                            strategy="speech_to_text",
                            outcome=str(speech.get("outcome")),
                            reason=speech.get("reason") or speech.get("detail"),
                            reason_code=str(
                                speech.get("reason_code")
                                or speech.get("outcome")
                                or REASON_UNKNOWN
                            ),
                        )
                    )
                elif not has_asset:
                    attempts.append(
                        AcquisitionAttempt(
                            strategy="media_asset",
                            outcome="skipped",
                            reason=(
                                (media_detail.get("fetch") or {}).get("reason")
                                or media_detail.get("reason")
                                or "no media Asset created"
                            ),
                            reason_code=str(
                                (media_detail.get("fetch") or {}).get("reason_code")
                                or media_detail.get("reason_code")
                                or "no_asset"
                            ),
                        )
                    )

                text = (media_detail.get("text") or "").strip()
                if media_detail.get("outcome") == "ok" and text:
                    record = AcquisitionRecord.from_attempts(
                        attempts, source_url=src
                    )
                    return {
                        "outcome": "ok",
                        "source": src,
                        "text": text,
                        "strategies": [a.as_dict() for a in attempts],
                        "acquisition": record.as_dict(),
                        "interactive_recovery": False,
                        "suggested_next_strategies": [],
                        "speech_to_text_status": speech_status,
                        "ingest": media_detail.get("ingest"),
                        "caption": caption_detail,
                        "media": media_detail,
                        "operator_summary": record.operator_summary,
                        "orchestrator": "media.learn",
                    }

                meta = media_detail.get("metadata")
                if meta and has_asset:
                    attempts.append(
                        AcquisitionAttempt(
                            strategy="media_metadata",
                            outcome="ok",
                            reason="metadata acquired without transcript text",
                            reason_code=REASON_OK,
                        )
                    )
        else:
            attempts.append(
                AcquisitionAttempt(
                    strategy="media_ingest",
                    outcome="skipped",
                    reason="MediaIngestor not configured",
                    reason_code=REASON_STRATEGY_NOT_ATTEMPTED,
                )
            )

        suggestions = default_media_recovery_strategies(speech_status=speech_status)
        record = AcquisitionRecord.from_attempts(
            attempts,
            source_url=src,
            suggested_next_strategies=suggestions,
            speech_to_text_status=speech_status,
            suggested_next_capability="speech_to_text",
        )
        return self._fail_result(
            record,
            interactive=True,
            reason="interactive_recovery_required",
            caption=caption_detail,
            media=media_detail,
        )

    def _fail_result(
        self,
        record: AcquisitionRecord,
        *,
        interactive: bool,
        reason: str,
        caption: dict[str, Any] | None = None,
        media: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "outcome": "waiting" if interactive else record.outcome,
            "source": record.source_url,
            "text": "",
            "strategies": [a.as_dict() for a in record.strategies_tried],
            "acquisition": record.as_dict(),
            "interactive_recovery": interactive,
            "suggested_next_strategies": list(record.suggested_next_strategies),
            "speech_to_text_status": record.speech_to_text_status,
            "ingest": None,
            "caption": caption,
            "media": media,
            "operator_summary": record.operator_summary,
            "blocked_reason": reason if interactive else None,
            "waiting_for": "media_asset" if interactive else None,
            "orchestrator": "media.learn",
        }

    # --- capability / tool surface --------------------------------------
    def get_transcript(self, video: str) -> dict[str, Any]:  # unused; Protocol flexibility
        return self.learn(video, to_knowledge=False)

    def media_learn(self, source: str, **kwargs: Any) -> dict[str, Any]:
        return self.learn(source, **kwargs)
