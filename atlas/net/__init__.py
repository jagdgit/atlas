"""Resilient & polite web fetching (Stage 2, S13, D10 / §5c).

One shared HTTP layer that every network capability (web fetch, search,
downloader, scholarly) uses so jobs **degrade, never crash**: per-domain rate
limiting + `robots.txt` awareness, bounded backoff/retry with jitter, response
caching, and structured outcomes (`ok`/`blocked`/`skipped`/`error`) that map onto
R2 (report the gap) and R3 (block/skip the source, keep the job going).
"""

from __future__ import annotations

from atlas.net.client import (
    OUTCOME_BLOCKED,
    OUTCOME_ERROR,
    OUTCOME_OK,
    OUTCOME_SKIPPED,
    FetchClient,
    FetchResult,
)
from atlas.net.download import DownloadError, DownloadResult, resumable_download

__all__ = [
    "FetchClient",
    "FetchResult",
    "OUTCOME_OK",
    "OUTCOME_BLOCKED",
    "OUTCOME_SKIPPED",
    "OUTCOME_ERROR",
    "resumable_download",
    "DownloadResult",
    "DownloadError",
]
