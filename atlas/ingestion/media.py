"""Local media ingest orchestration (Media Reader Family · M.4).

Asset-first path for operator files:

    local .vtt/.srt/.txt/.mp4/.mp3
        → AssetAcquirer (kind=video|audio|transcript)
        → MediaMetadataReader
        → TranscriptFileReader (transcript kinds) and/or AudioDemuxReader (video)
        → Knowledge (transcript text, or an honest metadata note for A/V)

No YouTube-specific branches past the Asset boundary (MD8). Speech-to-text is M.5.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from atlas.readers.media_kinds import (
    ASSET_KIND_TRANSCRIPT,
    ASSET_KIND_VIDEO,
    content_type_for,
    infer_media_kind,
)

if TYPE_CHECKING:
    from atlas.ingestion.acquire import AssetAcquirer
    from atlas.knowledge.service import KnowledgeService
    from atlas.readers.audio_demux import AudioDemuxReader
    from atlas.readers.media_metadata import MediaMetadataReader
    from atlas.readers.transcript_file import TranscriptFileReader


class MediaIngestor:
    """Acquire → metadata → transcript/demux → knowledge for local media files."""

    def __init__(
        self,
        acquirer: "AssetAcquirer",
        knowledge: "KnowledgeService",
        *,
        metadata_reader: "MediaMetadataReader | None" = None,
        transcript_reader: "TranscriptFileReader | None" = None,
        demux_reader: "AudioDemuxReader | None" = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._acq = acquirer
        self._knowledge = knowledge
        self._meta = metadata_reader
        self._transcript = transcript_reader
        self._demux = demux_reader
        self._logger = logger or logging.getLogger("atlas.ingestion.media")

    def ingest_file(
        self,
        path: str | Path,
        *,
        domain: str = "external",
        title: str | None = None,
        embed: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(str(p))
        kind = infer_media_kind(p.name)
        if kind is None:
            raise ValueError(f"not a media file: {p.name}")

        meta = {"filename": p.name, **(metadata or {})}
        acquired = self._acq.acquire_file(
            p,
            kind=kind,
            content_type=content_type_for(p.name),
            metadata=meta,
        )
        out: dict[str, Any] = {
            "asset_id": acquired.asset_id,
            "asset_version": acquired.asset_version,
            "asset_reused": acquired.reused,
            "kind": kind,
            "filename": p.name,
            "metadata": None,
            "demux": None,
            "ingest": None,
        }

        if self._meta is not None:
            out["metadata"] = self._meta.read(
                acquired.asset_id, acquired.asset_version, filename=p.name
            )

        if kind == ASSET_KIND_TRANSCRIPT and self._transcript is not None:
            art = self._transcript.read(
                acquired.asset_id, acquired.asset_version, filename=p.name
            )
            out["transcript"] = {
                "outcome": art.get("outcome"),
                "char_count": art.get("char_count"),
                "reason": art.get("reason"),
            }
            if art.get("outcome") == "ok" and (art.get("text") or "").strip():
                out["ingest"] = self._to_knowledge(
                    text=art["text"],
                    acquired=acquired,
                    filename=p.name,
                    title=title or (out.get("metadata") or {}).get("fields", {}).get("title") or p.name,
                    domain=domain,
                    embed=embed,
                    reader_id=self._transcript.id,
                    reader_version=self._transcript.VERSION,
                    source="media_transcript",
                )
            return out

        if kind == ASSET_KIND_VIDEO and self._demux is not None:
            out["demux"] = self._demux.read(
                acquired.asset_id, acquired.asset_version, filename=p.name
            )

        # A/V without speech-to-text (M.5): land an honest metadata note in Knowledge
        # so the asset is findable — never a fabricated transcript.
        note = _metadata_knowledge_note(
            filename=p.name,
            kind=kind,
            meta_artifact=out.get("metadata"),
            demux_artifact=out.get("demux"),
        )
        if note.strip():
            out["ingest"] = self._to_knowledge(
                text=note,
                acquired=acquired,
                filename=p.name,
                title=title or (out.get("metadata") or {}).get("fields", {}).get("title") or p.name,
                domain=domain,
                embed=embed,
                reader_id=(self._meta.id if self._meta else "media_metadata"),
                reader_version=(self._meta.VERSION if self._meta else "1.0.0"),
                source="media_metadata",
            )
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
    ) -> dict[str, Any]:
        summary = self._knowledge.ingest_text(
            source=source,
            content=text,
            uri=acquired.source_uri,
            title=title,
            content_type="text/plain",
            metadata={
                "asset_id": acquired.asset_id,
                "asset_version": acquired.asset_version,
                "sha256": acquired.checksum,
                "reader": reader_id,
                "reader_version": reader_version,
                "filename": filename,
                "media_kind": acquired.kind,
            },
            domain=domain,
            embed=embed,
        )
        return {
            "outcome": "ok",
            "document_id": summary.get("document_id"),
            "chunks": summary.get("chunks", 0),
            "deduped": bool(summary.get("deduped")),
        }


def _metadata_knowledge_note(
    *,
    filename: str,
    kind: str,
    meta_artifact: dict[str, Any] | None,
    demux_artifact: dict[str, Any] | None,
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
    lines.append(
        "Note: this is media metadata provenance, not a speech transcript "
        "(speech_to_text is a separate capability)."
    )
    return "\n".join(lines)
