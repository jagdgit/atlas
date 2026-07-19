"""Hermetic tests for asset-backed repo acquisition (Phase B · §B.1, BB1/BB12).

Real filesystem trees under ``tmp_path`` exercise the tree checksum + deterministic
packing; fakes stand in for the Asset Store / Storage / git so identity + versioning are
verified without a database, a network, or the ``git`` binary.
"""

from __future__ import annotations

import tarfile
import io

import pytest

from atlas.engineering.ingest import (
    ASSET_KIND_REPO,
    RepoAcquireError,
    RepoAcquirer,
    compute_tree_checksum,
)
from atlas.vcs.acquire import normalize_remote


# --- fakes ---------------------------------------------------------------
class FakeAssetStore:
    """Minimal Asset Store: versioned blobs keyed by (kind, name) with metadata."""

    def __init__(self):
        self._assets: dict[tuple[str, str], dict] = {}
        self._versions: dict[str, list[dict]] = {}
        self._seq = 0

    def get_by_name(self, kind, name):
        return self._assets.get((kind, name))

    def versions(self, asset_id):
        return list(reversed(self._versions.get(asset_id, [])))  # newest first

    def register(self, kind, name, data, *, source_uri=None, content_type=None, metadata=None):
        asset = self._assets.get((kind, name))
        if asset is None:
            self._seq += 1
            asset = {"id": f"asset-{self._seq}", "kind": kind, "name": name}
            self._assets[(kind, name)] = asset
            self._versions[asset["id"]] = []
        version = len(self._versions[asset["id"]]) + 1
        row = {"version": version, "metadata": dict(metadata or {}), "bytes": data}
        self._versions[asset["id"]].append(row)
        return {"asset": asset, "version": row}


class FakeStorage:
    def __init__(self, tmp_path):
        self._root = tmp_path

    def allocate_workspace(self, scope):
        ws = self._root / "workspaces" / scope
        ws.mkdir(parents=True, exist_ok=True)
        return ws


class FakeGit:
    def __init__(self, *, root_commit=None, remote=None, clone_tree=None):
        self._root_commit = root_commit
        self._remote = remote
        self._clone_tree = clone_tree or {}

    def root_commit(self, repo):
        return self._root_commit

    def remote_url(self, repo):
        return self._remote

    def clone_shallow(self, url, dest, *, branch=None):
        from pathlib import Path

        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        for rel, content in self._clone_tree.items():
            p = dest / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        return {"outcome": "ok", "dest": str(dest)}


def _make_repo(root, files):
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


# --- tree checksum -------------------------------------------------------
def test_tree_checksum_stable_and_content_sensitive(tmp_path):
    _make_repo(tmp_path, {"a.py": "print(1)\n", "pkg/b.py": "x = 2\n"})
    c1 = compute_tree_checksum(tmp_path)
    c2 = compute_tree_checksum(tmp_path)
    assert c1 == c2  # deterministic

    (tmp_path / "a.py").write_text("print(2)\n")
    assert compute_tree_checksum(tmp_path) != c1  # content change → new checksum


def test_tree_checksum_ignores_git_and_caches(tmp_path):
    _make_repo(tmp_path, {"a.py": "print(1)\n"})
    base = compute_tree_checksum(tmp_path)
    # Noise that must not affect the checksum (Q-B1 ignores).
    _make_repo(
        tmp_path,
        {
            ".git/HEAD": "ref: refs/heads/main\n",
            "__pycache__/a.cpython-312.pyc": "bytecode",
            "mod.pyc": "bytecode",
            "node_modules/dep/index.js": "module.exports = {}\n",
        },
    )
    assert compute_tree_checksum(tmp_path) == base


