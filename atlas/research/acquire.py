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
from typing import TYPE_CHECKING, Any, Callable, Protocol
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
from atlas.transcripts.acquisition import REASON_ROBOTS_DISALLOWED, AcquisitionRecord

if TYPE_CHECKING:
    from atlas.ingestion.media import MediaIngestor
    from atlas.jobs.activity import ActivityRecorder
    from atlas.jobs.workspace import JobWorkspace
    from atlas.transcripts.youtube import TranscriptResult

# Optional: url_or_id → TranscriptResult (Media Reader Family · M.1).
TranscriptFetcher = Callable[[str], "TranscriptResult"]

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


# Highwire/Google-Scholar metadata tag that publishers (IEEE, Springer, MDPI,
# Wiley, ScienceDirect, PLOS, …) expose on the article landing page to advertise
# the full-text PDF. Resolving it turns a landing-page HTML "0 claims" into the
# real article. Match regardless of attribute order or quote style.
_CITATION_PDF_RES = (
    re.compile(
        r"<meta[^>]+name=[\"']citation_pdf_url[\"'][^>]+content=[\"']([^\"']+)[\"']",
        re.IGNORECASE,
    ),
    re.compile(
        r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+name=[\"']citation_pdf_url[\"']",
        re.IGNORECASE,
    ),
)
# Below this many characters, an HTML "article" is almost certainly a landing
# page / abstract stub rather than full text worth extracting from.
_LANDING_MAX_CHARS = 4000


def citation_pdf_url(html: str, base_url: str = "") -> str | None:
    """Return the ``citation_pdf_url`` advertised by a publisher landing page."""
    if not html:
        return None
    for rx in _CITATION_PDF_RES:
        m = rx.search(html)
        if m:
            href = (m.group(1) or "").strip()
            if not href:
                continue
            if href.startswith("//"):
                scheme = urlparse(base_url).scheme or "https"
                return f"{scheme}:{href}"
            if href.startswith("/") and base_url:
                p = urlparse(base_url)
                return f"{p.scheme}://{p.netloc}{href}"
            return href
    return None


_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>]+)", re.IGNORECASE)


