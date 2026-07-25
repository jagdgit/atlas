"""Document Reader (Phase C · PHASE_C_PLAN §C.2, BB10/BB11 / constitution P11).

The first **non-code** reader: it turns a document **Asset** (pdf/docx/txt/md/html/…) into a
structured text **Artifact** — the derived product that later feeds both RAG chunking and prose
finding extraction. It reuses the shared extractor engine (:class:`atlas.documents.DocumentService`
over ``atlas.ingestion.extractors``) and caches the artifact in the **Derived Artifact Store**
keyed by ``{asset_id, asset_version, reader, reader_version}`` (BB11), so re-reading an unchanged
asset is a cheap cache hit and improving the *extractor* re-runs without re-fetching the asset.

Per constitution **P11** this reader owns no knowledge or state: it reads bytes and returns an
artifact. It is deliberately duck-typed against the Asset Store (needs ``get_bytes``/``versions``)
and the artifact cache (needs ``get``/``put``) so it does not couple to the engineering package.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from atlas.documents.service import DocumentService

if TYPE_CHECKING:
    from atlas.assets.service import AssetStore

DOCUMENT_READER_ID = "document"
DOCUMENT_READER_VERSION = "1.1.0"  # OI-M7: PDF ReaderStrategyChain (text → OCR)


class DocumentReader:
    """Read a document asset → cached text artifact (BB11); reuse when unchanged."""

    id = DOCUMENT_READER_ID
    VERSION = DOCUMENT_READER_VERSION

    def __init__(
        self,
        assets: "AssetStore",
        artifacts: Any,
        *,
        documents: DocumentService | None = None,
        pdf_ocr: Any | None = None,
        min_pdf_text_chars: int = 40,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = assets
        self._artifacts = artifacts  # DerivedArtifactStore (duck-typed: get/put)
        self._docs = documents or DocumentService()
        self._pdf_ocr = pdf_ocr
        self._min_pdf_text_chars = int(min_pdf_text_chars)
        self._logger = logger or logging.getLogger("atlas.readers.document")

    def supported_extensions(self) -> list[str]:
        """File extensions this reader can extract (e.g. ``.pdf``, ``.md``)."""
        return self._docs.supported()

    def read(
        self,
        asset_id: str,
        asset_version: int | None = None,
        *,
        filename: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Return the text artifact for ``(asset_id, version)`` — from cache unless ``force``.

        ``filename`` supplies the extension the extractor dispatches on; when omitted it is read
        from the asset version's ``metadata.filename`` (stamped by the Asset Acquirer).
        """
        version = self._resolve_version(asset_id, asset_version)

        if not force:
            cached = self._artifacts.get(asset_id, version, self.id, self.VERSION)
            if cached is not None:
                self._logger.debug(
                    "artifact hit for %s v%s (%s@%s)",
                    asset_id, version, self.id, self.VERSION,
                )
                return cached

        filename = filename or self._filename_from_metadata(asset_id, version)
        data = self._assets.get_bytes(asset_id, version)
        artifact = self._extract(data, filename, asset_id, version)
        self._artifacts.put(asset_id, version, self.id, self.VERSION, artifact)
        return artifact

    # --- internals ------------------------------------------------------
    def _extract(
        self, data: bytes, filename: str | None, asset_id: str, version: int
    ) -> dict[str, Any]:
        # Extractors dispatch on file extension, so materialize the bytes with the right suffix.
        suffix = Path(filename).suffix.lower() if filename else ""
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            tmp.write(data)
            tmp.flush()
            path = tmp.name
            if suffix == ".pdf":
                return self._extract_pdf_chained(path, asset_id, version, suffix)
            result = self._docs.extract(path)
        text = result.text or ""
        return {
            "reader": self.id,
            "reader_version": self.VERSION,
            "asset_id": asset_id,
            "asset_version": version,
            "outcome": result.outcome,
            "content_type": result.content_type,
            "extension": suffix,
            "text": text,
            "chars": len(text),
            "reason": result.reason,
            "method": "document",
            "strategies_tried": [],
            "sections": [{"ordinal": 0, "text": text}] if text else [],
        }

    def _extract_pdf_chained(
        self, path: str, asset_id: str, version: int, suffix: str
    ) -> dict[str, Any]:
        """OI-M7 — ReaderStrategyChain: pdf_text_layer → pdf_ocr (first ok wins)."""
        from atlas.readers.strategy_chain import ReaderStrategyChain, StrategyResult

        def text_layer() -> StrategyResult:
            result = self._docs.extract(path)
            text = (result.text or "").strip()
            if result.outcome == "ok" and len(text) >= self._min_pdf_text_chars:
                return StrategyResult(
                    name="pdf_text_layer",
                    outcome="ok",
                    reason=None,
                    bytes_read=len(text),
                    value=result,
                )
            return StrategyResult(
                name="pdf_text_layer",
                outcome="empty" if not text else "weak",
                reason=result.reason or "weak_or_empty_text_layer",
                reason_code="weak_text",
                bytes_read=len(text),
                value=result,
            )

        def ocr_layer() -> StrategyResult:
            if self._pdf_ocr is None:
                return StrategyResult(
                    name="pdf_ocr",
                    outcome="unavailable",
                    reason="pdf_ocr not configured",
                    reason_code="ocr_unavailable",
                )
            try:
                if callable(self._pdf_ocr):
                    out = self._pdf_ocr(path)
                elif hasattr(self._pdf_ocr, "ocr_pdf"):
                    out = self._pdf_ocr.ocr_pdf(path)
                else:
                    return StrategyResult(
                        name="pdf_ocr",
                        outcome="unavailable",
                        reason="pdf_ocr missing ocr_pdf",
                        reason_code="ocr_unavailable",
                    )
            except Exception as exc:  # noqa: BLE001
                return StrategyResult(
                    name="pdf_ocr",
                    outcome="error",
                    reason=str(exc),
                    reason_code="ocr_failed",
                )
            if isinstance(out, dict):
                text = str(out.get("text") or "").strip()
                ok = bool(text) and out.get("outcome", "ok") in {"ok", "partial", None}
            else:
                text = str(getattr(out, "text", "") or "").strip()
                ok = bool(text)
            if ok:
                return StrategyResult(
                    name="pdf_ocr",
                    outcome="ok",
                    bytes_read=len(text),
                    value=out,
                )
            return StrategyResult(
                name="pdf_ocr",
                outcome="empty",
                reason="ocr produced no text",
                reason_code="empty_text",
                value=out,
            )

        chain = ReaderStrategyChain()
        ran = chain.execute(
            [
                ("pdf_text_layer", text_layer),
                ("pdf_ocr", ocr_layer),
            ]
        )
        tried = [r.as_dict() for r in ran.tried]
        if ran.ok and ran.winner is not None:
            winner = ran.winner
            raw = winner.value
            if hasattr(raw, "text"):
                text = raw.text or ""
                content_type = getattr(raw, "content_type", "application/pdf")
                outcome = "ok"
                reason = None
            elif isinstance(raw, dict):
                text = str(raw.get("text") or "")
                content_type = "application/pdf"
                outcome = "ok"
                reason = raw.get("reason")
            else:
                text = ""
                content_type = "application/pdf"
                outcome = "ok"
                reason = None
            return {
                "reader": self.id,
                "reader_version": self.VERSION,
                "asset_id": asset_id,
                "asset_version": version,
                "outcome": outcome,
                "content_type": content_type,
                "extension": suffix,
                "text": text,
                "chars": len(text),
                "reason": reason,
                "method": winner.name,
                "strategies_tried": tried,
                "sections": [{"ordinal": 0, "text": text}] if text else [],
            }

        # No winner — surface best effort from text layer if present.
        first = ran.tried[0].value if ran.tried else None
        text = ""
        content_type = "application/pdf"
        outcome = "empty"
        reason = "pdf strategies exhausted"
        if first is not None and hasattr(first, "text"):
            text = first.text or ""
            content_type = getattr(first, "content_type", content_type)
            outcome = getattr(first, "outcome", outcome) or outcome
            reason = getattr(first, "reason", None) or reason
        return {
            "reader": self.id,
            "reader_version": self.VERSION,
            "asset_id": asset_id,
            "asset_version": version,
            "outcome": outcome,
            "content_type": content_type,
            "extension": suffix,
            "text": text,
            "chars": len(text),
            "reason": reason,
            "method": None,
            "strategies_tried": tried,
            "sections": [{"ordinal": 0, "text": text}] if text else [],
        }

    def _resolve_version(self, asset_id: str, asset_version: int | None) -> int:
        if asset_version is not None:
            return int(asset_version)
        versions = self._assets.versions(asset_id)
        if not versions:
            raise ValueError(f"asset has no versions: {asset_id}")
        return int(versions[0]["version"])

    def _filename_from_metadata(self, asset_id: str, version: int) -> str | None:
        for row in self._assets.versions(asset_id):
            if int(row.get("version", -1)) == version:
                meta = row.get("metadata") or {}
                name = meta.get("filename")
                return str(name) if name else None
        return None
