"""Tests for the generic Asset Acquirer (Phase C · §C.2).

Hermetic tests use the shared ``FakeAssetStore`` (content-addressed dedup logic lives in the
acquirer, not the store); a live-DB smoke wires the real Asset Store + Storage Manager to prove
bytes are checksum-verified and identical content reuses the same asset. DB tests skip when
PostgreSQL is unreachable (matches the other e2e modules).
"""

from __future__ import annotations

import pytest

from atlas.ingestion.acquire import (
    DEFAULT_ASSET_KIND,
    AcquiredAsset,
    AssetAcquireError,
    AssetAcquirer,
    sha256_bytes,
)
from tests.test_engineering_ingest import FakeAssetStore


# --- hermetic ------------------------------------------------------------
def test_acquire_bytes_registers_then_dedups():
    store = FakeAssetStore()
    acq = AssetAcquirer(store)

    first = acq.acquire_bytes(b"hello world", filename="a.txt")
    assert isinstance(first, AcquiredAsset)
    assert first.reused is False
    assert first.asset_version == 1
    assert first.kind == DEFAULT_ASSET_KIND
    assert first.name == sha256_bytes(b"hello world") == first.checksum
    assert first.size_bytes == len(b"hello world")

    # Identical bytes → reuse the same asset, no new version.
    second = acq.acquire_bytes(b"hello world", filename="a-copy.txt")
    assert second.reused is True
    assert second.asset_id == first.asset_id
    assert second.asset_version == 1
    assert len(store.versions(first.asset_id)) == 1  # no duplicate stored


def test_acquire_bytes_different_content_is_a_new_asset():
    store = FakeAssetStore()
    acq = AssetAcquirer(store)
    a = acq.acquire_bytes(b"one")
    b = acq.acquire_bytes(b"two")
    assert a.asset_id != b.asset_id
    assert a.checksum != b.checksum
    assert a.reused is False and b.reused is False


def test_acquire_kind_override_separates_assets():
    store = FakeAssetStore()
    acq = AssetAcquirer(store)
    doc = acq.acquire_bytes(b"same", kind="document")
    pdf = acq.acquire_bytes(b"same", kind="pdf")
    # Same bytes under different kinds are distinct assets (kind is part of identity).
    assert doc.asset_id != pdf.asset_id
    assert doc.checksum == pdf.checksum


def test_acquire_file_reads_and_guesses_content_type(tmp_path):
    store = FakeAssetStore()
    acq = AssetAcquirer(store)
    p = tmp_path / "notes.txt"
    p.write_text("some notes\n")

    out = acq.acquire_file(p)
    assert out.reused is False
    assert out.content_type == "text/plain"
    assert out.source_uri == str(p)
    assert out.checksum == sha256_bytes(b"some notes\n")

    # Re-acquiring the same file is a cheap no-op (content-addressed).
    again = acq.acquire_file(p)
    assert again.reused is True and again.asset_id == out.asset_id


def test_acquire_empty_and_missing_raise(tmp_path):
    acq = AssetAcquirer(FakeAssetStore())
    with pytest.raises(AssetAcquireError):
        acq.acquire_bytes(b"")
    with pytest.raises(AssetAcquireError):
        acq.acquire_bytes("not bytes")  # type: ignore[arg-type]
    with pytest.raises(AssetAcquireError):
        acq.acquire_file(tmp_path / "does-not-exist.txt")


# --- live DB smoke -------------------------------------------------------
@pytest.fixture(scope="module")
def db():
    from atlas.database.connection import DatabaseManager

    manager = DatabaseManager()
    try:
        if not manager.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001 - any connection error means skip
        pytest.skip(f"database unreachable: {exc}")
    yield manager
    manager.close()


def test_acquire_bytes_live_round_trip_and_reuse(db, tmp_path):
    import uuid

    from atlas.assets import AssetRepository, AssetStore
    from atlas.storage.repository import StorageRepository
    from atlas.storage.service import StorageManager

    storage = StorageManager(tmp_path / "storage", StorageRepository(db))
    storage.start()
    assets = AssetStore(storage, AssetRepository(db))
    acq = AssetAcquirer(assets)

    # Unique content per run so version numbering / dedup is hermetic across the shared DB.
    payload = f"phase-c c.2 acquire smoke {uuid.uuid4()}".encode("utf-8")
    first = acq.acquire_bytes(payload, filename="smoke.txt")
    assert first.reused is False and first.asset_version == 1

    # Bytes are retrievable + checksum-verified.
    assert assets.verify(first.asset_id) is True
    assert assets.get_bytes(first.asset_id) == payload

    # Identical bytes → reuse (no duplicate); different bytes → a new asset.
    again = acq.acquire_bytes(payload, filename="smoke-copy.txt")
    assert again.reused is True and again.asset_id == first.asset_id
    assert len(assets.versions(first.asset_id)) == 1

    other = acq.acquire_bytes(payload + b"!", filename="smoke2.txt")
    assert other.asset_id != first.asset_id and other.reused is False
