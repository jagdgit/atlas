"""Acquisition — fetch + read the top sources into Documents (§5d, C1 / D3.1 / D3.3).

Stage 3, Step 3. The Librarian takes classified sources and, in priority order
(open-access first, then by evidence level), tries to acquire and read each one:

    classify → prioritize → fetch (resilient net) → save to workspace/downloads
             → normalize to a Document (Reader) → record manifest + activity

Stage 3.2a: prefer ar5iv HTML for arXiv identities; propagate DOI/citation metadata;
surface every empty/OCR/parse failure with stable codes (D32.8).
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlparse

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

_ARXIV_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf|html)/|ar5iv\.labs\.arxiv\.org/html/)"
    r"(?P<id>\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})",
    re.IGNORECASE,
)


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
        empty = sum(1 for d in self.documents if not d.has_text)
        return {
            "downloaded": len(self.documents),
            "read": read,
            "empty": empty,
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


def arxiv_id_from_url(url: str) -> str | None:
    """Extract an arXiv id from abs/pdf/html/ar5iv URLs when present."""
    if not url:
        return None
    m = _ARXIV_ID_RE.search(url)
    if m:
        return m.group("id")
    path = urlparse(url).path or ""
    for part in path.strip("/").split("/"):
        if re.fullmatch(r"\d{4}\.\d{4,5}(?:v\d+)?", part):
            return part
    return None


def ar5iv_html_url(url: str) -> str | None:
    """Prefer ar5iv HTML for richer full text (A32.4)."""
    aid = arxiv_id_from_url(url)
    if not aid:
        return None
    return f"https://ar5iv.labs.arxiv.org/html/{aid}"


def _ext_for(content_type: str, url: str) -> str:
    ct = (content_type or "").lower()
    for needle, ext in _CT_EXT:
        if needle in ct:
            return ext
    lower = url.lower().split("?")[0]
    for _, ext in _CT_EXT:
        if lower.endswith(ext):
            return ext
    return ".html"


def _source_metadata(source: Source) -> dict[str, Any]:
    """Bibliographic fields for Document.metadata (D32.7)."""
    meta: dict[str, Any] = {}
    if source.doi:
        meta["doi"] = source.doi
    if source.citation:
        meta["citation"] = source.citation
    if source.authors:
        meta["authors"] = list(source.authors)
    if source.year is not None:
        meta["year"] = source.year
    if source.venue:
        meta["venue"] = source.venue
    return meta


@dataclass
class _OneOutcome:
    """Isolated result for one source (merged on the main thread in source_id order)."""

    source_id: str
    title: str = ""
    documents: list[Document] = field(default_factory=list)
    blocked: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)  # found/downloaded/read for manifest
    download_url: str = ""


class Librarian:
    """Acquires and reads the top-ranked sources into normalized Documents."""

    def __init__(
        self,
        fetcher: _Fetcher,
        *,
        reader: Reader | None = None,
        max_documents: int = 12,
        open_access_first: bool = True,
        prefer_ar5iv: bool = True,
        max_workers: int = 1,
        global_max_workers: int | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._fetcher = fetcher
        self._reader = reader or Reader()
        self._max_documents = max_documents
        self._open_access_first = open_access_first
        self._prefer_ar5iv = prefer_ar5iv
        self._max_workers = max(1, int(max_workers or 1))
        self._global_max_workers = (
            int(global_max_workers) if global_max_workers is not None else self._max_workers
        )
        self._logger = logger or logging.getLogger("atlas.research.acquire")
        self._manifest_lock = threading.Lock()

    def acquire(
        self,
        sources: list[Source],
        *,
        classifications: dict[str, Classification] | None = None,
        workspace: "JobWorkspace | None" = None,
        activity: "ActivityRecorder | None" = None,
        top_k: int | None = None,
    ) -> AcquireResult:
        from atlas.research.concurrency import clamp_workers, map_parallel

        cap = top_k or self._max_documents
        ranked = self._prioritize(sources, classifications)[:cap]
        result = AcquireResult()
        if not ranked:
            return result

        workers = clamp_workers(
            self._max_workers,
            global_max=self._global_max_workers,
            fallback=1,
        )
        if activity is not None and workers > 1:
            activity.record(
                "acquire",
                f"Acquiring {len(ranked)} source(s) with up to {workers} worker(s).",
                workers=workers,
            )

        def _run(pair: tuple[Source, Classification]) -> _OneOutcome:
            source, cls = pair
            return self._process_one(source, cls, workspace)

        outcomes = map_parallel(_run, ranked, max_workers=workers, ordered=True)
        # Deterministic merge by source_id (D32.4), stable even if pool reorders work.
        outcomes.sort(key=lambda o: o.source_id)
        for outcome in outcomes:
            source = next(s for s, _ in ranked if s.id == outcome.source_id)
            cls = next(c for s, c in ranked if s.id == outcome.source_id)
            for stage in outcome.stages:
                self._record(workspace, source, cls, stage=stage)
            result.documents.extend(outcome.documents)
            result.blocked.extend(outcome.blocked)
            result.skipped.extend(outcome.skipped)
            if activity is not None:
                self._emit_activity(activity, outcome, cls)

        # Keep documents in source_id order for callers.
        result.documents.sort(key=lambda d: d.source_id)
        if activity is not None:
            s = result.stats
            activity.record(
                "acquire",
                f"Acquired {s['downloaded']} document(s), read {s['read']}; "
                f"{s['empty']} empty, {s['blocked']} blocked, {s['skipped']} skipped.",
                **s,
            )
        return result

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

    def _process_one(
        self,
        source: Source,
        cls: Classification,
        workspace: "JobWorkspace | None",
    ) -> _OneOutcome:
        """Fetch+read one source without mutating shared AcquireResult (thread-safe)."""
        title = source.title or source.url or source.id
        out = _OneOutcome(source_id=source.id, title=title)

        if cls.access_method == ACCESS_VIDEO:
            out.skipped.append(
                {
                    "source_id": source.id,
                    "url": source.url,
                    "reason": "video source (transcript not acquired here)",
                    "failure_code": "unsupported",
                }
            )
            out.stages.append("found")
            return out
        if cls.access_method == ACCESS_PAYWALL:
            out.blocked.append(
                {
                    "source_id": source.id,
                    "url": source.url,
                    "reason": "paywall/login wall — provide the document to include it, or skip",
                    "failure_code": "paywall",
                }
            )
            out.stages.append("found")
            return out
        if not source.url:
            out.skipped.append(
                {
                    "source_id": source.id,
                    "url": "",
                    "reason": "no URL to fetch",
                    "failure_code": "empty_text",
                }
            )
            return out

        fetch_urls = self._candidate_urls(source.url)
        out.download_url = fetch_urls[0]
        last_skip: dict[str, Any] | None = None
        for attempt_url in fetch_urls:
            out.download_url = attempt_url
            try:
                res = self._fetcher.get(attempt_url)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("fetch failed for %s: %s", attempt_url, exc)
                last_skip = {
                    "source_id": source.id,
                    "url": attempt_url,
                    "reason": f"fetch error: {exc}",
                    "failure_code": "parse_error",
                }
                continue

            outcome = getattr(res, "outcome", None)
            if outcome == OUTCOME_BLOCKED:
                out.blocked.append(
                    {
                        "source_id": source.id,
                        "url": attempt_url,
                        "reason": getattr(res, "reason", None) or "login/paywall required",
                        "failure_code": "paywall",
                    }
                )
                out.stages.append("found")
                return out
            if outcome != OUTCOME_OK:
                last_skip = {
                    "source_id": source.id,
                    "url": attempt_url,
                    "reason": getattr(res, "reason", None) or f"fetch {outcome}",
                    "failure_code": "parse_error",
                }
                continue

            content_type = getattr(res, "content_type", "") or ""
            doc = self._read(res, source, content_type, workspace)
            doc.metadata.update(_source_metadata(source))
            out.documents.append(doc)
            out.stages.append("downloaded")
            if doc.has_text:
                out.stages.append("read")
            self._logger.debug(
                "acquired %s -> %s (%d chars, %s, quality=%s)",
                attempt_url,
                source.id,
                doc.chars,
                doc.read_method,
                doc.quality,
            )
            return out

        if last_skip is not None:
            out.skipped.append(last_skip)
            out.stages.append("found")
        return out

    def _emit_activity(
        self,
        activity: "ActivityRecorder",
        outcome: _OneOutcome,
        cls: Classification,
    ) -> None:
        title = outcome.title
        if outcome.blocked:
            activity.record(
                "acquire",
                f"Paywalled, skipping: {title[:80]}",
                source_id=outcome.source_id,
                url=outcome.blocked[0].get("url"),
                failure_code="paywall",
            )
            return
        if outcome.skipped and not outcome.documents:
            sk = outcome.skipped[0]
            if sk.get("failure_code") == "unsupported":
                return
            activity.record(
                "acquire",
                f"Fetch failed ({sk.get('failure_code')}): {title[:80]} — "
                f"{str(sk.get('reason', ''))[:120]}",
                source_id=outcome.source_id,
                failure_code=sk.get("failure_code"),
            )
            return
        if outcome.download_url:
            activity.record(
                "acquire",
                f"Downloading [{level_name(cls.evidence_level)}]: {title[:80]}",
                source_id=outcome.source_id,
                url=outcome.download_url,
            )
        for doc in outcome.documents:
            self._record_read_activity(activity, doc, title)

    def _candidate_urls(self, url: str) -> list[str]:
        """Try ar5iv first for arXiv identities, then the original URL (A32.4)."""
        urls: list[str] = []
        if self._prefer_ar5iv:
            alt = ar5iv_html_url(url)
            if alt and alt.rstrip("/") != url.rstrip("/"):
                urls.append(alt)
        urls.append(url)
        seen: set[str] = set()
        out: list[str] = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    @staticmethod
    def _record_read_activity(
        activity: "ActivityRecorder", doc: Document, title: str
    ) -> None:
        if doc.has_text:
            msg = (
                f"Read {doc.chars} chars ({doc.read_method}/{doc.reader_id}, "
                f"quality={doc.quality}) from: {title[:80]}"
            )
            if doc.failure_code:
                msg += f" [{doc.failure_code}]"
            activity.record(
                "read",
                msg,
                source_id=doc.source_id,
                chars=doc.chars,
                reader_id=doc.reader_id,
                quality=doc.quality,
                failure_code=doc.failure_code or None,
            )
        else:
            activity.record(
                "read",
                f"No extractable text ({doc.failure_code or 'empty_text'}): "
                f"{doc.failure_reason or 'scanned/empty'} — {title[:80]}",
                source_id=doc.source_id,
                failure_code=doc.failure_code or "empty_text",
                failure_reason=doc.failure_reason,
                reader_id=doc.reader_id,
                quality=doc.quality,
            )

    def _read(
        self,
        res: Any,
        source: Source,
        content_type: str,
        workspace: "JobWorkspace | None",
    ) -> Document:
        content: bytes = getattr(res, "content", b"") or b""
        text: str = getattr(res, "text", "") or ""
        meta = _source_metadata(source)
        if workspace is not None:
            ext = _ext_for(content_type, source.url)
            path = workspace.download_path(f"{source.id}{ext}")
            try:
                if content:
                    path.write_bytes(content)
                else:
                    path.write_text(text, encoding="utf-8")
                doc = self._reader.read_path(
                    path,
                    source_id=source.id,
                    title=source.title,
                    url=source.url,
                    content_type=content_type,
                    metadata=meta,
                )
                if doc.has_text:
                    workspace.write_text(
                        workspace.document_path(source.id).relative_to(workspace.root),
                        doc.text,
                    )
                return doc
            except OSError as exc:
                self._logger.debug("workspace read failed for %s: %s", source.id, exc)
        return self._reader.read_text(
            text,
            source_id=source.id,
            title=source.title,
            url=source.url,
            content_type=content_type,
            metadata=meta,
        )

    def _record(
        self,
        workspace: "JobWorkspace | None",
        source: Source,
        cls: Classification,
        *,
        stage: str,
    ) -> None:
        if workspace is None:
            return
        try:
            with self._manifest_lock:
                workspace.record_source(
                    source.id,
                    url=source.url,
                    title=source.title,
                    source_type=cls.source_type,
                    evidence_level=source.evidence_level or cls.evidence_level,
                    access_method=cls.access_method,
                    stage=stage,
                    doi=source.doi or None,
                    citation=source.citation or None,
                )
        except Exception:  # noqa: BLE001
            pass
