"""Log-reading plugin — Atlas reading its own logs (J0b).

Why this exists: the filesystem sandbox is pinned to ``paths.documents``, so no
capability could reach ``paths.logs``. Asked "why did you fail today, read your logs",
Atlas was structurally unable to look. ``sql`` (J0a) covers persisted state; this covers
everything that only ever reached a log line.

Read-only by construction: confined to ``paths.logs``, no write/delete surface, bounded
output, and **secret redaction on every line that leaves this module**. Logs are the one
place a credential can appear by accident, and their whole purpose is to be quoted into
reports and LLM prompts, so redaction is not optional here.

Tools (registered as the ``logs`` capability):
    logs.list()                                  -> log files with size and mtime
    logs.tail(file=?, lines=?)                   -> last N lines
    logs.search(pattern, file=?, max_matches=?)  -> matching lines with line numbers
"""

from __future__ import annotations

import logging
import re
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

from atlas.exceptions import PluginError
from atlas.plugins.base import BasePlugin
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.config import AtlasConfig
    from atlas.kernel.application import Application

LOGS_OK = "ok"
LOGS_EMPTY = "empty"
LOGS_BLOCKED = "blocked"
LOGS_UNAVAILABLE = "unavailable"
LOGS_ERROR = "error"

_MAX_LINES = 2000
_MAX_MATCHES = 500
_MAX_LINE_CHARS = 2000

# Redaction applied to every emitted line. Order matters: the auth-scheme rule must run
# before the key/value rule, otherwise `Authorization: Bearer <token>` has "Bearer"
# treated as the value and the real token survives.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Authorization headers / bearer tokens
    (re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9\-._~+/=]{8,}"), r"\1 [redacted]"),
    # URL query parameters carrying secrets
    (
        re.compile(
            r"(?i)([?&](?:access_token|api_key|apikey|token|key|signature|sig)=)[^&\s]+"
        ),
        r"\1[redacted]",
    ),
    # key=value / key: value for secret-ish keys (quoted or bare). The lookahead keeps
    # an already-redacted value from being redacted twice, which left stray brackets.
    (
        re.compile(
            r"(?i)\b(access[_-]?token|refresh[_-]?token|request[_-]?token|api[_-]?key|"
            r"apikey|secret|password|passwd|credential|private[_-]?key|authorization|"
            r"session[_-]?id|token)\b(\s*[:=]\s*)(?!\[redacted\])"
            r"(\"[^\"]*\"|'[^']*'|[^\s,;)\]}&]+)"
        ),
        r"\1\2[redacted]",
    ),
)


