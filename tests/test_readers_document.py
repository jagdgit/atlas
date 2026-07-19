"""Tests for the Document Reader (Phase C · §C.2, BB10/BB11).

Hermetic tests use in-memory fakes for the Asset Store (``get_bytes``/``versions``) and the
Derived Artifact Store (``get``/``put``) — the reader is duck-typed against both — and exercise
real extraction over temp files. A live-DB smoke wires the real Asset Store + Storage + artifact
cache via the Asset Acquirer. DB tests skip when PostgreSQL is unreachable.
"""

from __future__ import annotations

import pytest

from atlas.readers.document import DocumentReader


# --- fakes ---------------------------------------------------------------
class FakeAssets:
    """Minimal Asset Store: bytes + version rows (with metadata) keyed by asset/version."""

    def __init__(self):
        self._blobs: dict[tuple[str, int], bytes] = {}
        self._versions: dict[str, list[dict]] = {}

    def add(self, asset_id, version, data, *, filename=None):
        self._blobs[(asset_id, version)] = data
        meta = {"filename": filename} if filename else {}
        self._versions.setdefault(asset_id, []).append({"version": version, "metadata": meta})

    def get_bytes(self, asset_id, version=None):
        if version is None:
            version = self.versions(asset_id)[0]["version"]
        return self._blobs[(asset_id, version)]

    def versions(self, asset_id):
        return list(reversed(self._versions.get(asset_id, [])))  # newest first


class FakeArtifacts:
    """In-memory Derived Artifact Store keyed by (asset_id, version, reader, reader_version)."""

    def __init__(self):
        self.store: dict[tuple, dict] = {}
        self.puts = 0

    def get(self, asset_id, version, reader, reader_version):
        return self.store.get((asset_id, version, reader, reader_version))

    def put(self, asset_id, version, reader, reader_version, artifact):
        self.puts += 1
        self.store[(asset_id, version, reader, reader_version)] = artifact


# --- hermetic ------------------------------------------------------------
def test_reader_extracts_text_and_caches():
    assets = FakeAssets()
    assets.add("a1", 1, b"hello from a text file\n", filename="note.txt")
    arts = FakeArtifacts()
    reader = DocumentReader(assets, arts)

    art = reader.read("a1", 1, filename="note.txt")
    assert art["outcome"] == "ok"
    assert "hello from a text file" in art["text"]
    assert art["reader"] == "document" and art["reader_version"] == "1.0.0"
    assert art["asset_id"] == "a1" and art["asset_version"] == 1
    assert art["sections"] and art["sections"][0]["ordinal"] == 0
    assert arts.puts == 1

    # Second read is a cache hit — no re-extraction, no new put.
    again = reader.read("a1", 1, filename="note.txt")
    assert again == art
    assert arts.puts == 1


def test_reader_derives_filename_from_asset_metadata():
    assets = FakeAssets()
    assets.add("a2", 1, b"# Title\n\nbody text\n", filename="doc.md")
    reader = DocumentReader(assets, FakeArtifacts())
    # No filename passed → the reader reads it from the version metadata.
    art = reader.read("a2", 1)
    assert art["outcome"] == "ok"
    assert art["extension"] == ".md"
    assert "body text" in art["text"]


def test_reader_resolves_latest_version_when_unspecified():
    assets = FakeAssets()
    assets.add("a3", 1, b"old\n", filename="v.txt")
    assets.add("a3", 2, b"new content here\n", filename="v.txt")
    reader = DocumentReader(assets, FakeArtifacts())
    art = reader.read("a3")  # version None → latest (2)
    assert art["asset_version"] == 2
    assert "new content here" in art["text"]


def test_reader_force_rebuilds():
    assets = FakeAssets()
    assets.add("a4", 1, b"content\n", filename="c.txt")
    arts = FakeArtifacts()
    reader = DocumentReader(assets, arts)
    reader.read("a4", 1, filename="c.txt")
    assert arts.puts == 1
    reader.read("a4", 1, filename="c.txt", force=True)
    assert arts.puts == 2  # forced re-extraction wrote the artifact again


def test_reader_reports_unsupported_extension_without_crashing():
    assets = FakeAssets()
    assets.add("a5", 1, b"\x00\x01binary", filename="thing.zip")
    reader = DocumentReader(assets, FakeArtifacts())
    art = reader.read("a5", 1, filename="thing.zip")
    assert art["outcome"] == "unsupported"
    assert art["text"] == "" and art["sections"] == []


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


def test_document_reader_live_caches_and_reuses(db, tmp_path):
    import uuid

    from atlas.assets import AssetRepository, AssetStore
    from atlas.engineering.artifacts import DerivedArtifactStore
    from atlas.ingestion.acquire import AssetAcquirer
    from atlas.storage.repository import StorageRepository
    from atlas.storage.service import StorageManager

    storage = StorageManager(tmp_path / "storage", StorageRepository(db))
    storage.start()
    assets = AssetStore(storage, AssetRepository(db))
    artifacts = DerivedArtifactStore(storage)
    acq = AssetAcquirer(assets)
    reader = DocumentReader(assets, artifacts)

    body = f"# Phase C\n\nunified ingestion smoke {uuid.uuid4()}\n".encode("utf-8")
    acquired = acq.acquire_bytes(body, kind="document", filename="phase_c.md")

    art = reader.read(acquired.asset_id, acquired.asset_version)
    assert art["outcome"] == "ok"
    assert "unified ingestion smoke" in art["text"]
    assert art["extension"] == ".md"

    # It really landed in the derived artifact cache and is reused.
    cached = artifacts.get(
        acquired.asset_id, acquired.asset_version, reader.id, reader.VERSION
    )
    assert cached is not None and cached["text"] == art["text"]
