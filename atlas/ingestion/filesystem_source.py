"""Filesystem ingestion source (ADR-0033).

Scans a documents directory, extracts text per file type, and feeds each file
into the knowledge base. Content dedup (by checksum, in DocumentRepository) makes
re-scans idempotent: unchanged files are skipped, changed files re-ingest.

By default embedding is deferred to the scheduler: the source ingests with
``embed=False`` (chunk only) and enqueues an ``embed_document`` task, so large
scans survive restarts (resilience). If no enqueue callable is provided, it embeds
inline instead — handy for tests and one-shot runs.

Registered as the ``ingest_scan`` scheduler task so periodic ingestion is durable.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

from atlas.ingestion.extractors import content_type_for, extract
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.knowledge.service import KnowledgeService

# (task_type, payload, *, delay_seconds=..., ...) -> task row; matches
# SchedulerService.enqueue, so it can be passed directly.
EnqueueFn = Callable[..., Any]

DEFAULT_EXTENSIONS = (".txt", ".md", ".pdf", ".html", ".htm")


class FilesystemSource:
    name = "ingestion"

    def __init__(
        self,
        knowledge: "KnowledgeService",
        *,
        documents_dir: Path | str,
        extensions: "list[str] | tuple[str, ...]" = DEFAULT_EXTENSIONS,
        enqueue: EnqueueFn | None = None,
        count_pending: "Callable[[str], int] | None" = None,
        scan_interval: int = 0,
        enabled: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        self._knowledge = knowledge
        self._dir = Path(documents_dir)
        self._extensions = {e.lower() for e in extensions}
        self._enqueue = enqueue
        self._count_pending = count_pending
        self._scan_interval = scan_interval
        self._enabled = enabled
        self._logger = logger or logging.getLogger("atlas.ingestion")

    def discover(self) -> list[Path]:
        """Return files under the documents dir matching configured extensions."""
        if not self._dir.exists():
            return []
        return sorted(
            p
            for p in self._dir.rglob("*")
            if p.is_file() and p.suffix.lower() in self._extensions
        )

    def scan(self) -> dict[str, Any]:
        """Ingest all matching files. Returns a summary of what happened."""
        scanned = ingested = enqueued = skipped = 0
        for path in self.discover():
            scanned += 1
            try:
                text = extract(path)
            except Exception:  # noqa: BLE001 - a bad file must not stop the scan
                self._logger.exception("extract failed for %s", path)
                skipped += 1
                continue
            if not text:
                self._logger.info("no extractable text, skipping %s", path)
                skipped += 1
                continue

            summary = self._knowledge.ingest_text(
                "filesystem",
                text,
                uri=str(path),
                title=path.name,
                content_type=content_type_for(path),
                embed=False,
            )
            # Unchanged file already fully embedded: nothing to do.
            if summary["deduped"] and summary["status"] == "embedded":
                skipped += 1
                continue

            ingested += 1
            if summary["status"] != "embedded":
                self._embed(summary["document_id"])
                enqueued += 1

        result = {
            "scanned": scanned,
            "ingested": ingested,
            "enqueued": enqueued,
            "skipped": skipped,
        }
        self._logger.info(
            "scan complete: %d scanned, %d ingested, %d embed enqueued, %d skipped",
            scanned,
            ingested,
            enqueued,
            skipped,
        )
        return result

    # --- Service lifecycle ---------------------------------------------
    def start(self) -> None:
        """Seed a durable scan chain on startup (idempotent across restarts).

        Only when enabled, periodic, and no scan is already queued — so repeated
        restarts don't spawn multiple recurring chains.
        """
        if not self._enabled or self._enqueue is None or self._scan_interval <= 0:
            return
        if self._count_pending is not None and self._count_pending("ingest_scan") > 0:
            self._logger.info("ingest_scan already queued; not seeding another")
            return
        self._enqueue("ingest_scan", {})
        self._logger.info("seeded initial ingest_scan (interval %ds)", self._scan_interval)

    def stop(self) -> None:
        pass

    def health_check(self) -> HealthStatus:
        exists = self._dir.exists()
        mode = "manual" if self._scan_interval <= 0 else f"every {self._scan_interval}s"
        detail = f"documents dir {'ok' if exists else 'missing'} ({self._dir}); {mode}"
        return HealthStatus(
            healthy=exists,
            detail=detail,
            data={"dir": str(self._dir), "scan_interval": self._scan_interval},
        )

    # --- scheduler integration -----------------------------------------
    def scan_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Scheduler handler for task_type 'ingest_scan'.

        Re-enqueues itself after ``scan_interval`` seconds so periodic ingestion is
        durable (survives restarts) without a dedicated cron. One chain is kept
        alive; startup only seeds a scan when none is already pending.
        """
        result = self.scan()
        if self._enqueue is not None and self._scan_interval > 0:
            self._enqueue(
                "ingest_scan", {}, delay_seconds=float(self._scan_interval)
            )
        return result

    # --- internals ------------------------------------------------------
    def _embed(self, document_id: str) -> None:
        if self._enqueue is not None:
            self._enqueue("embed_document", {"document_id": document_id})
        else:
            self._knowledge.embed_document(document_id)
