"""Read-only Git client (S20a).

``GitClient`` shells out to ``git`` through an injectable ``CommandRunner`` and parses
the output into plain dicts. It is deliberately **read-only** — only inspection
subcommands are ever run (``status``/``log``/``diff``/``show``/``branch``/
``rev-parse``); there is no code path that fetches, pulls, pushes, commits, or mutates
a repository. The runner seam keeps the client fully hermetic in tests (feed canned
output) while the default ``SubprocessRunner`` runs the real binary with a timeout.

Outcomes are honest and never raise (R2/R3):
  ``ok`` | ``not_a_repo`` (path isn't a work tree) | ``unavailable`` (no git binary)
  | ``error`` (git returned non-zero / timed out).
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any, Protocol

GIT_OK = "ok"
GIT_NOT_A_REPO = "not_a_repo"
GIT_UNAVAILABLE = "unavailable"
GIT_ERROR = "error"

_RC_UNAVAILABLE = 127  # runner sentinel: git binary not found
_RC_TIMEOUT = 124      # runner sentinel: command timed out
_UNIT = "\x1f"         # field separator inside a formatted log line


class CommandRunner(Protocol):
    def run(self, args: list[str], *, cwd: str | None = None) -> tuple[int, str, str]:
        """Return (returncode, stdout, stderr). Must not raise."""
        ...


class SubprocessRunner:
    """Default runner: invoke the real ``git`` binary with a hard timeout."""

    def __init__(self, git_binary: str = "git", timeout: float = 15.0) -> None:
        self._git = git_binary
        self._timeout = timeout

    def run(self, args: list[str], *, cwd: str | None = None) -> tuple[int, str, str]:
        try:
            proc = subprocess.run(
                [self._git, *args],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
            return proc.returncode, proc.stdout, proc.stderr
        except FileNotFoundError:
            return _RC_UNAVAILABLE, "", "git binary not found"
        except subprocess.TimeoutExpired:
            return _RC_TIMEOUT, "", "git command timed out"
        except OSError as exc:  # pragma: no cover - defensive
            return 1, "", str(exc)


class GitClient:
    def __init__(
        self,
        runner: CommandRunner | None = None,
        *,
        max_log: int = 50,
        logger: logging.Logger | None = None,
    ) -> None:
        self._runner = runner or SubprocessRunner()
        self._max_log = max_log
        self._logger = logger or logging.getLogger("atlas.vcs.git")

    # --- public operations (all read-only) ------------------------------
    def status(self, repo: str) -> dict[str, Any]:
        rc, out, err = self._runner.run(
            ["-C", repo, "status", "--porcelain=v1", "--branch"], cwd=None
        )
        bad = self._non_ok(rc, err, repo)
        if bad:
            return bad
        return {"outcome": GIT_OK, "repo": repo, **_parse_status(out)}

    def log(self, repo: str, *, max_count: int | None = None) -> dict[str, Any]:
        n = min(max_count or self._max_log, 1000)
        fmt = _UNIT.join(["%H", "%h", "%an", "%ad", "%s"])
        rc, out, err = self._runner.run(
            ["-C", repo, "log", f"-n{n}", f"--pretty=format:{fmt}", "--date=short"]
        )
        bad = self._non_ok(rc, err, repo)
        if bad:
            return bad
        return {"outcome": GIT_OK, "repo": repo, "commits": _parse_log(out)}

    def diff(self, repo: str, *, ref: str | None = None) -> dict[str, Any]:
        args = ["-C", repo, "diff", "--stat"]
        if ref:
            args.append(ref)
        rc, out, err = self._runner.run(args)
        bad = self._non_ok(rc, err, repo)
        if bad:
            return bad
        return {
            "outcome": GIT_OK, "repo": repo, "ref": ref,
            "stat": out.strip(), "files_changed": _count_stat_files(out),
        }

    def show(self, repo: str, ref: str = "HEAD") -> dict[str, Any]:
        fmt = _UNIT.join(["%H", "%h", "%an", "%ad", "%s", "%b"])
        rc, out, err = self._runner.run(
            ["-C", repo, "show", "--stat", f"--pretty=format:{fmt}", "--date=short", ref]
        )
        bad = self._non_ok(rc, err, repo)
        if bad:
            return bad
        return {"outcome": GIT_OK, "repo": repo, **_parse_show(out)}

    def branches(self, repo: str) -> dict[str, Any]:
        rc, out, err = self._runner.run(
            ["-C", repo, "branch", "--format=%(refname:short)"]
        )
        bad = self._non_ok(rc, err, repo)
        if bad:
            return bad
        cur_rc, cur_out, _ = self._runner.run(
            ["-C", repo, "rev-parse", "--abbrev-ref", "HEAD"]
        )
        current = cur_out.strip() if cur_rc == 0 else None
        branches = [b.strip() for b in out.splitlines() if b.strip()]
        return {
            "outcome": GIT_OK, "repo": repo, "current": current, "branches": branches,
        }

    def file_history(
        self, repo: str, path: str, *, max_count: int | None = None
    ) -> dict[str, Any]:
        n = min(max_count or self._max_log, 1000)
        fmt = _UNIT.join(["%H", "%h", "%an", "%ad", "%s"])
        rc, out, err = self._runner.run(
            ["-C", repo, "log", f"-n{n}", f"--pretty=format:{fmt}", "--date=short",
             "--", path]
        )
        bad = self._non_ok(rc, err, repo)
        if bad:
            return bad
        return {
            "outcome": GIT_OK, "repo": repo, "path": path,
            "commits": _parse_log(out),
        }

    # --- internals ------------------------------------------------------
    def _non_ok(self, rc: int, err: str, repo: str) -> dict[str, Any] | None:
        if rc == 0:
            return None
        if rc == _RC_UNAVAILABLE:
            return {"outcome": GIT_UNAVAILABLE, "repo": repo,
                    "reason": "git is not installed or not on PATH"}
        low = (err or "").lower()
        if "not a git repository" in low or "does not exist" in low:
            return {"outcome": GIT_NOT_A_REPO, "repo": repo,
                    "reason": f"{repo} is not a git repository"}
        if rc == _RC_TIMEOUT:
            return {"outcome": GIT_ERROR, "repo": repo, "reason": "git command timed out"}
        return {"outcome": GIT_ERROR, "repo": repo,
                "reason": (err or "git error").strip().splitlines()[0] if err else "git error"}


# --- parsers (pure) ------------------------------------------------------
def _parse_status(out: str) -> dict[str, Any]:
    branch: str | None = None
    ahead = behind = 0
    changes: list[dict[str, str]] = []
    for line in out.splitlines():
        if line.startswith("## "):
            head = line[3:]
            # e.g. "main...origin/main [ahead 1, behind 2]" or "main" or "HEAD (no branch)"
            name = head.split("...", 1)[0].split(" ", 1)[0]
            branch = name
            if "ahead " in head:
                ahead = _int_after(head, "ahead ")
            if "behind " in head:
                behind = _int_after(head, "behind ")
        elif line.strip():
            code = line[:2]
            path = line[3:].strip()
            changes.append({"status": code.strip() or code, "path": path})
    return {
        "branch": branch,
        "ahead": ahead,
        "behind": behind,
        "changes": changes,
        "clean": not changes,
    }


def _int_after(text: str, marker: str) -> int:
    try:
        rest = text.split(marker, 1)[1]
        num = ""
        for ch in rest:
            if ch.isdigit():
                num += ch
            else:
                break
        return int(num) if num else 0
    except (IndexError, ValueError):
        return 0


def _parse_log(out: str) -> list[dict[str, Any]]:
    commits: list[dict[str, Any]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split(_UNIT)
        if len(parts) < 5:
            continue
        commits.append({
            "hash": parts[0],
            "short": parts[1],
            "author": parts[2],
            "date": parts[3],
            "subject": parts[4],
        })
    return commits


def _parse_show(out: str) -> dict[str, Any]:
    lines = out.splitlines()
    header = lines[0] if lines else ""
    parts = header.split(_UNIT)
    commit = {
        "hash": parts[0] if len(parts) > 0 else "",
        "short": parts[1] if len(parts) > 1 else "",
        "author": parts[2] if len(parts) > 2 else "",
        "date": parts[3] if len(parts) > 3 else "",
        "subject": parts[4] if len(parts) > 4 else "",
        "body": parts[5] if len(parts) > 5 else "",
    }
    stat = "\n".join(lines[1:]).strip()
    return {"commit": commit, "stat": stat}


def _count_stat_files(out: str) -> int:
    # The final summary line of --stat looks like "3 files changed, ...".
    for line in reversed(out.splitlines()):
        line = line.strip()
        if "file" in line and "changed" in line:
            return _leading_int(line)
    return 0


def _leading_int(text: str) -> int:
    num = ""
    for ch in text:
        if ch.isdigit():
            num += ch
        else:
            break
    return int(num) if num else 0
