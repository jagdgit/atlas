"""``media.learn`` orchestrator — one semantic step, multi-strategy journal (MO*).

Job/Assistant and Research call this instead of a lone ``youtube.transcript`` tool.
Automatic strategies run until spoken content is acquired or exhausted; interactive
recovery is suggestion-only. BA.1b: Browser success always registers an Asset
(transcript or metadata). CR.1: readiness matrix in every result.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from atlas.ingestion.browser_captions import (
    STRATEGY_BROWSER_DOM_CAPTIONS,
    browser_dom_captions,
)
from atlas.ingestion.media_readiness import build_media_readiness
from atlas.ingestion.source_fetch import is_youtube_url
from atlas.readers.media_kinds import ASSET_KIND_METADATA, ASSET_KIND_TRANSCRIPT
from atlas.transcripts.acquisition import (
    REASON_OK,
    REASON_STRATEGY_NOT_ATTEMPTED,
    REASON_UNKNOWN,
    STRATEGY_OFFICIAL_CAPTIONS_API,
    STRATEGY_YOUTUBE_OFFICIAL_CAPTIONS,
    AcquisitionAttempt,
    AcquisitionRecord,
    default_media_recovery_strategies,
)

CaptionFetch = Callable[[str], Any]
SpeechStatusFn = Callable[[], str]
BrowserRender = Callable[[str], dict[str, Any]]
ReadinessFn = Callable[[], dict[str, Any]]


def build_media_stages(
    *,
    acquire: str = "skipped",
    metadata: str = "skipped",
    transcript: str = "skipped",
    speech: str = "skipped",
    knowledge: str = "skipped",
) -> dict[str, str]:
    """AL2 stage statuses (independent; no generic ``partial``)."""
    return {
        "acquire": acquire,
        "metadata": metadata,
        "transcript": transcript,
        "speech": speech,
        "knowledge": knowledge,
    }


def _knowledge_count(ingest: dict[str, Any] | None) -> int:
    if not ingest or ingest.get("outcome") != "ok":
        return 0
    for key in ("chunks", "facts", "knowledge_produced", "documents"):
        val = ingest.get(key)
        if isinstance(val, int) and val > 0:
            return val
    # At least one document ingested.
    if ingest.get("document_id"):
        return 1
    return 1 if ingest.get("outcome") == "ok" else 0


def empty_knowledge_breakdown() -> dict[str, int]:
    """Operator-facing Knowledge categories (Phase 1 honesty + KE*)."""
    return {
        "metadata": 0,
        "transcript": 0,
        "transcript_chunks": 0,  # RAG chunks from ingest_text (not semantic facts)
        "concepts": 0,
        "entities": 0,
        "relationships": 0,
        "facts": 0,  # structured triples only (KE.2)
        "claims": 0,  # speaker assertions (KE.1 prose → claims)
        "summaries": 0,
    }


def build_knowledge_breakdown(
    *,
    metadata_artifacts: int = 0,
    transcript_artifacts: int = 0,
    transcript_chunks: int = 0,
    concepts: int = 0,
    entities: int = 0,
    relationships: int = 0,
    facts: int = 0,
    claims: int = 0,
    summaries: int = 0,
) -> dict[str, int]:
    return {
        "metadata": int(metadata_artifacts or 0),
        "transcript": int(transcript_artifacts or 0),
        "transcript_chunks": int(transcript_chunks or 0),
        "concepts": int(concepts or 0),
        "entities": int(entities or 0),
        "relationships": int(relationships or 0),
        "facts": int(facts or 0),
        "claims": int(claims or 0),
        "summaries": int(summaries or 0),
    }


def format_knowledge_breakdown(
    breakdown: dict[str, Any] | None,
    *,
    knowledge_produced: int | None = None,
) -> str:
    """Operator-facing Knowledge metrics (KE.0).

    ``knowledge_produced`` / ``transcript_chunks`` = RAG chunk count from ``ingest_text``.
    Category rows are artifact / finding counts — they are *not* required to sum to that total.
    """
    caps = breakdown or empty_knowledge_breakdown()
    chunks = int(
        knowledge_produced
        if knowledge_produced is not None
        else (caps.get("transcript_chunks") or 0)
    )
    lines = [
        "Knowledge Produced",
        f"  RAG transcript chunks: {chunks}",
        "",
        "Categories (artifacts / findings — not equal to chunk total)",
        "",
    ]
    for key in (
        "metadata",
        "transcript",
        "transcript_chunks",
        "concepts",
        "entities",
        "relationships",
        "facts",
        "claims",
        "summaries",
    ):
        lines.append(f"  {key:<18} {int(caps.get(key) or 0)}")
    return "\n".join(lines)


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
                asset_id=row.get("asset_id"),
                asset_kind=row.get("asset_kind"),
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
                asset_id=row.get("asset_id"),
                asset_kind=row.get("kind") or row.get("asset_kind"),
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
            asset_id=fetch.get("asset_id"),
            asset_kind=fetch.get("kind"),
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
        asset_acquirer: Any | None = None,
        speech_status: SpeechStatusFn | None = None,
        official_captions_api: Callable[[str], Any] | None = None,
        browser_render: BrowserRender | None = None,
        timedtext_fetch: Callable[[str], str] | None = None,
        readiness: ReadinessFn | None = None,
        extractor: Any | None = None,
        candidates: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._caption_fetch = caption_fetch
        self._media = media_ingestor
        self._knowledge = knowledge
        self._acq = asset_acquirer
        self._speech_status = speech_status
        self._official_api = official_captions_api
        self._browser_render = browser_render
        self._timedtext_fetch = timedtext_fetch
        self._readiness = readiness
        self._extractor = extractor
        self._candidates = candidates
        self._logger = logger or logging.getLogger("atlas.ingestion.media_learn")
        self.calls: list[dict[str, Any]] = []

    def learn(
        self,
        source: str,
        *,
        to_knowledge: bool = True,
        title: str | None = None,
        domain: str = "external",
        embed: bool = False,
    ) -> dict[str, Any]:
        src = (source or "").strip()
        self.calls.append({"source": src, "to_knowledge": to_knowledge})
        attempts: list[AcquisitionAttempt] = []
        speech_status = self._speech_status() if self._speech_status else None
        media_detail: dict[str, Any] | None = None
        caption_detail: dict[str, Any] | None = None
        readiness = (
            self._readiness()
            if self._readiness
            else build_media_readiness(speech_to_text=speech_status or "missing")
        )

        if not src:
            record = AcquisitionRecord.from_attempts(
                [],
                source_url="",
                suggested_next_strategies=default_media_recovery_strategies(
                    speech_status=speech_status
                ),
                speech_to_text_status=speech_status,
            )
            return self._fail_result(
                record,
                interactive=True,
                reason="missing_source",
                readiness=readiness,
            )

        path = Path(src).expanduser()
        is_local = path.is_file()

        # --- captions (YouTube URLs only) --------------------------------
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
                    asset_id, asset_kind = self._register_text_asset(
                        text,
                        kind=ASSET_KIND_TRANSCRIPT,
                        source_uri=src,
                        title=title or caption_detail.get("title"),
                        filename="captions.txt",
                    )
                    if asset_id and attempts:
                        last = attempts[-1]
                        attempts[-1] = AcquisitionAttempt(
                            strategy=last.strategy,
                            outcome=last.outcome,
                            reason=last.reason,
                            reason_code="asset_produced",
                            bytes_read=last.bytes_read,
                            asset_id=asset_id,
                            asset_kind=asset_kind,
                        )
                    return self._success(
                        src,
                        text=text,
                        title=caption_detail.get("title"),
                        attempts=attempts,
                        ingest=self._maybe_ingest(
                            src,
                            text,
                            domain=domain,
                            title=title or caption_detail.get("title"),
                            embed=embed,
                            to_knowledge=to_knowledge,
                        ),
                        caption=caption_detail,
                        readiness=readiness,
                        speech_status=None,
                    )

        # --- official captions API (OI-M1) --------------------------------
        if not is_local and is_youtube_url(src):
            if self._official_api is not None:
                try:
                    api_payload = _payload(self._official_api(src))
                    api_text = (api_payload.get("text") or "").strip()
                    asset_id = asset_kind = None
                    reason_code = str(api_payload.get("reason_code") or REASON_UNKNOWN)
                    if api_payload.get("outcome") == "ok" and api_text:
                        asset_id, asset_kind = self._register_text_asset(
                            api_text,
                            kind=ASSET_KIND_TRANSCRIPT,
                            source_uri=src,
                            title=title or api_payload.get("title"),
                            filename="official_captions.txt",
                        )
                        reason_code = "asset_produced"
                    attempts.append(
                        AcquisitionAttempt(
                            strategy=STRATEGY_YOUTUBE_OFFICIAL_CAPTIONS,
                            outcome=str(api_payload.get("outcome") or "error"),
                            reason=api_payload.get("reason"),
                            reason_code=reason_code,
                            bytes_read=int(api_payload.get("bytes_read") or 0),
                            asset_id=asset_id,
                            asset_kind=asset_kind,
                        )
                    )
                    if api_payload.get("outcome") == "ok" and api_text:
                        return self._success(
                            src,
                            text=api_text,
                            title=api_payload.get("title"),
                            attempts=attempts,
                            ingest=self._maybe_ingest(
                                src,
                                api_text,
                                domain=domain,
                                title=title or api_payload.get("title"),
                                embed=embed,
                                to_knowledge=to_knowledge,
                            ),
                            caption=caption_detail,
                            readiness=readiness,
                            speech_status=None,
                        )
                except Exception as exc:  # noqa: BLE001
                    from atlas.transcripts.official_captions import (
                        OfficialCaptionsFetchError,
                        classify_youtube_api_failure,
                    )

                    if isinstance(exc, OfficialCaptionsFetchError):
                        code, reason = exc.reason_code, str(exc)
                    else:
                        code = classify_youtube_api_failure(message=str(exc))
                        reason = str(exc)
                    attempts.append(
                        AcquisitionAttempt(
                            strategy=STRATEGY_YOUTUBE_OFFICIAL_CAPTIONS,
                            outcome="error",
                            reason=reason,
                            reason_code=code,
                        )
                    )
            else:
                # CR2: one skip row — not a fake attempt.
                attempts.append(
                    AcquisitionAttempt(
                        strategy=STRATEGY_YOUTUBE_OFFICIAL_CAPTIONS,
                        outcome="skipped",
                        reason="official captions API not configured",
                        reason_code="not_configured",
                    )
                )

        # --- Browser v1 + BA.1b Asset emission ----------------------------
        if not is_local and self._browser_render is not None:
            browser_out = browser_dom_captions(
                src,
                render=self._browser_render,
                fetch_timedtext=self._timedtext_fetch,
                logger=self._logger,
            )
            browser_text = (browser_out.get("text") or "").strip()
            page_opened = bool(
                browser_out.get("page_opened")
                or browser_out.get("outcome") == "ok"
                or browser_out.get("reason_code") == "no_caption_nodes_found"
            )
            asset_id = asset_kind = None
            reason_code = str(browser_out.get("reason_code") or REASON_UNKNOWN)
            outcome = str(browser_out.get("outcome") or "skipped")

            if outcome == "ok" and browser_text:
                asset_id, asset_kind = self._register_text_asset(
                    browser_text,
                    kind=ASSET_KIND_TRANSCRIPT,
                    source_uri=src,
                    title=title or browser_out.get("title"),
                    filename="browser_captions.txt",
                )
                reason_code = "asset_produced"
            elif page_opened:
                # BA.1b: metadata Asset even when no captions.
                meta = {
                    "source_url": src,
                    "title": browser_out.get("title")
                    or (browser_out.get("metadata") or {}).get("title"),
                    "final_url": (browser_out.get("metadata") or {}).get("final_url")
                    or browser_out.get("final_url"),
                    "browser_reason_code": browser_out.get("reason_code"),
                    "browser_reason": browser_out.get("reason"),
                }
                asset_id, asset_kind = self._register_metadata_asset(meta, source_uri=src)
                if asset_id:
                    reason_code = (
                        "no_caption_nodes_found"
                        if reason_code in ("no_captions", "no_caption_nodes_found", REASON_UNKNOWN)
                        else reason_code
                    )
                    # Still skipped for spoken content, but Asset was produced.
                    if outcome == "skipped":
                        outcome = "skipped"
                    # Annotate reason for MO.6
                    if not browser_out.get("reason"):
                        browser_out = {
                            **browser_out,
                            "reason": "metadata Asset produced; no caption nodes found",
                        }

            attempts.append(
                AcquisitionAttempt(
                    strategy=STRATEGY_BROWSER_DOM_CAPTIONS,
                    outcome=outcome,
                    reason=browser_out.get("reason"),
                    reason_code=reason_code,
                    bytes_read=int(browser_out.get("bytes_read") or 0),
                    asset_id=asset_id,
                    asset_kind=asset_kind,
                )
            )

            if outcome == "ok" and browser_text:
                return self._success(
                    src,
                    text=browser_text,
                    title=browser_out.get("title"),
                    attempts=attempts,
                    ingest=self._maybe_ingest(
                        src,
                        browser_text,
                        domain=domain,
                        title=title or browser_out.get("title"),
                        embed=embed,
                        to_knowledge=to_knowledge,
                    ),
                    caption=caption_detail,
                    browser=browser_out,
                    readiness=readiness,
                    speech_status=None,
                )
        elif not is_local:
            attempts.append(
                AcquisitionAttempt(
                    strategy=STRATEGY_BROWSER_DOM_CAPTIONS,
                    outcome="skipped",
                    reason="browser render not configured",
                    reason_code="not_configured",
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
                fetch_attempts = _attempts_from_fetch(media_detail.get("fetch"))
                asset_id = str(media_detail.get("asset_id") or "") or None
                asset_kind = str(media_detail.get("kind") or "") or None
                # AL1/AL4: stamp asset_id onto the winning fetch row (chain rows omit it).
                if asset_id and fetch_attempts:
                    stamped: list[AcquisitionAttempt] = []
                    for row in fetch_attempts:
                        if row.outcome == "ok" and not row.asset_id:
                            stamped.append(
                                AcquisitionAttempt(
                                    strategy=row.strategy,
                                    outcome=row.outcome,
                                    reason=row.reason or "Media Asset registered",
                                    reason_code="asset_registered",
                                    bytes_read=row.bytes_read,
                                    asset_id=asset_id,
                                    asset_kind=asset_kind,
                                )
                            )
                        else:
                            stamped.append(row)
                    fetch_attempts = stamped
                attempts.extend(fetch_attempts)
                has_asset = bool(asset_id)

                meta = media_detail.get("metadata") if isinstance(media_detail.get("metadata"), dict) else {}
                speech = media_detail.get("speech") if isinstance(media_detail.get("speech"), dict) else {}
                ingest = media_detail.get("ingest") if isinstance(media_detail.get("ingest"), dict) else None
                text = (media_detail.get("text") or "").strip()
                ingest_ok = bool(ingest and ingest.get("outcome") == "ok")
                spoken = bool(text) and (
                    (speech.get("outcome") == "ok")
                    or any(a.strategy.endswith("captions") or "transcript" in a.strategy for a in attempts)
                    or (media_detail.get("kind") == ASSET_KIND_TRANSCRIPT)
                )
                # Prefer explicit speech/transcript; metadata note still counts as text (AL3).
                metadata_ok = bool(meta) and str(meta.get("outcome") or "") == "ok"
                if has_asset:
                    attempts.append(
                        AcquisitionAttempt(
                            strategy="media_metadata",
                            outcome="ok" if metadata_ok else str(meta.get("outcome") or "skipped"),
                            reason=meta.get("reason")
                            or (
                                "metadata artifact acquired"
                                if metadata_ok
                                else "metadata reader did not succeed"
                            ),
                            reason_code="artifact_produced" if metadata_ok else str(
                                meta.get("reason_code") or meta.get("outcome") or "skipped"
                            ),
                            asset_id=asset_id,
                            asset_kind=asset_kind,
                        )
                    )

                if has_asset and speech:
                    attempts.append(
                        AcquisitionAttempt(
                            strategy="speech_to_text",
                            outcome=str(speech.get("outcome") or "skipped"),
                            reason=speech.get("reason") or speech.get("detail"),
                            reason_code=str(
                                speech.get("reason_code")
                                or speech.get("capability_gap")
                                or speech.get("outcome")
                                or REASON_UNKNOWN
                            ),
                            asset_id=asset_id,
                            asset_kind=asset_kind,
                        )
                    )
                elif has_asset and not speech and speech_status and speech_status != "ready":
                    attempts.append(
                        AcquisitionAttempt(
                            strategy="speech_to_text",
                            outcome="skipped",
                            reason=f"speech_to_text status: {speech_status}",
                            reason_code=str(speech_status),
                            asset_id=asset_id,
                            asset_kind=asset_kind,
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

                knowledge_produced = _knowledge_count(ingest)
                # Phase 1 honesty: classify *what kind* of Knowledge was produced.
                spoken_ingest = bool(
                    ingest_ok
                    and (
                        (speech.get("outcome") == "ok")
                        or (media_detail.get("kind") == ASSET_KIND_TRANSCRIPT and text)
                        or any(
                            a.strategy.endswith("captions")
                            and a.outcome == "ok"
                            and a.asset_kind == ASSET_KIND_TRANSCRIPT
                            for a in attempts
                        )
                    )
                )
                metadata_ingest = bool(ingest_ok and not spoken_ingest)
                # Captions/speech that also ran metadata still count metadata artifact.
                if metadata_ok and ingest_ok:
                    metadata_ingest = True
                if spoken_ingest:
                    # Spoken path supersedes "metadata-only" for transcript count.
                    pass
                knowledge_breakdown = build_knowledge_breakdown(
                    metadata_artifacts=1 if (metadata_ok and ingest_ok) or metadata_ingest else 0,
                    transcript_artifacts=1 if spoken_ingest else 0,
                    transcript_chunks=knowledge_produced if spoken_ingest else 0,
                )
                # If only metadata note was ingested, ensure metadata >= 1.
                if ingest_ok and knowledge_breakdown["metadata"] == 0 and knowledge_breakdown["transcript"] == 0:
                    knowledge_breakdown = build_knowledge_breakdown(
                        metadata_artifacts=1,
                        transcript_chunks=0,
                    )

                if ingest_ok:
                    attempts.append(
                        AcquisitionAttempt(
                            strategy="knowledge",
                            outcome="ok",
                            reason=(
                                "speech_ingested"
                                if spoken_ingest
                                else "metadata_ingested"
                            ),
                            reason_code=(
                                "speech_ingested"
                                if spoken_ingest
                                else "metadata_ingested"
                            ),
                            asset_id=asset_id,
                            asset_kind=asset_kind,
                            bytes_read=len(text.encode("utf-8")) if text else 0,
                        )
                    )

                stages = build_media_stages(
                    acquire="success" if has_asset else "failed",
                    metadata=(
                        "success"
                        if metadata_ok
                        else ("skipped" if not meta else "failed")
                    ),
                    transcript=(
                        "success"
                        if media_detail.get("kind") == ASSET_KIND_TRANSCRIPT and text
                        else (
                            "success"
                            if spoken_ingest or (spoken and speech.get("outcome") == "ok")
                            else (
                                "failed"
                                if speech.get("outcome") in ("error", "unavailable", "unsupported")
                                else "waiting"
                                if has_asset
                                else "skipped"
                            )
                        )
                    ),
                    speech=(
                        "success"
                        if speech.get("outcome") == "ok"
                        else (
                            "failed"
                            if speech.get("outcome") in ("error", "unavailable", "unsupported")
                            else (
                                "waiting"
                                if has_asset
                                else "skipped"
                            )
                        )
                    ),
                    knowledge="success" if ingest_ok else ("empty" if has_asset else "skipped"),
                )

                # AL3: Asset + Knowledge (metadata or speech) ⇒ learn success; do not block on Whisper.
                if has_asset and (ingest_ok or (media_detail.get("outcome") == "ok" and text)):
                    return self._success(
                        src,
                        text=text or (ingest or {}).get("preview") or f"Media Asset {asset_id}",
                        title=title,
                        attempts=attempts,
                        ingest=ingest,
                        caption=caption_detail,
                        media=media_detail,
                        readiness=readiness,
                        speech_status=speech_status,
                        asset_id=asset_id,
                        asset_kind=asset_kind,
                        stages=stages,
                        knowledge_produced=knowledge_produced,
                        knowledge_breakdown=knowledge_breakdown,
                        domain=domain,
                    )

                # Asset registered but nothing ingestible yet — wait for speech/upload, not Asset.
                if has_asset:
                    suggestions = default_media_recovery_strategies(speech_status=speech_status)
                    record = AcquisitionRecord.from_attempts(
                        attempts,
                        source_url=src,
                        suggested_next_strategies=suggestions,
                        speech_to_text_status=speech_status,
                        suggested_next_capability="speech_to_text",
                        asset_id=asset_id,
                        asset_kind=asset_kind,
                    )
                    return self._fail_result(
                        record,
                        interactive=True,
                        reason="speech_to_text_required",
                        caption=caption_detail,
                        media=media_detail,
                        readiness=readiness,
                        waiting_for="speech_to_text",
                        stages=stages,
                        knowledge_produced=knowledge_produced,
                        knowledge_breakdown=knowledge_breakdown,
                        ingest=ingest,
                    )
        else:
            attempts.append(
                AcquisitionAttempt(
                    strategy="media_ingest",
                    outcome="skipped",
                    reason="MediaIngestor not configured",
                    reason_code="not_configured",
                )
            )

        suggestions = default_media_recovery_strategies(speech_status=speech_status)
        # Keep recovery hint for enabling official API when not configured.
        if self._official_api is None and STRATEGY_OFFICIAL_CAPTIONS_API not in suggestions:
            suggestions = tuple(list(suggestions) + [STRATEGY_OFFICIAL_CAPTIONS_API])
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
            readiness=readiness,
            waiting_for="media_asset",
        )

    # --- helpers --------------------------------------------------------
    def _register_text_asset(
        self,
        text: str,
        *,
        kind: str,
        source_uri: str,
        title: str | None,
        filename: str,
    ) -> tuple[str | None, str | None]:
        if self._acq is None or not (text or "").strip():
            return None, None
        try:
            acquired = self._acq.acquire_bytes(
                text.encode("utf-8"),
                kind=kind,
                filename=filename,
                source_uri=source_uri,
                content_type="text/plain",
                metadata={"title": title, "source_url": source_uri},
            )
            return str(acquired.asset_id), kind
        except Exception:  # noqa: BLE001
            self._logger.exception("asset register failed (%s)", kind)
            return None, None

    def _register_metadata_asset(
        self, meta: dict[str, Any], *, source_uri: str
    ) -> tuple[str | None, str | None]:
        if self._acq is None:
            return None, None
        try:
            payload = json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8")
            acquired = self._acq.acquire_bytes(
                payload,
                kind=ASSET_KIND_METADATA,
                filename="media_metadata.json",
                source_uri=source_uri,
                content_type="application/json",
                metadata=meta,
            )
            return str(acquired.asset_id), ASSET_KIND_METADATA
        except Exception:  # noqa: BLE001
            self._logger.exception("metadata asset register failed")
            return None, None

    def _typed_extract_done(self, breakdown: dict[str, Any]) -> bool:
        return any(
            int(breakdown.get(k) or 0) > 0
            for k in ("concepts", "entities", "relationships", "facts", "claims")
        )

    def _extract_knowledge(
        self,
        text: str,
        *,
        asset_id: str | None,
        domain: str,
        source_url: str,
        duration_seconds: float | None = None,
    ) -> dict[str, Any]:
        """KE.2.3: transcript → typed candidates → consolidator + preview/quality.

        Returns ``{counts, preview, quality}``. Findings are UNVERIFIED until
        Research verification runs.
        """
        empty_counts = {
            "concepts": 0,
            "entities": 0,
            "relationships": 0,
            "facts": 0,
            "claims": 0,
        }
        empty = {"counts": empty_counts, "preview": {}, "quality": {}}
        if self._extractor is None or self._candidates is None:
            return empty
        body = (text or "").strip()
        if not body:
            return empty
        evidence_ref = {
            "asset_id": asset_id,
            "source": "media_transcript",
            "source_url": source_url,
            "reader": "media.learn",
            "reader_version": getattr(self._extractor, "VERSION", "ke.2.3"),
        }
        if duration_seconds is not None:
            evidence_ref["duration_seconds"] = duration_seconds
        try:
            extract_bundle = getattr(self._extractor, "extract_bundle", None)
            duration = duration_seconds
            if duration is None and evidence_ref.get("duration_seconds") is not None:
                try:
                    duration = float(evidence_ref["duration_seconds"])
                except (TypeError, ValueError):
                    duration = None
            if callable(extract_bundle):
                bundle = extract_bundle(
                    body,
                    evidence_ref=evidence_ref,
                    domain=domain,
                    duration_seconds=duration,
                )
                payloads = list(bundle.candidates)
                counts = dict(bundle.counts)
                preview = dict(bundle.preview)
                quality = dict(bundle.quality)
            else:
                from atlas.knowledge.media_extraction import (
                    build_extraction_quality,
                    build_knowledge_preview,
                    count_candidates_by_type,
                )

                payloads = self._extractor.extract(
                    body,
                    evidence_ref=evidence_ref,
                    domain=domain,
                    duration_seconds=duration,
                )
                counts = count_candidates_by_type(payloads)
                preview = build_knowledge_preview(payloads)
                quality = build_extraction_quality(body, payloads)
            if not payloads:
                return empty
            version = getattr(self._extractor, "VERSION", "ke.2.3")
            for p in payloads:
                p.setdefault("reader", "media.learn")
                p.setdefault("reader_version", version)
            emitted = self._candidates.emit_many(payloads)
            for c in emitted:
                self._candidates.consume(c)
            return {"counts": counts, "preview": preview, "quality": quality}
        except Exception:  # noqa: BLE001
            self._logger.exception("typed knowledge extract failed")
            return empty

    def _maybe_ingest(
        self,
        source: str,
        text: str,
        *,
        domain: str,
        title: str | None,
        embed: bool,
        to_knowledge: bool,
    ) -> Any:
        if not to_knowledge or self._knowledge is None or not text.strip():
            return None
        try:
            return self._knowledge.ingest_text(
                source, text, domain=domain, title=title, embed=embed
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.exception("knowledge ingest failed")
            return {"outcome": "error", "reason": str(exc)}

    def _success(
        self,
        source: str,
        *,
        text: str,
        title: str | None,
        attempts: list[AcquisitionAttempt],
        ingest: Any,
        readiness: dict[str, Any],
        speech_status: str | None,
        caption: dict[str, Any] | None = None,
        browser: dict[str, Any] | None = None,
        media: dict[str, Any] | None = None,
        asset_id: str | None = None,
        asset_kind: str | None = None,
        stages: dict[str, str] | None = None,
        knowledge_produced: int | None = None,
        knowledge_breakdown: dict[str, int] | None = None,
        domain: str = "external",
    ) -> dict[str, Any]:
        aid = asset_id or next(
            (a.asset_id for a in reversed(attempts) if a.asset_id), None
        )
        akind = asset_kind or next(
            (a.asset_kind for a in reversed(attempts) if a.asset_kind), None
        )
        ingest_dict = ingest if isinstance(ingest, dict) else None
        kp = (
            knowledge_produced
            if knowledge_produced is not None
            else _knowledge_count(ingest_dict)
        )
        breakdown = dict(knowledge_breakdown or empty_knowledge_breakdown())
        body = (text or "").strip()
        # Caption / early-return paths may omit breakdown — fill KE.0 defaults.
        if body and int(breakdown.get("transcript") or 0) == 0:
            breakdown["transcript"] = 1
        if body and int(breakdown.get("transcript_chunks") or 0) == 0 and kp:
            breakdown["transcript_chunks"] = kp
        knowledge_preview: dict[str, list[str]] | None = None
        extraction_quality: dict[str, Any] | None = None
        # KE.2.2/2.3: typed extract once if not already counted.
        if body and not self._typed_extract_done(breakdown):
            duration = None
            if isinstance(media, dict):
                meta = media.get("metadata") if isinstance(media.get("metadata"), dict) else {}
                fields = meta.get("fields") if isinstance(meta.get("fields"), dict) else {}
                for key in ("duration_seconds", "duration"):
                    raw = fields.get(key) if fields else media.get(key)
                    if raw is None and isinstance(meta, dict):
                        raw = meta.get(key)
                    if raw is not None:
                        try:
                            duration = float(raw)
                            break
                        except (TypeError, ValueError):
                            pass
            extracted = self._extract_knowledge(
                body,
                asset_id=aid,
                domain=domain,
                source_url=source,
                duration_seconds=duration,
            )
            counts = extracted.get("counts") if isinstance(extracted, dict) else {}
            if isinstance(counts, dict) and any(int(counts.get(k) or 0) for k in counts):
                for key, n in counts.items():
                    if key in breakdown:
                        breakdown[key] = int(n)
                reason = (
                    "concepts={concepts}, entities={entities}, "
                    "relationships={relationships}, facts={facts}, claims={claims}"
                ).format(
                    concepts=int(counts.get("concepts") or 0),
                    entities=int(counts.get("entities") or 0),
                    relationships=int(counts.get("relationships") or 0),
                    facts=int(counts.get("facts") or 0),
                    claims=int(counts.get("claims") or 0),
                )
                attempts.append(
                    AcquisitionAttempt(
                        strategy="knowledge_extract",
                        outcome="ok",
                        reason=reason,
                        reason_code="typed_extracted",
                        asset_id=aid,
                        asset_kind=akind,
                    )
                )
                preview = extracted.get("preview")
                if isinstance(preview, dict):
                    knowledge_preview = {
                        str(k): [str(x) for x in (v or [])]
                        for k, v in preview.items()
                        if isinstance(v, list)
                    }
                quality = extracted.get("quality")
                if isinstance(quality, dict):
                    extraction_quality = quality
        record = AcquisitionRecord.from_attempts(
            attempts,
            source_url=source,
            speech_to_text_status=None,
            asset_id=aid,
            asset_kind=akind,
        )
        stage_map = stages or build_media_stages(
            acquire="success" if record.ok else "failed",
            metadata="skipped",
            transcript="success" if body else "waiting",
            speech="skipped",
            knowledge="success" if kp else "empty",
        )
        return {
            "outcome": "ok",
            "source": source,
            "text": text,
            "title": title,
            "strategies": [a.as_dict() for a in attempts],
            "acquisition": record.as_dict(),
            "stages": stage_map,
            "interactive_recovery": False,
            "suggested_next_strategies": [],
            "speech_to_text_status": speech_status,
            "ingest": ingest,
            "caption": caption,
            "browser": browser,
            "media": media,
            "readiness": readiness,
            "operator_summary": record.operator_summary,
            "knowledge_produced": kp,
            "knowledge_breakdown": breakdown,
            "knowledge_preview": knowledge_preview or {},
            "extraction_quality": extraction_quality or {},
            "waiting_for": None,
            "orchestrator": "media.learn",
        }

    def _fail_result(
        self,
        record: AcquisitionRecord,
        *,
        interactive: bool,
        reason: str,
        caption: dict[str, Any] | None = None,
        media: dict[str, Any] | None = None,
        readiness: dict[str, Any] | None = None,
        waiting_for: str | None = None,
        stages: dict[str, str] | None = None,
        knowledge_produced: int = 0,
        knowledge_breakdown: dict[str, int] | None = None,
        ingest: Any = None,
    ) -> dict[str, Any]:
        wait = waiting_for
        if wait is None and interactive:
            wait = "media_asset" if not record.asset_id else "speech_to_text"
        stage_map = stages or build_media_stages(
            acquire="success" if record.ok else "failed",
            knowledge="success" if knowledge_produced else "empty",
        )
        return {
            "outcome": "waiting" if interactive else record.outcome,
            "source": record.source_url,
            "text": "",
            "strategies": [a.as_dict() for a in record.strategies_tried],
            "acquisition": record.as_dict(),
            "stages": stage_map,
            "interactive_recovery": interactive,
            "suggested_next_strategies": list(record.suggested_next_strategies),
            "speech_to_text_status": record.speech_to_text_status,
            "ingest": ingest,
            "caption": caption,
            "media": media,
            "readiness": readiness,
            "operator_summary": record.operator_summary,
            "blocked_reason": reason if interactive else None,
            "waiting_for": wait if interactive else None,
            "knowledge_produced": int(knowledge_produced or 0),
            "knowledge_breakdown": knowledge_breakdown or empty_knowledge_breakdown(),
            "orchestrator": "media.learn",
        }

    def get_transcript(self, video: str) -> dict[str, Any]:
        return self.learn(video, to_knowledge=False)

    def media_learn(self, source: str, **kwargs: Any) -> dict[str, Any]:
        return self.learn(source, **kwargs)
