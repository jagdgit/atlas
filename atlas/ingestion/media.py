"""Local / remote media ingest orchestration (Media Reader Family · M.4–M.7).

Asset-first path:

    local file | URL
        → SourceFetcher (M.6; provider-specific HERE only)
        → MediaMetadataReader
        → TranscriptFileReader / AudioDemuxReader / SpeechToTextReader
        → Knowledge (optional) + media events (M.7)

No YouTube-specific branches past the Asset boundary (MD8).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from atlas.ingestion.media_events import (
    EVENT_MEDIA_METADATA_ACQUIRED,
    EVENT_MEDIA_READ_FAILED,
    EVENT_SPEECH_TO_TEXT_GAP,
    EVENT_TRANSCRIPT_ACQUIRED,
    emit_media_event,
)
from atlas.ingestion.source_fetch import stable_source_id
from atlas.readers.media_kinds import (
    ASSET_KIND_AUDIO,
    ASSET_KIND_TRANSCRIPT,
    ASSET_KIND_VIDEO,
    content_type_for,
    infer_media_kind,
)
from atlas.speech.engine import STT_OK

if TYPE_CHECKING:
    from atlas.ingestion.acquire import AssetAcquirer, AcquiredAsset
    from atlas.ingestion.source_fetch import SourceFetcher
    from atlas.knowledge.service import KnowledgeService
    from atlas.readers.audio_demux import AudioDemuxReader
    from atlas.readers.media_metadata import MediaMetadataReader
    from atlas.readers.speech_to_text import SpeechToTextReader
    from atlas.readers.transcript_file import TranscriptFileReader


class MediaIngestor:
    """Acquire (file or URL) → metadata → transcript/demux/speech → knowledge."""

    def __init__(
        self,
        acquirer: "AssetAcquirer",
        knowledge: "KnowledgeService",
        *,
        metadata_reader: "MediaMetadataReader | None" = None,
        transcript_reader: "TranscriptFileReader | None" = None,
        demux_reader: "AudioDemuxReader | None" = None,
        speech_reader: "SpeechToTextReader | None" = None,
        source_fetcher: "SourceFetcher | None" = None,
        events: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._acq = acquirer
        self._knowledge = knowledge
        self._meta = metadata_reader
        self._transcript = transcript_reader
        self._demux = demux_reader
        self._speech = speech_reader
        self._fetcher = source_fetcher
        self._events = events
        self._logger = logger or logging.getLogger("atlas.ingestion.media")

    def ingest_file(
        self,
        path: str | Path,
        *,
        domain: str = "external",
        title: str | None = None,
        embed: bool = False,
        metadata: dict[str, Any] | None = None,
        to_knowledge: bool = True,
    ) -> dict[str, Any]:
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(str(p))
        kind = infer_media_kind(p.name)
        if kind is None:
            raise ValueError(f"not a media file: {p.name}")

        source_id = stable_source_id(str(p))
        meta = {"filename": p.name, "source_id": source_id, **(metadata or {})}
        acquired = self._acq.acquire_file(
            p,
            kind=kind,
            content_type=content_type_for(p.name),
            metadata=meta,
        )
        return self._after_acquire(
            acquired,
            kind=kind,
            filename=p.name,
            domain=domain,
            title=title,
            embed=embed,
            source_url=str(p),
            source_id=source_id,
            to_knowledge=to_knowledge,
        )

    def ingest_url(
        self,
        url: str,
        *,
        domain: str = "external",
        title: str | None = None,
        embed: bool = False,
        to_knowledge: bool = True,
    ) -> dict[str, Any]:
        """Fetch a remote/local source via SourceFetcher, then the same Reader path."""
        if self._fetcher is None:
            out = {
                "outcome": "unsupported",
                "source_url": url,
                "source_id": stable_source_id(url),
                "reason": "SourceFetcher not configured",
                "operator_hint": "upload a local file or a transcript asset",
                "ingest": None,
                "text": "",
            }
            emit_media_event(
                self._events,
                EVENT_MEDIA_READ_FAILED,
                {
                    "source_url": url,
                    "reason": out["reason"],
                    "reason_code": "fetch_unavailable",
                    "operator_hint": out["operator_hint"],
                },
            )
            return out

        fetched = self._fetcher.fetch(url)
        out: dict[str, Any] = {
            "source_url": url,
            "source_id": fetched.source_id,
            "fetch": fetched.as_dict(),
            "outcome": fetched.outcome,
            "operator_hint": fetched.operator_hint,
            "asset_id": fetched.asset_id,
            "asset_version": fetched.asset_version,
            "kind": fetched.kind,
            "filename": fetched.filename,
            "metadata": None,
            "demux": None,
            "speech": None,
            "ingest": None,
            "text": "",
        }
        if not fetched.ok:
            emit_media_event(
                self._events,
                EVENT_MEDIA_READ_FAILED,
                {
                    "source_url": url,
                    "source_id": fetched.source_id,
                    "reason": fetched.reason,
                    "reason_code": fetched.reason_code,
                    "operator_hint": fetched.operator_hint,
                    "strategies_tried": list(fetched.strategies_tried),
                },
            )
            return out

        from atlas.ingestion.acquire import AcquiredAsset

        acquired = AcquiredAsset(
            asset_id=str(fetched.asset_id),
            asset_version=int(fetched.asset_version or 1),
            kind=str(fetched.kind),
            name="",
            checksum="",
            content_type=content_type_for(fetched.filename),
            source_uri=url,
            size_bytes=fetched.bytes_read,
            reused=fetched.reused,
            source=fetched.filename or url,
        )
        processed = self._after_acquire(
            acquired,
            kind=str(fetched.kind),
            filename=fetched.filename or "media",
            domain=domain,
            title=title,
            embed=embed,
            source_url=url,
            source_id=fetched.source_id or stable_source_id(url),
            to_knowledge=to_knowledge,
        )
        out.update(processed)
        out["fetch"] = fetched.as_dict()
        out["source_id"] = fetched.source_id
        if processed.get("text") or (processed.get("ingest") or {}).get("outcome") == "ok":
            out["outcome"] = "ok"
        elif not to_knowledge and not (processed.get("text") or "").strip():
            out["outcome"] = processed.get("outcome") or "empty"
        return out

    def ingest(
        self,
        source: str | Path,
        *,
        domain: str = "external",
        title: str | None = None,
        embed: bool = False,
        metadata: dict[str, Any] | None = None,
        to_knowledge: bool = True,
    ) -> dict[str, Any]:
        """Route a path or URL to the appropriate ingest entrypoint."""
        s = str(source).strip()
        parsed = urlparse(s)
        if parsed.scheme in ("http", "https"):
            return self.ingest_url(
                s, domain=domain, title=title, embed=embed, to_knowledge=to_knowledge
            )
        return self.ingest_file(
            s,
            domain=domain,
            title=title,
            embed=embed,
            metadata=metadata,
            to_knowledge=to_knowledge,
        )

    def _after_acquire(
        self,
        acquired: "AcquiredAsset",
        *,
        kind: str,
        filename: str,
        domain: str,
        title: str | None,
        embed: bool,
        source_url: str,
        source_id: str,
        to_knowledge: bool,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {
            "asset_id": acquired.asset_id,
            "asset_version": acquired.asset_version,
            "asset_reused": acquired.reused,
            "kind": kind,
            "filename": filename,
            "source_url": source_url,
            "source_id": source_id,
            "metadata": None,
            "demux": None,
            "speech": None,
            "ingest": None,
            "text": "",
            "outcome": "ok",
        }

        if self._meta is not None:
            out["metadata"] = self._meta.read(
                acquired.asset_id, acquired.asset_version, filename=filename
            )
            if (out["metadata"] or {}).get("outcome") == "ok":
                emit_media_event(
                    self._events,
                    EVENT_MEDIA_METADATA_ACQUIRED,
                    {
                        "asset_id": acquired.asset_id,
                        "asset_version": acquired.asset_version,
                        "source_id": source_id,
                        "source_url": source_url,
                        "kind": kind,
                        "filename": filename,
                    },
                )

        if kind == ASSET_KIND_TRANSCRIPT and self._transcript is not None:
            art = self._transcript.read(
                acquired.asset_id, acquired.asset_version, filename=filename
            )
            out["transcript"] = {
                "outcome": art.get("outcome"),
                "char_count": art.get("char_count"),
                "reason": art.get("reason"),
            }
            text = (art.get("text") or "").strip()
            if art.get("outcome") == "ok" and text:
                out["text"] = text
                emit_media_event(
                    self._events,
                    EVENT_TRANSCRIPT_ACQUIRED,
                    {
                        "asset_id": acquired.asset_id,
                        "source_id": source_id,
                        "source_url": source_url,
                        "strategy": "transcript_file",
                        "char_count": len(text),
                    },
                )
                if to_knowledge:
                    out["ingest"] = self._to_knowledge(
                        text=text,
                        acquired=acquired,
                        filename=filename,
                        title=title
                        or (out.get("metadata") or {}).get("fields", {}).get("title")
                        or filename,
                        domain=domain,
                        embed=embed,
                        reader_id=self._transcript.id,
                        reader_version=self._transcript.VERSION,
                        source="media_transcript",
                        source_id=source_id,
                    )
            return out

        speech_asset_id = acquired.asset_id
        speech_asset_version = acquired.asset_version
        speech_filename = filename

        if kind == ASSET_KIND_VIDEO and self._demux is not None:
            out["demux"] = self._demux.read(
                acquired.asset_id, acquired.asset_version, filename=filename
            )
            demux = out["demux"] or {}
            if demux.get("outcome") == "ok" and demux.get("audio_asset_id"):
                speech_asset_id = str(demux["audio_asset_id"])
                speech_asset_version = int(demux.get("audio_asset_version") or 1)
                speech_filename = Path(filename).stem + ".wav"

        if kind in (ASSET_KIND_VIDEO, ASSET_KIND_AUDIO) and self._speech is not None:
            out["speech"] = self._speech.read(
                speech_asset_id, speech_asset_version, filename=speech_filename
            )
            speech = out["speech"] or {}
            text = (speech.get("text") or "").strip()
            if speech.get("outcome") == STT_OK and text:
                out["text"] = text
                emit_media_event(
                    self._events,
                    EVENT_TRANSCRIPT_ACQUIRED,
                    {
                        "asset_id": acquired.asset_id,
                        "source_id": source_id,
                        "source_url": source_url,
                        "strategy": "speech_to_text",
                        "model": speech.get("model"),
                        "char_count": len(text),
                    },
                )
                if to_knowledge:
                    out["ingest"] = self._to_knowledge(
                        text=text,
                        acquired=acquired,
                        filename=filename,
                        title=title
                        or (out.get("metadata") or {}).get("fields", {}).get("title")
                        or filename,
                        domain=domain,
                        embed=embed,
                        reader_id=self._speech.id,
                        reader_version=self._speech.VERSION,
                        source="media_speech_to_text",
                        source_id=source_id,
                        extra_metadata={
                            "model": speech.get("model"),
                            "strategy": "speech_to_text",
                            "evidence_level": speech.get("evidence_level", 1),
                        },
                    )
                return out

            if speech.get("capability_gap") or speech.get("outcome") != STT_OK:
                emit_media_event(
                    self._events,
                    EVENT_SPEECH_TO_TEXT_GAP,
                    {
                        "asset_id": acquired.asset_id,
                        "source_id": source_id,
                        "source_url": source_url,
                        "outcome": speech.get("outcome"),
                        "reason": speech.get("reason"),
                        "capability_gap": speech.get("capability_gap") or "speech_to_text",
                    },
                )

        note = _metadata_knowledge_note(
            filename=filename,
            kind=kind,
            meta_artifact=out.get("metadata"),
            demux_artifact=out.get("demux"),
            speech_artifact=out.get("speech"),
        )
        if note.strip() and to_knowledge:
            out["ingest"] = self._to_knowledge(
                text=note,
                acquired=acquired,
                filename=filename,
                title=title
                or (out.get("metadata") or {}).get("fields", {}).get("title")
                or filename,
                domain=domain,
                embed=embed,
                reader_id=(self._meta.id if self._meta else "media_metadata"),
                reader_version=(self._meta.VERSION if self._meta else "1.0.0"),
                source="media_metadata",
                source_id=source_id,
            )
        elif not to_knowledge and not out["text"]:
            out["outcome"] = "empty"
            out["reason"] = "no transcript text (speech_to_text gap or metadata-only)"
        return out

    def _to_knowledge(
        self,
        *,
        text: str,
        acquired: Any,
        filename: str,
        title: str,
        domain: str,
        embed: bool,
        reader_id: str,
        reader_version: str,
        source: str,
        source_id: str,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        meta = {
            "asset_id": acquired.asset_id,
            "asset_version": acquired.asset_version,
            "sha256": acquired.checksum,
            "reader": reader_id,
            "reader_version": reader_version,
            "filename": filename,
            "media_kind": acquired.kind,
            "source_id": source_id,
            **(extra_metadata or {}),
        }
        # URI keyed by stable source_id so re-ingest of the same source dedupes (P13).
        uri = acquired.source_uri or f"media:{source_id}"
        summary = self._knowledge.ingest_text(
            source=source,
            content=text,
            uri=uri,
            title=title,
            content_type="text/plain",
            metadata=meta,
            domain=domain,
            embed=embed,
            asset_id=acquired.asset_id,
            asset_version=acquired.asset_version,
        )
        return {
            "outcome": "ok",
            "document_id": summary.get("document_id"),
            "chunks": summary.get("chunks", 0),
            "deduped": bool(summary.get("deduped")),
            "source_id": source_id,
        }


def _metadata_knowledge_note(
    *,
    filename: str,
    kind: str,
    meta_artifact: dict[str, Any] | None,
    demux_artifact: dict[str, Any] | None,
    speech_artifact: dict[str, Any] | None = None,
) -> str:
    fields = (meta_artifact or {}).get("fields") if isinstance(meta_artifact, dict) else {}
    fields = fields if isinstance(fields, dict) else {}
    lines = [
        f"Media asset ({kind}): {filename}",
    ]
    for key in ("title", "description", "language", "duration", "channel", "uploader", "source_uri"):
        if fields.get(key) not in (None, "", []):
            lines.append(f"{key}: {fields[key]}")
    if demux_artifact and demux_artifact.get("outcome") == "ok":
        lines.append(
            f"audio_demux: ok → asset {demux_artifact.get('audio_asset_id')} "
            f"v{demux_artifact.get('audio_asset_version')}"
        )
    elif demux_artifact and demux_artifact.get("outcome"):
        lines.append(
            f"audio_demux: {demux_artifact.get('outcome')} "
            f"({demux_artifact.get('reason') or demux_artifact.get('capability_gap') or ''})".strip()
        )
    if speech_artifact and speech_artifact.get("outcome"):
        gap = speech_artifact.get("capability_gap") or "speech_to_text"
        lines.append(
            f"speech_to_text: {speech_artifact.get('outcome')} "
            f"({speech_artifact.get('reason') or gap})"
        )
        if speech_artifact.get("outcome") != STT_OK:
            lines.append(f"capability_gap: {gap}")
    else:
        lines.append(
            "Note: this is media metadata provenance, not a speech transcript "
            "(speech_to_text is a separate capability)."
        )
    return "\n".join(lines)
