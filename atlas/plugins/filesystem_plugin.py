"""Filesystem plugin (ADR-0041): sandboxed read/list over a configured root.

Exposes two tools (ADR-0050):
    fs.list(path=".")   -> entries under the sandbox root
    fs.read(path)       -> text contents of a file (size-capped)

All paths are resolved against and confined to ``plugins.filesystem.root`` (defaults
to ``paths.documents``); attempts to escape the sandbox raise ``PluginError``. This
is the read side an agent needs to reason over local files without handing it the
whole filesystem.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from atlas.exceptions import PluginError
from atlas.plugins.base import BasePlugin
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.config import AtlasConfig
    from atlas.kernel.application import Application


class FilesystemPlugin(BasePlugin):
    name = "filesystem"
    version = "0.1.0"

    def __init__(
        self,
        root: Path | str,
        *,
        max_bytes: int = 1_048_576,
        logger: logging.Logger | None = None,
    ) -> None:
        self._root = Path(root).resolve()
        self._max_bytes = max_bytes
        self._logger = logger or logging.getLogger("atlas.plugins.filesystem")

    def register(self, kernel: "Application") -> None:
        kernel.capabilities.register("filesystem", self, kind="plugin")
        kernel.tools.register(
            "fs.list",
            self.list_dir,
            description="List files/dirs under the filesystem sandbox root.",
            params={"path": "relative path under the root (default '.')"},
            plugin=self.name,
        )
        kernel.tools.register(
            "fs.read",
            self.read_file,
            description="Read a text file under the filesystem sandbox root.",
            params={"path": "relative path to a file under the root"},
            plugin=self.name,
        )

    # --- actions --------------------------------------------------------
    def list_dir(self, path: str = ".") -> list[dict[str, Any]]:
        target = self._resolve(path)
        if not target.is_dir():
            raise PluginError(f"not a directory: {path}", path=path)
        entries = []
        for child in sorted(target.iterdir()):
            entries.append(
                {
                    "path": child.relative_to(self._root).as_posix(),
                    "is_dir": child.is_dir(),
                    "size": child.stat().st_size if child.is_file() else None,
                }
            )
        return entries

    def read_file(self, path: str) -> str:
        target = self._resolve(path)
        if not target.is_file():
            raise PluginError(f"not a file: {path}", path=path)
        size = target.stat().st_size
        if size > self._max_bytes:
            raise PluginError(
                f"file too large ({size} > {self._max_bytes} bytes): {path}",
                path=path,
            )
        return target.read_text(encoding="utf-8", errors="replace")

    # --- lifecycle ------------------------------------------------------
    def health_check(self) -> HealthStatus:
        ok = self._root.is_dir()
        return HealthStatus(
            healthy=ok,
            detail=f"sandbox root {'ok' if ok else 'missing'}: {self._root}",
            data={"root": str(self._root)},
        )

    # --- internals ------------------------------------------------------
    def _resolve(self, path: str) -> Path:
        candidate = (self._root / path).resolve()
        if candidate != self._root and not candidate.is_relative_to(self._root):
            raise PluginError(f"path escapes sandbox root: {path}", path=path)
        return candidate


def build(config: "AtlasConfig") -> FilesystemPlugin:
    root = config.plugins.filesystem.root or config.paths.documents
    return FilesystemPlugin(root, max_bytes=config.plugins.filesystem.max_bytes)