def canonical_source_id(source: Any) -> str:
    """A stable identity for the *logical paper*, collapsing representations.

    arXiv abstract/PDF/HTML/ar5iv URLs and DOI landing pages all map to a single
    key so the same study is never counted as two independent sources (which would
    inflate convergence and support). Falls back to a normalized URL, then id.
    """
    doi = (getattr(source, "doi", "") or "").strip().lower()
    if not doi:
        # DOIs sometimes only live in the citation string or URL.
        for text in (getattr(source, "citation", ""), getattr(source, "url", "")):
            m = _DOI_RE.search(str(text or ""))
            if m:
                doi = m.group(1).lower()
                break
    if doi:
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi).rstrip("/.")
        return f"doi:{doi}"
    url = (getattr(source, "url", "") or "").strip()
    aid = arxiv_id_from_url(url)
    if aid:
        return "arxiv:" + re.sub(r"v\d+$", "", aid)
    if url:
        p = urlparse(url.lower())
        host = p.netloc.replace("www.", "")
        path = (p.path or "").rstrip("/")
        return f"url:{host}{path}"
    return f"id:{getattr(source, 'id', '')}"


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
        transcript_fetcher: TranscriptFetcher | None = None,
        media_ingestor: "MediaIngestor | None" = None,
        events: Any | None = None,
        max_documents: int = 12,
        open_access_first: bool = True,
        prefer_ar5iv: bool = True,
        max_workers: int = 1,
        global_max_workers: int | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._fetcher = fetcher
        self._reader = reader or Reader()
        self._transcript_fetcher = transcript_fetcher
        self._media = media_ingestor
        self._events = events
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

        outcomes = map_parallel(
            _run, ranked, max_workers=workers, ordered=True, logger=self._logger
        )
        # Deterministic merge by source_id (D32.4), stable even if pool reorders work.
        outcomes.sort(key=lambda o: o.source_id)
        by_source = {s.id: (s, c) for s, c in ranked}
        for outcome in outcomes:
            source, cls = by_source.get(outcome.source_id, (None, None))
            # Always merge the acquired artifacts — even if we somehow can't map the
            # source back for manifest/activity, the documents must not be lost.
            result.documents.extend(outcome.documents)
            result.blocked.extend(outcome.blocked)
            result.skipped.extend(outcome.skipped)
            if source is None or cls is None:
                continue
            for stage in outcome.stages:
                self._record(workspace, source, cls, stage=stage)
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
            return self._acquire_video(source, out)
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
            # Read + optional landing-page→PDF resolution are isolated per source:
            # a single reader/resolver exception must NEVER abort the acquisition
            # batch. (Regression 2026-07-18: one worker raising here propagated up
            # through the thread pool and discarded every already-read document, so
            # the funnel showed 0 acquired/read even though a doc was on disk.)
            try:
                doc = self._read(res, source, content_type, workspace)
                doc.metadata.update(_source_metadata(source))
                # Publisher landing page → resolve to the advertised article PDF.
                doc = self._maybe_resolve_pdf(
                    doc, res, source, content_type, attempt_url, workspace
                )
            except Exception as exc:  # noqa: BLE001 - one bad source ≠ batch failure
                self._logger.exception(
                    "read/resolve failed for %s (%s)", attempt_url, source.id
                )
                last_skip = {
                    "source_id": source.id,
                    "url": attempt_url,
                    "reason": f"reader error: {type(exc).__name__}: {exc}",
                    "failure_code": "parse_error",
                }
                continue
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

    def _acquire_video(self, source: Source, out: _OneOutcome) -> _OneOutcome:
        """Media Reader Family · M.1–M.7: captions first, then Asset-first media path.

        Never fabricates transcript text. Provider logic stops once bytes/text exist;
        Documents are stamped with a stable ``source_id`` (P13), not YouTube-specific
        Knowledge branches.
        """
        from atlas.ingestion.media_events import (
            EVENT_MEDIA_READ_FAILED,
            EVENT_TRANSCRIPT_ACQUIRED,
            emit_media_event,
        )
        from atlas.ingestion.source_fetch import stable_source_id

        url = source.url or ""
        source_id = stable_source_id(url or source.id)
        out.stages.append("found")

        # --- 1) Caption / transcript strategy chain (existing YouTube captions) ---
        caption_entry: dict[str, Any]
        if self._transcript_fetcher is not None:
            try:
                result = self._transcript_fetcher(url or source.id)
            except Exception as exc:  # noqa: BLE001 - acquisition must never abort the batch
                self._logger.debug("transcript fetch failed for %s: %s", url, exc)
                acq = AcquisitionRecord.not_attempted(
                    source_url=url, reason=f"transcript fetch error: {exc}"
                )
                caption_entry = {
                    "source_id": source.id,
                    "url": url,
                    "reason": str(exc),
                    "failure_code": "parse_error",
                    "acquisition": acq.as_dict(),
                }
            else:
                acq = result.acquisition or AcquisitionRecord.not_attempted(source_url=url)
                caption_entry = {
                    "source_id": source.id,
                    "url": url,
                    "reason": result.reason or acq.reason or result.outcome,
                    "failure_code": acq.reason_code,
                    "acquisition": acq.as_dict(),
                }
                if result.ok and (result.text or "").strip():
                    title = result.title or source.title or source.url or source.id
                    doc = self._reader.read_text(
                        result.text,
                        source_id=source.id,
                        title=title,
                        url=url,
                        content_type="text/plain",
                        metadata={
                            "kind": "transcript",
                            "source_id": source_id,
                            "language": result.language,
                            "strategy": "caption_tracks",
                            "acquisition": acq.as_dict(),
                        },
                        reader_id="media_transcript",
                    )
                    out.documents.append(doc)
                    out.stages.extend(
                        ["downloaded", "read"] if doc.has_text else ["downloaded"]
                    )
                    emit_media_event(
                        self._events,
                        EVENT_TRANSCRIPT_ACQUIRED,
                        {
                            "source_url": url,
                            "source_id": source_id,
                            "strategy": "caption_tracks",
                            "char_count": len(result.text or ""),
                            "job_source_id": source.id,
                        },
                    )
                    return out

                # Robots / hard blocks stay blocked (honest failure, 0 docs).
                if (
                    result.outcome == OUTCOME_BLOCKED
                    or acq.reason_code == REASON_ROBOTS_DISALLOWED
                    or "robots" in (result.reason or "").lower()
                ):
                    out.blocked.append(caption_entry)
                    emit_media_event(
                        self._events,
                        EVENT_MEDIA_READ_FAILED,
                        {
                            "source_url": url,
                            "source_id": source_id,
                            "reason": caption_entry["reason"],
                            "reason_code": caption_entry["failure_code"],
                            "job_source_id": source.id,
                        },
                    )
                    return out
        else:
            caption_entry = {
                "source_id": source.id,
                "url": url,
                "reason": "video source — transcript fetcher not configured",
                "failure_code": "unsupported",
                "acquisition": AcquisitionRecord.not_attempted(
                    source_url=url,
                    reason="video source — transcript fetcher not configured",
                ).as_dict(),
            }

        # --- 2) Asset-first fallback (SourceFetcher → Metadata → speech/transcript) ---
        if self._media is not None and url:
            try:
                media_out = self._media.ingest_url(url, embed=False, to_knowledge=False)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("media ingest failed for %s: %s", url, exc)
                media_out = {
                    "outcome": "error",
                    "reason": str(exc),
                    "text": "",
                    "operator_hint": "upload a local file or a transcript asset",
                }
            text = (media_out.get("text") or "").strip()
            if text:
                title = source.title or media_out.get("filename") or url or source.id
                strategy = "speech_to_text" if media_out.get("speech") else "media_asset"
                doc = self._reader.read_text(
                    text,
                    source_id=source.id,
                    title=title,
                    url=url,
                    content_type="text/plain",
                    metadata={
                        "kind": "transcript",
                        "source_id": media_out.get("source_id") or source_id,
                        "strategy": strategy,
                        "asset_id": media_out.get("asset_id"),
                        "media_kind": media_out.get("kind"),
                    },
                    reader_id="media_transcript",
                )
                out.documents.append(doc)
                out.stages.extend(["downloaded", "read"] if doc.has_text else ["downloaded"])
                emit_media_event(
                    self._events,
                    EVENT_TRANSCRIPT_ACQUIRED,
                    {
                        "source_url": url,
                        "source_id": media_out.get("source_id") or source_id,
                        "strategy": strategy,
                        "char_count": len(text),
                        "job_source_id": source.id,
                    },
                )
                return out

            outcome = media_out.get("outcome") or "skipped"
            entry = {
                "source_id": source.id,
                "url": url,
                "reason": media_out.get("reason")
                or (media_out.get("fetch") or {}).get("reason")
                or caption_entry.get("reason")
                or outcome,
                "failure_code": (media_out.get("fetch") or {}).get("reason_code")
                or caption_entry.get("failure_code")
                or outcome,
                "operator_hint": media_out.get("operator_hint"),
                "acquisition": caption_entry.get("acquisition"),
                "media": {
                    k: media_out.get(k)
                    for k in ("outcome", "fetch", "speech", "source_id")
                    if media_out.get(k) is not None
                },
            }
            if outcome == "blocked" or entry["failure_code"] == REASON_ROBOTS_DISALLOWED:
                out.blocked.append(entry)
            else:
                out.skipped.append(entry)
            emit_media_event(
                self._events,
                EVENT_MEDIA_READ_FAILED,
                {
                    "source_url": url,
                    "source_id": media_out.get("source_id") or source_id,
                    "reason": entry["reason"],
                    "reason_code": entry["failure_code"],
                    "operator_hint": entry.get("operator_hint"),
                    "job_source_id": source.id,
                },
            )
            return out

        # --- 3) No media path — report caption failure honestly ---
        if caption_entry.get("failure_code") == REASON_ROBOTS_DISALLOWED:
            out.blocked.append(caption_entry)
        else:
            out.skipped.append(caption_entry)
        emit_media_event(
            self._events,
            EVENT_MEDIA_READ_FAILED,
            {
                "source_url": url,
                "source_id": source_id,
                "reason": caption_entry.get("reason"),
                "reason_code": caption_entry.get("failure_code"),
                "job_source_id": source.id,
            },
        )
        return out

    def _emit_activity(
        self,
        activity: "ActivityRecorder",
        outcome: _OneOutcome,
        cls: Classification,
    ) -> None:
        title = outcome.title
        if outcome.blocked:
            blk = outcome.blocked[0]
            acq = blk.get("acquisition") if isinstance(blk.get("acquisition"), dict) else None
            if acq and acq.get("operator_summary"):
                activity.record(
                    "acquire",
                    str(acq["operator_summary"])[:240],
                    source_id=outcome.source_id,
                    url=blk.get("url"),
                    failure_code=blk.get("failure_code"),
                    reason_code=acq.get("reason_code"),
                )
                return
            activity.record(
                "acquire",
                f"Paywalled, skipping: {title[:80]}",
                source_id=outcome.source_id,
                url=blk.get("url"),
                failure_code="paywall",
            )
            return
        if outcome.skipped and not outcome.documents:
            sk = outcome.skipped[0]
            acq = sk.get("acquisition") if isinstance(sk.get("acquisition"), dict) else None
            if acq and acq.get("operator_summary"):
                activity.record(
                    "acquire",
                    str(acq["operator_summary"])[:240],
                    source_id=outcome.source_id,
                    url=sk.get("url"),
                    failure_code=sk.get("failure_code"),
                    reason_code=acq.get("reason_code"),
                )
                return
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

    def _maybe_resolve_pdf(
        self,
        doc: Document,
        res: Any,
        source: Source,
        content_type: str,
        attempt_url: str,
        workspace: "JobWorkspace | None",
    ) -> Document:
        """If ``doc`` is a publisher landing page, fetch the advertised article PDF.

        Turns the common "IEEE/Springer landing page → 0 claims" failure into
        either the real full text, or an honest reader-failure reason that names
        the landing page — never a silent empty document.
        """
        if "html" not in (content_type or "").lower():
            return doc
        # Only bother when this looks like a stub (no text or short abstract page).
        if doc.has_text and doc.chars >= _LANDING_MAX_CHARS:
            return doc
        raw_html = getattr(res, "text", "") or ""
        if not raw_html:
            raw = getattr(res, "content", b"") or b""
            if isinstance(raw, bytes):
                raw_html = raw.decode("utf-8", "ignore")
        pdf_url = citation_pdf_url(raw_html, base_url=attempt_url)
        if not pdf_url or pdf_url.rstrip("/") == attempt_url.rstrip("/"):
            # No advertised PDF: if we also have no text, say *why* explicitly.
            if not doc.has_text and not doc.failure_reason:
                doc.failure_code = doc.failure_code or "landing_page"
                doc.failure_reason = (
                    "publisher landing page with no extractable full text and no "
                    "advertised PDF (citation_pdf_url absent)"
                )
            return doc
        try:
            pdf_res = self._fetcher.get(pdf_url)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("citation_pdf fetch failed for %s: %s", pdf_url, exc)
            pdf_res = None
        if pdf_res is not None and getattr(pdf_res, "outcome", None) == OUTCOME_OK:
            pdf_ct = getattr(pdf_res, "content_type", "") or "application/pdf"
            better = self._read(pdf_res, source, pdf_ct, workspace)
            better.metadata.update(_source_metadata(source))
            if better.has_text:
                better.metadata["resolved_pdf_url"] = pdf_url
                return better
        # Landing page found a PDF link but we couldn't read it (paywall/JS/OCR).
        if not doc.has_text:
            doc.failure_code = doc.failure_code or "landing_page"
            doc.failure_reason = (
                f"downloaded publisher landing page; article PDF ({pdf_url}) "
                f"was not retrievable (paywall or unreadable)"
            )
        return doc

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
