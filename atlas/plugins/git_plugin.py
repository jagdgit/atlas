"""Git plugin (S20a): read-only local version-control inspection.

Exposes tools (registered as the ``git`` capability):
    git.status(repo)                      -> branch, ahead/behind, changes, clean
    git.log(repo, max_count=?)            -> recent commits
    git.diff(repo, ref=?)                 -> --stat summary + files_changed
    git.show(repo, ref="HEAD")            -> one commit's metadata + stat
    git.branches(repo)                    -> branches + current
    git.file_history(repo, path, ...)     -> commits touching a path

Read-only by design (no fetch/pull/push/commit) and network-free. Every tool returns
a structured outcome (`ok`/`not_a_repo`/`unavailable`/`error`) and never raises (R2/R3).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.plugins.base import BasePlugin
from atlas.services.base import HealthStatus
from atlas.vcs.git import GitClient, SubprocessRunner

if TYPE_CHECKING:
    from atlas.config import AtlasConfig
    from atlas.kernel.application import Application


class GitPlugin(BasePlugin):
    name = "git"
    version = "0.1.0"

    def __init__(self, client: GitClient, *, logger: logging.Logger | None = None) -> None:
        self._client = client
        self._logger = logger or logging.getLogger("atlas.plugins.git")

    def register(self, kernel: "Application") -> None:
        from atlas.capabilities import CAP_GIT, GitCapability

        kernel.capabilities.register(
            CAP_GIT, self, contract=GitCapability, kind="plugin"
        )
        kernel.tools.register(
            "git.status", self.status,
            description="Read a local git repo's branch/ahead-behind/working changes.",
            params={"repo": "path to a git repository"}, plugin=self.name,
        )
        kernel.tools.register(
            "git.log", self.log,
            description="List recent commits in a local git repository.",
            params={"repo": "repository path", "max_count": "max commits (default 50)"},
            plugin=self.name,
        )
        kernel.tools.register(
            "git.diff", self.diff,
            description="Summarize working-tree (or ref) changes in a repo (--stat).",
            params={"repo": "repository path", "ref": "optional commit/range"},
            plugin=self.name,
        )
        kernel.tools.register(
            "git.show", self.show,
            description="Show one commit's metadata and file stat.",
            params={"repo": "repository path", "ref": "commit ref (default HEAD)"},
            plugin=self.name,
        )
        kernel.tools.register(
            "git.branches", self.branches,
            description="List branches (and the current one) in a repo.",
            params={"repo": "repository path"}, plugin=self.name,
        )
        kernel.tools.register(
            "git.file_history", self.file_history,
            description="List commits that touched a specific file.",
            params={"repo": "repository path", "path": "file path within the repo"},
            plugin=self.name,
        )

    # --- capability (delegates to the read-only client) -----------------
    def status(self, repo: str) -> dict[str, Any]:
        return self._client.status(repo)

    def log(self, repo: str, max_count: int | None = None) -> dict[str, Any]:
        return self._client.log(repo, max_count=max_count)

    def diff(self, repo: str, ref: str | None = None) -> dict[str, Any]:
        return self._client.diff(repo, ref=ref)

    def show(self, repo: str, ref: str = "HEAD") -> dict[str, Any]:
        return self._client.show(repo, ref)

    def branches(self, repo: str) -> dict[str, Any]:
        return self._client.branches(repo)

    def file_history(
        self, repo: str, path: str, max_count: int | None = None
    ) -> dict[str, Any]:
        return self._client.file_history(repo, path, max_count=max_count)

    def health_check(self) -> HealthStatus:
        return HealthStatus.ok("git (read-only) ready")


def build(config: "AtlasConfig") -> GitPlugin:
    git = config.plugins.git
    client = GitClient(
        SubprocessRunner(git_binary=git.git_binary, timeout=git.timeout),
        max_log=git.max_log,
    )
    return GitPlugin(client)