def test_tree_checksum_rejects_non_directory(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    with pytest.raises(RepoAcquireError):
        compute_tree_checksum(f)


# --- normalize_remote ----------------------------------------------------
@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/Foo/Bar.git", "github.com/foo/bar"),
        ("https://user:token@github.com/Foo/Bar", "github.com/foo/bar"),
        ("git@github.com:Foo/Bar.git", "github.com/foo/bar"),
        ("ssh://git@example.com/x/y.git", "example.com/x/y"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_remote(url, expected):
    assert normalize_remote(url) == expected


# --- acquire: local path -------------------------------------------------
def test_acquire_local_registers_asset_with_commit_identity(tmp_path):
    repo = tmp_path / "repo"
    _make_repo(repo, {"a.py": "print(1)\n"})
    assets = FakeAssetStore()
    acq = RepoAcquirer(assets, FakeStorage(tmp_path), git=FakeGit(root_commit="abc123"))

    out = acq.acquire(path=str(repo))
    assert out.reused is False
    assert out.root_commit == "abc123"
    assert out.asset_version == 1
    # repo_uid derived from the root commit (stable, uuid5).
    import uuid
    from atlas.engineering.ingest import _REPO_NS

    assert out.repo_uid == str(uuid.uuid5(_REPO_NS, "commit:abc123"))
    # The asset carries the tree checksum + identity in its metadata.
    asset = assets.get_by_name(ASSET_KIND_REPO, out.repo_uid)
    assert asset is not None
    meta = assets.versions(asset["id"])[0]["metadata"]
    assert meta["tree_checksum"] == out.tree_checksum
    assert meta["root_commit"] == "abc123"


def test_acquire_unchanged_tree_reuses_version(tmp_path):
    repo = tmp_path / "repo"
    _make_repo(repo, {"a.py": "print(1)\n"})
    assets = FakeAssetStore()
    acq = RepoAcquirer(assets, FakeStorage(tmp_path), git=FakeGit(root_commit="abc123"))

    first = acq.acquire(path=str(repo))
    second = acq.acquire(path=str(repo))
    assert first.asset_version == 1
    assert second.reused is True
    assert second.asset_version == 1  # no new version for an unchanged tree

    # A real change cuts a new version.
    (repo / "a.py").write_text("print(2)\n")
    third = acq.acquire(path=str(repo))
    assert third.reused is False
    assert third.asset_version == 2


def test_repo_uid_stable_across_clone_paths(tmp_path):
    """Same root commit at two different paths → same repo_uid (BB12)."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    _make_repo(a, {"a.py": "print(1)\n"})
    _make_repo(b, {"a.py": "print(9)\n"})  # different content, same identity
    assets = FakeAssetStore()
    git = FakeGit(root_commit="deadbeef")
    acq = RepoAcquirer(assets, FakeStorage(tmp_path), git=git)

    ua = acq.acquire(path=str(a)).repo_uid
    ub = acq.acquire(path=str(b)).repo_uid
    assert ua == ub


def test_acquire_uid_falls_back_to_remote_then_path(tmp_path):
    repo = tmp_path / "repo"
    _make_repo(repo, {"a.py": "x\n"})
    assets = FakeAssetStore()

    import uuid
    from atlas.engineering.ingest import _REPO_NS

    # No commit, but a remote → remote-derived uid.
    acq_remote = RepoAcquirer(
        assets, FakeStorage(tmp_path),
        git=FakeGit(root_commit=None, remote="https://github.com/x/y.git"),
    )
    out = acq_remote.acquire(path=str(repo))
    assert out.repo_uid == str(uuid.uuid5(_REPO_NS, "remote:github.com/x/y"))

    # Neither commit nor remote → path-derived uid (deterministic per location).
    assets2 = FakeAssetStore()
    acq_path = RepoAcquirer(assets2, FakeStorage(tmp_path), git=FakeGit())
    out2 = acq_path.acquire(path=str(repo))
    assert out2.repo_uid == str(uuid.uuid5(_REPO_NS, f"path:{repo.resolve()}"))


def test_acquire_requires_exactly_one_source(tmp_path):
    acq = RepoAcquirer(FakeAssetStore(), FakeStorage(tmp_path), git=FakeGit())
    with pytest.raises(RepoAcquireError):
        acq.acquire()
    with pytest.raises(RepoAcquireError):
        acq.acquire(path="/x", url="https://e/x.git")


def test_acquire_missing_local_path_raises(tmp_path):
    acq = RepoAcquirer(FakeAssetStore(), FakeStorage(tmp_path), git=FakeGit())
    with pytest.raises(RepoAcquireError):
        acq.acquire(path=str(tmp_path / "does-not-exist"))


# --- acquire: remote clone ----------------------------------------------
def test_acquire_remote_clones_and_cleans_up(tmp_path):
    assets = FakeAssetStore()
    git = FakeGit(root_commit="c0ffee", clone_tree={"main.py": "print('hi')\n"})
    acq = RepoAcquirer(assets, FakeStorage(tmp_path), git=git)

    out = acq.acquire(url="https://github.com/x/y.git")
    assert out.asset_version == 1
    assert out.normalized_remote == "github.com/x/y"
    from pathlib import Path

    assert Path(out.working_dir).exists()  # still present until cleanup()
    out.cleanup()
    assert not Path(out.working_dir).exists()  # workspace deleted (Q-B2)


def test_acquire_remote_clone_failure_raises(tmp_path):
    class FailingGit(FakeGit):
        def clone_shallow(self, url, dest, *, branch=None):
            return {"outcome": "error", "reason": "boom"}

    acq = RepoAcquirer(FakeAssetStore(), FakeStorage(tmp_path), git=FailingGit())
    with pytest.raises(RepoAcquireError):
        acq.acquire(url="https://github.com/x/y.git")


# --- deterministic packing ----------------------------------------------
def test_packed_asset_is_a_readable_deterministic_tar(tmp_path):
    repo = tmp_path / "repo"
    _make_repo(repo, {"a.py": "print(1)\n", "pkg/b.py": "x = 2\n"})
    assets = FakeAssetStore()
    acq = RepoAcquirer(assets, FakeStorage(tmp_path), git=FakeGit(root_commit="abc"))
    out = acq.acquire(path=str(repo))

    blob = assets.versions(out.asset_id)[0]["bytes"]
    assert isinstance(blob, bytes)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        names = sorted(tar.getnames())
    assert names == ["a.py", "pkg/b.py"]
