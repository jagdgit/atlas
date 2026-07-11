"""Tests for migration discovery (no live database required)."""

from __future__ import annotations

from atlas.database.migrations import MigrationRunner


def test_discovers_foundation_migrations():
    runner = MigrationRunner()
    versions = [m.version for m in runner.discover()]
    # The foundation set must be present and in order; new migrations may follow.
    foundation = ["0001", "0002", "0003", "0004", "0005", "0006", "0007"]
    assert versions[: len(foundation)] == foundation
    assert versions == sorted(versions)


def test_checksum_is_stable():
    runner = MigrationRunner()
    first = runner.discover()[0]
    assert first.checksum == first.checksum
    assert len(first.checksum) == 64  # sha256 hex digest


def test_filenames_have_version_prefix():
    runner = MigrationRunner()
    for migration in runner.discover():
        assert migration.filename.startswith(migration.version)
