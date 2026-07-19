"""Git acquisition (Phase B · §B.1, BB1).

``GitAcquirer`` is the **write-capable** companion to the read-only :class:`GitClient`.
It exists so that ``GitClient`` can stay strictly read-only (status/log/diff/…): the one
thing Phase B needs that mutates the local filesystem is a **shallow, read-only clone**
of a remote (``git clone --depth 1``) — it never fetches/pulls/pushes/commits into an
existing repo. It also exposes two tiny read-only helpers used for **repository identity**
(BB12): the **root-commit** hash and the (normalized) origin **remote URL**.

Like ``GitClient`` it shells out through the injectable :class:`CommandRunner` seam, so it
is fully hermetic in tests (feed canned output) and honest on failure (never raises).
"""

from __future__ import annotations

import logging
from pathlib import Path

from atlas.vcs.git import (
    GIT_ERROR,
    GIT_OK,
    GIT_UNAVAILABLE,
    _RC_UNAVAILABLE,
    CommandRunner,
    SubprocessRunner,
)


def normalize_remote(url: str | None) -> str | None:
    """Normalize a remote URL for identity: strip creds, scheme noise, and a ``.git`` tail.

    ``https://user:tok@github.com/Foo/Bar.git`` and ``git@github.com:Foo/Bar`` both
    normalize to ``github.com/foo/bar`` so the same repo maps to one identity (BB12).
    """
    if not url:
        return None
    u = url.strip()
    if not u:
        return None
    # scp-like syntax: git@host:owner/repo → host/owner/repo
    if "://" not in u and "@" in u and ":" in u:
        u = u.split("@", 1)[1].replace(":", "/", 1)
    else:
        for scheme in ("https://", "http://", "ssh://", "git://"):
            if u.startswith(scheme):
                u = u[len(scheme):]
                break
        if "@" in u:  # strip user[:token]@
            u = u.split("@", 1)[1]
    if u.endswith(".git"):
        u = u[:-4]
    return u.strip("/").lower() or None


class GitAcquirer:
    """Shallow read-only clone + identity helpers (BB1/BB12)."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        *,
        clone_timeout: float = 300.0,
        logger: logging.Logger | None = None,
    ) -> None:
        # Clones can take a while; give them their own (longer) timeout runner.
        self._runner = runner or SubprocessRunner(timeout=clone_timeout)
        self._logger = logger or logging.getLogger("atlas.vcs.acquire")

    def clone_shallow(
        self, url: str, dest: str | Path, *, branch: str | None = None
    ) -> dict[str, str]:
        """``git clone --depth 1`` ``url`` into ``dest`` (read-only, no history, no tags)."""
        dest = str(dest)
        args = ["clone", "--depth", "1", "--no-tags", "--single-branch"]
        if branch:
            args += ["--branch", branch]
        args += [url, dest]
        rc, _out, err = self._runner.run(args)
        if rc == 0:
            return {"outcome": GIT_OK, "dest": dest}
        if rc == _RC_UNAVAILABLE:
            return {"outcome": GIT_UNAVAILABLE, "reason": "git is not installed or not on PATH"}
        reason = (err or "git clone failed").strip().splitlines()[-1] if err else "git clone failed"
        return {"outcome": GIT_ERROR, "reason": reason}

    def root_commit(self, repo: str | Path) -> str | None:
        """The repository's first (root) commit hash — a clone/move-stable identity anchor."""
        rc, out, _err = self._runner.run(
            ["-C", str(repo), "rev-list", "--max-parents=0", "HEAD"]
        )
        if rc != 0:
            return None
        # A repo may have multiple roots (merged histories); the oldest listed is stable.
        roots = [line.strip() for line in out.splitlines() if line.strip()]
        return roots[-1] if roots else None

    def remote_url(self, repo: str | Path) -> str | None:
        """The ``origin`` remote URL of a local checkout, if any (read-only)."""
        rc, out, _err = self._runner.run(
            ["-C", str(repo), "config", "--get", "remote.origin.url"]
        )
        if rc != 0:
            return None
        return out.strip() or None
