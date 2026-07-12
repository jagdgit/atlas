"""Tests for the read-only Git capability (S20a).

Hermetic by construction: ``GitClient`` takes an injectable ``CommandRunner`` so we
feed canned ``git`` output and assert parsing, plus honest outcomes for the
missing-binary / not-a-repo / error paths. A final integration test drives the real
``git`` binary against a temp repo (skipped when git is unavailable).
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from atlas.plugins.git_plugin import GitPlugin
from atlas.vcs.git import (
    GIT_ERROR,
    GIT_NOT_A_REPO,
    GIT_OK,
    GIT_UNAVAILABLE,
    GitClient,
)

_UNIT = "\x1f"


class FakeRunner:
    """Canned ``git`` output keyed on the subcommand (args[2] after ``-C repo``)."""

    def __init__(self, table: dict[str, tuple[int, str, str]]) -> None:
        self.table = table
        self.calls: list[list[str]] = []

    def run(self, args, *, cwd=None):
        self.calls.append(args)
        sub = args[2] if len(args) > 2 else args[0]
        return self.table.get(sub, (0, "", ""))


def _log_line(*fields: str) -> str:
    return _UNIT.join(fields)


# --- status --------------------------------------------------------------
def test_status_parses_branch_tracking_and_changes():
    out = "## main...origin/main [ahead 2, behind 1]\n M atlas/a.py\n?? new.txt\n"
    client = GitClient(FakeRunner({"status": (0, out, "")}))
    res = client.status("/repo")
    assert res["outcome"] == GIT_OK
    assert res["branch"] == "main"
    assert res["ahead"] == 2 and res["behind"] == 1
    assert res["clean"] is False
    assert {c["path"] for c in res["changes"]} == {"atlas/a.py", "new.txt"}


def test_status_clean_tree():
    client = GitClient(FakeRunner({"status": (0, "## main\n", "")}))
    res = client.status("/repo")
    assert res["clean"] is True
    assert res["changes"] == []
    assert res["ahead"] == 0 and res["behind"] == 0


# --- log / file history --------------------------------------------------
def test_log_parses_commits():
    out = "\n".join([
        _log_line("h1full", "h1", "Ada", "2026-07-01", "first"),
        _log_line("h2full", "h2", "Bob", "2026-07-02", "second"),
    ])
    client = GitClient(FakeRunner({"log": (0, out, "")}))
    res = client.log("/repo", max_count=10)
    assert res["outcome"] == GIT_OK
    assert [c["short"] for c in res["commits"]] == ["h1", "h2"]
    assert res["commits"][0]["author"] == "Ada"
    assert res["commits"][1]["subject"] == "second"


def test_file_history_delegates_to_log_format():
    out = _log_line("hfull", "h", "Ada", "2026-07-01", "touch file")
    runner = FakeRunner({"log": (0, out, "")})
    res = GitClient(runner).file_history("/repo", "atlas/a.py")
    assert res["path"] == "atlas/a.py"
    assert res["commits"][0]["subject"] == "touch file"
    # the path must be passed after a `--` separator (read-only pathspec)
    assert "--" in runner.calls[0] and "atlas/a.py" in runner.calls[0]


# --- diff ----------------------------------------------------------------
def test_diff_counts_files_changed():
    stat = " atlas/a.py | 2 +-\n atlas/b.py | 5 +++++\n 2 files changed, 6 insertions(+)\n"
    client = GitClient(FakeRunner({"diff": (0, stat, "")}))
    res = client.diff("/repo")
    assert res["outcome"] == GIT_OK
    assert res["files_changed"] == 2


# --- branches ------------------------------------------------------------
def test_branches_lists_and_marks_current():
    runner = FakeRunner({
        "branch": (0, "main\ndev\nfeature\n", ""),
        "rev-parse": (0, "dev\n", ""),
    })
    res = GitClient(runner).branches("/repo")
    assert res["current"] == "dev"
    assert res["branches"] == ["main", "dev", "feature"]


# --- honest outcomes (R2/R3) --------------------------------------------
def test_unavailable_when_binary_missing():
    client = GitClient(FakeRunner({"status": (127, "", "git binary not found")}))
    assert client.status("/repo")["outcome"] == GIT_UNAVAILABLE


def test_not_a_repo():
    err = "fatal: not a git repository (or any of the parent directories): .git"
    client = GitClient(FakeRunner({"status": (128, "", err)}))
    res = client.status("/nope")
    assert res["outcome"] == GIT_NOT_A_REPO


def test_generic_error_is_reported_not_raised():
    client = GitClient(FakeRunner({"log": (1, "", "fatal: bad revision 'zzz'")}))
    res = client.log("/repo")
    assert res["outcome"] == GIT_ERROR
    assert "bad revision" in res["reason"]


# --- plugin wiring -------------------------------------------------------
def test_plugin_delegates_to_client():
    plugin = GitPlugin(GitClient(FakeRunner({"status": (0, "## main\n", "")})))
    res = plugin.status("/repo")
    assert res["outcome"] == GIT_OK
    assert plugin.health_check().healthy is True


class _Kernel:
    def __init__(self) -> None:
        registered_caps: dict = {}
        registered_tools: dict = {}
        self.caps = registered_caps
        self.tool_map = registered_tools

        class _Caps:
            def register(self, name, provider, *, contract=None, kind=None):
                registered_caps[name] = provider

        class _Tools:
            def register(self, name, fn, *, description="", params=None, plugin=None):
                registered_tools[name] = fn

        self.capabilities = _Caps()
        self.tools = _Tools()


def test_plugin_registers_capability_and_tools():
    plugin = GitPlugin(GitClient(FakeRunner({})))
    kernel = _Kernel()
    plugin.register(kernel)
    assert "git" in kernel.caps
    for name in ("git.status", "git.log", "git.diff", "git.show",
                 "git.branches", "git.file_history"):
        assert name in kernel.tool_map


# --- integration against a real repo ------------------------------------
@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_real_repo_status_log_and_branches(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True, text=True)

    git("init", "-q")
    git("config", "user.email", "t@t.dev")
    git("config", "user.name", "Tester")
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    git("add", "a.txt")
    git("commit", "-qm", "initial commit")

    client = GitClient()
    status = client.status(str(repo))
    assert status["outcome"] == GIT_OK
    assert status["clean"] is True

    log = client.log(str(repo))
    assert log["commits"][0]["subject"] == "initial commit"

    branches = client.branches(str(repo))
    assert branches["current"] in branches["branches"]

    # a dirty working tree is reported
    (repo / "a.txt").write_text("changed\n", encoding="utf-8")
    assert client.status(str(repo))["clean"] is False

    # not-a-repo outcome for a plain directory
    plain = tmp_path / "plain"
    plain.mkdir()
    assert client.status(str(plain))["outcome"] == GIT_NOT_A_REPO
