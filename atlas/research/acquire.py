"""Acquisition — fetch + read the top sources into Documents (§5d, C1 / D3.1 / D3.3).

Stage 3, Step 3. The Librarian takes classified sources and, in priority order
(open-access first, then by evidence level), tries to acquire and read each one:

    classify → prioritize → fetch (resilient net) → save to workspace/downloads
             → normalize to a Document (Reader) → record manifest + activity

Honesty (D3.3): open-access content is read directly; a hard **paywall/login wall**
is **not** guessed at — the source is recorded as *blocked* with an honest reason
(the user can provide the file and resume, per Stage-2 HITL), and the run continues
with whatever is accessible. Video sources are skipped here (transcripts are a separate
tool wired into the loop later). A per-run **document cap** (D3.2) bounds cost.

The Librarian is deliberately decoupled: it depends on a ``fetcher`` with
``get(url) -> FetchResult`` (the resilient ``net.FetchClient``), an optional workspace
(durable artifacts), and an optional activity recorder (the live feed) — all injectable,
so the whole thing runs offline in tests with a fake fetcher.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from atlas.evidence.models import Source, level_name
from atlas.net import OUTCOME_BLOCKED, OUTCOME_OK
from atlas.research.classifier import (
    ACCESS_OPEN,
    ACCESS_PAYWALL,
    ACCESS_VIDEO,
    Classification,
    classify,
)
from atlas.research.reader import Document, Reader

if TYPE_CHECKING:
    from atlas.jobs.activity import ActivityRecorder
    from atlas.jobs.workspace import JobWorkspace

# Extension to save a fetched artifact under, so the Reader's extension-keyed
# extractors fire. Keyed by a coarse content-type family.
_CT_EXT = [
    ("pdf", ".pdf"),
    ("html", ".html"),
    ("xml", ".html"),
    ("markdown", ".md"),
    ("plain", ".txt"),
    ("json", ".json"),
    ("csv", ".csv"),
]


class _Fetcher(Protocol):
    def get(self, url: str) -> Any: ...  # returns a net.FetchResult-like object


@dataclass
class AcquireResult:
    """The outcome of an acquisition pass over a set of sources."""

    documents: list[Document] = field(default_factory=list)
    blocked: list[dict[str, Any]] = field(default_factory=list)   # paywalls / login walls
    skipped: list[dict[str, Any]] = field(default_factory=list)   # errors / video / no text

    @property
    def stats(self) -> dict[str, int]:
        read = sum(1 for d in self.documents if d.has_text)
        return {
            "downloaded": len(self.documents),
            "read": read,
            "blocked": len(self.blocked),
            "skipped": len(self.skipped),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "documents": [d.as_dict() for d in self.documents],
            "blocked": self.blocked,
            "skipped": self.skipped,
            "stats": self.stats,
        }


def _ext_for(content_type: str, url: str) -> str:
    ct = (content_type or "").lower()
    for needle, ext in _CT_EXT:
        if needle in ct:
            return ext
    # Fall back to the URL's own suffix if it looks like a known document.
    lower = url.lower().split("?")[0]
    for _, ext in _CT_EXT:
        if lower.endswith(ext):
            return ext
    return ".html"  # most web hits are HTML pages


class Librarian:
    """Acquires and reads the top-ranked sources into normalized Documents."""

    def __init__(
        self,
        fetcher: _Fetcher,
        *,
        reader: Reader | None = None,
        max_documents: int = 12,
        open_access_first: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        self._fetcher = fetcher
        self._reader = reader or Reader()
        self._max_documents = max_documents
        self._open_access_first = open_access_first
        self._logger = logger or logging.getLogger("atlas.research.acquire")

    def acquire(
        self,
        sources: list[Source],
        *,
        classifications: dict[str, Classification] | None = None,
        workspace: "JobWorkspace | None" = None,
        activity: "ActivityRecorder | None" = None,
        top_k: int | None = None,
    ) -> AcquireResult:
        cap = top_k or self._max_documents
        ranked = self._prioritize(sources, classifications)
        result = AcquireResult()
        attempted = 0
        for source, cls in ranked:
            if attempted >= cap:
                break
            attempted += 1
            self._acquire_one(source, cls, result, workspace, activity)
        if activity is not None:
            s = result.stats
            activity.record(
                "acquire",
                f"Acquired {s['downloaded']} document(s), read {s['read']}; "
                f"{s['blocked']} blocked, {s['skipped']} skipped.",
                **s,
            )
        return result

    # --- internals ------------------------------------------------------
    def _prioritize(
        self,
        sources: list[Source],
        classifications: dict[str, Classification] | None,
    ) -> list[tuple[Source, Classification]]:
        pairs: list[tuple[Source, Classification]] = []
        for src in sources:
            cls = (classifications or {}).get(src.id) or classify(src.url)
            pairs.append((src, cls))

        def sort_key(pair: tuple[Source, Classification]):
            src, cls = pair
            open_rank = 0 if (self._open_access_first and cls.access_method == ACCESS_OPEN) else 1
            return (open_rank, -int(src.evidence_level or cls.evidence_level))

        return sorted(pairs, key=sort_key)

    def _acquire_one(
        self,
        source: Source,
        cls: Classification,
        result: AcquireResult,
        workspace: "JobWorkspace | None",
        activity: "ActivityRecorder | None",
    ) -> None:
        title = source.title or source.url or source.id
        if cls.access_method == ACCESS_VIDEO:
            result.skipped.append(
                {"source_id": source.id, "url": source.url,
                 "reason": "video source (transcript not acquired here)"}
            )
            self._record(workspace, source, cls, stage="found")
            return
        if cls.access_method == ACCESS_PAYWALL:
            reason = "paywall/login wall — provide the document to include it, or skip"
            result.blocked.append(
                {"source_id": source.id, "url": source.url, "reason": reason}
            )
            self._record(workspace, source, cls, stage="found")
            if activity is not None:
                activity.record("acquire", f"Paywalled, skipping: {title[:80]}",
                                 source_id=source.id, url=source.url)
            return

        if not source.url:
            result.skipped.append(
                {"source_id": source.id, "url": "", "reason": "no URL to fetch"}
            )
            return

        if activity is not None:
            activity.record(
                "acquire",
                f"Downloading [{level_name(cls.evidence_level)}]: {title[:80]}",
                source_id=source.id, url=source.url,
            )
        try:
            res = self._fetcher.get(source.url)
        except Exception as exc:  # noqa: BLE001 - a bad fetch must not crash the loop
            self._logger.debug("fetch failed for %s: %s", source.url, exc)
            result.skipped.append(
                {"source_id": source.id, "url": source.url, "reason": f"fetch error: {exc}"}
            )
            return

        outcome = getattr(res, "outcome", None)
        if outcome == OUTCOME_BLOCKED:
            result.blocked.append(
                {"source_id": source.id, "url": source.url,
                 "reason": getattr(res, "reason", None) or "login/paywall required"}
            )
            self._record(workspace, source, cls, stage="found")
            return
        if outcome != OUTCOME_OK:
            result.skipped.append(
                {"source_id": source.id, "url": source.url,
                 "reason": getattr(res, "reason", None) or f"fetch {outcome}"}
            )
            self._record(workspace, source, cls, stage="found")
            return

        content_type = getattr(res, "content_type", "") or ""
        doc = self._read(res, source, content_type, workspace)
        result.documents.append(doc)
        stage = "read" if doc.has_text else "downloaded"
        self._record(workspace, source, cls, stage="downloaded")
        if doc.has_text:
            self._record(workspace, source, cls, stage="read")
        if activity is not None:
            if doc.has_text:
                activity.record(
                    "read",
                    f"Read {doc.chars} chars ({doc.read_method}) from: {title[:80]}",
                    source_id=source.id, chars=doc.chars,
                )
            else:
                activity.record(
                    "read",
                    f"No extractable text (scanned/empty): {title[:80]}",
                    source_id=source.id,
                )
        self._logger.debug("acquired %s -> %s (%d chars, %s)",
                           source.url, source.id, doc.chars, stage)

    def _read(
        self,
        res: Any,
        source: Source,
        content_type: str,
        workspace: "JobWorkspace | None",
    ) -> Document:
        content: bytes = getattr(res, "content", b"") or b""
        text: str = getattr(res, "text", "") or ""
        if workspace is not None:
            # Persist the raw artifact under downloads/ with a format-appropriate
            # suffix so the Reader's extension-keyed extractors fire, then read it.
            ext = _ext_for(content_type, source.url)
            path = workspace.download_path(f"{source.id}{ext}")
            try:
                if content:
                    path.write_bytes(content)
                else:
                    path.write_text(text, encoding="utf-8")
                doc = self._reader.read_path(
                    path, source_id=source.id, title=source.title,
                    url=source.url, content_type=content_type,
                )
                if doc.has_text:
                    workspace.write_text(
                        workspace.document_path(source.id).relative_to(workspace.root),
                        doc.text,
                    )
                return doc
            except OSError as exc:
                self._logger.debug("workspace read failed for %s: %s", source.id, exc)
        # No workspace (or write failed): read from the decoded text in memory.
        return self._reader.read_text(
            text, source_id=source.id, title=source.title,
            url=source.url, content_type=content_type,
        )

    @staticmethod
    def _record(
        workspace: "JobWorkspace | None",
        source: Source,
        cls: Classification,
        *,
        stage: str,
    ) -> None:
        if workspace is None:
            return
        try:
            workspace.record_source(
                source.id,
                url=source.url,
                title=source.title,
                source_type=cls.source_type,
                evidence_level=source.evidence_level or cls.evidence_level,
                access_method=cls.access_method,
                stage=stage,
            )
        except Exception:  # noqa: BLE001 - manifest is best-effort
            pass
