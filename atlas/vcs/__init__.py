"""Version-control integration (Stage 2, S20a).

A **read-only** Git capability over a local repository: status, log, diff, show,
branches, and per-file history. Read-only by design (no fetch/pull/push/commit) and
network-free, so it is a safe Tier-2 tool that complements Code Understanding (S14)
and Engineering Intelligence (S19). Every operation returns a structured outcome and
**never raises** into the caller (R2/R3).
"""

from __future__ import annotations

from atlas.vcs.git import (
    GIT_ERROR,
    GIT_NOT_A_REPO,
    GIT_OK,
    GIT_UNAVAILABLE,
    GitClient,
    SubprocessRunner,
)

__all__ = [
    "GitClient",
    "SubprocessRunner",
    "GIT_OK",
    "GIT_ERROR",
    "GIT_NOT_A_REPO",
    "GIT_UNAVAILABLE",
]
