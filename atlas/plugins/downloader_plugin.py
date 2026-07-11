"""Downloader plugin (S13b): fetch a URL to a file on disk (via the net layer).

Exposes one tool:
    web.download(url, filename=None)
        -> {"url", "path", "bytes", "content_type", "outcome", "from_cache"}

Bytes are fetched through the resilient net layer (throttle/robots/backoff/cache),
capped at ``net.max_bytes``, and written under a controlled downloads directory
(``plugins.downloader.dir`` or ``paths.data/downloads``). A hard block/unavailable
source raises ``PluginError`` with the honest outcome (R2). Filenames are sanitised
and confined to the downloads dir (no path escape).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

from atlas.exceptions import PluginError
from atlas.net import OUTCOME_BLOCKED, OUTCOME_OK, FetchClient
from atlas.plugins.base import BasePlugin
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.config import AtlasConfig
    from atlas.kernel.application import Application

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class DownloaderPlugin(BasePlugin):
    name = "downloader"
    version = "0.1.0"

    def __init__(
        self,
        client: FetchClient,
        download_dir: Path | str,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._client = client
        self._dir = Path(download_dir)
        self._logger = logger or logging.getLogger("atlas.plugins.downloader")

    def register(self, kernel: "Application") -> None:
        kernel.capabilities.register("downloader", self, kind="plugin")
        kernel.tools.register(
            "web.download",
            self.download,
            description="Download an http(s) URL to a file in the downloads dir.",
            params={
                "url": "absolute http(s) URL to download",
                "filename": "optional output filename (sanitised)",
            },
            plugin=self.name,
        )

    # --- actions --------------------------------------------------------
    def download(self, url: str, filename: str | None = None) -> dict[str, Any]:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise PluginError(f"only http(s) URLs are allowed: {url}", url=url)

        result = self._client.get(url)
        if result.outcome != OUTCOME_OK:
            hint = "needs login" if result.outcome == OUTCOME_BLOCKED else "unavailable"
            raise PluginError(
                f"download {result.outcome} ({hint}) for {url}: {result.reason}",
                url=url,
            )

        name = self._safe_name(filename or self._name_from_url(parsed))
        self._dir.mkdir(parents=True, exist_ok=True)
        target = (self._dir / name).resolve()
        if not target.is_relative_to(self._dir.resolve()):
            raise PluginError(f"filename escapes downloads dir: {name}", url=url)
        target.write_bytes(result.content)
        self._logger.info("downloaded %s -> %s (%d bytes)", url, target, len(result.content))
        return {
            "url": result.final_url or url,
            "path": str(target),
            "bytes": len(result.content),
            "content_type": result.content_type,
            "outcome": result.outcome,
            "from_cache": result.from_cache,
        }

    def health_check(self) -> HealthStatus:
        return HealthStatus.ok(f"downloader ready (dir {self._dir})",
                               dir=str(self._dir))

    # --- internals ------------------------------------------------------
    @staticmethod
    def _name_from_url(parsed: Any) -> str:
        base = Path(unquote(parsed.path)).name
        return base or (parsed.netloc.replace(":", "_") + ".download")

    @staticmethod
    def _safe_name(name: str) -> str:
        cleaned = _SAFE_NAME_RE.sub("_", name).strip("._") or "download"
        return cleaned[:200]


def build(config: "AtlasConfig") -> DownloaderPlugin:
    net = config.net
    download_dir = config.plugins.downloader.dir or (Path(config.paths.data) / "downloads")
    client = FetchClient(
        user_agent=net.user_agent,
        timeout=net.timeout,
        max_bytes=net.max_bytes,
        per_domain_delay=net.per_domain_delay,
        max_retries=net.max_retries,
        backoff_base=net.backoff_base,
        backoff_cap=net.backoff_cap,
        jitter=net.jitter,
        respect_robots=net.respect_robots,
        cache_ttl=net.cache_ttl,
    )
    return DownloaderPlugin(client, download_dir)