def redact(line: str) -> str:
    """Remove anything that looks like a credential from a log line.

    Deliberately conservative in the other direction: ``token_len``/``token_count``
    style size fields are not secrets and survive, because they are useful in
    diagnosis.
    """
    text = str(line or "")
    if len(text) > _MAX_LINE_CHARS:
        text = text[:_MAX_LINE_CHARS] + " …[truncated]"
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class LogsPlugin(BasePlugin):
    name = "logs"
    version = "0.1.0"

    def __init__(
        self,
        root: Path | str,
        *,
        default_file: str = "atlas.log",
        logger: logging.Logger | None = None,
    ) -> None:
        self._root = Path(root).resolve()
        self._default_file = default_file
        self._logger = logger or logging.getLogger("atlas.plugins.logs")

    def register(self, kernel: "Application") -> None:
        from atlas.capabilities import CAP_LOGS, LogsCapability

        kernel.capabilities.register(
            CAP_LOGS, self, contract=LogsCapability, kind="plugin"
        )
        kernel.tools.register(
            "logs.list",
            self.list_files,
            description="List Atlas's own log files with size and modification time.",
            params={},
            plugin=self.name,
        )
        kernel.tools.register(
            "logs.tail",
            self.tail,
            description="Read the last N lines of one of Atlas's own log files.",
            params={
                "file": "log file name under the log directory (default atlas.log)",
                "lines": "how many trailing lines to return (default 200)",
            },
            plugin=self.name,
        )
        kernel.tools.register(
            "logs.search",
            self.search,
            description="Search Atlas's own logs for a regular expression and return "
            "matching lines with line numbers.",
            params={
                "pattern": "regular expression to search for",
                "file": "log file name (default atlas.log); 'all' searches every log",
                "max_matches": "cap on matches returned (default 100)",
            },
            plugin=self.name,
        )

    # --- internals ------------------------------------------------------
    def _resolve(self, file: str | None) -> Path:
        name = (file or self._default_file).strip() or self._default_file
        candidate = (self._root / name).resolve()
        if candidate != self._root and not candidate.is_relative_to(self._root):
            raise PluginError(f"path escapes the log directory: {file}", path=str(file))
        return candidate

    def _log_files(self) -> list[Path]:
        if not self._root.is_dir():
            return []
        return sorted(
            (p for p in self._root.iterdir() if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    # --- capability -----------------------------------------------------
    def list_files(self) -> dict[str, Any]:
        base = {"root": str(self._root)}
        if not self._root.is_dir():
            return {**base, "outcome": LOGS_UNAVAILABLE, "reason": "log directory missing"}
        files = [
            {
                "file": p.name,
                "bytes": p.stat().st_size,
                "modified": __import__("datetime")
                .datetime.fromtimestamp(p.stat().st_mtime)
                .isoformat(timespec="seconds"),
            }
            for p in self._log_files()
        ]
        return {
            **base,
            "outcome": LOGS_OK if files else LOGS_EMPTY,
            "files": files,
            "count": len(files),
        }

    def tail(self, file: str | None = None, lines: int = 200) -> dict[str, Any]:
        base = {"file": file or self._default_file}
        try:
            path = self._resolve(file)
        except PluginError as exc:
            return {**base, "outcome": LOGS_BLOCKED, "reason": str(exc)}
        if not path.is_file():
            return {**base, "outcome": LOGS_UNAVAILABLE, "reason": f"no such log file: {path.name}"}
        n = max(1, min(int(lines or 200), _MAX_LINES))
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                tail = deque(fh, maxlen=n)
        except OSError as exc:
            return {**base, "outcome": LOGS_ERROR, "reason": str(exc)}
        out = [redact(line.rstrip("\n")) for line in tail]
        return {
            **base,
            "outcome": LOGS_OK if out else LOGS_EMPTY,
            "lines": out,
            "line_count": len(out),
        }

    def search(
        self,
        pattern: str,
        file: str | None = None,
        max_matches: int = 100,
    ) -> dict[str, Any]:
        base = {"pattern": pattern, "file": file or self._default_file}
        if not str(pattern or "").strip():
            return {**base, "outcome": LOGS_BLOCKED, "reason": "empty pattern"}
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return {**base, "outcome": LOGS_BLOCKED, "reason": f"invalid regex: {exc}"}
        cap = max(1, min(int(max_matches or 100), _MAX_MATCHES))

        if str(file or "").strip().lower() == "all":
            targets = self._log_files()
        else:
            try:
                path = self._resolve(file)
            except PluginError as exc:
                return {**base, "outcome": LOGS_BLOCKED, "reason": str(exc)}
            if not path.is_file():
                return {
                    **base,
                    "outcome": LOGS_UNAVAILABLE,
                    "reason": f"no such log file: {path.name}",
                }
            targets = [path]

        matches: list[dict[str, Any]] = []
        truncated = False
        for target in targets:
            if truncated:
                break
            try:
                with target.open("r", encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, start=1):
                        if not regex.search(line):
                            continue
                        if len(matches) >= cap:
                            truncated = True
                            break
                        matches.append(
                            {
                                "file": target.name,
                                "line": lineno,
                                "text": redact(line.rstrip("\n")),
                            }
                        )
            except OSError as exc:
                self._logger.debug("log search failed on %s: %s", target.name, exc)
                continue
        return {
            **base,
            "outcome": LOGS_OK if matches else LOGS_EMPTY,
            "matches": matches,
            "match_count": len(matches),
            "truncated": truncated,
            "files_searched": [t.name for t in targets],
        }

    def health_check(self) -> HealthStatus:
        if not self._root.is_dir():
            return HealthStatus.degraded(f"log directory missing: {self._root}")
        return HealthStatus.ok(f"logs (read-only) ready: {self._root}")


def build(config: "AtlasConfig") -> LogsPlugin:
    return LogsPlugin(config.paths.logs)
