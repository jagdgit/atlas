"""Storage Manager tests (Phase 0 · ATLAS_OS_ROADMAP §5.8, P8).

Hermetic: the DB-backed ``StorageRepository`` is replaced with an in-memory fake so
the manager's file/checksum/workspace/quota/integrity logic is exercised without a
live Postgres. The SQL itself is covered by the migration + repository shape.
"""

from __future__ import annotations

from typing import Any

import pytest

from atlas.storage import StorageError, StorageManager


class FakeStorageRepo:
    """In-memory stand-in for StorageRepository (duck-typed)."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.quotas: dict[str, dict[str, Any]] = {}
        self._id = 0

    def next_version(self, scope: str, name: str) -> int:
        versions = [r["version"] for r in self.rows if r["scope"] == scope and r["name"] == name]
        return (max(versions) + 1) if versions else 1

    def insert_file(self, **kw: Any) -> dict[str, Any]:
        self._id += 1
        row = {"id": self._id, **kw}
        self.rows.append(row)
        return row

    def get_file(self, scope: str, name: str, version: int | None = None) -> dict[str, Any] | None:
        matches = [r for r in self.rows if r["scope"] == scope and r["name"] == name]
        if version is not None:
            matches = [r for r in matches if r["version"] == version]
        if not matches:
            return None
        return max(matches, key=lambda r: r["version"])

    def list_files(self, scope: str) -> list[dict[str, Any]]:
        return [r for r in self.rows if r["scope"] == scope]

    def all_files(self) -> list[dict[str, Any]]:
        return list(self.rows)

    def scope_size(self, scope: str) -> int:
        return sum(r["size_bytes"] for r in self.rows if r["scope"] == scope)

    def get_quota(self, scope: str) -> dict[str, Any] | None:
        return self.quotas.get(scope)

    def set_quota(self, scope: str, limit_bytes: int, *, enforce: bool = False) -> dict[str, Any]:
        row = {"scope": scope, "limit_bytes": limit_bytes, "enforce": enforce}
        self.quotas[scope] = row
        return row


@pytest.fixture()
def manager(tmp_path):
    return StorageManager(tmp_path / "storage", FakeStorageRepo())


def test_put_and_get_roundtrip(manager):
    rec = manager.put_file("docs", "note.txt", b"hello world")
    assert rec["version"] == 1
    assert rec["size_bytes"] == 11
    assert rec["tier"] == "hot"
    assert manager.get_bytes("docs", "note.txt") == b"hello world"


def test_checksum_is_sha256_of_content(manager):
    import hashlib

    rec = manager.put_file("docs", "a.bin", b"\x00\x01\x02")
    assert rec["checksum"] == hashlib.sha256(b"\x00\x01\x02").hexdigest()


def test_versions_increment_and_are_independently_readable(manager):
    manager.put_file("docs", "note.txt", b"v1")
    rec2 = manager.put_file("docs", "note.txt", b"v2")
    assert rec2["version"] == 2
    assert manager.get_bytes("docs", "note.txt") == b"v2"  # latest
    assert manager.get_bytes("docs", "note.txt", version=1) == b"v1"


def test_get_missing_file_raises(manager):
    with pytest.raises(StorageError):
        manager.get_bytes("docs", "nope.txt")


def test_put_from_path_source(manager, tmp_path):
    src = tmp_path / "src.txt"
    src.write_bytes(b"from disk")
    rec = manager.put_file("imports", "src.txt", src)
    assert rec["size_bytes"] == len(b"from disk")
    assert manager.get_bytes("imports", "src.txt") == b"from disk"


def test_put_from_missing_path_raises(manager, tmp_path):
    with pytest.raises(StorageError):
        manager.put_file("imports", "x", tmp_path / "does-not-exist")


def test_corruption_is_detected_on_read(manager):
    manager.put_file("docs", "note.txt", b"trusted")
    path = manager.path_of("docs", "note.txt")
    path.write_bytes(b"tampered!")
    assert manager.verify("docs", "note.txt") is False
    with pytest.raises(StorageError):
        manager.get_bytes("docs", "note.txt")


def test_verify_true_for_intact_file(manager):
    manager.put_file("docs", "ok.txt", b"intact")
    assert manager.verify("docs", "ok.txt") is True


def test_verify_false_when_file_deleted(manager):
    manager.put_file("docs", "gone.txt", b"data")
    manager.path_of("docs", "gone.txt").unlink()
    assert manager.verify("docs", "gone.txt") is False


def test_integrity_check_reports_ok_missing_and_corrupt(manager):
    manager.put_file("docs", "good.txt", b"good")
    manager.put_file("docs", "bad.txt", b"bad")
    manager.put_file("docs", "lost.txt", b"lost")
    manager.path_of("docs", "bad.txt").write_bytes(b"corrupted")
    manager.path_of("docs", "lost.txt").unlink()

    report = manager.integrity_check()
    assert report["checked"] == 3
    assert report["ok"] == 1
    assert report["corrupt"] == ["docs/bad.txt v1"]
    assert report["missing"] == ["docs/lost.txt v1"]


def test_list_files_scoped(manager):
    manager.put_file("a", "one", b"1")
    manager.put_file("a", "two", b"2")
    manager.put_file("b", "three", b"3")
    assert len(manager.list_files("a")) == 2
    assert len(manager.list_files("b")) == 1


def test_allocate_workspace_creates_scoped_dir(manager):
    ws = manager.allocate_workspace("job-123")
    assert ws.exists() and ws.is_dir()
    assert ws.name == "job-123"


def test_unsafe_names_do_not_escape_root(manager, tmp_path):
    root = tmp_path / "storage"
    manager.put_file("../../etc", "../../passwd", b"safe")
    # Nothing was written outside the storage root.
    written = list(root.rglob("*"))
    assert all(str(p).startswith(str(root)) for p in written)
    assert manager.get_bytes("../../etc", "../../passwd") == b"safe"


def test_quota_status_default_no_limit(manager):
    manager.put_file("docs", "a", b"12345")
    status = manager.quota_status("docs")
    assert status["used_bytes"] == 5
    assert status["limit_bytes"] == 0
    assert status["over"] is False


def test_quota_status_over_limit_is_advisory(manager, caplog):
    manager.set_quota("docs", limit_bytes=4)
    with caplog.at_level("WARNING"):
        rec = manager.put_file("docs", "big", b"12345")  # 5 > 4
    # Advisory: the write still succeeded.
    assert rec["size_bytes"] == 5
    status = manager.quota_status("docs")
    assert status["over"] is True
    assert any("quota exceeded" in m for m in caplog.messages)


def test_default_quota_applies_without_row(tmp_path):
    mgr = StorageManager(tmp_path / "s", FakeStorageRepo(), default_quota_bytes=3)
    mgr.put_file("docs", "a", b"12345")
    status = mgr.quota_status("docs")
    assert status["limit_bytes"] == 3
    assert status["over"] is True


def test_run_backup_without_manager_raises(manager):
    with pytest.raises(StorageError):
        manager.run_backup()


def test_run_backup_delegates_to_backup_manager(tmp_path):
    class FakeBackup:
        def __init__(self):
            self.calls = 0

        def backup(self):
            self.calls += 1
            return tmp_path / "atlas.dump"

    backup = FakeBackup()
    mgr = StorageManager(tmp_path / "s", FakeStorageRepo(), backup=backup)
    out = mgr.run_backup()
    assert backup.calls == 1
    assert out == tmp_path / "atlas.dump"


def test_health_ok_after_start(manager):
    manager.start()
    health = manager.health_check()
    assert health.healthy is True
    assert "tiering" in health.data
